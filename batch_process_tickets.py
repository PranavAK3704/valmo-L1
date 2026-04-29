"""
Batch process scraped tickets through the brain for demo variety.
Usage: python batch_process_tickets.py [--count 20]
"""
import json, logging, re, sys, argparse
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

from src.llm.agent_brain import get_agent_brain
from src.api.decision_store import save_decision, get_conn

AWB_RE = re.compile(r'\b(VL\d{13}|EX\d{9})\b', re.IGNORECASE)

def extract_awbs(text: str) -> list:
    return list(set(AWB_RE.findall(text or "")))

def load_diverse_tickets(jsonl_path: str, count: int) -> list:
    """Load tickets with variety across queues and ticket types."""
    all_tickets = []
    with open(jsonl_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.strip():
                try:
                    t = json.loads(line)
                    if t.get('detail') and len(t.get('detail', '')) > 30:
                        all_tickets.append(t)
                except:
                    pass

    # Get already-processed ticket IDs to skip duplicates
    conn = get_conn()
    existing = {r[0] for r in conn.execute("SELECT ticket_id FROM decisions").fetchall()}
    conn.close()

    all_tickets = [t for t in all_tickets if str(t.get('ticket_id', '')) not in existing]
    log.info(f"  {len(all_tickets)} unprocessed tickets available")

    # Pick diverse selection by queue
    by_queue = {}
    for t in all_tickets:
        q = t.get('queue_key') or t.get('queue') or 'unknown'
        by_queue.setdefault(q, []).append(t)

    selected = []
    queue_order = sorted(by_queue.keys(), key=lambda q: -len(by_queue[q]))
    i = 0
    while len(selected) < count and i < 1000:
        for q in queue_order:
            if len(by_queue[q]) > 0 and len(selected) < count:
                selected.append(by_queue[q].pop(0))
        i += 1

    log.info(f"  Selected {len(selected)} tickets across {len(queue_order)} queues: {queue_order}")
    return selected


def process_ticket(brain, ticket: dict) -> dict:
    tid = str(ticket.get('ticket_id', ''))
    subject = ticket.get('subject', '')[:120]
    detail = ticket.get('detail', '')
    queue = ticket.get('queue_key') or ticket.get('queue') or ''

    full_ticket = {
        "ticket_id": tid,
        "task_id": str(ticket.get('task_id', '')),
        "subject": subject,
        "queue": queue,
        "queue_key": queue,
        "detail": detail,
        "awb_numbers": extract_awbs(detail) + extract_awbs(subject),
        "hub_code": ticket.get('hub_code_field') or ticket.get('hub_code') or "",
        "created_time": ticket.get('created_time', ''),
        "last_conversation_time": ticket.get('updated_time', ''),
        "email": ticket.get('email', ''),
        "phone": str(ticket.get('phone', '')),
    }

    decision = brain.process(full_ticket, [])
    usage = getattr(decision, 'usage', {}) or {}

    row_id = save_decision(full_ticket, decision, usage)
    return {"id": row_id, "ticket_id": tid, "action": decision.action,
            "scenario": decision.scenario_identified, "confidence": decision.confidence}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=20, help='Number of tickets to process')
    parser.add_argument('--source', default='data/scraped_tickets.jsonl')
    args = parser.parse_args()

    log.info(f"Loading diverse tickets from {args.source}")
    tickets = load_diverse_tickets(args.source, args.count)

    if not tickets:
        log.info("No new tickets to process")
        return

    brain = get_agent_brain()
    results = []

    for i, t in enumerate(tickets, 1):
        tid = t.get('ticket_id', '?')
        subj = t.get('subject', '')[:60]
        log.info(f"[{i}/{len(tickets)}] {tid} | {subj}")
        try:
            r = process_ticket(brain, t)
            results.append(r)
            log.info(f"  -> {r['action']} | {str(r['scenario'])[:50]} | conf={r['confidence']}")
        except Exception as e:
            log.error(f"  FAILED: {e}")

    # Summary
    from collections import Counter
    action_counts = Counter(r['action'] for r in results)
    log.info(f"\n=== DONE: {len(results)} processed ===")
    for action, cnt in action_counts.most_common():
        log.info(f"  {action}: {cnt}")


if __name__ == "__main__":
    main()
