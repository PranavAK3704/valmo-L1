"""
AgentBrain — the reasoning core of the L1 agent.

Replaces the 12 hardcoded resolvers with Gemini-powered reasoning.
Flow:
  ticket → retrieve SOP context → run queries → Gemini reasons → BrainDecision

The brain doesn't care which SOP scenario it is — it reads the SOP,
looks at the data, and decides. Just like a human agent would.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional  # noqa: F401

from src.llm.gemini_client import get_gemini_client
from src.llm.sop_store import get_sop_store, format_grouped_chunks
from src.llm import stage0 as _stage0

logger = logging.getLogger(__name__)

STUCK_QUEUE_FILE = Path(__file__).parent.parent.parent / "data" / "stuck_queue.jsonl"
TRAINER_QA_FILE  = Path(__file__).parent.parent.parent / "data" / "trainer_qa.jsonl"
_SOP_STRUCTURED_FILE = Path(__file__).parent.parent.parent / "data" / "sop_knowledge" / "sop_structured.json"

# Load structured SOP JSON once at import time
def _load_structured_sop() -> list:
    try:
        with open(_SOP_STRUCTURED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[Brain] Could not load sop_structured.json: {e}")
        return []

_SOP_STRUCTURED: list = _load_structured_sop()


import re as _re

def _extract_awbs_from_text(text: str) -> list:
    """Extract AWB numbers matching VL/VLR + 8-15 digits from any text."""
    return list(set(_re.findall(r'VL[R]?\d{8,15}', text or "")))


def _match_structured_sop(ticket: Dict) -> str:
    """
    Find the relevant problem_theme(s) from sop_structured.json for this ticket.
    Returns a compact, structured block describing matching scenarios and their
    explicit conditions/actions — injected into the prompt so Gemini has a
    deterministic decision tree, not just fuzzy prose.
    """
    if not _SOP_STRUCTURED:
        return ""

    queue = (ticket.get("queue") or ticket.get("queue_key") or "").strip().lower()
    subject = (ticket.get("subject") or "").lower()
    detail = (ticket.get("detail") or ticket.get("description") or ticket.get("full_description") or "").lower()
    text = f"{subject} {detail}"

    # Normalize queue aliases — maps Kapture UI labels to internal SOP queue IDs.
    # Both 'w- ld' AND 'shipment_shortage' map to the broader "losses_and_debits"
    # bucket so BOTH hardstop and shortage scenarios get injected. Keyword scoring
    # then picks the right specific theme. The W- LD queue in Kapture contains
    # both hardstop and shortage tickets — gating only on queue label loses ~50%
    # of the relevant SOP context.
    QUEUE_MAP = {
        # Internal codes — collapse all L&D variants to one bucket
        "w- ld": "losses_and_debits", "w-ld": "losses_and_debits",
        "ld": "losses_and_debits", "hardstop": "losses_and_debits",
        "shipment_shortage": "losses_and_debits", "shortage": "losses_and_debits",
        "c_v": "c_v", "m_v": "m_v",
        # Kapture dropdown display names (from sub_type field)
        "losses & debits": "losses_and_debits",
        "losses and debits": "losses_and_debits",
        "payments": "m_v",
        "consumable": "c_v",
        "consumables": "c_v",
        "orders": "orders",
        "orders & planning": "orders",
        "orders and planning": "orders",
    }
    norm_queue = QUEUE_MAP.get(queue, queue)

    # "Losses & Debits" encompasses both hardstop_loss (W- LD) and shortage_loss
    LOSSES_AND_DEBITS_THEMES = {"w- ld", "shipment_shortage"}

    matched_themes = []
    for theme in _SOP_STRUCTURED:
        theme_queue = (theme.get("queue") or "").strip().lower()

        # tech_issue applies to ALL queues — always include it for keyword scoring
        is_universal = theme.get("problem_theme") == "tech_issue" or theme_queue == "*"

        if not is_universal:
            if norm_queue == "losses_and_debits":
                # Include both W- LD and shipment_shortage; keyword scoring picks the right one
                if theme_queue not in LOSSES_AND_DEBITS_THEMES:
                    continue
            elif norm_queue == "orders":
                if theme.get("problem_theme") != "orders_and_planning":
                    continue
            elif theme_queue and norm_queue:
                if not (norm_queue in theme_queue or theme_queue in norm_queue):
                    continue

        # Score by trigger_keywords overlap
        keywords = [k.lower() for k in (theme.get("trigger_keywords") or [])]
        hits = sum(1 for k in keywords if k in text)
        matched_themes.append((hits, theme))

    if not matched_themes:
        return ""

    # Sort by keyword hits desc; take top 1-2 themes
    matched_themes.sort(key=lambda x: x[0], reverse=True)
    top_themes = [t for score, t in matched_themes[:2] if score > 0]
    if not top_themes:
        top_themes = [matched_themes[0][1]]  # fallback: queue-only match

    lines = ["## STRUCTURED SOP DECISION TREE (from sop_structured.json)"]
    lines.append("Use these explicit conditions to decide. Each scenario lists exact conditions — check them against the ticket and query data.\n")

    for theme in top_themes:
        lines.append(f"### Problem Theme: {theme.get('problem_theme', '')} | Queue: {theme.get('queue', '')} | TAT: {theme.get('tat_hours', '?')}h")

        req = theme.get("required_inputs", [])
        if req:
            lines.append(f"Required inputs: {', '.join(req)}")

        for rule in (theme.get("validation_rules") or []):
            if rule.get("action_if_failed") == "request_input_from_captain":
                lines.append(f"  → If '{rule['field']}' is missing: use action=needs_info and request it")

        pre = theme.get("preprocessing") or {}
        if pre.get("note"):
            lines.append(f"Preprocessing note: {pre['note']}")

        derived = theme.get("derived_conditions") or []
        if derived:
            lines.append("Derived conditions to check:")
            if isinstance(derived, dict):
                for field_name, logic in list(derived.items())[:6]:
                    lines.append(f"  {field_name}: {logic}")
            else:
                for dc in derived:
                    if isinstance(dc, dict):
                        lines.append(f"  {dc.get('field', '')}: {dc.get('logic', dc.get('note', ''))}")
                    else:
                        lines.append(f"  {dc}")

        lines.append("\nScenarios (check IN ORDER — first match wins):")
        for sc in (theme.get("scenarios") or []):
            sid   = sc.get("scenario_id", "")
            label = sc.get("label", "")
            conds = sc.get("conditions") or []
            action = sc.get("action", "")
            esc   = sc.get("escalation") or {}
            resp  = sc.get("response_to_captain", "")

            esc_str = f" → escalate to {esc.get('level','L2')}: {esc.get('reason','')}" if esc else ""
            cond_str = " AND ".join(conds) if conds else "(always matches)"
            lines.append(f"  [{sid}] {label}")
            lines.append(f"    Conditions: {cond_str}")
            lines.append(f"    Action: {action}{esc_str}")
            if resp:
                lines.append(f"    Template response: \"{resp[:120]}\"")

        lines.append("")

    return "\n".join(lines)


AUTO_SEND_CONFIDENCE = 7.0   # >= 7 auto-send, < 7 goes for review

# ── Rule 1 — captain claims verified-data guardrail ─────────────────
# Case-insensitive substring matches in ticket description.
# When the captain asserts they checked Metabase/Log10 but our independent
# queries returned nothing, the agent must NOT act on the captain's claim.
CAPTAIN_CLAIM_PHRASES = [
    "i checked", "i have checked",
    "metabase shows", "metabase says", "as per metabase", "verified from metabase",
    "log10 shows", "log10 says", "as per log10", "verified from log10",
    "amount_recovered", "amount recovered",
    "fe loss marked shows", "per lm fe loss marked",
]

# Required Metabase queries for L&D — if these are empty/failed AND the
# captain has cited verifying them, we cannot proceed.
_RULE_1_REQUIRED_QUERIES = {"get_loss_attribution", "get_shipment_scan_history_single"}

# Queue aliases that map to losses_and_debits (must match _match_structured_sop).
_LD_QUEUE_TOKENS = {"w- ld", "w-ld", "ld", "hardstop", "shipment_shortage",
                    "shortage", "losses & debits", "losses and debits",
                    "losses_and_debits"}


def _is_ld_queue(ticket: Dict) -> bool:
    q = (ticket.get("queue") or ticket.get("queue_key") or "").strip().lower()
    return q in _LD_QUEUE_TOKENS


def _rule_1_match(ticket: Dict, query_results: List[Dict]) -> Optional[str]:
    """
    Returns the first matched captain-claim phrase if Rule 1 conditions hold,
    else None. Conditions:
      - queue is losses_and_debits
      - at least one AWB extracted
      - at least one required Metabase query is empty OR failed
      - ticket description contains any CAPTAIN_CLAIM_PHRASES entry
    """
    if not _is_ld_queue(ticket):
        return None
    awbs = ticket.get("awb_numbers") or ticket.get("awbs") or []
    if not awbs:
        return None

    # Index query results by name. Missing entirely == empty.
    by_name: Dict[str, Dict] = {qr.get("query_name", ""): qr for qr in (query_results or [])}
    required_empty_or_failed = False
    for qname in _RULE_1_REQUIRED_QUERIES:
        qr = by_name.get(qname)
        if qr is None:
            required_empty_or_failed = True
            break
        if not qr.get("success"):
            required_empty_or_failed = True
            break
        rows = (qr.get("data") or {}).get("rows") or []
        if not rows:
            required_empty_or_failed = True
            break
    if not required_empty_or_failed:
        return None

    desc = " ".join([
        ticket.get("detail") or "",
        ticket.get("description") or "",
        ticket.get("full_description") or "",
        ticket.get("subject") or "",
    ]).lower()
    for phrase in CAPTAIN_CLAIM_PHRASES:
        if phrase in desc:
            return phrase
    return None


@dataclass
class BrainDecision:
    action: str                        # respond | escalate | needs_info | stuck
    clean_problem: str = ""            # ops-language translation of what captain needs
    response_to_captain: str = ""      # draft reply
    escalation_queue: str = ""
    escalation_reason: str = ""
    stuck_question: str = ""
    missing_fields: List[str] = field(default_factory=list)
    confidence: float = 0.0
    scenario_identified: str = ""
    reasoning: str = ""
    auto_send: bool = False            # True if confidence >= threshold
    thinking_steps: List[Dict] = field(default_factory=list)  # step-by-step trace for UI
    usage: Dict = field(default_factory=dict)  # {input_tokens, output_tokens, cost_inr}
    stage0: Dict = field(default_factory=dict)  # situational assessment dump
    guardrail_triggered: str = ""              # "" | "rule_2_family_mismatch" | "rule_1_unverified_claim"


def _blocker_upgrade(ticket: Dict, decision: "BrainDecision", query_results: List[Dict]) -> str:
    """Return a friendly upgrade message for the thinker UI when agent is stuck."""
    queue = (ticket.get("queue") or ticket.get("queue_key") or "").lower()
    failed = [q["query_name"] for q in query_results if not q.get("success")]
    if any(k in queue for k in ("ld", "loss", "hardstop", "w- ld")):
        return ("Hey! \U0001f4a1 If I had Log10 access, I could verify the exact scan timestamps "
                "and SOP compliance for this shipment — and give you a definitive answer in seconds, no human needed.")
    if any(k in queue for k in ("shortage", "shipment_shortage")):
        return ("Hey! \U0001f4a1 I know the Shortage SOP. But to resolve this I need Log10 scan data "
                "to verify which node's evidence holds up. Wire me Log10 and I'll own this queue fully.")
    if failed:
        return (f"Hey! \U0001f4a1 My Metabase connection failed on: {', '.join(failed)}. "
                "Once that's stable I'll resolve this automatically.")
    if any(k in queue for k in ("c_v", "m_v")):
        return ("Hey! \U0001f4a1 I have partial SOPs for this queue. "
                "Share the full SOP document and I'll handle these tickets on my own.")
    if any(k in queue for k in ("consumable",)):
        return ("Hey! \U0001f4a1 I now have the Consumables SOP. "
                "AWB numbers are needed in the ticket for me to run the Metabase queries and resolve this.")
    return ("Hey! \U0001f4a1 I'm missing some key info to resolve this confidently. "
            "Share the SOP or the missing data and I'll be fully autonomous here.")


def _format_query_results(query_results: List[Dict]) -> str:
    """Format Metabase query results into readable text for the prompt."""
    if not query_results:
        return "No query results available."
    parts = []
    for qr in query_results:
        name    = qr.get("query_name", "unknown")
        success = qr.get("success", False)
        if not success:
            parts.append(f"Query '{name}': FAILED — {qr.get('error', 'unknown error')}")
            continue
        rows = qr.get("data", {}).get("rows", [])
        if not rows:
            parts.append(f"Query '{name}': returned 0 rows (empty result)")
        else:
            parts.append(f"Query '{name}': {len(rows)} row(s)")
            for i, row in enumerate(rows[:5]):   # Show max 5 rows
                parts.append(f"  Row {i+1}: {json.dumps(row, ensure_ascii=False)}")
            if len(rows) > 5:
                parts.append(f"  ... ({len(rows)-5} more rows)")
    return "\n".join(parts)


def _extract_attachment_summary(ticket: Dict) -> str:
    """
    Extract attachment/proof info from scraped ticket data.
    If S3 URLs are present for PDFs/images, downloads and reads them via Gemini Vision.
    """
    lines = []
    api_data = ticket.get("api_data") or {}

    # ── Use the per-ticket cache populated in process() Step 1 ────
    # _read_all_attachments has already downloaded + parsed each file
    # (Excel/CSV locally, PDF/image via Vision). Just format for the prompt.
    attachment_urls = ticket.get("attachment_urls") or []
    cache = ticket.get("_attachment_text_cache")
    if cache is None and attachment_urls:
        # Direct callers (legacy test paths) might invoke _build_prompt
        # without running process() first. Populate the cache lazily.
        try:
            cache = _read_all_attachments(ticket)
        except Exception as e:
            cache = {}
            lines.append(f"Attachment read error: {e}")
    if isinstance(cache, dict):
        import pathlib as _pl
        for url, content in cache.items():
            fname = _pl.Path(url.split("?")[0]).name
            if content:
                # Truncate big Excel dumps so they don't dominate the prompt
                shown = content if len(content) <= 1500 else content[:1500] + f"\n…(+{len(content)-1500} chars truncated)"
                lines.append(f"--- Attachment: {fname} ---\n{shown}\n---")
            else:
                lines.append(f"Attachment {fname}: (no text extracted)")

    # ── Check explicit attachment API response (filenames only) ──
    attachments = api_data.get("attachments") or []
    if isinstance(attachments, list) and attachments:
        names = [a.get("file_name") or a.get("name") or a.get("fileName") or "file"
                 for a in attachments[:10] if isinstance(a, dict)]
        if names:
            lines.append(f"Additional attachments listed ({len(attachments)}): {', '.join(names)}")
    elif isinstance(attachments, dict) and attachments:
        lines.append(f"Attachments present (raw): {str(attachments)[:200]}")

    # ── Check page text for attachment/proof mentions ─────────────
    page_text = ticket.get("page_text_snippet") or ""
    if page_text and not attachment_urls:
        proof_hints = []
        for kw in ["attachment", "image", "photo", "CCTV", "cctv", "proof", "evidence", ".jpg", ".png", ".pdf"]:
            if kw.lower() in page_text.lower():
                proof_hints.append(kw)
        if proof_hints:
            lines.append(f"Proof keywords in ticket page: {', '.join(set(proof_hints))}")

    # ── Check conversation thread for attachment mentions ─────────
    conversations = api_data.get("conversations") or api_data.get("email") or []
    if isinstance(conversations, list):
        for c in conversations[:5]:
            body = (c.get("body") or c.get("message") or c.get("email_body") or "")
            if any(k in str(body).lower() for k in ["attach", "photo", "image", "cctv", "proof"]):
                lines.append("Proof mentioned in conversation thread")
                break

    return "\n".join(lines) if lines else "No attachments detected"


def _format_captain_section(ticket: Dict) -> str:
    """Render the captain's voice block with explicit source attribution.
    Pulls from the new role-aware fields populated by scrape_tickets_v2.
    Falls back to the legacy 'detail' field for backward compatibility."""
    cap_problem = ticket.get("captain_problem") or ""
    cap_source  = ticket.get("captain_problem_source") or ""
    captain_msgs = ticket.get("captain_messages") or []

    # Legacy fallback: when running against cached tickets (no role parsing yet)
    if not cap_problem:
        cap_problem = (
            ticket.get("detail") or ticket.get("description")
            or ticket.get("full_description") or ""
        )
        cap_source = "legacy_description_field"

    src_tag = f"  (source: {cap_source})" if cap_source else ""
    out = [f"## CAPTAIN'S PROBLEM{src_tag}"]
    out.append(cap_problem.strip() if cap_problem else "(No captain problem statement could be extracted — agent should use action=needs_info.)")

    # Captain follow-ups (excluding the first one if it was already used as captain_problem)
    follow_ups = []
    if captain_msgs:
        # Skip the first message if it's the source we used
        skip_first = cap_source.startswith("first_captain_message")
        start_idx = 1 if skip_first else 0
        for m in captain_msgs[start_idx:start_idx + 5]:
            ts = (m.get("ts") or "")[:16]
            sender = m.get("sender") or "Captain"
            body = (m.get("body") or "")[:600]
            follow_ups.append(f"  [{ts}] {sender}: {body}")
    if follow_ups:
        out.append("")
        out.append("## CAPTAIN'S FOLLOW-UP MESSAGES (chronological)")
        out.extend(follow_ups)

    # Misplaced-description warning (prose in wrong field)
    misplaced = ticket.get("misplaced_description") or {}
    if misplaced.get("field"):
        out.append("")
        out.append(f"## WRONG-FIELD WARNING")
        out.append(f"  Captain entered prose content in the field \"{misplaced['field']}\" "
                   f"which is usually short/structured. The text above as CAPTAIN'S PROBLEM "
                   f"was extracted from there — do not treat this as data corruption; treat "
                   f"it as the captain's actual statement.")

    # Misplaced-attachment warning (image URL leaked into AWB / other text field)
    mp_att = ticket.get("misplaced_attachment_field") or ""
    if mp_att:
        out.append("")
        out.append(f"## ATTACHMENT-IN-WRONG-FIELD WARNING")
        out.append(f"  An image/PDF attachment appears to have been uploaded into the "
                   f"\"{mp_att}\" field (which usually holds text data). If CAPTAIN'S PROBLEM "
                   f"above is blank or unhelpful AND attachments are listed in the Attachments "
                   f"section above, the captain's actual problem may be ONLY in the image. "
                   f"In that case use action=needs_info and specifically ask the captain to "
                   f"type out what's in the image (or what their issue is in words).")
    return "\n".join(out)


def _format_l1_thread(ticket: Dict) -> str:
    """L1-only voice. Provided for context (e.g. has L1 already asked for AWB?)
    but EXPLICITLY labeled so the model doesn't confuse it with captain's voice."""
    l1_msgs = ticket.get("l1_messages") or []
    if not l1_msgs:
        return ""
    out = ["## L1 AGENT THREAD (for context only — these are PREVIOUS L1 RESPONSES, not the captain's problem)"]
    for m in l1_msgs[:6]:
        ts = (m.get("ts") or "")[:16]
        sender = m.get("sender") or "L1"
        body = (m.get("body") or "")[:500]
        out.append(f"  [{ts}] {sender}: {body}")
    return "\n".join(out)


# OCR prompt tuned for "captain uploaded screenshot as their problem statement".
# Different from gemini_client.read_attachment's default (which is evidence-doc tuned).
_CAPTAIN_OCR_PROMPT = (
    "A delivery partner (captain) uploaded this image/document to a support "
    "ticket. They appear to have used it INSTEAD OF typing their problem in "
    "the text field. Extract: 1) what the captain is claiming is wrong "
    "(in 2-3 sentences, in plain English), 2) any AWB numbers visible "
    "(format VL followed by digits), 3) any amounts/dates/hub codes visible. "
    "Reply concisely — no markdown formatting. If the image is blank, "
    "low-quality, or shows no useful problem statement, reply EXACTLY: "
    "NO_CAPTAIN_CONTENT"
)


def _read_all_attachments(ticket: Dict, max_attachments: int = 3) -> Dict[str, str]:
    """Read every attachment on the ticket (up to max_attachments) and return
    {url: text_content}. Caches the result on ticket['_attachment_text_cache']
    so we don't re-OCR / re-parse the same files. Excel/CSV are parsed
    locally; PDFs/images go through Gemini Vision.

    Each cache entry is the extracted text, or "" when extraction failed."""
    cache = ticket.get("_attachment_text_cache")
    if isinstance(cache, dict):
        return cache

    attachments = ticket.get("attachment_urls") or []
    out: Dict[str, str] = {}
    if not attachments:
        ticket["_attachment_text_cache"] = out
        return out

    import pathlib
    client = get_gemini_client()
    for url in attachments[:max_attachments]:
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        fname = pathlib.Path(url.split("?")[0]).name
        try:
            text = client.read_attachment(url, filename=fname)
            if not text:
                out[url] = ""
                continue
            if text.startswith("[Could not") or text.startswith("[Attachment type"):
                logger.info(f"[Brain] attachment skipped ({fname}): {text[:80]}")
                out[url] = ""
                continue
            out[url] = text.strip()
            logger.info(f"[Brain] read attachment ({fname}): {len(text)} chars")
        except Exception as e:
            logger.warning(f"[Brain] attachment read failed ({fname}): {e}")
            out[url] = ""

    ticket["_attachment_text_cache"] = out
    return out


def _ocr_captain_attachment(ticket: Dict) -> str:
    """When the captain skipped the text description but uploaded a JPEG/PDF/
    Excel (often misplaced into the AWB field), recover a problem statement
    from the attachments. Uses the per-ticket attachment cache so this is free
    if _read_all_attachments has already run.

    For images/PDFs we re-OCR with the captain-specific prompt (since the
    default prompt is tuned for evidence-doc extraction, not problem statements).
    For Excel/CSV the local-parse output is already raw cell text — we just
    feed that through, capped to ~500 chars so the model sees a summary."""
    attachments = ticket.get("attachment_urls") or []
    if not attachments:
        return ""

    import pathlib
    pieces: List[str] = []
    client = get_gemini_client()
    cache = ticket.get("_attachment_text_cache") or {}

    for url in attachments[:3]:
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        fname = pathlib.Path(url.split("?")[0]).name
        ext = pathlib.Path(fname).suffix.lower()

        if ext in (".xlsx", ".xls", ".csv"):
            # Local-parse output already in cache (or re-fetchable cheaply)
            text = cache.get(url) or client.read_attachment(url, filename=fname)
            if text and not text.startswith("[Could not"):
                pieces.append(f"[from {fname}] {text[:500]}")
            continue

        # Image/PDF: re-OCR with captain prompt
        try:
            text = client.read_attachment(url, filename=fname, prompt=_CAPTAIN_OCR_PROMPT)
        except Exception as e:
            logger.warning(f"[Brain] captain-attachment OCR failed ({fname}): {e}")
            continue
        if not text:
            continue
        text = text.strip()
        if text.upper().startswith("NO_CAPTAIN_CONTENT"):
            continue
        if text.startswith("[Could not") or text.startswith("[Attachment type"):
            continue
        pieces.append(f"[from {fname}] {text}")

    return "\n\n".join(pieces)


def _build_prompt(ticket: Dict, sop_context: str, query_results_text: str,
                  stage0_block: str = "") -> str:
    """Build the full prompt for Gemini."""
    awbs = ticket.get("awb_numbers") or ticket.get("awbs") or []
    attachment_summary = _extract_attachment_summary(ticket)

    # Role-aware sections (replaces the old flat 'Description:' + 'Conversation Thread:')
    captain_block = _format_captain_section(ticket)
    l1_block      = _format_l1_thread(ticket)

    # Structured SOP decision tree (pre-filtered by queue + keywords)
    structured_block = _match_structured_sop(ticket)

    return f"""## TICKET METADATA
Ticket ID  : {ticket.get('ticket_id', 'N/A')}
Partner ID : {ticket.get('partner_id', 'N/A')}
Queue      : {ticket.get('queue', ticket.get('queue_key', 'N/A'))}
Sub-Queue  : {ticket.get('sub_queue', 'N/A')}
Hub Code   : {ticket.get('hub_code', 'N/A')}
AWBs       : {', '.join(awbs) if awbs else 'Not provided'}
Subject    : {ticket.get('subject', '')}
Attachments: {attachment_summary}

{captain_block}
{f"""
{l1_block}
""" if l1_block else ""}
---
{f"""
{stage0_block}

---
""" if stage0_block else ""}
{f"""
{structured_block}

---
""" if structured_block else ""}

## RELEVANT SOP & KT (retrieved knowledge base)
{sop_context}

---

## METABASE QUERY RESULTS
{query_results_text}

---

Based on the ticket, the structured decision tree above, the SOP knowledge, and the query results, make your decision.
Remember:
- If the STAGE 0 — SITUATION ASSESSMENT block is present and its loss_type is NOT 'unknown' AND its domain_confidence is 'high', you MUST pick a scenario from that loss_type's family. Do NOT switch to a different family (especially do NOT pick tech_issue scenarios) unless the ticket text explicitly contains tech-failure phrases like "scan not working", "app crashed", "page not loading", "system error". The captain merely citing system names like Log10 or Metabase as evidence sources is NOT a tech failure.
- The STRUCTURED SOP DECISION TREE above has explicit conditions — use it as your primary reference
- Follow the SOP exactly; do not make up any data not present in query results
- If data is missing, use needs_info or stuck
- Set scenario_identified to the EXACT scenario ID shown in brackets (e.g. HS_5, HS_WAIVER, SS_3, CON_PAY_1) — never use the theme name like "hardstop_loss"
- Set clean_problem to a single clear ops-language sentence describing what the captain needs. If the ticket cites multiple AWBs or a discrepancy across multiple systems, mention the count and the dispute axis (e.g. "captain disputes attribution of 6 AWBs across Log10/Metabase").
- Respond in the exact JSON format specified
"""


class AgentBrain:
    def __init__(self):
        self._gemini = get_gemini_client()
        self._sop    = get_sop_store()

    def process(self, ticket: Dict, query_results: List[Dict]) -> BrainDecision:
        """
        Main entry point. Takes ticket dict and query results, returns BrainDecision.
        """
        steps: List[Dict] = []

        # ── Step 1: Ticket intake ──────────────────────────────────
        awbs = ticket.get("awb_numbers") or ticket.get("awbs") or []
        # Fallback A: extract AWBs from description text if not explicitly set
        if not awbs:
            desc_text = ticket.get("detail") or ticket.get("description") or ticket.get("full_description") or ""
            awb_field = ticket.get("awb_field") or ""
            awbs = _extract_awbs_from_text(desc_text + " " + awb_field)

        # Fallback B: read every attachment (Excel/CSV via openpyxl locally,
        # PDF/images via Gemini Vision) and extract AWBs from the contents.
        # Cached on the ticket so we don't re-read for the prompt assembly.
        attachment_texts = _read_all_attachments(ticket)
        att_awbs: list = []
        if attachment_texts:
            joined = "\n\n".join(attachment_texts.values())
            att_awbs = _extract_awbs_from_text(joined)
            if att_awbs:
                logger.info(
                    f"[Brain] recovered {len(att_awbs)} AWB(s) from attachments "
                    f"for ticket={ticket.get('ticket_id')}: {att_awbs[:5]}"
                    f"{'…' if len(att_awbs) > 5 else ''}"
                )
        # Merge: prefer existing AWBs but extend with attachment ones (dedup,
        # preserve order)
        seen = set(awbs)
        for a in att_awbs:
            if a not in seen:
                awbs.append(a); seen.add(a)
        if awbs:
            ticket["awb_numbers"] = awbs

        queue = ticket.get("queue") or ticket.get("queue_key") or "Unknown"
        hub   = ticket.get("hub_code") or ticket.get("partner_id") or "—"
        intake_detail = f"Queue: {queue} | AWBs: {', '.join(awbs[:5]) if awbs else 'None found'}{' +' + str(len(awbs)-5) if len(awbs) > 5 else ''} | Hub: {hub}"
        if att_awbs:
            intake_detail += f" | {len(att_awbs)} AWBs recovered from attachments"
        steps.append({
            "icon": "\U0001f50d", "label": "Reading ticket",
            "detail": intake_detail,
            "status": "done",
        })

        # ── Step 1b: OCR fallback — recover captain's problem from a
        # misplaced attachment when the text description is empty ──
        if not (ticket.get("captain_problem") or "").strip() and ticket.get("attachment_urls"):
            steps.append({
                "icon": "\U0001f5bc️", "label": "Captain uploaded attachment instead of typing — running OCR",
                "detail": f"{len(ticket.get('attachment_urls') or [])} attachment(s) — extracting problem statement via Gemini Vision",
                "status": "thinking",
            })
            ocr_text = _ocr_captain_attachment(ticket)
            if ocr_text:
                ticket["captain_problem"] = ocr_text
                ticket["captain_problem_source"] = "attachment_ocr"
                steps[-1] = {
                    "icon": "\U0001f5bc️", "label": "OCR recovered captain's problem",
                    "detail": (ocr_text[:140] + ("…" if len(ocr_text) > 140 else "")),
                    "status": "done",
                }
                logger.info(f"[Brain] OCR recovered captain_problem ({len(ocr_text)} chars) for ticket={ticket.get('ticket_id')}")
                # Also retry AWB extraction against OCR'd text
                if not awbs:
                    new_awbs = _extract_awbs_from_text(ocr_text)
                    if new_awbs:
                        awbs = new_awbs
                        ticket["awb_numbers"] = awbs
                        logger.info(f"[Brain] OCR also recovered AWBs: {awbs}")
            else:
                steps[-1] = {
                    "icon": "\U0001f5bc️", "label": "OCR did not find usable captain content",
                    "detail": "Attachment was blank or unreadable — will request text description",
                    "status": "warning",
                }

        # ── Step 2: Stage 0 — situational reasoning ───────────────
        stage0_block = ""
        try:
            assessment = _stage0.assess(ticket)
            stage0_block = _stage0.to_prompt_block(assessment)
            if assessment.physical_event:
                detail_parts = []
                if assessment.loss_type and assessment.loss_type != "unknown":
                    detail_parts.append(f"loss_type={assessment.loss_type}")
                if assessment.scenario_hint:
                    detail_parts.append(f"hint={assessment.scenario_hint}")
                detail_parts.append(f"conf={assessment.domain_confidence}")
                steps.append({
                    "icon": "\U0001f9ea", "label": "Stage 0: Situation assessment",
                    "detail": f"{assessment.physical_event[:140]} | {' | '.join(detail_parts)}",
                    "status": "done",
                })
            elif assessment.queue_status == "unknown":
                steps.append({
                    "icon": "\U0001f9ea", "label": "Stage 0: Situation assessment",
                    "detail": f"Queue '{queue}' not in domain model — defer to SOP retrieval",
                    "status": "warning",
                })
            elif assessment.queue_status == "placeholder":
                steps.append({
                    "icon": "\U0001f9ea", "label": "Stage 0: Situation assessment",
                    "detail": f"Queue '{assessment.queue_key_matched or queue}' has placeholder domain — add KT to activate",
                    "status": "warning",
                })
            else:
                # queue matched + complete domain, but Gemini call returned nothing
                steps.append({
                    "icon": "\U0001f9ea", "label": "Stage 0: Situation assessment",
                    "detail": assessment.scan_logic or "Stage 0 returned no diagnosis",
                    "status": "warning",
                })
        except Exception as e:
            logger.warning(f"[Brain] Stage 0 failed (non-fatal): {e}")
            steps.append({
                "icon": "\U0001f9ea", "label": "Stage 0: Situation assessment",
                "detail": f"Stage 0 skipped — {e}",
                "status": "warning",
            })

        # ── Step 3: SOP lookup ────────────────────────────────────
        search_query = " ".join(filter(None, [
            ticket.get("subject", ""),
            ticket.get("detail", ticket.get("description", "")),
            queue, ticket.get("sub_queue", ""),
        ]))[:500]
        # Use Stage 0's canonical queue match when available so retrieval
        # filters chunks to {this_queue, general}. Falls back to None when
        # Stage 0 didn't resolve a queue (unknown / placeholder domain).
        retrieval_queue = locals().get("assessment", None)
        retrieval_queue = (
            getattr(retrieval_queue, "queue_key_matched", "") or ""
        ) if retrieval_queue is not None else ""
        grouped_chunks = self._sop.retrieve(
            search_query, k=10, queue=retrieval_queue or None
        )
        sop_context = format_grouped_chunks(grouped_chunks)
        chunk_count = sum(len(v) for v in grouped_chunks.values())

        # Novel-scenario signal: log when retrieval returned 0 precedents +
        # 0 trainer-QA. Means the system has never been calibrated on a
        # ticket like this. Useful for flagging tickets the human reviewer
        # should pay extra attention to (and that should later become eval
        # set rows).
        precedent_count = len(grouped_chunks.get("resolved_precedent", []) or [])
        trainer_count   = len(grouped_chunks.get("trainer_qa", []) or [])
        if precedent_count == 0 and trainer_count == 0:
            logger.info(
                f"[Brain] NOVEL_SCENARIO ticket={ticket.get('ticket_id')} "
                f"queue={queue!r} — 0 precedents, 0 trainer Q&A retrieved. "
                f"Agent will reason from canonical SOP only."
            )
        # Per-source breakdown for the trace UI — "3 SOP + 2 precedent + 1 KT"
        ctype_summary = ", ".join(
            f"{len(v)} {k.replace('_', ' ')}"
            for k, v in sorted(grouped_chunks.items(), key=lambda kv: -len(kv[1]))
            if v
        ) or "none"
        steps.append({
            "icon": "\U0001f4d6", "label": "Searching SOP knowledge base",
            "detail": f"{chunk_count} chunk(s) retrieved: {ctype_summary}",
            "status": "done",
        })

        # ── Steps 3+: Metabase queries ────────────────────────────
        if query_results:
            for qr in query_results:
                rows = (qr.get("data") or {}).get("rows", [])
                name = qr.get("query_name", "query").replace("_", " ")
                if qr.get("success"):
                    preview = f" | {str(rows[0])[:80]}" if rows else " (empty)"
                    steps.append({
                        "icon": "\U0001f4ca", "label": f"Metabase: {name}",
                        "detail": f"{len(rows)} row(s) returned{preview}",
                        "status": "done",
                    })
                else:
                    steps.append({
                        "icon": "\u26a0\ufe0f", "label": f"Metabase: {name}",
                        "detail": f"Query failed — {qr.get('error', 'unknown error')}",
                        "status": "warning",
                    })
        else:
            steps.append({
                "icon": "\U0001f4ca", "label": "Metabase queries",
                "detail": "No AWBs found in ticket — skipped data queries",
                "status": "warning",
            })

        # ── Step: Gemini reasoning (placeholder while calling) ────
        steps.append({
            "icon": "\U0001f914", "label": "Reasoning with Gemini...",
            "detail": "Applying SOP rules to ticket context and query data",
            "status": "thinking",
        })

        # Format query results
        query_text = _format_query_results(query_results)

        # Build prompt (Stage 0 block is injected ahead of the SOP block)
        prompt = _build_prompt(ticket, sop_context, query_text, stage0_block=stage0_block)

        logger.info(f"[Brain] Processing ticket {ticket.get('ticket_id')} — calling Gemini")

        # Call Gemini
        raw = self._gemini.decide(prompt)

        # Build BrainDecision
        decision = BrainDecision(
            action              = raw.get("action", "stuck"),
            clean_problem       = raw.get("clean_problem", ""),
            response_to_captain = raw.get("response_to_captain", ""),
            escalation_queue    = raw.get("escalation_queue", ""),
            escalation_reason   = raw.get("escalation_reason", ""),
            stuck_question      = raw.get("stuck_question", ""),
            missing_fields      = raw.get("missing_fields", []),
            confidence          = float(raw.get("confidence", 0)),
            scenario_identified = raw.get("scenario_identified", ""),
            reasoning           = raw.get("reasoning", ""),
            usage               = raw.get("_usage", {}),
        )

        # ── Guardrail: Rule 1 — captain's claim with empty Metabase ──
        # Captain asserts they verified data ("metabase shows X", "amount
        # recovered", etc.) but our independent Metabase queries returned
        # nothing. Acting on the captain's claim violates Rule 1.
        try:
            if decision.action in ("respond", "escalate"):
                _matched_phrase = _rule_1_match(ticket, query_results)
                if _matched_phrase:
                    _orig_action     = decision.action
                    _orig_confidence = decision.confidence
                    decision.action = "stuck"
                    decision.stuck_question = (
                        f"Captain claims they verified data (\"{_matched_phrase}\"), "
                        f"but Metabase queries returned empty/failed. Trainer needs to "
                        f"pull Log10 / verify independently before {_orig_action}."
                    )
                    decision.confidence = min(decision.confidence, 5.0)
                    decision.guardrail_triggered = "rule_1_unverified_claim"
                    logger.warning(
                        f"[Guardrail] rule_1_unverified_claim fired on ticket="
                        f"{ticket.get('ticket_id')}: phrase=\"{_matched_phrase}\", "
                        f"queue={ticket.get('queue')}, awbs={ticket.get('awb_numbers')}. "
                        f"Overrode action {_orig_action}->stuck, capped confidence "
                        f"{_orig_confidence}->{decision.confidence}"
                    )
        except Exception as e:
            logger.debug(f"[Guardrail] rule_1 check skipped: {e}")

        # ── Guardrail: Rule 2 — Stage 0 family lock ───────────────
        # If Stage 0 ran with high confidence and emitted a specific L&D
        # loss_type, the chosen scenario MUST belong to that loss family.
        # Otherwise main reasoning silently escaped Stage 0's diagnosis.
        # Skip if Rule 1 already triggered (one guardrail flag per decision).
        try:
            if not decision.guardrail_triggered:
                from src.llm.scenario_families import (
                    family_mismatch, describe_families,
                )
                _a = locals().get("assessment", None)
                if (_a is not None
                    and getattr(_a, "domain_confidence", "") == "high"
                    and family_mismatch(decision.scenario_identified, getattr(_a, "loss_type", ""))):
                    _orig_action     = decision.action
                    _orig_confidence = decision.confidence
                    _actual_family   = describe_families(decision.scenario_identified)
                    decision.action = "stuck"
                    decision.stuck_question = (
                        f"Stage 0 diagnosed loss_type={_a.loss_type} with high confidence, "
                        f"but main reasoning picked scenario {decision.scenario_identified} "
                        f"from family {_actual_family}. Which is correct?"
                    )
                    decision.confidence = min(decision.confidence, 5.0)
                    decision.guardrail_triggered = "rule_2_family_mismatch"
                    logger.warning(
                        f"[Guardrail] rule_2_family_mismatch fired on ticket="
                        f"{ticket.get('ticket_id')}: stage0={_a.loss_type}/high vs "
                        f"scenario={decision.scenario_identified} ({_actual_family}). "
                        f"Overrode action {_orig_action}->stuck, capped confidence "
                        f"{_orig_confidence}->{decision.confidence}"
                    )
        except Exception as e:
            logger.debug(f"[Guardrail] rule_2 check skipped: {e}")

        decision.auto_send = (
            decision.action == "respond"
            and decision.confidence >= AUTO_SEND_CONFIDENCE
        )

        # ── Mode gate — review mode blocks all auto-sends ─────────
        # When data/.mode == "review", even high-confidence respond decisions
        # must be human-approved. Default is "review" (safe). Only flip to
        # "autonomous" via the dashboard toggle once flip-rate data justifies it.
        if decision.auto_send:
            try:
                from src.api.mode import get_mode
                if get_mode() != "autonomous":
                    decision.auto_send = False
                    logger.info(
                        f"[Mode] auto_send blocked by review mode for ticket="
                        f"{ticket.get('ticket_id')} (confidence={decision.confidence}, "
                        f"scenario={decision.scenario_identified})"
                    )
            except Exception as e:
                logger.debug(f"[Mode] mode check skipped: {e}")

        # ── Update reasoning step ─────────────────────────────────
        steps[-1] = {
            "icon": "\U0001f914", "label": "Gemini reasoning complete",
            "detail": (decision.reasoning[:200] + "…") if len(decision.reasoning) > 200 else decision.reasoning,
            "status": "done",
        }

        # ── Final decision step ───────────────────────────────────
        if decision.action == "respond":
            auto_tag = " · AUTO-SEND" if decision.auto_send else " · Queued for review"
            steps.append({
                "icon": "\u2705", "label": f"Decision: RESPOND — confidence {decision.confidence}/10",
                "detail": (decision.scenario_identified or "SOP matched — draft reply ready") + auto_tag,
                "status": "done",
            })
        elif decision.action == "escalate":
            steps.append({
                "icon": "\U0001f53a", "label": f"Decision: ESCALATE — confidence {decision.confidence}/10",
                "detail": f"Route to: {decision.escalation_queue or 'L2'} | {decision.escalation_reason[:100]}",
                "status": "done",
            })
        else:
            upgrade_msg = _blocker_upgrade(ticket, decision, query_results)
            steps.append({
                "icon": "\U0001f6ab", "label": f"Blocked — {decision.action}",
                "detail": decision.stuck_question or "Missing information required to resolve",
                "status": "blocked",
                "upgrade": upgrade_msg,
            })

        decision.thinking_steps = steps
        # Capture Stage 0 dump on the decision for downstream observability (test runs, UI)
        try:
            decision.stage0 = {
                "queue_key_matched":   getattr(assessment, "queue_key_matched", ""),
                "queue_status":        getattr(assessment, "queue_status", ""),
                "physical_event":      getattr(assessment, "physical_event", ""),
                "loss_type":           getattr(assessment, "loss_type", ""),
                "reason_l1_likely":    getattr(assessment, "reason_l1_likely", ""),
                "captain_claim":       getattr(assessment, "captain_claim", ""),
                "scenario_hint":       getattr(assessment, "scenario_hint", ""),
                "scan_logic":          getattr(assessment, "scan_logic", ""),
                "domain_confidence":   getattr(assessment, "domain_confidence", ""),
                "missing_info":        list(getattr(assessment, "missing_info", []) or []),
            }
        except NameError:
            # `assessment` not bound (Stage 0 errored) — leave default {}
            pass

        # Log stuck tickets to queue file for trainer review
        if decision.action == "stuck":
            self._log_stuck(ticket, decision)

        logger.info(
            f"[Brain] ticket={ticket.get('ticket_id')} "
            f"action={decision.action} confidence={decision.confidence} "
            f"auto_send={decision.auto_send}"
        )
        return decision

    def _log_stuck(self, ticket: Dict, decision: BrainDecision):
        """Save stuck tickets to file for trainer review in the morning."""
        STUCK_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp":    datetime.utcnow().isoformat(),
            "ticket_id":    ticket.get("ticket_id"),
            "subject":      ticket.get("subject", ""),
            "queue":        ticket.get("queue", ticket.get("queue_key", "")),
            "question":     decision.stuck_question,
            "reasoning":    decision.reasoning,
            "answered":     False,
            "answer":       None,
        }
        with open(STUCK_QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"[Brain] Stuck ticket logged: {ticket.get('ticket_id')}")

    def answer_stuck(self, ticket_id: str, answer: str):
        """
        Trainer answers a stuck question.
        Answer gets added back to the SOP store as new KT.
        """
        # Load stuck queue, find the entry
        if not STUCK_QUEUE_FILE.exists():
            return
        entries = []
        question_text = ""
        with open(STUCK_QUEUE_FILE, encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                if e["ticket_id"] == ticket_id and not e["answered"]:
                    e["answered"] = True
                    e["answer"]   = answer
                    question_text = e["question"]
                entries.append(e)

        # Rewrite file
        with open(STUCK_QUEUE_FILE, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        # Save Q&A to trainer file
        TRAINER_QA_FILE.parent.mkdir(parents=True, exist_ok=True)
        qa_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "ticket_id": ticket_id,
            "question":  question_text,
            "answer":    answer,
        }
        with open(TRAINER_QA_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(qa_entry, ensure_ascii=False) + "\n")

        # Add answer to SOP store so agent learns from it
        kt_text = f"Q: {question_text}\nA: {answer}"
        self._sop.add_knowledge(
            kt_text,
            source=f"trainer_qa_{ticket_id}",
            content_type="trainer_qa",
        )
        logger.info(f"[Brain] Trainer answer for {ticket_id} added to knowledge base")

    def reload_knowledge(self):
        """Reload all SOP files + Stage 0 domain — call after KT updates."""
        self._sop.reload()
        _stage0.reload_domain()
        logger.info("[Brain] Knowledge base + Stage 0 domain reloaded")


# Singleton
_brain: AgentBrain | None = None

def get_agent_brain() -> AgentBrain:
    global _brain
    if _brain is None:
        _brain = AgentBrain()
    return _brain
