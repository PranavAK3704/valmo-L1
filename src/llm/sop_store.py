"""
SOPStore — ChromaDB-backed knowledge base for SOPs and KT.

Loads all .md files from data/sop_knowledge/.
On each ticket, retrieves the top-k most relevant chunks.

To update KT: just edit or add .md files in data/sop_knowledge/
and call sop_store.reload(). No restart needed.
"""

import os
import logging
from pathlib import Path
from typing import Dict, List

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "data" / "sop_knowledge"
CHROMA_DIR    = Path(__file__).parent.parent.parent / "data" / "chroma_db"
COLLECTION    = "valmo_sop_kt"
CHUNK_SIZE    = 600   # characters per chunk (legacy chunker for ad-hoc text)
CHUNK_OVERLAP = 100
MD_SECTION_SOFT_LIMIT = 1500  # chars — when a heading section grows beyond this, split by paragraph

# Queue inference keyword map. Order matters — earlier entries win on tie.
# Each tuple = (queue_key, list of substrings; case-insensitive match against
# section_path + first ~500 chars of body).
_QUEUE_KEYWORDS: List[tuple] = [
    ("cash_handover",       ["cod ", "cash handover", "cash on delivery", "cms",
                              "cash deposit", "pendency"]),
    ("payments",            ["payment", "fnf", "invoice", "settlement",
                              "e-sign", "esign", " gst ", "finance hold",
                              "captain payment"]),
    ("consumables",         ["consumable", "packing material", "packaging",
                              "rvp consumable", "captain payout consumables"]),
    ("orders_and_planning", ["order planning", "orders and planning",
                              "volume target", "user pin allocation"]),
    ("losses_and_debits",   ["hardstop", "shortage", "loss marked", "loss ",
                              "losses", "debit", "awb", "log10", "scan",
                              "manifest", "inscan", "ofd", "rto", "consignment",
                              "pilot lost", "misroute", "waiver"]),
]


def _infer_queue(section_path: str, body: str) -> str:
    """Map a markdown section to its primary queue based on keywords.
    Returns 'general' when no keyword matches (section applies to all queues)."""
    haystack = f" {section_path}  {body[:500]} ".lower()
    for queue_key, keywords in _QUEUE_KEYWORDS:
        for kw in keywords:
            if kw in haystack:
                return queue_key
    return "general"

# Allowed content_type values. Stored as metadata on every chunk so retrieval
# and the dashboard can distinguish authoritative SOP from precedents, trainer
# Q&A, ad-hoc KT additions, and structured domain activations.
CONTENT_TYPES = {
    "sop_canonical",          # base SOP / KT files loaded from disk
    "resolved_precedent",     # approved past decisions fed back as examples
    "trainer_qa",             # trainer answers to stuck questions
    "kt_addition",            # free-form notes added via KT engine text/voice
    "kt_domain_activation",   # structured per-queue domain KT (Stage 0 activation)
}
DEFAULT_CONTENT_TYPE = "sop_canonical"


def _infer_content_type(source: str) -> str:
    """Backfill helper — guess content_type from a source string prefix.
    Used by reindex_missing_content_type() for legacy chunks predating the field."""
    s = (source or "").lower()
    if s.startswith("resolved_"):              return "resolved_precedent"
    if s.startswith("trainer_qa") or s.startswith("trainer_"): return "trainer_qa"
    if s.startswith("kt_domain_") or s.startswith("kt_freeform_") \
       or s.startswith("kt_guided_"):          return "kt_domain_activation"
    if s.startswith("kt_"):                    return "kt_addition"
    return "sop_canonical"


def _chunk_text(text: str, source: str) -> List[dict]:
    """Legacy 600-char overlap chunker. Used for ad-hoc prose that doesn't
    have markdown structure (KT engine text/voice notes, trainer Q&A,
    resolved-precedent dumps). For canonical .md SOPs use _chunk_md_by_heading."""
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if chunk.strip():
            chunks.append({
                "id":      f"{source}_{idx}",
                "text":    chunk.strip(),
                "source":  source,
            })
        start = end - CHUNK_OVERLAP
        idx += 1
    return chunks


def _split_long_section(heading_block: str, body: str, limit: int) -> List[str]:
    """Split a too-long section into paragraph-bounded pieces, repeating
    the heading hierarchy at the top of each. Returns the rendered chunk
    texts (heading + body slice)."""
    if len(body) <= limit:
        return [f"{heading_block}\n{body}".strip()]
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    out = []
    buf = ""
    for p in paragraphs:
        if buf and (len(buf) + len(p) + 2) > limit:
            out.append(f"{heading_block}\n{buf}".strip())
            buf = p
        else:
            buf = (buf + "\n\n" + p) if buf else p
    if buf:
        out.append(f"{heading_block}\n{buf}".strip())
    return out


def _chunk_md_by_heading(text: str, source: str) -> List[dict]:
    """Heading-aware chunker for canonical SOP markdown.

    Parses the file into sections boundary'd by ## (H2) and ### (H3) headings.
    Each chunk text starts with its heading hierarchy ("## Three Types of Losses\\n### 1. Hardstop Loss\\n...")
    so the embedding captures section context. Sections longer than
    MD_SECTION_SOFT_LIMIT chars are split by paragraph, with the heading block
    repeated at the top of each split.

    Each chunk gets metadata: source, section_path, queue (inferred).
    content_type is added by the caller (reload/reindex_canonical).
    """
    lines = text.splitlines()
    h2_title: str = ""
    h3_title: str = ""
    current_body: List[str] = []
    sections: List[tuple] = []   # list of (h2, h3, body_text)

    def flush():
        body = "\n".join(current_body).strip()
        # Skip pre-heading prose (h2 and h3 both empty) — that's typically
        # the H1 title's intro paragraph, not a meaningful section.
        if not (h2_title or h3_title):
            return
        if body or h3_title:
            sections.append((h2_title, h3_title, body))

    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            flush()
            h2_title = line[3:].strip()
            h3_title = ""
            current_body = []
        elif line.startswith("### "):
            flush()
            h3_title = line[4:].strip()
            current_body = []
        else:
            # Skip H1 title line; collect H4+ and prose into body
            if line.startswith("# ") and not line.startswith("## "):
                continue
            current_body.append(line)
    flush()

    chunks: List[dict] = []
    idx = 0
    for h2, h3, body in sections:
        # Skip sections with no useful content (e.g. an H2 followed immediately by H3s, no intro prose)
        if not body and not h3:
            continue
        # Build heading block + section_path
        if h2 and h3:
            heading_block = f"## {h2}\n### {h3}"
            section_path = f"{h2} > {h3}"
        elif h2:
            heading_block = f"## {h2}"
            section_path = h2
        elif h3:
            heading_block = f"### {h3}"
            section_path = h3
        else:
            heading_block = ""
            section_path = "(unnamed)"

        queue = _infer_queue(section_path, body)
        texts = _split_long_section(heading_block, body, MD_SECTION_SOFT_LIMIT)
        for txt in texts:
            chunks.append({
                "id":           f"{source}_{idx}",
                "text":         txt,
                "source":       source,
                "section_path": section_path,
                "queue":        queue,
            })
            idx += 1
    return chunks


class SOPStore:
    def __init__(self):
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        self._col = self._client.get_or_create_collection(
            name=COLLECTION,
            embedding_function=self._ef,
        )
        if self._col.count() == 0:
            logger.info("[SOPStore] Empty collection — loading knowledge files")
            self.reload()
        else:
            logger.info(f"[SOPStore] Loaded {self._col.count()} chunks from cache")
            # One-shot migration for chunks predating content_type metadata
            try:
                n = self.backfill_content_type()
                if n:
                    logger.info(f"[SOPStore] backfilled content_type on {n} legacy chunks")
            except Exception as e:
                logger.warning(f"[SOPStore] backfill failed (non-fatal): {e}")
            # One-shot migration for canonical chunks predating heading-aware
            # chunking (no queue / section_path metadata yet). Detect by
            # sampling canonical chunks for missing 'queue' metadata.
            try:
                items = self._col.get(include=["metadatas"])
                metas = items.get("metadatas") or []
                needs_reindex = any(
                    (m or {}).get("content_type") == "sop_canonical"
                    and not (m or {}).get("queue")
                    for m in metas
                )
                if needs_reindex:
                    logger.info("[SOPStore] detected legacy flat canonical chunks; triggering reindex")
                    self.reindex_canonical()
            except Exception as e:
                logger.warning(f"[SOPStore] canonical reindex check failed (non-fatal): {e}")

    def reload(self):
        """Re-read all .md files and rebuild the collection.

        Canonical SOP files (content_type=sop_canonical, inferred from the
        filename) get heading-aware chunking + queue metadata.
        Non-canonical .md files (kt_*, resolved_*, trainer_qa_*) keep the
        legacy 600-char chunker because they're flat prose dumps."""
        if not KNOWLEDGE_DIR.exists():
            logger.warning(f"[SOPStore] Knowledge dir not found: {KNOWLEDGE_DIR}")
            return

        all_ids, all_docs, all_metas = [], [], []
        for md_file in KNOWLEDGE_DIR.glob("*.md"):
            text = md_file.read_text(encoding="utf-8")
            src = md_file.stem
            ctype = _infer_content_type(src)
            if ctype == "sop_canonical":
                chunks = _chunk_md_by_heading(text, src)
                for chunk in chunks:
                    all_ids.append(chunk["id"])
                    all_docs.append(chunk["text"])
                    all_metas.append({
                        "source":       chunk["source"],
                        "content_type": ctype,
                        "section_path": chunk.get("section_path", ""),
                        "queue":        chunk.get("queue", "general"),
                    })
            else:
                for chunk in _chunk_text(text, src):
                    all_ids.append(chunk["id"])
                    all_docs.append(chunk["text"])
                    all_metas.append({
                        "source":       chunk["source"],
                        "content_type": ctype,
                    })

        if not all_ids:
            logger.warning("[SOPStore] No knowledge files found")
            return

        # Clear and re-add
        try:
            self._client.delete_collection(COLLECTION)
        except Exception:
            pass
        self._col = self._client.get_or_create_collection(
            name=COLLECTION,
            embedding_function=self._ef,
        )
        self._col.add(documents=all_docs, ids=all_ids, metadatas=all_metas)
        logger.info(f"[SOPStore] Indexed {len(all_ids)} chunks from {KNOWLEDGE_DIR}")

    def reindex_canonical(self) -> int:
        """Surgical re-chunk of canonical SOP files only. Preserves resolved
        precedents, trainer Q&A, and KT additions. Returns count of chunks
        added after the reindex. Idempotent — safe to run repeatedly."""
        if not KNOWLEDGE_DIR.exists():
            logger.warning(f"[SOPStore] reindex skipped — knowledge dir missing")
            return 0

        # Identify canonical chunks to delete. Match by content_type=sop_canonical
        # AND fall back to inferring from source for legacy chunks predating Fix 4.
        try:
            all_items = self._col.get(include=["metadatas"])
        except Exception as e:
            logger.warning(f"[SOPStore] reindex skipped — could not read collection: {e}")
            return 0
        ids   = all_items.get("ids") or []
        metas = all_items.get("metadatas") or []
        canonical_ids = []
        for cid, meta in zip(ids, metas):
            meta = meta or {}
            ctype = meta.get("content_type") or _infer_content_type(meta.get("source", ""))
            if ctype == "sop_canonical":
                canonical_ids.append(cid)

        if canonical_ids:
            try:
                self._col.delete(ids=canonical_ids)
                logger.info(f"[SOPStore] reindex: deleted {len(canonical_ids)} stale canonical chunks")
            except Exception as e:
                logger.warning(f"[SOPStore] reindex delete failed: {e}")
                return 0

        # Re-add canonical files only, using heading-aware chunker
        added = 0
        new_ids, new_docs, new_metas = [], [], []
        for md_file in KNOWLEDGE_DIR.glob("*.md"):
            src = md_file.stem
            if _infer_content_type(src) != "sop_canonical":
                continue
            text = md_file.read_text(encoding="utf-8")
            for chunk in _chunk_md_by_heading(text, src):
                new_ids.append(chunk["id"])
                new_docs.append(chunk["text"])
                new_metas.append({
                    "source":       chunk["source"],
                    "content_type": "sop_canonical",
                    "section_path": chunk.get("section_path", ""),
                    "queue":        chunk.get("queue", "general"),
                })
                added += 1
        if new_ids:
            self._col.add(ids=new_ids, documents=new_docs, metadatas=new_metas)
            logger.info(f"[SOPStore] reindex: added {added} new heading-aware canonical chunks")
        return added

    def retrieve(self, query: str, k: int = 10, queue: str = None) -> Dict[str, List[Dict]]:
        """Return top-k relevant chunks grouped by content_type.

        Shape: {content_type: [{text, source, section_path, queue, distance}, ...], ...}

        If queue is provided, only canonical chunks matching that queue (or "general",
        which applies to all queues) are kept. Chunks without a queue tag (legacy
        flat chunks, or non-canonical content like resolved precedents) are always
        kept — the queue filter is opt-in narrowing, not exclusion.

        We over-query (k*3) then post-filter to avoid returning too few hits when
        the filter is tight. Legacy chunks without content_type metadata get
        content_type inferred from source. Returns {} when the collection is empty."""
        n = self._col.count()
        if n == 0:
            return {}

        over_k = min(max(k * 3, k), n)
        results = self._col.query(query_texts=[query], n_results=over_k)
        docs  = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        dists = (results.get("distances") or [[]])[0] or ([0.0] * len(docs))

        q_target = (queue or "").strip()
        normalized_chunks: List[Dict] = []
        for doc, meta, dist in zip(docs, metas, dists):
            meta = meta or {}

            # Soft-delete filter: skip chunks marked deprecated via the
            # scenario audit page. Reversible by toggling the flag back off.
            if meta.get("deprecated"):
                continue

            ctype = meta.get("content_type") or _infer_content_type(meta.get("source", ""))
            chunk_queue = meta.get("queue") or ""  # missing → legacy / non-canonical

            # Queue filter: only apply when caller specified a queue AND the chunk
            # has a queue tag. Untagged chunks always pass (legacy + non-canonical).
            if q_target and chunk_queue:
                if chunk_queue != q_target and chunk_queue != "general":
                    continue

            normalized_chunks.append({
                "text":         doc,
                "source":       meta.get("source", "?"),
                "section_path": meta.get("section_path", ""),
                "queue":        chunk_queue,
                "distance":     float(dist),
                "_ctype":       ctype,
            })

        # Take top-k by original distance order
        normalized_chunks = normalized_chunks[:k]

        grouped: Dict[str, List[Dict]] = {}
        for c in normalized_chunks:
            grouped.setdefault(c.pop("_ctype"), []).append(c)
        return grouped

    def add_knowledge(self, text: str, source: str, content_type: str = None):
        """Dynamically add new knowledge (e.g., trainer Q&A answers).
        content_type must be one of CONTENT_TYPES. If omitted, it's inferred
        from the source prefix (backward-compat for existing callers)."""
        ctype = content_type or _infer_content_type(source)
        if ctype not in CONTENT_TYPES:
            logger.warning(
                f"[SOPStore] Unknown content_type={ctype!r} for source={source!r}; "
                f"falling back to {DEFAULT_CONTENT_TYPE!r}"
            )
            ctype = DEFAULT_CONTENT_TYPE
        chunks = _chunk_text(text, source)
        if not chunks:
            return
        self._col.add(
            documents=[c["text"] for c in chunks],
            ids=[c["id"] for c in chunks],
            metadatas=[{"source": c["source"], "content_type": ctype} for c in chunks],
        )
        logger.info(f"[SOPStore] Added {len(chunks)} chunks source={source!r} ctype={ctype!r}")

    def find_chunks_mentioning(self, needle: str) -> List[Dict]:
        """Return all chunks where the needle string appears in the text.
        Used by the scenario audit page to surface every place a scenario_id
        is referenced across canonical SOP, precedents, trainer Q&A, KT
        additions, and domain activations."""
        needle = (needle or "").strip()
        if not needle:
            return []
        try:
            items = self._col.get(
                where_document={"$contains": needle},
                include=["documents", "metadatas"],
            )
        except Exception as e:
            logger.warning(f"[SOPStore] find_chunks_mentioning({needle!r}) failed: {e}")
            return []
        ids   = items.get("ids") or []
        docs  = items.get("documents") or []
        metas = items.get("metadatas") or []
        out = []
        for cid, d, m in zip(ids, docs, metas):
            m = m or {}
            out.append({
                "id":           cid,
                "text":         d,
                "source":       m.get("source", "?"),
                "content_type": m.get("content_type") or _infer_content_type(m.get("source", "")),
                "section_path": m.get("section_path", ""),
                "queue":        m.get("queue", ""),
                "deprecated":   bool(m.get("deprecated")),
            })
        return out

    def set_chunk_deprecated(self, chunk_id: str, deprecated: bool = True) -> bool:
        """Toggle the deprecated flag on a chunk. Soft delete — the chunk
        stays in the collection but retrieve() filters it out. Reversible
        by passing deprecated=False. Returns True iff the chunk exists."""
        try:
            items = self._col.get(ids=[chunk_id], include=["metadatas"])
        except Exception:
            return False
        metas = items.get("metadatas") or []
        if not metas:
            return False
        new_meta = dict(metas[0] or {})
        new_meta["deprecated"] = bool(deprecated)
        try:
            self._col.update(ids=[chunk_id], metadatas=[new_meta])
        except Exception as e:
            logger.warning(f"[SOPStore] deprecate update failed for {chunk_id}: {e}")
            return False
        logger.info(f"[SOPStore] chunk {chunk_id} deprecated={deprecated}")
        return True

    def backfill_content_type(self) -> int:
        """One-time migration — scan existing entries; update any missing
        content_type metadata using _infer_content_type(source). Returns
        the number of chunks updated. Safe to call repeatedly (idempotent)."""
        try:
            all_items = self._col.get(include=["metadatas"])
        except Exception as e:
            logger.warning(f"[SOPStore] backfill skipped — could not read collection: {e}")
            return 0
        ids   = all_items.get("ids") or []
        metas = all_items.get("metadatas") or []
        to_update_ids, to_update_meta = [], []
        for cid, meta in zip(ids, metas):
            if isinstance(meta, dict) and meta.get("content_type"):
                continue   # already tagged
            inferred = _infer_content_type((meta or {}).get("source", ""))
            new_meta = dict(meta or {})
            new_meta["content_type"] = inferred
            to_update_ids.append(cid)
            to_update_meta.append(new_meta)
        if not to_update_ids:
            return 0
        try:
            self._col.update(ids=to_update_ids, metadatas=to_update_meta)
            logger.info(f"[SOPStore] backfilled content_type on {len(to_update_ids)} chunks")
        except Exception as e:
            logger.warning(f"[SOPStore] backfill update failed: {e}")
            return 0
        return len(to_update_ids)


# ── Prompt formatting ───────────────────────────────────────────────
# Section order + headers used by agent_brain to inject grouped chunks
# into the main Gemini prompt. Order matters: canonical SOP first
# (authoritative), then precedents (pattern-only, must defer to SOP),
# then trainer Q&A, then ad-hoc KT and structured domain activations.
_PROMPT_SECTIONS: List[tuple] = [
    (
        "sop_canonical",
        "## CANONICAL SOP (authoritative — follow this)",
    ),
    (
        "resolved_precedent",
        "## RESOLVED PRECEDENTS (similar past cases — use for pattern reference, "
        "NOT as authority. If a precedent contradicts the canonical SOP above, "
        "the SOP wins. If you cannot reconcile a precedent with the SOP, set "
        "action=stuck.)",
    ),
    (
        "trainer_qa",
        "## TRAINER Q&A (answers given by trainers to past stuck questions)",
    ),
    (
        "kt_addition",
        "## KT ADDITIONS (recent knowledge additions — may not yet be in canonical SOP)",
    ),
    # kt_domain_activation is grouped with kt_addition above for prompt purposes
    # — both are stakeholder-contributed supplements to canonical SOP.
]


def format_grouped_chunks(grouped: Dict[str, List[Dict]]) -> str:
    """Render the dict from retrieve() into a single prompt-ready string with
    distinct, ordered section headers. Omits any empty section."""
    if not grouped:
        return "(No SOP knowledge loaded)"

    # Merge kt_domain_activation into kt_addition for display purposes
    merged: Dict[str, List[Dict]] = {k: list(v) for k, v in grouped.items()}
    if "kt_domain_activation" in merged:
        merged.setdefault("kt_addition", []).extend(merged.pop("kt_domain_activation"))

    parts: List[str] = []
    for ctype, header in _PROMPT_SECTIONS:
        chunks = merged.get(ctype) or []
        if not chunks:
            continue
        body = "\n\n---\n\n".join(
            f"[Source: {c['source']}]\n{c['text']}" for c in chunks
        )
        parts.append(f"{header}\n\n{body}")

    # Catch-all for any new content_type that's not in _PROMPT_SECTIONS yet.
    handled = {c for c, _ in _PROMPT_SECTIONS} | {"kt_domain_activation"}
    for ctype, chunks in merged.items():
        if ctype in handled or not chunks:
            continue
        body = "\n\n---\n\n".join(
            f"[Source: {c['source']}]\n{c['text']}" for c in chunks
        )
        parts.append(f"## OTHER KNOWLEDGE ({ctype})\n\n{body}")

    return "\n\n===\n\n".join(parts) if parts else "(No SOP knowledge loaded)"


# Singleton
_store: SOPStore | None = None

def get_sop_store() -> SOPStore:
    global _store
    if _store is None:
        _store = SOPStore()
    return _store

