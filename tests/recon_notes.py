"""
Recon: log into Kapture, pull raw notes + info-panel for given ticket IDs,
dump the structure so we can identify the captain-vs-L1 discriminator.

Usage: python tests/recon_notes.py <ticket_id> [ticket_id ...]
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


async def recon(ticket_ids):
    from playwright.async_api import async_playwright
    from scrape_tickets_v2 import login

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, slow_mo=50)
        page = await (await browser.new_context(viewport={"width":1440,"height":900})).new_page()
        await login(page)

        for tid in ticket_ids:
            print(f"\n{'='*80}\nTICKET {tid}\n{'='*80}")
            # Search
            for status in ("C","O","P"):
                search = await page.evaluate(f"""
                    async () => {{
                        const body = new URLSearchParams({{
                            sort_by_column:'last_conversation_time', type:'7', status:'{status}',
                            folder_id:'-1', query:'{tid}', page_no:'0', sort_type:'desc',
                            page_size:'10', response_type:'json', key_beautify:'yes', isElasticSearch:'true'
                        }});
                        const r = await fetch('/api/version3/ticket/get-ticket-list',
                            {{method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body: body.toString()}});
                        return r.json();
                    }}
                """)
                tickets = (search.get("response") or {}).get("tickets") or []
                meta = next((t for t in tickets if str(t.get("ticketId"))==tid), None)
                if meta: break
            if not meta:
                print(f"  NOT FOUND")
                continue

            task_id = str(meta.get("id",""))
            print(f"  task_id    = {task_id}")
            print(f"  queue      = {meta.get('queueKey','')}")
            print(f"  creator email (from list API): {meta.get('email','')}")
            print(f"  assignedTo : {meta.get('assignedTo','')!r}")

            # Pull notes + conversations + email + ticket detail
            data = await page.evaluate(f"""
                async () => {{
                    const get = async (url) => {{
                        try {{ const r = await fetch(url); if (!r.ok) return null;
                              const j = await r.json(); return j.response !== undefined ? j.response : j; }}
                        catch(e) {{ return null; }}
                    }};
                    const t = '{task_id}'; const tid = '{tid}';
                    const base = '/api/version3/ticket/get-ticket-detail';
                    const [detail, notes, email, conv] = await Promise.all([
                        get(`${{base}}?id=${{t}}&ticket_id=${{tid}}&skip_unread_action=no&data_type=ticket`),
                        get(`${{base}}?id=${{t}}&data_type=notes`),
                        get(`${{base}}?id=${{t}}&ticket_id=${{tid}}&data_type=email&last_con_id=0&last_con_type=E`),
                        get(`${{base}}?id=${{t}}&ticket_id=${{tid}}&data_type=conversations&last_con_id=0`),
                    ]);
                    return {{detail, notes, email, conversations: conv}};
                }}
            """)

            # ── notes ──
            notes = data.get("notes")
            print(f"\n  --- notes payload shape ---")
            if isinstance(notes, dict):
                print(f"  keys: {list(notes.keys())}")
                # try common keys
                for k in ("notes","list","data","items"):
                    if k in notes and isinstance(notes[k], list):
                        for i, n in enumerate(notes[k][:5]):
                            print(f"  note[{i}] keys: {list(n.keys()) if isinstance(n,dict) else type(n).__name__}")
                            if isinstance(n, dict):
                                for kk in list(n.keys())[:25]:
                                    v = n[kk]
                                    if isinstance(v, str) and len(v) > 80: v = v[:80]+'...'
                                    print(f"    {kk}: {v!r}")
                                print()
                        break
            elif isinstance(notes, list):
                print(f"  list of {len(notes)} notes")
                for i, n in enumerate(notes[:5]):
                    print(f"  note[{i}] keys: {list(n.keys()) if isinstance(n,dict) else type(n).__name__}")
                    if isinstance(n, dict):
                        for kk in list(n.keys())[:25]:
                            v = n[kk]
                            if isinstance(v, str) and len(v) > 80: v = v[:80]+'...'
                            print(f"    {kk}: {v!r}")
                        print()

            # ── ticket detail → who's the creator? ──
            det = data.get("detail")
            print(f"\n  --- detail.ticket keys ---")
            if isinstance(det, dict):
                ticket_obj = det.get("ticket") or det
                if isinstance(ticket_obj, dict):
                    for k in ("createdById","createdByName","createdByEmail","assignedToName",
                              "assignedToEmail","email","name","customerEmail","customerName",
                              "userName","userEmail","customer"):
                        if k in ticket_obj:
                            v = ticket_obj[k]
                            if isinstance(v, dict): v = list(v.keys())
                            print(f"    {k}: {v!r}")

            # ── conversations ──
            conv = data.get("conversations")
            if conv:
                print(f"\n  --- conversations shape ---")
                if isinstance(conv, dict):
                    print(f"  keys: {list(conv.keys())[:15]}")
                    for k in ("conversations","emails","list"):
                        if k in conv and isinstance(conv[k], list) and conv[k]:
                            print(f"  first {k} entry keys: {list(conv[k][0].keys())[:20]}")
                            n = conv[k][0]
                            for kk in list(n.keys())[:20]:
                                v = n[kk]
                                if isinstance(v, str) and len(v) > 80: v = v[:80]+'...'
                                print(f"    {kk}: {v!r}")
                            break

            # ── email ──
            em = data.get("email")
            if em:
                print(f"\n  --- email shape ---")
                if isinstance(em, dict):
                    print(f"  keys: {list(em.keys())[:15]}")
                    for k in ("emails","list","emailList"):
                        if k in em and isinstance(em[k], list) and em[k]:
                            print(f"  first {k} entry keys: {list(em[k][0].keys())[:25]}")
                            n = em[k][0]
                            for kk in list(n.keys())[:25]:
                                v = n[kk]
                                if isinstance(v, str) and len(v) > 80: v = v[:80]+'...'
                                print(f"    {kk}: {v!r}")
                            break

        await browser.close()


def main():
    ids = sys.argv[1:] or ["779517636659", "779370998763", "779274776251"]
    asyncio.run(recon(ids))


if __name__ == "__main__":
    main()
