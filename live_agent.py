"""
Valmo L1 Live Agent — polls Kapture for pending tickets and processes them.

Usage:
    python live_agent.py              # runs once (for testing)
    python live_agent.py --loop       # polls every 5 minutes continuously

Mode is read from data/.mode file (review | autonomous).
In review mode: decisions saved to dashboard for human approval.
In autonomous mode: decisions saved + marked auto_send=True (dashboard shows them as Sent).

Does NOT currently send replies back to Kapture — that requires a separate step.
The dashboard is the interface: reviewer clicks Approve to act on the decision.
"""
import asyncio, json, logging, os, re, sys, time, argparse
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from playwright.async_api import async_playwright

from scrape_tickets_v2 import login, extract_ticket

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/live_agent.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

BASE_URL    = os.getenv("KAPTURE_URL", "https://valmostagging.kapturecrm.com")
PROCESSED   = Path("data/live_processed.json")   # {ticket_id: last_msg_time}

from src.api.mode import get_mode  # canonical mode source — gates auto_send


def load_processed() -> dict:
    """Returns {ticket_id: last_msg_time}. Supports old flat-list format for migration."""
    try:
        raw = json.loads(PROCESSED.read_text())
        if isinstance(raw, list):
            # Migrate old flat list → dict with empty timestamps
            return {tid: "" for tid in raw}
        return raw
    except:
        return {}


def save_processed(done: dict):
    PROCESSED.parent.mkdir(exist_ok=True)
    PROCESSED.write_text(json.dumps(done))


def is_new_or_updated(ticket: dict, done: dict) -> bool:
    """Return True if this ticket is new or has a new message since last processing."""
    tid = ticket["ticket_id"]
    last_seen = done.get(tid)
    if last_seen is None:
        return True  # never seen
    current_msg_time = ticket.get("last_conversation_time", "")
    if not current_msg_time or not last_seen:
        return False  # no time info — skip to avoid reprocessing
    return current_msg_time != last_seen  # new message arrived


def extract_awbs(text: str) -> list:
    return list(set(re.findall(r'VL[R]?\d{10,15}', text or '')))


async def fetch_pending_tickets(page) -> list:
    """Fetch tickets pending review — assigned to current user."""
    result = await page.evaluate("""
        async () => {
            const body = new URLSearchParams({
                sort_by_column: 'last_conversation_time', type: '5',
                status: 'P', folder_id: '-1', query: '',
                page_no: '0', sort_type: 'desc',
                page_size: '50', response_type: 'json',
                key_beautify: 'yes', isElasticSearch: 'true'
            });
            const r = await fetch('/api/version3/ticket/get-ticket-list', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: body.toString()
            });
            return await r.json();
        }
    """)
    batch = (result.get("response") or {}).get("tickets") or []
    tickets = []
    for t in batch:
        tid = str(t.get("ticketId", ""))
        if not tid:
            continue
        tickets.append({
            "task_id":               str(t.get("id", "")),
            "ticket_id":             tid,
            "subject":               (t.get("subject") or t.get("detail", ""))[:120],
            "queue_key":             t.get("queueKey", ""),
            "status":                t.get("status", ""),
            "email":                 t.get("email", ""),
            "phone":                 str(t.get("phone", "")),
            "detail":                t.get("detail", ""),
            "created_time":          t.get("createdTime", ""),
            "last_conversation_time": str(t.get("lastConversationTime", "") or t.get("lastUpdatedTime", "")),
        })
    return tickets


async def process_batch(page, tickets: list, done: dict) -> int:
    """Process one batch of new/updated tickets through the brain."""
    from src.llm.agent_brain import get_agent_brain
    from src.query_engine.metabase_engine import MetabaseQueryEngine
    from src.api.decision_store import save_decision

    brain  = get_agent_brain()
    engine = MetabaseQueryEngine()
    mode   = get_mode()
    new_count = 0

    for t in tickets:
        tid = t["ticket_id"]
        if not is_new_or_updated(t, done):
            continue
        if tid in done and done[tid] != t.get("last_conversation_time", ""):
            log.info(f"  Multi-turn: {tid} has new message, reprocessing")

        log.info(f"  Processing {tid} | {t['subject'][:60]}")
        try:
            # Extract full ticket data
            detail = await extract_ticket(page, t["task_id"], tid)
            full_ticket = {**t, **detail}

            # Use full description from INFO panel if available
            # Prefer the role-aware captain_problem (Fix 11). Fall back to the
            # canonical please_describe_issue field. Never use page_text_snippet —
            # it's the entire Kapture UI rendered as text.
            full_desc = (
                detail.get("captain_problem") or
                detail.get("full_description") or
                ""
            )
            if full_desc:
                full_ticket["detail"] = full_desc
            # Use full subject line from INFO panel if available
            if detail.get("subject_line"):
                full_ticket["subject"] = detail["subject_line"]

            # Extract AWBs — also check dedicated AWB field
            awbs = extract_awbs(full_ticket.get("detail", ""))
            awbs += extract_awbs(t["subject"])
            awbs += extract_awbs(detail.get("awb_field", ""))
            awbs += detail.get("awbs_on_page", [])
            full_ticket["awb_numbers"] = list(set(awbs))

            # Run Metabase queries
            query_results = []
            if awbs:
                params = {"awb_list": awbs, "partner_id": t.get("email", "")}
                for qname in ["get_loss_attribution", "get_shipment_scan_history_single"]:
                    try:
                        qr = engine.execute(qname, params)
                        query_results.append({
                            "query_name": qname,
                            "success": qr.success,
                            "data": qr.data,
                            "error": qr.error,
                        })
                    except Exception as e:
                        query_results.append({
                            "query_name": qname, "success": False,
                            "data": {"rows": []}, "error": str(e)
                        })

            # Single-call: Stage 0 + SOP + Gemini decision in brain.process()
            decision = brain.process(full_ticket, query_results)
            usage = getattr(decision, "usage", {}) or {}
            row_id = save_decision(full_ticket, decision, usage)
            log.info(
                f"    [{decision.action.upper()}] scenario={decision.scenario_identified} "
                f"conf={decision.confidence}/10 | saved id={row_id}"
            )

            done[tid] = t.get("last_conversation_time", "")
            new_count += 1

        except Exception as e:
            log.error(f"    FAILED: {e}")

        await page.wait_for_timeout(500)

    return new_count


async def run_once():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, slow_mo=50)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        log.info("Logging in to Kapture...")
        await login(page)

        await page.goto(f"{BASE_URL}/nui/tickets/completed_by_me/7/-1/0",
                        wait_until="networkidle", timeout=30000)

        done = load_processed()
        log.info(f"Fetching pending tickets (mode: {get_mode()})...")
        tickets = await fetch_pending_tickets(page)
        new_tickets = [t for t in tickets if is_new_or_updated(t, done)]
        log.info(f"Found {len(tickets)} pending, {len(new_tickets)} new/updated to process")

        if new_tickets:
            n = await process_batch(page, new_tickets, done)
            save_processed(done)
            log.info(f"Processed {n} new tickets")
        else:
            log.info("No new tickets to process")

        await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Poll continuously every 5 minutes")
    parser.add_argument("--interval", type=int, default=300, help="Poll interval in seconds")
    args = parser.parse_args()

    if args.loop:
        log.info(f"Starting live agent loop (interval: {args.interval}s)")
        while True:
            try:
                asyncio.run(run_once())
            except Exception as e:
                log.error(f"Run failed: {e}")
            log.info(f"Sleeping {args.interval}s until next poll...")
            time.sleep(args.interval)
    else:
        log.info("Running single pass...")
        asyncio.run(run_once())


if __name__ == "__main__":
    main()
