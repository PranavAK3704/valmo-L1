"""
One-off: process 20 L&D tickets through the agent (with Stage 0 enabled).
Mix of W- LD (hardstop) and shipment_shortage queues.
"""
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ld_batch")

from src.llm.agent_brain import get_agent_brain
from src.api.decision_store import save_decision

import html as _html_mod

AWB_RE = re.compile(r'\b(VL[R]?\d{10,15})\b', re.IGNORECASE)


def clean_detail(raw: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', raw or "")
    text = _html_mod.unescape(text)
    text = text.replace(' ', ' ').replace('﻿', '').replace('​', '')
    return re.sub(r'[ \t]{3,}', '  ', text).strip()


_AUTO_NOISE_RX = re.compile(
    r"(auto[-\s]?disposed|auto[-\s]?closed|ticket has been (auto|automatically)|"
    r"system[-\s]generated notification|case (was|has been) closed.*evidence|"
    r"closed due to (lack|no) (of )?(evidence|response))",
    re.IGNORECASE,
)


def _is_real_ticket(t: dict) -> bool:
    """Skip auto-disposed system notifications — they have no captain content."""
    detail = (t.get("full_description") or t.get("detail") or "").strip()
    subject = (t.get("subject_line") or t.get("subject") or "").strip()
    blob = f"{subject}\n{detail}"
    if _AUTO_NOISE_RX.search(blob):
        return False
    # Also skip if there's basically nothing to read
    return len(detail) > 60


def load_ld_tickets(target=20):
    """Pick {target} REAL L&D captain tickets (W- LD + shipment_shortage), skipping
    auto-disposed system notifications. Most cached shipment_shortage entries are
    auto-disposed — real shortage cases live in W- LD with sub-type=shortage."""
    by_q = {"W- LD": [], "shipment_shortage": []}
    skipped = 0
    with open("data/scraped_tickets_v2.jsonl", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                t = json.loads(line)
                q = t.get("queue_key") or t.get("queue") or ""
                if q not in by_q:
                    continue
                if not _is_real_ticket(t):
                    skipped += 1
                    continue
                by_q[q].append(t)
            except Exception:
                pass

    log.info(f"Filtered out {skipped} auto-disposed/empty tickets")
    log.info(f"Pool: W- LD={len(by_q['W- LD'])}, shipment_shortage={len(by_q['shipment_shortage'])}")

    # Even split if both have content; otherwise pull all from whichever has them
    selected = []
    half = target // 2
    if by_q["shipment_shortage"]:
        take_ss = min(half, len(by_q["shipment_shortage"]))
        selected.extend(by_q["shipment_shortage"][:take_ss])
    take_ld = target - len(selected)
    selected.extend(by_q["W- LD"][:take_ld])
    return selected[:target]


def to_ticket_dict(t: dict) -> dict:
    queue = t.get("queue_key") or t.get("queue") or ""
    raw_detail = (
        t.get("full_description")
        or t.get("detail")
        or t.get("subject", "")
    )
    detail = clean_detail(raw_detail)
    subject = (t.get("subject_line") or t.get("subject") or "")[:200]
    awbs = list(set(AWB_RE.findall(detail + " " + subject)))
    awbs += t.get("awbs_on_page") or []
    awbs = list(set(awbs))
    return {
        "ticket_id":     str(t.get("ticket_id", "")),
        "task_id":       str(t.get("task_id", "")),
        "subject":       subject,
        "queue":         queue,
        "queue_key":     queue,
        "sub_queue":     t.get("sub_type_field") or "",
        "detail":        detail,
        "description":   detail,
        "hub_code":      t.get("hub_code_field") or "",
        "awb_numbers":   awbs,
        "created_time":  t.get("created_time", ""),
        "email":         t.get("email", ""),
        "phone":         str(t.get("phone", "")),
    }


def process_one(brain, ticket: dict) -> dict:
    decision = brain.process(ticket, [])
    usage = getattr(decision, "usage", {}) or {}
    row_id = save_decision(ticket, decision, usage)
    # Pull Stage 0 detail out of the thinking steps
    stage0_step = next(
        (s for s in decision.thinking_steps if "Stage 0" in s.get("label", "")),
        None,
    )
    return {
        "row_id":    row_id,
        "ticket_id": ticket["ticket_id"],
        "queue":     ticket["queue"],
        "action":    decision.action,
        "scenario":  decision.scenario_identified,
        "confidence": decision.confidence,
        "stage0":    (stage0_step or {}).get("detail", "")[:120],
    }


def main():
    log.info("Loading L&D tickets from cache...")
    tickets = load_ld_tickets(20)
    log.info(f"Selected {len(tickets)} tickets")

    raw_tickets = [to_ticket_dict(t) for t in tickets]
    brain = get_agent_brain()

    results = []
    t_start = time.time()

    # 3 workers — Gemini Flash Tier 1 free quota tolerates this fine
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(process_one, brain, tk): tk["ticket_id"]
            for tk in raw_tickets
        }
        for i, fut in enumerate(as_completed(futures), 1):
            tid = futures[fut]
            try:
                r = fut.result()
                results.append(r)
                log.info(
                    f"[{i:>2}/{len(raw_tickets)}] {r['ticket_id']} | {r['queue']:<20} "
                    f"-> {r['action']:<10} | {str(r['scenario'])[:25]:<25} | "
                    f"conf={r['confidence']} | s0: {r['stage0']}"
                )
            except Exception as e:
                log.error(f"  [{tid}] FAILED: {e}")

    elapsed = time.time() - t_start
    from collections import Counter
    actions = Counter(r["action"] for r in results)
    by_queue = {}
    for r in results:
        by_queue.setdefault(r["queue"], Counter())[r["action"]] += 1

    log.info(f"\n{'='*60}")
    log.info(f"DONE — {len(results)} processed in {elapsed:.1f}s ({elapsed/max(len(results),1):.1f}s/ticket)")
    log.info("Action breakdown:")
    for a, c in actions.most_common():
        log.info(f"  {a:>12}: {c}")
    log.info("By queue:")
    for q, ctr in by_queue.items():
        log.info(f"  {q}: {dict(ctr)}")


if __name__ == "__main__":
    main()
