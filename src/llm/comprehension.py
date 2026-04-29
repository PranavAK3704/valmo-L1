"""
Stage 1: Ticket Comprehension
Stage 2: Scenario Matching

Stage 1 translates raw captain gibberish → clean ops language (no SOP knowledge).
Stage 2 matches the clean problem against the scenario catalog → top 3 ranked matches.
"""

import json
import logging
import re
from typing import Dict, List

from src.llm.scenario_catalog import SCENARIO_CATALOG, SCENARIO_BY_ID, get_catalog_for_queue

logger = logging.getLogger(__name__)


COMPREHENSION_SYSTEM = """You are a senior Valmo logistics operations analyst with 5 years of experience.

Your job is NOT to paraphrase what the captain said.
Your job is to THINK about what they need — then state that clearly.

Read the ticket, reason through it like a human ops expert would, and output structured JSON.

## How to think:

Step 1 — What is the captain's SITUATION? (what happened)
Step 2 — What do they NEED from us? (what action they want)
Step 3 — What ops category does this fall into? (shortage, hardstop, consumables, payment, orders, tech)
Step 4 — What specific signals identify this?

## Examples of good vs bad comprehension:

BAD: "Captain says flyer not available and order not dispatched"
GOOD: "Captain's consumables order (2000 flyers, order #197012, seller: Prin Polymers) has not been dispatched — needs order status check and priority dispatch escalation"

BAD: "Captain complaining about loss marked"
GOOD: "Hardstop loss marked on AWB VLxxx — captain claims wrong loss because they made a valid connection within SOP timeline — needs Log10 scan verification for reversal"

BAD: "Captain says suspicious shipment"
GOOD: "UNCLEAR: captain flags shipment as suspicious but does not specify what is suspicious — clarification needed before any SOP can be applied"

## Output ONLY valid JSON — no markdown:
{
  "clean_problem": "What the captain needs — framed as the ACTION required, not a paraphrase of their complaint",
  "ops_translation": "Precise ops category: shortage_loss | hardstop_loss | missing_item | consumables_order | consumables_quality | payment_pending | cod_pendency | orders_planning | tech_issue | unclear",
  "key_signals": ["specific identifiable facts from the ticket — order numbers, AWBs, quantities, seller names, SOP-relevant terms"],
  "is_gibberish": false,
  "gibberish_reason": null
}

## Rules:
- is_gibberish = true ONLY if literally nothing coherent can be extracted
- key_signals = concrete facts, not vague words. "order #197012", "2000 flyers", "Prin Polymers", "AWB VL123" — not "captain is upset"
- Common Hinglish: "muje/mujhe"=me, "reciverd/milna"=received, "nahi aaya"=didn't arrive, "galat"=wrong, "loss lag raha"=loss being marked, "reversal chahiye"=need reversal, "nahi mila"=not received, "bhej do"=please send
- "delivered" = delivered to END CUSTOMER (not to hub)
- VAGUE TERMS: If captain uses undefined terms ("suspicious", "some issue", "problem") without explaining what — write "UNCLEAR: [term] mentioned but not explained — clarification needed" in clean_problem
- Do NOT invent facts not in the ticket. If order number is there, include it. If not, don't make one up.
"""


def understand_ticket(ticket: Dict) -> Dict:
    """
    Stage 1: Translate raw ticket into clean ops language.
    Returns: {clean_problem, ops_translation, key_signals, is_gibberish, gibberish_reason}
    """
    from src.llm.gemini_client import get_gemini_client
    gemini = get_gemini_client()

    subject = ticket.get("subject") or ticket.get("subject_line") or ""
    detail = (
        ticket.get("full_description") or
        ticket.get("detail") or
        ticket.get("description") or
        ""
    )
    queue = ticket.get("queue") or ticket.get("queue_key") or ""
    awbs = ticket.get("awb_numbers") or []

    ticket_text = f"""Queue: {queue}
AWBs: {', '.join(awbs) if awbs else 'None provided'}
Subject: {subject}
Captain's message: {detail or subject}"""

    try:
        result = gemini.generate_json(ticket_text, system_prompt=COMPREHENSION_SYSTEM)
        logger.info(f"[Stage1] clean_problem: {result.get('clean_problem', '')[:120]}")
        return result
    except Exception as e:
        logger.error(f"[Stage1] Failed: {e}")
        return {
            "clean_problem": f"{subject} — {detail}"[:300],
            "ops_translation": f"Queue: {queue}",
            "key_signals": [],
            "is_gibberish": False,
            "gibberish_reason": None,
        }


MATCHING_SYSTEM = """You are a Valmo SOP scenario matcher.
Given a clean problem statement and a catalog of SOP scenarios, rank the TOP 3 most relevant scenarios.

Output ONLY a valid JSON array — no markdown:
[
  {"id": "scenario_id", "score": 95, "reason": "one-line reason this matches"},
  {"id": "scenario_id", "score": 60, "reason": "one-line reason"},
  {"id": "scenario_id", "score": 25, "reason": "one-line reason"}
]

Score 0-100. Only include entries with score >= 10. If fewer than 3 match, return fewer.
Be precise — wrong scenario identification leads to wrong resolutions.
"""


def match_scenario(clean_problem: str, key_signals: List[str], queue: str) -> List[Dict]:
    """
    Stage 2: Match clean problem against scenario catalog.
    Returns top 3: [{id, title, score, reason, action, action_detail, sop_reference}]
    """
    from src.llm.gemini_client import get_gemini_client
    gemini = get_gemini_client()

    relevant = get_catalog_for_queue(queue)

    catalog_text = "\n".join([
        f'id="{s["id"]}" | title="{s["title"]}" | signals={s["signals"]}'
        for s in relevant
    ])

    prompt = f"""Clean problem: "{clean_problem}"
Key signals: {key_signals}
Queue: {queue}

Scenario catalog:
{catalog_text}"""

    try:
        matches_raw = gemini.generate_json(prompt, system_prompt=MATCHING_SYSTEM, expect_list=True)
        # generate_json wraps lists as {"_list": [...], "_usage": {...}} for token tracking
        if isinstance(matches_raw, dict) and "_list" in matches_raw:
            matches_raw = matches_raw["_list"]
        if not isinstance(matches_raw, list):
            matches_raw = []

        result = []
        for m in matches_raw[:3]:
            sid = m.get("id", "")
            entry = SCENARIO_BY_ID.get(sid, {})
            if not entry:
                continue
            result.append({
                "id": sid,
                "title": entry.get("title", sid),
                "score": int(m.get("score", 0)),
                "reason": m.get("reason", ""),
                "action": entry.get("action", ""),
                "action_detail": entry.get("action_detail", ""),
                "needs_data": entry.get("needs_data", False),
                "sop_reference": entry.get("sop_reference", ""),
                "category": entry.get("category", ""),
            })

        top = result[0] if result else {}
        logger.info(f"[Stage2] Top match: {top.get('id')} ({top.get('score')}%) — {top.get('title', '')[:60]}")
        return result

    except Exception as e:
        logger.error(f"[Stage2] Matching failed: {e}")
        return []
