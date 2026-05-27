"""
Eval harness — runs a labeled ticket set through brain.process() and
reports scenario accuracy, action accuracy, per-scenario precision/recall,
confidence calibration, and a diff against the previous run.

Usage:
    python -m src.eval.harness                          # run with defaults
    python -m src.eval.harness --set custom.jsonl       # custom eval set
    python -m src.eval.harness --no-save                # print only
    python -m src.eval.harness --limit 10               # first N tickets only
    python -m src.eval.harness --no-diff                # skip last-run comparison

Eval-set format: data/eval/labeled_tickets.jsonl
Each line is one ticket with the schema below (see EVAL_SCHEMA constant).
metabase_results is optional — when present, the harness uses it as a mock
Metabase response; when absent, brain.process() runs with empty query_results
(deterministic, no network).

Runs are saved to data/eval/runs/{ISO_timestamp}.json.
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
EVAL_DIR = ROOT / "data" / "eval"
DEFAULT_EVAL_SET = EVAL_DIR / "labeled_tickets.jsonl"
RUNS_DIR = EVAL_DIR / "runs"

# Documented schema for one row of labeled_tickets.jsonl
EVAL_SCHEMA = {
    "ticket_id":         "str — unique identifier (real Kapture id or synthetic)",
    "subject":           "str — ticket subject line",
    "description":       "str — full ticket body / captain's message",
    "queue":             "str — Kapture queue label (e.g. 'W- LD', 'Payments')",
    "awbs":              "list[str] — AWB numbers in the ticket",
    "expected_scenario": "str — the scenario_id the agent should pick (e.g. 'HS_1_1')",
    "expected_action":   "str — 'respond' | 'escalate' | 'needs_info' | 'stuck'",
    "notes":             "str — why this is the expected answer (for human review)",
    "metabase_results":  "list[dict] — OPTIONAL. If present, mocks Metabase responses.",
}

# Confidence calibration buckets — [lo, hi) ranges
CALIBRATION_BUCKETS = [(0.0, 3.0), (3.0, 5.0), (5.0, 7.0), (7.0, 10.001)]


def load_eval_set(path: Path) -> List[Dict[str, Any]]:
    """Load a labeled eval set from JSONL. Skips blank lines + comment lines
    (starting with #). Raises if file missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"Eval set not found at {path}.\n"
            f"Create it with at least one labeled ticket — see {DEFAULT_EVAL_SET.name} "
            f"for the schema."
        )
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            try:
                row = json.loads(s)
            except json.JSONDecodeError as e:
                logger.warning(f"[Eval] {path.name}:{lineno} — JSON parse failed: {e}")
                continue
            # Skip rows that haven't been labeled yet (template / placeholder)
            if not row.get("ticket_id") or not row.get("expected_scenario"):
                logger.info(f"[Eval] {path.name}:{lineno} — skipping unlabeled row")
                continue
            rows.append(row)
    return rows


def run_ticket(brain, eval_row: Dict[str, Any]):
    """Run one eval row through brain.process(). Mocks Metabase results if
    the row has them, else passes empty query_results. Returns the BrainDecision."""
    ticket = {
        "ticket_id":   eval_row.get("ticket_id", ""),
        "subject":     eval_row.get("subject", ""),
        "detail":      eval_row.get("description", ""),
        "queue":       eval_row.get("queue", ""),
        "queue_key":   eval_row.get("queue", ""),
        "awb_numbers": eval_row.get("awbs") or [],
        "task_id":     eval_row.get("task_id", ""),
        "created_time": eval_row.get("created_time", ""),
    }
    query_results = eval_row.get("metabase_results") or []
    return brain.process(ticket, query_results)


def _compute_scenario_prf(per_scenario_rows: List[Tuple[str, str]]) -> List[Dict]:
    """per_scenario_rows = [(expected, predicted), ...] across the whole eval set.
    Returns per-scenario precision/recall/f1 + counts."""
    expected_counts = defaultdict(int)
    predicted_counts = defaultdict(int)
    tp_counts = defaultdict(int)
    for exp, pred in per_scenario_rows:
        expected_counts[exp] += 1
        predicted_counts[pred] += 1
        if exp == pred:
            tp_counts[exp] += 1

    out = []
    seen = set(list(expected_counts.keys()) + list(predicted_counts.keys()))
    for sid in sorted(seen):
        tp = tp_counts[sid]
        exp_n = expected_counts[sid]
        pred_n = predicted_counts[sid]
        precision = tp / pred_n if pred_n else 0.0
        recall    = tp / exp_n  if exp_n  else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        out.append({
            "scenario":  sid,
            "expected":  exp_n,
            "predicted": pred_n,
            "tp":        tp,
            "precision": round(precision, 3),
            "recall":    round(recall, 3),
            "f1":        round(f1, 3),
        })
    out.sort(key=lambda x: (-x["expected"], x["scenario"]))
    return out


def _confidence_calibration(decisions: List[Dict]) -> List[Dict]:
    """Bucket decisions by confidence; report what fraction were correct
    (scenario-level match) in each bucket."""
    out = []
    for lo, hi in CALIBRATION_BUCKETS:
        bucket = [d for d in decisions if lo <= float(d["confidence"]) < hi]
        n = len(bucket)
        correct = sum(1 for d in bucket if d["scenario_match"])
        out.append({
            "bucket":   f"{lo:.0f}-{int(hi) if hi <= 10 else 10}",
            "n":        n,
            "correct":  correct,
            "accuracy": round(correct / n, 3) if n else None,
        })
    return out


def _last_run_path() -> Optional[Path]:
    if not RUNS_DIR.exists():
        return None
    runs = sorted(RUNS_DIR.glob("*.json"))
    return runs[-1] if runs else None


def _diff_against_last(current_decisions: List[Dict]) -> Optional[Dict]:
    """Compare current decisions to the most recent saved run. Returns
    {improved, regressed, unchanged_match, unchanged_miss, new_tickets, dropped_tickets, last_run_path}
    or None if no previous run exists."""
    last = _last_run_path()
    if not last:
        return None
    try:
        prev = json.loads(last.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[Eval] could not load previous run {last}: {e}")
        return None
    prev_by_id = {d["ticket_id"]: d for d in (prev.get("decisions") or [])}
    curr_by_id = {d["ticket_id"]: d for d in current_decisions}

    improved, regressed, unchanged_m, unchanged_x, new_t = [], [], [], [], []
    for tid, curr in curr_by_id.items():
        prev_d = prev_by_id.get(tid)
        if prev_d is None:
            new_t.append(tid)
            continue
        prev_match = prev_d.get("scenario_match")
        curr_match = curr.get("scenario_match")
        if prev_match == curr_match:
            (unchanged_m if curr_match else unchanged_x).append(tid)
        elif curr_match and not prev_match:
            improved.append({
                "ticket_id": tid,
                "expected":  curr["expected_scenario"],
                "was":       prev_d.get("predicted_scenario"),
                "now":       curr["predicted_scenario"],
            })
        else:
            regressed.append({
                "ticket_id": tid,
                "expected":  curr["expected_scenario"],
                "was":       prev_d.get("predicted_scenario"),
                "now":       curr["predicted_scenario"],
            })
    dropped = [tid for tid in prev_by_id if tid not in curr_by_id]
    return {
        "last_run_path":    str(last),
        "last_run_at":      prev.get("timestamp", ""),
        "improved":         improved,
        "regressed":        regressed,
        "unchanged_match":  len(unchanged_m),
        "unchanged_miss":   len(unchanged_x),
        "new_tickets":      new_t,
        "dropped_tickets": dropped,
    }


def evaluate(eval_set: List[Dict], brain) -> Dict[str, Any]:
    """Run every row through brain.process() and tabulate results.
    Returns a dict suitable for JSON-serialization."""
    decisions = []
    scenario_pairs = []
    scenario_correct = 0
    action_correct = 0

    for i, row in enumerate(eval_set, 1):
        tid = row.get("ticket_id", f"row_{i}")
        try:
            decision = run_ticket(brain, row)
        except Exception as e:
            logger.error(f"[Eval] ticket {tid} crashed: {e}")
            decisions.append({
                "ticket_id":          tid,
                "expected_scenario":  row.get("expected_scenario", ""),
                "expected_action":    row.get("expected_action", ""),
                "predicted_scenario": "",
                "predicted_action":   "ERROR",
                "confidence":         0.0,
                "scenario_match":     False,
                "action_match":       False,
                "guardrail_triggered": "",
                "error":              str(e),
            })
            continue

        exp_sc = row.get("expected_scenario", "")
        exp_ac = row.get("expected_action", "")
        sc_match = (decision.scenario_identified == exp_sc)
        ac_match = (decision.action == exp_ac)
        if sc_match: scenario_correct += 1
        if ac_match: action_correct += 1

        scenario_pairs.append((exp_sc, decision.scenario_identified))
        decisions.append({
            "ticket_id":          tid,
            "expected_scenario":  exp_sc,
            "expected_action":    exp_ac,
            "predicted_scenario": decision.scenario_identified,
            "predicted_action":   decision.action,
            "confidence":         float(decision.confidence),
            "scenario_match":     sc_match,
            "action_match":       ac_match,
            "guardrail_triggered": getattr(decision, "guardrail_triggered", "") or "",
            "notes":              row.get("notes", ""),
        })
        print(f"  [{i}/{len(eval_set)}] {tid}: "
              f"expected={exp_sc}/{exp_ac} -> got={decision.scenario_identified}/{decision.action} "
              f"[{'OK' if sc_match else 'MISS'}{'' if ac_match else ' /ACT'}] "
              f"conf={decision.confidence:.1f}")

    n = len(eval_set)
    results = {
        "timestamp":           datetime.now(timezone.utc).isoformat(),
        "eval_set_size":       n,
        "scenario_accuracy":   round(scenario_correct / n, 3) if n else 0.0,
        "action_accuracy":     round(action_correct   / n, 3) if n else 0.0,
        "scenario_correct":    scenario_correct,
        "action_correct":      action_correct,
        "per_scenario":        _compute_scenario_prf(scenario_pairs),
        "confidence_calibration": _confidence_calibration(decisions),
        "decisions":           decisions,
    }
    diff = _diff_against_last(decisions)
    if diff is not None:
        results["diff_vs_last"] = diff
    return results


def save_run(results: Dict, runs_dir: Path = RUNS_DIR) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    ts = results.get("timestamp", datetime.now(timezone.utc).isoformat())
    safe_ts = ts.replace(":", "-").replace(".", "-")
    path = runs_dir / f"{safe_ts}.json"
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def print_summary(results: Dict) -> None:
    n = results["eval_set_size"]
    sc_n = results["scenario_correct"]
    ac_n = results["action_correct"]
    print()
    print("=" * 60)
    print(f"  EVAL RUN  {results['timestamp']}")
    print("=" * 60)
    print(f"  Eval set:           {n} ticket(s)")
    print(f"  Scenario accuracy:  {sc_n}/{n} ({results['scenario_accuracy']*100:.1f}%)")
    print(f"  Action accuracy:    {ac_n}/{n} ({results['action_accuracy']*100:.1f}%)")
    print()
    print("  Confidence calibration (correctness within each conf bucket):")
    for c in results["confidence_calibration"]:
        if c["n"] == 0:
            print(f"    conf {c['bucket']:>4s}:  --  (0 tickets)")
        else:
            print(f"    conf {c['bucket']:>4s}:  {c['correct']:>3d}/{c['n']:<3d} ({c['accuracy']*100:.1f}%)")
    print()
    print("  Per-scenario (sorted by expected count):")
    for s in results["per_scenario"][:15]:
        print(f"    {s['scenario']:<12s} exp={s['expected']:>3d}  pred={s['predicted']:>3d}  "
              f"tp={s['tp']:>3d}  P={s['precision']:.2f}  R={s['recall']:.2f}  F1={s['f1']:.2f}")
    if len(results["per_scenario"]) > 15:
        print(f"    ... and {len(results['per_scenario'])-15} more scenarios")
    diff = results.get("diff_vs_last")
    if diff:
        print()
        print(f"  Diff vs last run ({diff['last_run_at']}):")
        print(f"    Improved:        {len(diff['improved'])}")
        for d in diff["improved"][:10]:
            print(f"      + {d['ticket_id']}: was={d['was']} -> now={d['now']} (expected={d['expected']})")
        print(f"    Regressed:       {len(diff['regressed'])}")
        for d in diff["regressed"][:10]:
            print(f"      - {d['ticket_id']}: was={d['was']} -> now={d['now']} (expected={d['expected']})")
        print(f"    Unchanged match: {diff['unchanged_match']}")
        print(f"    Unchanged miss:  {diff['unchanged_miss']}")
        if diff["new_tickets"]:    print(f"    New tickets:     {len(diff['new_tickets'])}")
        if diff["dropped_tickets"]: print(f"    Dropped tickets: {len(diff['dropped_tickets'])}")
    print("=" * 60)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the Valmo L1 eval harness.")
    parser.add_argument("--set", dest="eval_path", default=str(DEFAULT_EVAL_SET),
                        help=f"Path to eval JSONL (default: {DEFAULT_EVAL_SET})")
    parser.add_argument("--limit", type=int, default=0,
                        help="Run only the first N tickets (0 = all)")
    parser.add_argument("--no-save", action="store_true",
                        help="Print summary only; don't write to data/eval/runs/")
    parser.add_argument("--no-diff", action="store_true",
                        help="Skip diff against previous run")
    args = parser.parse_args(argv)

    eval_path = Path(args.eval_path)
    print(f"[Eval] loading {eval_path}...")
    eval_set = load_eval_set(eval_path)
    if args.limit > 0:
        eval_set = eval_set[:args.limit]
    if not eval_set:
        print("[Eval] no labeled tickets found — nothing to run.")
        print("[Eval] add labeled rows to your eval set; see schema in src/eval/harness.py")
        sys.exit(2)
    print(f"[Eval] running brain.process() on {len(eval_set)} ticket(s)...")

    # Lazy import — keeps import-time cheap and avoids brain init on --help
    from src.llm.agent_brain import get_agent_brain
    brain = get_agent_brain()

    results = evaluate(eval_set, brain)
    if args.no_diff:
        results.pop("diff_vs_last", None)
    print_summary(results)

    if not args.no_save:
        path = save_run(results)
        print(f"[Eval] saved run to {path}")


if __name__ == "__main__":
    main()
