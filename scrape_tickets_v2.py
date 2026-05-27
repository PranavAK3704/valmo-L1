"""
Kapture Ticket Scraper v3 — Network Interception

Problem with v2: called wrong API data_types, conversation came back empty.
Fix: intercept ALL network responses while the ticket page loads — Kapture's
own frontend fetches the right endpoints, we just listen and capture them.

Output:
  data/scraped_tickets_v2.jsonl  — full data per ticket
  data/ground_truth.jsonl        — clean (captain_message, agent_reply) pairs for accuracy testing

Usage:
    python scrape_tickets_v2.py
"""

import asyncio, html as html_mod, json, logging, os, re, sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from playwright.async_api import async_playwright, Page, Response

# Windows console fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/scrape_v2.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

BASE_URL    = os.getenv("KAPTURE_URL", "https://valmostagging.kapturecrm.com").rstrip("/")
EMAIL       = os.getenv("KAPTURE_EMAIL", "")
PASSWORD    = os.getenv("KAPTURE_PASSWORD", "")
OUTPUT      = Path("data/scraped_tickets_v2.jsonl")
GROUND_TRUTH = Path("data/ground_truth.jsonl")
HEADLESS    = os.getenv("HEADLESS", "false").lower() == "true"
DELAY_MS    = 1500
FOLDER_TYPE = 7


# ─── Resume support ───────────────────────────────────────────────

def load_done() -> set:
    done = set()
    for f in [OUTPUT, GROUND_TRUTH]:
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                try: done.add(str(json.loads(line)["ticket_id"]))
                except: pass
    log.info(f"Already scraped: {len(done)} tickets")
    return done

def save_record(path: Path, data: dict):
    path.parent.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


# ─── Login ────────────────────────────────────────────────────────

async def login(page: Page):
    log.info(f"Logging in as {EMAIL}")
    # Use domcontentloaded instead of networkidle — Kapture has long-poll
    # XHRs that never let networkidle fire under normal conditions.
    await page.goto(f"{BASE_URL}/nui/login", wait_until="domcontentloaded", timeout=60000)
    await page.locator('input[name="userName"]').first.fill(EMAIL)
    await page.locator('input[type="password"]').first.fill(PASSWORD)
    await page.locator('button:has-text("Log in")').first.click()
    await page.wait_for_function(
        "() => !window.location.href.includes('/nui/login')", timeout=60000
    )
    await page.wait_for_timeout(2000)
    log.info("Logged in OK")


# ─── Collect ticket list ──────────────────────────────────────────

async def collect_ticket_ids(page: Page) -> list[dict]:
    list_url = f"{BASE_URL}/nui/tickets/list/7/-1/0"
    await page.goto(list_url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    all_tickets, seen, start = [], set(), 0
    page_size = 50

    while True:
        result = await page.evaluate(f"""
            async () => {{
                const body = new URLSearchParams({{
                    sort_by_column: 'last_conversation_time', type: '{FOLDER_TYPE}',
                    status: 'C', folder_id: '-1', query: '',
                    page_no: '{start // page_size}', sort_type: 'desc',
                    page_size: '{page_size}', response_type: 'json',
                    key_beautify: 'yes', isElasticSearch: 'true'
                }});
                const r = await fetch('/api/version3/ticket/get-ticket-list', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                    body: body.toString()
                }});
                return await r.json();
            }}
        """)
        batch = (result.get("response") or {}).get("tickets") or []
        if not batch: break

        new = 0
        for t in batch:
            tid = str(t.get("ticketId", ""))
            if not tid or tid in seen: continue
            seen.add(tid)
            all_tickets.append({
                "task_id":      str(t.get("id", "")),
                "ticket_id":    tid,
                "subject":      (t.get("subject") or t.get("detail", "")),
                "queue_key":    t.get("queueKey", ""),
                "status":       t.get("status", ""),
                "email":        t.get("email", ""),
                "phone":        str(t.get("phone", "")),
                "detail":       t.get("detail", ""),
                "created_time": t.get("createdTime", ""),
            })
            new += 1

        end_idx = (result.get("response") or {}).get("endIndex", start + len(batch))
        log.info(f"  Page {start // page_size}: +{new} tickets (total {len(all_tickets)})")
        if len(batch) < page_size: break
        start = int(end_idx) + 1

    log.info(f"Collected {len(all_tickets)} tickets total")
    return all_tickets


# ─── Extract one ticket with network interception ─────────────────

async def extract_ticket(page: Page, task_id: str, ticket_id: str) -> dict:
    """
    Navigate to ticket detail page. Intercept ALL API responses that Kapture's
    frontend fetches — this captures the real conversation endpoint automatically.
    """
    captured: dict[str, any] = {}
    tasks_pending: list[asyncio.Task] = []

    async def _handle(response: Response):
        url = response.url
        if response.status != 200 or "/api/" not in url:
            return
        try:
            body = await response.json()
            resp_body = body.get("response", body) if isinstance(body, dict) else body
            url_lower = url.lower()

            # Classify by URL keywords
            if any(k in url_lower for k in ["conversation", "email", "mail", "compose"]):
                captured.setdefault("conversations", [])
                if isinstance(resp_body, list):
                    captured["conversations"].extend(resp_body)
                elif isinstance(resp_body, dict):
                    captured["conversations"].append(resp_body)

            elif "history" in url_lower:
                captured["history"] = resp_body

            elif "attachment" in url_lower:
                captured["attachments"] = resp_body

            elif "custom" in url_lower or "additional" in url_lower:
                captured["customFields"] = resp_body

            elif "get-ticket-detail" in url_lower:
                # May contain different data_types
                if isinstance(resp_body, dict):
                    captured.update(resp_body)

        except Exception:
            pass

    def _sync_handle(response: Response):
        task = asyncio.create_task(_handle(response))
        tasks_pending.append(task)

    page.on("response", _sync_handle)

    detail_url = f"{BASE_URL}/nui/tickets/completed_by_me/7/-1/0/detail/{task_id}/{ticket_id}"
    # Use domcontentloaded — Kapture's long-poll XHRs prevent networkidle
    # from ever firing under normal conditions, same as the login flow.
    await page.goto(detail_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)   # let lazy-loaded calls finish

    # Also explicitly call conversation APIs we know about
    extra = await page.evaluate(f"""
        async () => {{
            const get = async (url) => {{
                try {{
                    const r = await fetch(url);
                    if (!r.ok) return null;
                    const j = await r.json();
                    return j.response !== undefined ? j.response : j;
                }} catch(e) {{ return null; }}
            }};

            const taskId = '{task_id}';
            const tid    = '{ticket_id}';
            const base   = '/api/version3/ticket/get-ticket-detail';

            // Try every data_type variant we know
            const [
                detailData, histData, emailData, conData,
                noteData, cfData, emailList
            ] = await Promise.all([
                get(`${{base}}?id=${{taskId}}&ticket_id=${{tid}}&skip_unread_action=no&data_type=ticket`),
                get(`${{base}}?id=${{taskId}}&data_type=history&fetch_action_name=yes`),
                get(`${{base}}?id=${{taskId}}&ticket_id=${{tid}}&data_type=email&last_con_id=0&last_con_type=E`),
                get(`${{base}}?id=${{taskId}}&ticket_id=${{tid}}&data_type=conversations&last_con_id=0`),
                get(`${{base}}?id=${{taskId}}&data_type=notes`),
                get(`${{base}}?id=${{taskId}}&data_type=additional_info&status=C&last_con_id=0&last_con_type=O`),
                get(`/api/version3/ticket/get-ticket-conversations?task_id=${{taskId}}&type=E&last_id=0`),
            ]);

            return {{
                detail: detailData, history: histData,
                email: emailData, conversations: conData,
                notes: noteData, additionalInfo: cfData,
                emailList: emailList,
            }};
        }}
    """)

    # Wait for intercepted response tasks
    if tasks_pending:
        await asyncio.gather(*tasks_pending, return_exceptions=True)

    page.remove_listener("response", _sync_handle)

    # Merge explicit calls into captured
    for k, v in (extra or {}).items():
        if v is not None and v != {} and v != []:
            captured[k] = v

    # ── Extract visible sent messages from DOM ─────────────────────
    sent_msgs = await _extract_sent_messages(page)

    # ── Extract all AWBs from full page text ───────────────────────
    try:
        page_text = await page.locator("body").inner_text(timeout=3000)
        awbs = list(set(re.findall(r'VL[R]?\d{10,15}', page_text)))
    except Exception:
        page_text, awbs = "", []

    # ── Parse structured fields from additional_info API response ───
    parsed = _parse_additional_info(captured)

    # ── Scrape INFO panel from DOM (gets full rendered text incl. HTML tables) ──
    panel_fields = await _extract_info_panel_fields(page)

    # The ticket object from get-ticket-detail has full 'detail' field
    ticket_obj = {}
    if captured.get("detail") and isinstance(captured["detail"], dict):
        ticket_obj = captured["detail"].get("ticket") or captured["detail"]

    # Canonical captain description comes ONLY from field 26926 ("Please Describe
    # Issue In Detail"). The Kapture-internal `ticket.detail` field looks similar
    # but is actually the LATEST dispose draft / ticket-state body — i.e. L1 voice.
    # Falling back to it pollutes captain_problem with L1 reply text.
    # See ticket 779244875125 — described in the diff that introduced this.
    api_desc_raw = parsed.get("please_describe_issue") or ""
    api_desc     = _strip_html(api_desc_raw)

    # DOM gives rendered text — tables come out as tab-separated columns
    dom_desc_label = (
        panel_fields.get("Please Describe Issue In Detail") or
        panel_fields.get("Issue Description") or
        ""
    )

    # Normalize non-breaking spaces from DOM innerText before comparison
    dom_desc_label = dom_desc_label.replace('\u00a0', ' ').replace('\ufeff', '').replace('\u200b', '').strip()

    # Prefer whichever is longer (DOM usually has more since API truncates)
    if len(dom_desc_label) > len(api_desc.strip()):
        canonical_description = dom_desc_label
        log.info(f"[extract_ticket] Using DOM description ({len(canonical_description)} chars) — API had {len(api_desc)} chars")
    else:
        canonical_description = api_desc

    # ── Role-aware thread parsing ──────────────────────────────────
    # The canonical captain email comes from the ticket detail object.
    captain_email = ""
    if isinstance(ticket_obj, dict):
        captain_email = (ticket_obj.get("email") or ticket_obj.get("customerEmail")
                         or ticket_obj.get("userEmail") or "")

    l1_notes_from_notes_table = _parse_notes(captured)
    email_thread = _parse_email_thread(captured, captain_email)
    captain_messages = [m for m in email_thread if m["role"] == "captain"]
    l1_messages_from_email = [m for m in email_thread if m["role"] == "l1"]

    # Combine all L1 voice for downstream context
    l1_messages = sorted(l1_notes_from_notes_table + l1_messages_from_email,
                          key=lambda m: m.get("ts") or "")

    # ── Misplaced-description guardrail ───────────────────────────
    misplaced = _detect_misplaced_description(panel_fields, canonical_description)

    # Detect "attachment uploaded into wrong field" — captains sometimes drop
    # file URLs into the AWB field or other short fields. Surface this so the
    # agent can offer to read the attachment instead of demanding text.
    # Cover xlsx/xls/csv too — Excel sheets of AWBs are common.
    _ATT_EXT_RE = re.compile(r"\.(jpe?g|png|pdf|webp|gif|xlsx|xls|csv)\b", re.I)
    _STORAGE_HINT_RE = re.compile(r"googleapis\.com|/storage/|kapture-p-v2", re.I)

    misplaced_attachment = ""
    for label, val in (panel_fields or {}).items():
        if (label or "").strip().lower() in _DESCRIPTION_FIELD_NAMES:
            continue
        v = str(val or "")
        if _ATT_EXT_RE.search(v) or _STORAGE_HINT_RE.search(v):
            misplaced_attachment = label
            break
    awb_field_raw = parsed.get("awbs") or ""
    if _ATT_EXT_RE.search(awb_field_raw) or _STORAGE_HINT_RE.search(awb_field_raw):
        # awb_field has a non-AWB URL — flag it.
        if not misplaced_attachment:
            misplaced_attachment = "AW Bs"

    # ── Promote URLs found in awb_field (and other short fields) into
    # attachment_urls so the OCR/Excel-parser pipeline picks them up.
    # Without this, files uploaded into the AWB form slot are silently lost.
    existing_urls = list(parsed.get("attachment_urls") or [])
    seen_urls = set(existing_urls)
    _URL_RE = re.compile(r"https?://[^\s,;'\"]+", re.I)
    sources_to_scan = [awb_field_raw] + [
        str(v or "") for k, v in (panel_fields or {}).items()
        if (k or "").strip().lower() not in _DESCRIPTION_FIELD_NAMES
    ]
    for src in sources_to_scan:
        for u in _URL_RE.findall(src):
            # Only count file-like URLs — avoid pulling in random http links from text
            if _ATT_EXT_RE.search(u) or _STORAGE_HINT_RE.search(u):
                if u not in seen_urls:
                    existing_urls.append(u)
                    seen_urls.add(u)
                    log.info(f"[extract_ticket] promoted URL into attachment_urls: {u[:120]}")
    parsed["attachment_urls"] = existing_urls

    # ── Priority-laddered captain_problem resolver ────────────────
    # 1) canonical description field if substantive
    # 2) first captain email/conversation message
    # 3) misplaced field content (captain typed in the wrong slot)
    # 4) concatenated captain messages
    # 5) empty (agent will go needs_info)
    captain_problem = ""
    captain_problem_source = ""
    if canonical_description and len(canonical_description.strip()) >= 30:
        captain_problem = canonical_description.strip()
        captain_problem_source = "please_describe_issue"
    elif captain_messages:
        captain_problem = captain_messages[0]["body"]
        captain_problem_source = f"first_captain_message:{captain_messages[0]['ts']}"
    elif misplaced:
        captain_problem = misplaced["value"]
        captain_problem_source = f"misplaced_field:{misplaced['field']}"
    elif captain_messages:
        captain_problem = "\n\n".join(m["body"] for m in captain_messages[:3])
        captain_problem_source = "concatenated_captain_messages"

    if not captain_problem:
        log.info(f"[extract_ticket] No captain_problem resolvable — agent will go needs_info")
    else:
        log.info(f"[extract_ticket] captain_problem source={captain_problem_source!r} "
                 f"len={len(captain_problem)}")
    if misplaced:
        log.warning(f"[extract_ticket] MISPLACED description detected in field "
                    f"{misplaced['field']!r} ({len(misplaced['value'])} chars)")
    if misplaced_attachment:
        log.warning(f"[extract_ticket] MISPLACED attachment detected in field "
                    f"{misplaced_attachment!r}")

    return {
        "url":               detail_url,
        "scraped_at":        datetime.utcnow().isoformat(),
        "api_data":          captured,
        "sent_messages":     sent_msgs,
        "awbs_on_page":      awbs,
        "page_text_snippet": page_text[:3000],
        # ── Top-level clean fields ──
        "full_description":  canonical_description,    # legacy: what was in the description field
        "subject_line":      parsed.get("subject_line") or (ticket_obj.get("taskTitle") if isinstance(ticket_obj, dict) else "") or "",
        "hub_code_field":    parsed.get("hub_code") or "",
        "awb_field":         parsed.get("awbs") or "",
        "sub_type_field":    parsed.get("sub_type") or (ticket_obj.get("folders", [None, None, None])[2] if isinstance(ticket_obj, dict) else "") or "",
        "sub_sub_type_field":parsed.get("sub_sub_type") or "",
        "attachment_urls":   parsed.get("attachment_urls") or [],  # list of S3 URLs
        # ── Role-aware extraction (new) ──
        "captain_email":     captain_email,
        "captain_problem":   captain_problem,
        "captain_problem_source": captain_problem_source,
        "captain_messages":  captain_messages,           # all captain voice from email thread
        "l1_messages":       l1_messages,                # all L1 voice (notes table + L1 emails)
        "misplaced_description": misplaced,              # {} or {"field": ..., "value": ...}
        "misplaced_attachment_field": misplaced_attachment,  # "" or field name where image URL leaked in
        "info_panel_fields": panel_fields,               # full raw panel for audit
    }


# ─── Role-aware thread parsing ────────────────────────────────────
# Notes table = exclusively L1 voice (internal staff dispose drafts + info notes).
# Captain's voice lives in email/conversations endpoints, OR misplaced into
# info-panel fields (Transaction ID, Previous Ticket, etc.).
#
# Discriminator for email senders: anyone @meesho.com (or matching the
# ticket's assignedToEmail) is L1; everything else is captain. The captain's
# canonical email comes from ticket.detail.ticket.email.

_L1_EMAIL_DOMAINS = ("@meesho.com", "@valmostaging.kapturecrm.com",
                     "@valmostagging.kapturecrm.com")  # cover both spellings

# Field names in the info panel that are EXPECTED to hold the description.
# Everything else is checked for misplaced prose.
_DESCRIPTION_FIELD_NAMES = {
    "please describe issue in detail",
    "issue description",
    "describe issue",
}
# Field names that are EXPECTED to be short / structured (IDs, codes, flags).
# These are the prime candidates for misplaced descriptions.
_SHORT_FIELD_NAMES = {
    "transaction id", "transactionid",
    "hub code", "hub_code",
    "aw bs", "awbs", "awb numbers",
    "sub type", "sub sub type",
    "previous ticket raised for this concern if any",
    "previous ticket raised", "previous ticket",
    "current landing volume", "promised load if any",
    "shipments impacted", "request type", "issue type",
    "web form attachement", "ticket attachement",
}


def _strip_dispose(detail: str) -> str:
    """Remove the <dispose>...</dispose> wrapper Kapture uses for outgoing L1
    drafts. Handles both balanced and unterminated tags."""
    if not detail:
        return ""
    s = re.sub(r"^\s*<dispose>", "", detail)
    s = re.sub(r"</dispose>\s*$", "", s)
    return s


def _strip_html_minimal(s: str) -> str:
    """Strip HTML tags + collapse whitespace for prompt display."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace(" ", " ").replace("​", "").replace("﻿", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_notes(captured: dict) -> list[dict]:
    """Extract entries from the notes table. Every note in this table is
    authored by Kapture-internal staff (L1 agents). Returns:
        [{role: 'l1', sender: name, body: cleaned_text, ts: date, raw_type: ...}, ...]
    sorted by date ascending.
    """
    raw_notes = captured.get("notes") or {}
    items = []
    if isinstance(raw_notes, dict):
        items = raw_notes.get("notes") or raw_notes.get("list") or []
    elif isinstance(raw_notes, list):
        items = raw_notes
    out = []
    for n in items:
        if not isinstance(n, dict):
            continue
        body = _strip_html_minimal(_strip_dispose(n.get("detail") or ""))
        if not body:
            continue
        out.append({
            "role":     "l1",  # notes endpoint is exclusively L1
            "sender":   n.get("creatorName") or n.get("memberName") or "L1",
            "body":     body,
            "ts":       n.get("date", ""),
            "raw_type": n.get("type", ""),
            "note_id":  n.get("id"),
        })
    out.sort(key=lambda x: x["ts"] or "")
    return out


def _parse_email_thread(captured: dict, captain_email: str) -> list[dict]:
    """Extract messages from email + conversations endpoints. Classify sender
    as 'captain' vs 'l1' using email match + L1 domain heuristic. Returns
    chronologically-ordered list of {role, sender, sender_email, body, ts}."""
    captain_email = (captain_email or "").strip().lower()

    def _classify(sender_email: str, sender_name: str = "") -> str:
        e = (sender_email or "").strip().lower()
        if captain_email and e == captain_email:
            return "captain"
        if any(e.endswith(d) for d in _L1_EMAIL_DOMAINS):
            return "l1"
        # Heuristic: if it doesn't match captain and isn't a known L1 domain,
        # default to captain — surfacing unknown senders to the reviewer is
        # safer than silently treating them as L1 noise.
        return "captain" if e else "l1"

    sources = []
    for key in ("email", "conversations", "emailList"):
        val = captured.get(key)
        if isinstance(val, dict):
            for sub in ("emails", "conversations", "list", "emailList", "items"):
                lst = val.get(sub)
                if isinstance(lst, list):
                    sources.extend(lst)
                    break
        elif isinstance(val, list):
            sources.extend(val)

    out = []
    seen_ids = set()
    for msg in sources:
        if not isinstance(msg, dict):
            continue
        mid = msg.get("id") or msg.get("emailId") or msg.get("messageId")
        if mid and mid in seen_ids:
            continue
        if mid:
            seen_ids.add(mid)
        sender_email = (
            msg.get("fromEmail") or msg.get("senderEmail") or msg.get("from") or
            msg.get("sender_email") or msg.get("emailFrom") or ""
        )
        sender_name = (
            msg.get("fromName") or msg.get("senderName") or msg.get("sender_name") or
            msg.get("name") or ""
        )
        body_raw = (
            msg.get("body") or msg.get("message") or msg.get("emailBody") or
            msg.get("email_body") or msg.get("description") or msg.get("detail") or ""
        )
        body = _strip_html_minimal(_strip_dispose(body_raw))
        if not body:
            continue
        ts = msg.get("date") or msg.get("createdAt") or msg.get("created_at") or msg.get("time") or ""
        out.append({
            "role":         _classify(sender_email, sender_name),
            "sender":       sender_name or sender_email or "Unknown",
            "sender_email": sender_email,
            "body":         body,
            "ts":           ts,
        })
    out.sort(key=lambda x: x["ts"] or "")
    return out


def _detect_misplaced_description(panel_fields: dict, canonical_desc: str) -> dict:
    """Scan info-panel fields for prose content in fields that are expected
    to be short/structured. Returns {"field": name, "value": text} when
    a likely misplaced description is found, else {}.

    Heuristic: a field qualifies as 'misplaced description' if it's NOT
    the description field, its value is > 120 chars, AND the text looks
    like natural prose (starts with a greeting OR has >= 3 sentence breaks
    OR multi-line)."""
    if not isinstance(panel_fields, dict):
        return {}
    canonical_desc = (canonical_desc or "").strip()
    canon_len = len(canonical_desc)
    candidates = []
    for label, val in panel_fields.items():
        lname = (label or "").strip().lower()
        if lname in _DESCRIPTION_FIELD_NAMES:
            continue
        v = (val or "").strip()
        if len(v) < 120:
            continue
        # Don't re-flag content that's identical to (or contained in) the canonical desc
        if canonical_desc and (v in canonical_desc or canonical_desc in v):
            continue
        # Prose heuristics
        is_prose = (
            re.match(r"^(dear|hi|hello|team|sir|madam|namaste)\b", v, re.I) is not None
            or v.count(".") >= 3
            or v.count(",") >= 4
            or "\n" in v
        )
        if not is_prose:
            continue
        candidates.append({"field": label, "value": v, "len": len(v)})

    if not candidates:
        return {}
    # Pick the most prose-like (prefer longer, but prefer short-expected fields too)
    candidates.sort(key=lambda c: (
        0 if c["field"].strip().lower() in _SHORT_FIELD_NAMES else 1,
        -c["len"],
    ))
    best = candidates[0]
    return {"field": best["field"], "value": best["value"]}


def _parse_additional_info(captured: dict) -> dict:
    """
    Parse the additional_info API response to extract named custom fields.
    Field IDs are stable per Kapture instance — mapped from the observed response.
    Falls back to scanning fieldConfig displayNames for portability.
    """
    result = {}
    ai = captured.get("additionalInfo") or captured.get("additional_info") or {}
    if not isinstance(ai, dict):
        return result

    existing = ai.get("existing") or {}
    field_config = ai.get("fieldConfig") or {}

    # Build fieldId → displayName map from fieldConfig
    id_to_name = {}
    for fid, cfg in field_config.items():
        if isinstance(cfg, dict):
            id_to_name[str(fid)] = cfg.get("displayName", "")

    # Known field IDs (discovered from Kapture instance):
    KNOWN = {
        "21871": "subject_line",
        "21867": "hub_code",
        "21873": "attachment_urls_raw",
        "21975": "sub_type",
        "26772": "sub_sub_type",
        "26926": "please_describe_issue",
        "21868": "awbs",
        "21869": "previous_ticket",
        "21870": "shipments_impacted",
        "21865": "opstech_issue",
    }

    # Collect all field values across all objects
    all_fields = {}
    for obj_id, obj in existing.items():
        if not isinstance(obj, dict):
            continue
        for fid, val in (obj.get("fields") or {}).items():
            if val:
                all_fields[str(fid)] = val

    # Map known IDs to names
    for fid, key in KNOWN.items():
        val = all_fields.get(fid, "")
        if val:
            result[key] = str(val).strip()

    # Also scan by displayName for unknown instances — BUT skip
    # `please_describe_issue` here. Kapture has multiple fields whose
    # displayName contains "describe" or "description", and at least one
    # of them holds the L1 dispose draft body (looks like
    # `<dispose>Dear Partner, we understand your concern...`).
    # Letting that match would silently overwrite captain_problem with L1
    # voice — exactly the bug we found on ticket 779244875125. The known
    # field-ID mapping above is the only safe source for the captain's
    # description text.
    for fid, name in id_to_name.items():
        val = all_fields.get(fid, "")
        if not val:
            continue
        nl = name.lower()
        if "subject" in nl:
            result.setdefault("subject_line", str(val))
        elif "hub" in nl:
            result.setdefault("hub_code", str(val))
        elif "awb" in nl or "airway" in nl:
            result.setdefault("awbs", str(val))
        elif "attach" in nl:
            result.setdefault("attachment_urls_raw", str(val))

    # Parse attachment URLs (comma-separated S3 links)
    raw_att = result.pop("attachment_urls_raw", "")
    if raw_att:
        result["attachment_urls"] = [u.strip() for u in raw_att.split(",") if u.strip().startswith("http")]

    return result


async def _extract_info_panel_fields(page) -> dict:
    """
    Scrape the key-value pairs from Kapture's INFO panel (right side).
    Handles the label → value pattern: <div>Label</div><div>Value</div>
    Also captures: Subject Line, Issue Description, Please Describe Issue In Detail,
    Hub Code, AW Bs, Sub Type, Sub Sub Type, Web Form Attachement, etc.
    """
    fields = {}
    try:
        # Strategy: find all text nodes, pair labels with their adjacent values
        # Kapture renders these as sibling divs or table cells
        result = await page.evaluate("""
            () => {
                const fields = {};
                const LABELS = [
                    'Subject Line', 'Issue Description', 'Please Describe Issue In Detail',
                    'Hub Code', 'AW Bs', 'AWBs', 'Sub Type', 'Sub Sub Type',
                    'Issue Type', 'Shipments Impacted', 'Request Type',
                    'Web Form Attachement', 'Ticket Attachement',
                    'Previous Ticket Raised For This',
                ];

                // Walk all elements looking for ones whose text matches a label
                const allEls = document.querySelectorAll('div, td, span, p');
                for (const el of allEls) {
                    const text = (el.innerText || el.textContent || '').trim();
                    if (!LABELS.includes(text)) continue;

                    // Helper: get text+table content from an element
                    function getVal(el) {
                        if (!el) return '';
                        // For elements containing tables, innerText gives tab-separated rows
                        return (el.innerText || el.textContent || '').trim();
                    }

                    // Try next sibling
                    let val = '';
                    const nextSib = el.nextElementSibling;
                    if (nextSib) {
                        val = getVal(nextSib);
                    }
                    // Try parent's next sibling
                    if (!val && el.parentElement) {
                        const parentNext = el.parentElement.nextElementSibling;
                        if (parentNext) {
                            val = getVal(parentNext);
                        }
                    }
                    // Try same container: look for value div after this label div
                    if (!val && el.parentElement) {
                        const siblings = Array.from(el.parentElement.children);
                        const idx = siblings.indexOf(el);
                        if (idx >= 0 && siblings[idx + 1]) {
                            val = getVal(siblings[idx + 1]);
                        }
                    }

                    if (val && val !== text && val !== 'N/A') {
                        fields[text] = val;
                    } else if (val === 'N/A') {
                        fields[text] = '';  // store empty for N/A
                    }
                }
                return fields;
            }
        """)
        fields = result or {}
    except Exception as e:
        log.warning(f"[BROWSER] Info panel extraction failed: {e}")

    log.info(f"[BROWSER] Info panel fields: {list(fields.keys())}")
    return fields


async def _extract_sent_messages(page: Page) -> list[dict]:
    """
    Scrape every 'Sent' message from the Kapture conversation thread.
    These are the ground-truth resolutions written by the human agent.
    """
    sent = []

    # Strategy 1: look for elements near a "Sent" label
    try:
        # Kapture NUI renders each message as a card with a status badge
        msg_containers = await page.locator(
            "[class*='message'], [class*='conversation-item'], [class*='email-item'], [class*='chat-item']"
        ).all()
        for container in msg_containers:
            try:
                text = await container.inner_text(timeout=1000)
                if "sent" in text.lower() or "valmo support" in text.lower():
                    sent.append({"source": "dom_container", "text": text.strip()[:2000]})
            except Exception:
                pass
    except Exception:
        pass

    # Strategy 2: look for Sent badge + sibling text
    if not sent:
        try:
            sent_badges = await page.locator("text=Sent").all()
            for badge in sent_badges[:10]:
                try:
                    parent = badge.locator("xpath=ancestor::*[contains(@class,'message') or contains(@class,'card') or contains(@class,'item')][1]")
                    text = await parent.inner_text(timeout=1000)
                    if text and len(text) > 20:
                        sent.append({"source": "sent_badge", "text": text.strip()[:2000]})
                except Exception:
                    pass
        except Exception:
            pass

    # Strategy 3: grab all visible text that looks like an agent reply
    if not sent:
        try:
            page_text = await page.locator("body").inner_text(timeout=3000)
            # Look for patterns: "Dear Partner", "Dear Captain", followed by resolution text
            patterns = re.findall(
                r'(Dear\s+(?:Partner|Captain|Sir|Team)[^.]{0,20}\..*?)(?=Dear\s+(?:Partner|Captain|Sir|Team)|$)',
                page_text, re.DOTALL | re.IGNORECASE
            )
            for p in patterns[:5]:
                if len(p) > 50:
                    sent.append({"source": "pattern_match", "text": p.strip()[:2000]})
        except Exception:
            pass

    return sent


# ─── HTML stripping helper ────────────────────────────────────────

def _strip_html(raw: str) -> str:
    """Strip HTML tags and decode entities, normalize whitespace.
    Preserves table structure as tab-separated plain text rows."""
    # Remove style/script blocks entirely
    text = re.sub(r'<(style|script)[^>]*>.*?</\1>', '', raw, flags=re.IGNORECASE | re.DOTALL)
    # Table cells → tab separator (so table data isn't squashed together)
    text = re.sub(r'<t[dh]\b[^>]*>', '\t', text, flags=re.IGNORECASE)
    text = re.sub(r'</t[dh]>', '', text, flags=re.IGNORECASE)
    # Replace block tags with newlines
    text = re.sub(r'<(?:br|p|div|tr|li|h[1-6])\s*/?>', '\n', text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    text = html_mod.unescape(text)
    # Normalize non-breaking spaces and other Unicode whitespace to regular space
    text = text.replace('\u00a0', ' ').replace('\ufeff', '').replace('\u200b', '')
    # Normalize line endings and remove trailing spaces per line
    text = re.sub(r'\r\n|\r', '\n', text)
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    # Collapse 3+ blank lines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove ticket number header line (noise for training)
    text = re.sub(r'^Ticket No:\d+\s*\n', '', text.strip())
    return text.strip()


def _extract_emails_list(api: dict) -> list:
    """
    Pull the emails list from wherever it lives in api_data.
    Kapture puts it under 'emails' (intercepted) or inside api_data['email']['emails'].
    """
    # Direct: intercepted get-ticket-detail had {'emails': [...]}
    emails = api.get("emails")
    if isinstance(emails, list) and emails:
        return emails

    # Explicit call: data_type=email returns {'emails': [...]} stored under 'email' key
    email_val = api.get("email")
    if isinstance(email_val, dict):
        inner = email_val.get("emails")
        if isinstance(inner, list) and inner:
            return inner
    if isinstance(email_val, list) and email_val:
        return email_val

    return []


# ─── Build ground truth pair ─────────────────────────────────────

def extract_ground_truth(ticket_meta: dict, detail: dict) -> dict | None:
    """
    Build a ground-truth training pair:
      input  → captain's message + ticket context
      output → agent's sent reply

    Email-channel tickets: uses the 'emails' list from api_data.
      conversationType 'S' = Sent by agent (ground truth reply)
      conversationType 'R' = Received from partner/captain

    Fallback for non-email tickets: DOM-scraped sent_messages.
    """
    captain_msg = ticket_meta.get("detail", "")
    awbs = detail.get("awbs_on_page", [])
    api  = detail.get("api_data", {})

    agent_replies   = []  # [(source, clean_text)]
    captain_msgs    = []

    # ── Strategy 1: structured emails list ────────────────────────
    email_list = _extract_emails_list(api)
    for em in email_list:
        body = em.get("body", "")
        if not body:
            continue
        clean = _strip_html(body)
        if len(clean) < 20:
            continue
        conv_type  = em.get("conversationType", "")
        from_addr  = (em.get("fromAddress") or em.get("encryptedFromAddress") or "").lower()
        is_sent    = conv_type == "S" or "@valmo.in" in from_addr
        if is_sent:
            agent_replies.append(("email_sent", clean))
        else:
            captain_msgs.append(clean)

    # If we got a captain email, use that as captain_msg (richer than ticket detail field)
    if not captain_msg and captain_msgs:
        captain_msg = captain_msgs[0]

    # ── Strategy 2: other api_data keys (non-email channel) ───────
    if not agent_replies:
        for key in ["conversations", "emailList", "additionalInfo"]:
            val = api.get(key)
            if not val:
                continue
            items = val if isinstance(val, list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                body = (item.get("body") or item.get("content") or
                        item.get("message") or item.get("email_body", ""))
                direction = (item.get("type") or item.get("direction") or
                             item.get("conType") or item.get("conversationType", ""))
                if body and direction in ("S", "sent", "out", "E", ""):
                    agent_replies.append((key, _strip_html(str(body))))

    # ── Strategy 3: DOM-scraped sent messages ─────────────────────
    if not agent_replies:
        for s in detail.get("sent_messages", []):
            text = s.get("text", "")
            if len(text) > 30:
                agent_replies.append(("dom", text))

    if not captain_msg or not agent_replies:
        return None

    # Take the first clean sent reply and scrub navigation noise
    agent_reply = agent_replies[0][1]
    for noise in ["Dashboard\n", "Tickets\n", "Configuration\n", "Quick Settings\n"]:
        agent_reply = agent_reply.replace(noise, "")
    agent_reply = agent_reply.strip()

    if len(agent_reply) < 30:
        return None

    return {
        "ticket_id":    ticket_meta["ticket_id"],
        "queue":        ticket_meta.get("queue_key", ""),
        "subject":      ticket_meta.get("subject", ""),
        "awbs":         awbs,
        "captain_msg":  captain_msg,
        "agent_reply":  agent_reply,
        "num_replies":  len(agent_replies),
        "reply_source": agent_replies[0][0],
        "scraped_at":   datetime.utcnow().isoformat(),
    }


# ─── Main ────────────────────────────────────────────────────────

async def main():
    if not EMAIL or not PASSWORD:
        log.error("Set KAPTURE_EMAIL and KAPTURE_PASSWORD in .env")
        sys.exit(1)

    OUTPUT.parent.mkdir(exist_ok=True)
    done = load_done()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            slow_mo=100,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        await login(page)

        log.info("Collecting ticket list...")
        all_tickets = await collect_ticket_ids(page)
        to_scrape = [t for t in all_tickets if t["ticket_id"] not in done]
        log.info(f"{len(to_scrape)} new tickets to scrape")

        success = failed = gt_saved = 0

        for i, t in enumerate(to_scrape, 1):
            tid = t["ticket_id"]
            log.info(f"[{i}/{len(to_scrape)}] {tid} | {t['subject'][:60]}")
            try:
                detail = await extract_ticket(page, t["task_id"], tid)
                record = {**t, **detail}
                save_record(OUTPUT, record)
                success += 1

                # Build and save ground truth if we have agent reply
                gt = extract_ground_truth(t, detail)
                if gt:
                    save_record(GROUND_TRUTH, gt)
                    gt_saved += 1
                    log.info(f"  [OK] Ground truth captured ({len(gt['agent_reply'])} chars)")
                else:
                    api_keys = [k for k, v in detail.get("api_data", {}).items() if v]
                    log.info(f"  [OK] No reply captured. API keys with data: {api_keys}")

            except Exception as e:
                log.error(f"  [FAIL] {e}")
                save_record(OUTPUT, {**t, "error": str(e), "scraped_at": datetime.utcnow().isoformat()})
                failed += 1

            await page.wait_for_timeout(DELAY_MS)

        await browser.close()

    log.info(f"\n{'='*50}")
    log.info(f"Scraped: {success}  Failed: {failed}  Ground truth pairs: {gt_saved}")
    log.info(f"Output: {OUTPUT.resolve()}")
    log.info(f"Ground truth: {GROUND_TRUTH.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
