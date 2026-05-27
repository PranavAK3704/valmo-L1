"""
Stuck queue clustering — groups unanswered stuck questions by semantic
similarity so the trainer can fix root causes instead of one-off questions.

Uses ChromaDB's existing embedding function (no extra model load) and
scipy.cluster.hierarchy when available, falling back to greedy O(n²)
clustering otherwise. Results cached for 1 hour to avoid re-embedding on
every dashboard page load.
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

STUCK_QUEUE_FILE = Path(__file__).parent.parent.parent / "data" / "stuck_queue.jsonl"
DEFAULT_DISTANCE_THRESHOLD = 0.35
WINDOW_DAYS = 30
CACHE_TTL_SECONDS = 3600   # 1 hour

# Module-level cache. Single dashboard process — no concurrency story needed.
_cache: Dict[str, dict] = {}   # key=tuple-of-params-as-str -> {data, expires_at}


def _load_stuck_entries(window_days: int = WINDOW_DAYS) -> List[dict]:
    """Read stuck_queue.jsonl. Keep only answered=False entries from the
    last `window_days`. Returns the raw dicts (caller will project fields)."""
    if not STUCK_QUEUE_FILE.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    out = []
    for line in STUCK_QUEUE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("answered"):
            continue
        ts = entry.get("timestamp") or ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                continue
        except Exception:
            # Bad timestamp — keep it anyway, better to surface than drop
            pass
        q = (entry.get("question") or "").strip()
        if not q:
            continue
        out.append(entry)
    return out


def _embed_questions(questions: List[str]) -> np.ndarray:
    """Embed a list of questions using the same model ChromaDB uses for SOP
    chunks. Returns an (N, D) numpy array. Lazily imports sop_store to avoid
    circular dep + delay model init until first use."""
    from src.llm.sop_store import get_sop_store
    ef = get_sop_store()._ef
    raw = ef(questions)
    arr = np.asarray(raw, dtype=np.float64)
    return arr


def _cluster_scipy(vectors: np.ndarray, threshold: float) -> List[List[int]]:
    """Agglomerative clustering with average linkage + cosine distance.
    Returns list of clusters where each cluster is a list of row indices."""
    from scipy.cluster.hierarchy import fcluster, linkage
    if len(vectors) == 1:
        return [[0]]
    # 'average' linkage + 'cosine' metric is the canonical text-clustering combo
    Z = linkage(vectors, method="average", metric="cosine")
    labels = fcluster(Z, t=threshold, criterion="distance")
    buckets: Dict[int, List[int]] = {}
    for i, lab in enumerate(labels):
        buckets.setdefault(int(lab), []).append(i)
    return list(buckets.values())


def _cluster_greedy(vectors: np.ndarray, threshold: float) -> List[List[int]]:
    """Fallback: greedy single-pass clustering. For each vector, find the
    first cluster whose centroid is within `threshold` cosine distance; else
    start a new cluster. Centroids updated as members join. O(n²) but fine
    for n up to a few hundred."""
    def cos_dist(a: np.ndarray, b: np.ndarray) -> float:
        na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if na == 0 or nb == 0:
            return 1.0
        return 1.0 - float(np.dot(a, b) / (na * nb))

    clusters: List[dict] = []  # {indices: [int...], centroid: np.ndarray, sum: np.ndarray}
    for i, vec in enumerate(vectors):
        placed = False
        for c in clusters:
            if cos_dist(vec, c["centroid"]) <= threshold:
                c["indices"].append(i)
                c["sum"] = c["sum"] + vec
                c["centroid"] = c["sum"] / len(c["indices"])
                placed = True
                break
        if not placed:
            clusters.append({"indices": [i], "sum": vec.copy(), "centroid": vec.copy()})
    return [c["indices"] for c in clusters]


def _representative(indices: List[int], vectors: np.ndarray) -> int:
    """Return the row index closest to the cluster's centroid."""
    if len(indices) == 1:
        return indices[0]
    sub = vectors[indices]
    centroid = sub.mean(axis=0)
    # Cosine distance to centroid
    norms = np.linalg.norm(sub, axis=1) * float(np.linalg.norm(centroid))
    norms[norms == 0] = 1.0
    sims = sub @ centroid / norms
    best_local = int(np.argmax(sims))
    return indices[best_local]


def compute_clusters(threshold: float = DEFAULT_DISTANCE_THRESHOLD,
                     window_days: int = WINDOW_DAYS) -> dict:
    """Cluster unanswered stuck questions. Returns:
    {
      'generated_at': ISO timestamp,
      'method': 'scipy' | 'greedy',
      'total_entries': N,
      'cluster_count': K,
      'clusters': [
        {
          'cluster_size': int,
          'representative_question': str,
          'sample_ticket_ids': [...],
          'sample_subjects': [...],
          'suggested_queue': str,
          'sample_timestamps': [...],
        }, ...
      ]
    }
    Sorted by cluster_size desc.
    """
    entries = _load_stuck_entries(window_days=window_days)
    if not entries:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "method": "none",
            "total_entries": 0,
            "cluster_count": 0,
            "clusters": [],
        }

    questions = [e.get("question", "") for e in entries]
    vectors = _embed_questions(questions)

    method = "scipy"
    try:
        index_clusters = _cluster_scipy(vectors, threshold)
    except Exception as e:
        logger.warning(f"[StuckClusters] scipy clustering failed ({e}); falling back to greedy")
        index_clusters = _cluster_greedy(vectors, threshold)
        method = "greedy"

    # Sort clusters by size desc
    index_clusters.sort(key=lambda c: -len(c))

    from collections import Counter
    out_clusters = []
    for idxs in index_clusters:
        rep_i = _representative(idxs, vectors)
        rep_q = questions[rep_i]
        sample_tids = [entries[i].get("ticket_id") for i in idxs[:5]]
        sample_subjects = [entries[i].get("subject", "")[:80] for i in idxs[:5]]
        sample_timestamps = [entries[i].get("timestamp", "") for i in idxs[:5]]
        queue_counts = Counter(entries[i].get("queue", "") for i in idxs if entries[i].get("queue"))
        suggested_queue = queue_counts.most_common(1)[0][0] if queue_counts else ""
        out_clusters.append({
            "cluster_size":            len(idxs),
            "representative_question": rep_q,
            "representative_ticket":   entries[rep_i].get("ticket_id"),
            "sample_ticket_ids":       sample_tids,
            "sample_subjects":         sample_subjects,
            "sample_timestamps":       sample_timestamps,
            "suggested_queue":         suggested_queue,
        })

    return {
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "method":         method,
        "total_entries":  len(entries),
        "cluster_count":  len(out_clusters),
        "threshold":      threshold,
        "window_days":    window_days,
        "clusters":       out_clusters,
    }


def get_clusters_cached(threshold: float = DEFAULT_DISTANCE_THRESHOLD,
                        window_days: int = WINDOW_DAYS,
                        force_refresh: bool = False) -> dict:
    """Wraps compute_clusters with a 1-hour cache. Cache key includes the
    threshold + window_days so different views don't collide."""
    key = f"{threshold}|{window_days}"
    now = time.time()
    cached = _cache.get(key)
    if cached and not force_refresh and cached.get("expires_at", 0) > now:
        out = dict(cached["data"])
        out["_from_cache"] = True
        out["_cache_age_seconds"] = int(now - cached["computed_at"])
        return out
    data = compute_clusters(threshold=threshold, window_days=window_days)
    _cache[key] = {
        "data": data,
        "computed_at": now,
        "expires_at": now + CACHE_TTL_SECONDS,
    }
    out = dict(data)
    out["_from_cache"] = False
    out["_cache_age_seconds"] = 0
    return out


def invalidate_cache():
    """Clear the cluster cache — call after a trainer answers a stuck
    question so the next dashboard load reflects the new state."""
    _cache.clear()
