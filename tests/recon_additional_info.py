"""Dump RAW additionalInfo.existing fields for one ticket so we can see
which field is leaking the L1 dispose text into `please_describe_issue`."""
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
    from scrape_tickets_v2 import login

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, slow_mo=50)
        page = await (await browser.new_context(viewport={"width":1440,"height":900})).new_page()
        await login(page)

        # Find ticket
        for status in ("C","O","P"):
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
            print("NOT FOUND"); await browser.close(); return
        task_id = str(meta.get("id",""))

        # Navigate to detail page (so all the API calls fire & we have session context)
        BASE = "https://valmostaging.kapturecrm.com"
        await page.goto(f"{BASE}/nui/tickets/completed_by_me/7/-1/0/detail/{task_id}/{tid}",
                          wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # Pull additionalInfo raw
        ai = await page.evaluate(f"""
            async () => {{
                const r = await fetch(`/api/version3/ticket/get-ticket-detail?id={task_id}&data_type=additional_info&status=C&last_con_id=0&last_con_type=O`);
                const j = await r.json();
                return j.response !== undefined ? j.response : j;
            }}
        """)
        await browser.close()

        existing = (ai or {}).get("existing") or {}
        fc = (ai or {}).get("fieldConfig") or {}
        id_to_name = {str(fid): cfg.get("displayName","") for fid, cfg in fc.items() if isinstance(cfg, dict)}

        print(f"\n=== TICKET {tid} — raw additionalInfo.existing dump ===")
        print(f"  # of 'existing' objects: {len(existing)}")
        for obj_id, obj in existing.items():
            if not isinstance(obj, dict): continue
            fields = obj.get("fields") or {}
            print(f"\n  --- existing[{obj_id}] ({len(fields)} fields) ---")
            for fid, val in fields.items():
                if not val: continue
                name = id_to_name.get(str(fid), "?")
                v_str = str(val)[:300].replace("\n"," / ")
                print(f"    [{fid}] {name!r}")
                print(f"        value ({len(str(val))} chars): {v_str!r}")


if __name__ == "__main__":
    asyncio.run(recon(sys.argv[1] if len(sys.argv) > 1 else "779244875125"))
