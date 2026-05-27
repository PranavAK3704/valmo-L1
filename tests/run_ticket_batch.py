"""
Run a list of Kapture ticket IDs through the brain pipeline and report results.

No DB write. No reply send. Pure dry-run — useful for verifying the new
guardrails / retrieval grouping / mode gate on fresh tickets without
polluting decisions.db.

Usage:
    python tests/run_ticket_batch.py 779607702065 779450625342 ...

Or import + call run_batch(ids) programmatically.
"""

import asyncio
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


async def _fetch_ticket_via_kapture(page, ticket_id: str) -> dict | None:
    """Replicates run_dashboard.fetch_live_ticket's search step. Tries the
    completed-by-me queue first, then the open queue, returns ticket meta
    (with task_id) or None."""
    for status in ("C", "O", "P"):
        search = await page.evaluate(f"""
            async () => {{
                const body = new URLSearchParams({{
                    sort_by_column: 'last_conversation_time', type: '7',
                    status: '{status}', folder_id: '-1', query: '{ticket_id}',
                    page_no: '0', sort_type: 'desc', page_size: '10',
                    response_type: 'json', key_beautify: 'yes', isElasticSearch: 'true'
                }});
                const r = await fetch('/api/version3/ticket/get-ticket-list', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                    body: body.toString()
                }});
                return await r.json();
            }}
        """)
        tickets = (search.get("response") or {}).get("tickets") or []
        for t in tickets:
            if str(t.get("ticketId")) == str(ticket_id):
                return t
    return None


def _shape_for_brain(t: dict, detail: dict) -> dict:
    """Combine list-API meta + extract_ticket() detail into a brain-ready dict."""
    import re as _re
    AWB_RE = _re.compile(r'\b(VL[R]?\d{10,15})\b', _re.IGNORECASE)
    # Priority: captain_problem (role-aware) > full_description (canonical
    # please_describe_issue field). Do NOT fall back to t.get("detail") —
    # that's Kapture's ticket-state body which mirrors the latest L1 dispose
    # draft, not the captain's voice. Same root cause as the ticket_obj.detail
    # bug fixed earlier. If nothing resolves, leave empty — the brain will
    # render "(No captain problem statement could be extracted)" in the prompt
    # and use action=needs_info.
    desc = (
        detail.get("captain_problem")
        or detail.get("full_description")
        or ""
    )
    subject = detail.get("subject_line") or (t.get("subject") or t.get("detail", ""))[:120]
    awbs = list(set(AWB_RE.findall(desc + " " + subject)))
    awbs += (detail.get("awbs_on_page") or [])
    awbs = list(set(awbs))
    return {
        "ticket_id":   str(t.get("ticketId", "")),
        "task_id":     str(t.get("id", "")),
        "subject":     subject,
        "queue":       t.get("queueKey", ""),
        "queue_key":   t.get("queueKey", ""),
        "detail":      desc,                              # legacy field, still populated for safety
        "hub_code":    detail.get("hub_code_field", ""),
        "awb_numbers": awbs,
        "created_time": t.get("createdTime", ""),
        "email":       t.get("email", ""),
        # Role-aware extraction fields (consumed by agent_brain._build_prompt)
        "captain_email":          detail.get("captain_email", t.get("email", "")),
        "captain_problem":        detail.get("captain_problem", ""),
        "captain_problem_source": detail.get("captain_problem_source", ""),
        "captain_messages":       detail.get("captain_messages", []),
        "l1_messages":            detail.get("l1_messages", []),
        "misplaced_description":  detail.get("misplaced_description", {}),
        "misplaced_attachment_field": detail.get("misplaced_attachment_field", ""),
        "info_panel_fields":      detail.get("info_panel_fields", {}),
        # Attachment URLs — read by brain for OCR fallback when captain skipped text
        "attachment_urls":        detail.get("attachment_urls", []),
    }


def _print_result(tid: str, decision, ticket: dict, error: str = ""):
    """Compact per-ticket report."""
    print()
    print("=" * 78)
    print(f"  TICKET {tid}")
    print("=" * 78)
    if error:
        print(f"  ERROR: {error}")
        return
    queue = ticket.get("queue", "?")
    subj  = (ticket.get("subject") or "")[:100]
    awbs  = ticket.get("awb_numbers") or []
    print(f"  queue        : {queue}")
    print(f"  subject      : {subj}")
    print(f"  awbs         : {', '.join(awbs) if awbs else '(none)'}")

    s0 = decision.stage0 or {}
    if s0.get("physical_event"):
        print()
        print(f"  STAGE 0:")
        print(f"    physical_event : {s0.get('physical_event','')[:120]}")
        print(f"    loss_type      : {s0.get('loss_type','')!r}")
        print(f"    scenario_hint  : {s0.get('scenario_hint','')!r}")
        print(f"    confidence     : {s0.get('domain_confidence','')!r}")
    else:
        print(f"  STAGE 0       : (no diagnosis — queue may be placeholder)")

    print()
    print(f"  DECISION:")
    print(f"    action       : {decision.action.upper()}")
    print(f"    scenario     : {decision.scenario_identified}")
    print(f"    confidence   : {decision.confidence}/10")
    print(f"    auto_send    : {decision.auto_send}")
    if decision.guardrail_triggered:
        print(f"    GUARDRAIL    : *** {decision.guardrail_triggered} ***")

    if decision.action == "respond" and decision.response_to_captain:
        print()
        print(f"  REPLY DRAFT (first 400 chars):")
        for line in textwrap.wrap(decision.response_to_captain[:400], width=74):
            print(f"    {line}")
    elif decision.action == "escalate":
        print()
        print(f"  ESCALATE     : queue={decision.escalation_queue}")
        print(f"  REASON       : {decision.escalation_reason[:200]}")
    elif decision.action == "stuck":
        print()
        print(f"  STUCK Q      : {decision.stuck_question[:300]}")
    elif decision.action == "needs_info":
        print()
        print(f"  NEEDS        : {', '.join(decision.missing_fields)}")

    if decision.reasoning:
        print()
        print(f"  REASONING:")
        for line in textwrap.wrap(decision.reasoning[:500], width=74):
            print(f"    {line}")


async def run_batch(ticket_ids: list[str], save: bool = False):
    from playwright.async_api import async_playwright
    from scrape_tickets_v2 import login, extract_ticket
    from src.llm.agent_brain import get_agent_brain
    from src.query_engine.metabase_engine import MetabaseQueryEngine

    brain = get_agent_brain()
    try:
        engine = MetabaseQueryEngine()
    except Exception:
        engine = None
    save_decision = None
    if save:
        from src.api.decision_store import save_decision as _sd
        save_decision = _sd

    mode_tag = "SAVING to decisions.db" if save else "no DB write"
    print(f"\n[Batch] processing {len(ticket_ids)} ticket(s) — {mode_tag}\n")
    print("Logging in to Kapture...")

    summary = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, slow_mo=50)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        await login(page)
        print("Login OK\n")

        for i, tid in enumerate(ticket_ids, 1):
            print(f"[{i}/{len(ticket_ids)}] fetching {tid}...")
            try:
                meta = await _fetch_ticket_via_kapture(page, tid)
                if not meta:
                    _print_result(tid, None, {}, error="Not found in Kapture (any status)")
                    summary.append((tid, "NOT_FOUND", "", 0.0, ""))
                    continue
                detail = await extract_ticket(page, str(meta.get("id", "")), tid)
                ticket = _shape_for_brain(meta, detail)
            except Exception as e:
                _print_result(tid, None, {}, error=f"scrape failed: {e}")
                summary.append((tid, "SCRAPE_ERR", "", 0.0, ""))
                continue

            # Optional: Metabase queries when AWBs present
            qr = []
            if ticket["awb_numbers"] and engine is not None:
                params = {"awb_list": ticket["awb_numbers"], "partner_id": ticket.get("email", "")}
                for qname in ["get_loss_attribution", "get_shipment_scan_history_single"]:
                    try:
                        r = engine.execute(qname, params)
                        qr.append({"query_name": qname, "success": r.success,
                                    "data": r.data, "error": r.error})
                    except Exception as e:
                        qr.append({"query_name": qname, "success": False,
                                    "data": {"rows": []}, "error": str(e)})

            try:
                decision = brain.process(ticket, qr)
                row_id = None
                if save_decision is not None:
                    usage = getattr(decision, "usage", {}) or {}
                    row_id = save_decision(ticket, decision, usage)
                _print_result(tid, decision, ticket)
                if row_id:
                    print(f"  → saved as decision id={row_id}")
                summary.append((
                    tid, decision.action.upper(), decision.scenario_identified,
                    decision.confidence, decision.guardrail_triggered or "",
                ))
            except Exception as e:
                _print_result(tid, None, ticket, error=f"brain failed: {e}")
                summary.append((tid, "BRAIN_ERR", "", 0.0, ""))

            await page.wait_for_timeout(500)

        await browser.close()

    # ── Summary table ──
    print()
    print("=" * 78)
    print("  BATCH SUMMARY")
    print("=" * 78)
    print(f"  {'TICKET':<14} {'ACTION':<12} {'SCENARIO':<10} {'CONF':>5}  GUARDRAIL")
    print(f"  {'-'*14} {'-'*12} {'-'*10} {'-'*5}  {'-'*30}")
    for tid, act, scn, cf, g in summary:
        print(f"  {tid:<14} {act:<12} {scn:<10} {cf:>5.1f}  {g}")
    print()

    return summary


def main():
    args = sys.argv[1:]
    save = False
    if args and args[0] in ("--save", "-s"):
        save = True
        args = args[1:]
    if not args:
        print("Usage: python tests/run_ticket_batch.py [--save] <ticket_id> [ticket_id ...]")
        print("  --save   persist decisions to decisions.db (else dry-run)")
        sys.exit(2)
    asyncio.run(run_batch(args, save=save))


if __name__ == "__main__":
    main()
