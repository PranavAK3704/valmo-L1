"""
Run the REAL extract_ticket() and dump the captured payload + extracted
fields, so we can see exactly what came back from Kapture for one ticket.
"""
import asyncio, json, sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


async def recon(tid):
    from playwright.async_api import async_playwright
    from scrape_tickets_v2 import login, extract_ticket

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, slow_mo=50)
        page = await (await browser.new_context(viewport={"width": 1440, "height": 900})).new_page()
        await login(page)

        # Find ticket
        for status in ("C", "O", "P"):
            search = await page.evaluate(f"""
                async () => {{
                    const body = new URLSearchParams({{
                        sort_by_column:'last_conversation_time', type:'7', status:'{status}',
                        folder_id:'-1', query:'{tid}', page_no:'0', sort_type:'desc',
                        page_size:'10', response_type:'json', key_beautify:'yes', isElasticSearch:'true'
                    }});
                    const r = await fetch('/api/version3/ticket/get-ticket-list',
                        {{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:body.toString()}});
                    return r.json();
                }}
            """)
            tickets = (search.get("response") or {}).get("tickets") or []
            meta = next((t for t in tickets if str(t.get("ticketId"))==tid), None)
            if meta: break
        if not meta:
            print(f"NOT FOUND: {tid}"); await browser.close(); return

        task_id = str(meta.get("id", ""))
        print(f"task_id = {task_id}, queue = {meta.get('queueKey')}")
        print(f"creator email (list API): {meta.get('email')}")
        print(f"assignedTo: {meta.get('assignedTo')}")

        # Real extraction
        detail = await extract_ticket(page, task_id, tid)
        await browser.close()

        print("\n" + "=" * 80)
        print("TOP-LEVEL FIELDS RETURNED BY extract_ticket()")
        print("=" * 80)
        for k in ("subject_line", "hub_code_field", "awb_field", "sub_type_field",
                  "captain_email", "captain_problem_source"):
            print(f"  {k}: {detail.get(k)!r}")

        print(f"\n  full_description (len={len(detail.get('full_description') or '')}):")
        fd = detail.get("full_description") or ""
        for line in fd[:1500].splitlines()[:30]:
            print(f"    {line!r}")

        print(f"\n  captain_problem (len={len(detail.get('captain_problem') or '')}):")
        cp = detail.get("captain_problem") or ""
        for line in cp[:1500].splitlines()[:30]:
            print(f"    {line!r}")

        misplaced = detail.get("misplaced_description") or {}
        if misplaced:
            print(f"\n  misplaced_description: field={misplaced.get('field')!r}")
            print(f"    value: {(misplaced.get('value') or '')[:400]!r}")

        cap_msgs = detail.get("captain_messages") or []
        l1_msgs  = detail.get("l1_messages") or []
        print(f"\n  captain_messages: {len(cap_msgs)} entries")
        for i, m in enumerate(cap_msgs[:5]):
            print(f"    [{i}] sender={m.get('sender')!r} ts={m.get('ts')!r}")
            print(f"        body: {(m.get('body') or '')[:200]!r}")
        print(f"\n  l1_messages: {len(l1_msgs)} entries")
        for i, m in enumerate(l1_msgs[:5]):
            print(f"    [{i}] sender={m.get('sender')!r} ts={m.get('ts')!r}")
            print(f"        body: {(m.get('body') or '')[:200]!r}")

        print(f"\n  info_panel_fields ({len(detail.get('info_panel_fields') or {})}):")
        for k, v in (detail.get("info_panel_fields") or {}).items():
            v_str = str(v)[:300].replace("\n", " ")
            print(f"    {k!r}: {v_str!r}")

        # api_data dump for everything else
        api_data = detail.get("api_data") or {}
        print(f"\n  api_data keys: {list(api_data.keys())}")

        # Dump full payload for offline inspection
        outpath = ROOT / "data" / f"recon_{tid}.json"
        # Strip non-serializable bits
        dump = {k: v for k, v in detail.items() if k != "api_data"}
        dump["api_data_keys"] = list(api_data.keys())
        outpath.write_text(json.dumps(dump, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"\nFull payload written to: {outpath}")


if __name__ == "__main__":
    asyncio.run(recon(sys.argv[1] if len(sys.argv) > 1 else "779244875125"))
