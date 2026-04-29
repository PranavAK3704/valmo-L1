"""
Stage 0 — Supply Chain Situation Assessment.

One Gemini call BEFORE SOP matching that reasons about what physically happened
in the Valmo network. Output is a structured assessment injected into the main
reasoning prompt — so the main call diagnoses from a starting point, not blind.

Per-queue domain knowledge lives in data/sop_knowledge/stage0_domain.json.
That file has L&D fully populated and other queues as placeholders that the KT
engine can fill via /api/kt/structured (no restart needed).
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.llm.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)

DOMAIN_FILE = Path(__file__).parent.parent.parent / "data" / "sop_knowledge" / "stage0_domain.json"


@dataclass
class SituationAssessment:
    domain_confidence: str = "low"           # high | medium | low
    queue_status: str = "unknown"            # complete | placeholder | unknown
    queue_key_matched: str = ""              # e.g. "losses_and_debits"
    physical_event: str = ""                 # one-sentence ops diagnosis
    loss_type: str = ""                      # hardstop | shortage | misroute | ...
    reason_l1_likely: str = ""               # canonical Reason L1 from PDF taxonomy
    captain_claim: str = ""                  # what captain says happened
    critical_scans_to_check: List[str] = field(default_factory=list)
    scan_logic: str = ""                     # the exact scan condition that decides
    scenario_hint: str = ""                  # likely scenario_id(s) e.g. "HS_1_1 or HS_1_2"
    missing_info: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    usage: Dict[str, Any] = field(default_factory=dict)


def _load_domain() -> dict:
    try:
        with open(DOMAIN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[Stage0] Could not load domain file: {e}")
        return {"queues": {}}


_DOMAIN = _load_domain()


def reload_domain():
    """Re-read stage0_domain.json — call after KT engine updates a queue section."""
    global _DOMAIN
    _DOMAIN = _load_domain()
    logger.info(f"[Stage0] Domain reloaded — queues: {list(_DOMAIN.get('queues', {}).keys())}")


def get_domain() -> dict:
    return _DOMAIN


def list_queues() -> list:
    """Return [(queue_key, status, aliases)] for the KT UI."""
    out = []
    for qkey, section in _DOMAIN.get("queues", {}).items():
        out.append({
            "queue_key": qkey,
            "status": section.get("status", "unknown"),
            "aliases": section.get("queue_aliases", []),
            "metabase_query_count": len(section.get("metabase_columns", {}) or {}),
            "loss_type_count": len(section.get("loss_type_taxonomy", {}) or {}),
            "rule_count": len(section.get("preprocessing_rules", []) or []),
        })
    return out


def get_template(queue_key: str) -> dict:
    """
    Return a structured KT template for a queue. If the queue already has data,
    merges current state into the template so the user sees what's filled vs blank.
    """
    domain = _load_domain()
    section = domain.get("queues", {}).get(queue_key, {})

    # Pre-filled with current state, or hints if empty
    template = {
        "_comment": (
            "Fill what you know — partial is fine. Validate first, then Activate. "
            "Required: queue_aliases (>=1), metabase_columns (>=1 with real description). "
            "Lines starting with '_' are ignored."
        ),
        "queue_key": queue_key,
        "queue_aliases": section.get("queue_aliases") or [],
        "metabase_columns": section.get("metabase_columns") or {
            "_example_query_name": "<comma-separated columns>; what each means; which values trigger which response"
        },
        "preprocessing_rules": section.get("preprocessing_rules") or [
            "<gotcha or mandatory check the agent must do before answering>"
        ],
        "scenarios": [
            {
                "_comment": "Optional. Adds a new scenario beyond what's already in sop_structured.json.",
                "scenario_id": "<e.g. CON_5>",
                "label": "<short label>",
                "captain_signals": ["<phrase the captain uses>"],
                "conditions": ["<what makes this scenario match>"],
                "action": "respond | escalate | needs_info",
                "response_to_captain": "<template reply>",
            }
        ],
    }

    # For L&D-shape queues, expose loss_type/reason_l1 too
    if section.get("loss_type_taxonomy") or queue_key == "losses_and_debits":
        template["loss_type_taxonomy"] = section.get("loss_type_taxonomy") or {
            "_example": {
                "physical_event": "<one-line ops description>",
                "trigger_scans": "<which scan condition triggers this>",
                "captain_signals": ["..."],
                "scenario_family": "...",
                "common_sub_scenarios": ["..."]
            }
        }
        template["reason_l1_taxonomy"] = section.get("reason_l1_taxonomy") or {}

    return template


def validate_payload(payload: Dict[str, Any]) -> dict:
    """
    Lint a structured KT payload. Returns {ok: bool, errors: [...], warnings: [...]}.
    Strips comment fields (keys starting with _) before saving.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(payload, dict):
        return {"ok": False, "errors": ["Payload must be a JSON object"], "warnings": []}

    queue_key = (payload.get("queue_key") or "").strip()
    if not queue_key:
        errors.append("queue_key is required (e.g. 'consumables')")

    aliases = payload.get("queue_aliases") or []
    if not isinstance(aliases, list) or len(aliases) == 0:
        errors.append("queue_aliases must have at least 1 entry — these are the names Kapture sends in the queue field")

    cols = payload.get("metabase_columns") or {}
    if not isinstance(cols, dict):
        errors.append("metabase_columns must be a JSON object {query_name: description}")
    else:
        # Strip comment fields
        real_cols = {k: v for k, v in cols.items() if not k.startswith("_")}
        if not real_cols:
            errors.append("metabase_columns must have at least 1 real query (no _ prefix)")
        else:
            for q, desc in real_cols.items():
                d = str(desc or "").strip()
                if not d:
                    errors.append(f"metabase_columns['{q}']: description is empty")
                elif "TODO" in d.upper() or d.startswith("<"):
                    errors.append(f"metabase_columns['{q}']: description still has placeholder text (TODO or <...>)")
                elif len(d) < 25:
                    warnings.append(f"metabase_columns['{q}']: description is very short ({len(d)} chars) — agent may struggle to interpret query results")

    rules = payload.get("preprocessing_rules") or []
    if isinstance(rules, list):
        for r in rules:
            if isinstance(r, str) and r.startswith("<"):
                warnings.append(f"preprocessing_rules: still has placeholder text — '{r[:50]}'")

    scenarios = payload.get("scenarios") or []
    if isinstance(scenarios, list):
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            if sc.get("_comment"):
                continue  # template stub
            if sc.get("scenario_id", "").startswith("<"):
                continue  # unfilled stub
            if not sc.get("scenario_id"):
                warnings.append("A scenario is missing scenario_id")
            if sc.get("action") not in ("respond", "escalate", "needs_info", None):
                warnings.append(f"scenarios[{sc.get('scenario_id', '?')}]: action should be respond | escalate | needs_info")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def _strip_comments(obj: Any) -> Any:
    """Remove keys starting with _ recursively, and skip stub list entries."""
    if isinstance(obj, dict):
        return {
            k: _strip_comments(v)
            for k, v in obj.items()
            if not k.startswith("_") and not (isinstance(v, str) and v.startswith("<"))
        }
    if isinstance(obj, list):
        cleaned = []
        for item in obj:
            if isinstance(item, dict) and item.get("_comment"):
                continue
            if isinstance(item, str) and item.startswith("<"):
                continue
            cleaned.append(_strip_comments(item))
        return cleaned
    return obj


def upsert_queue(queue_key: str, payload: Dict[str, Any]) -> dict:
    """
    Merge KT-provided fields into a queue's section in stage0_domain.json.
    Creates the queue section if it doesn't exist. Persists to disk and reloads.

    payload may contain (all optional):
      - queue_aliases: list[str]               (extends existing aliases, dedup)
      - metabase_columns: dict[str,str]        (merged — overwrites per-key)
      - loss_type_taxonomy: dict[str,dict]     (merged per loss type)
      - reason_l1_taxonomy: dict[str,str]      (merged per key)
      - preprocessing_rules: list[str]         (appended, dedup)

    Returns the updated section.
    """
    payload = _strip_comments(payload) or {}

    domain = _load_domain()
    queues = domain.setdefault("queues", {})
    section = queues.get(queue_key)
    if section is None:
        section = {
            "status": "placeholder",
            "queue_aliases": [],
            "loss_type_taxonomy": {},
            "metabase_columns": {},
            "preprocessing_rules": [],
        }
        queues[queue_key] = section

    # Merge aliases (dedup, preserve order)
    if payload.get("queue_aliases"):
        existing = section.get("queue_aliases") or []
        for a in payload["queue_aliases"]:
            if a and a not in existing:
                existing.append(a)
        section["queue_aliases"] = existing

    # Merge metabase columns
    if payload.get("metabase_columns"):
        cols = section.get("metabase_columns") or {}
        for k, v in payload["metabase_columns"].items():
            if k:
                cols[k] = v
        section["metabase_columns"] = cols

    # Merge loss type taxonomy
    if payload.get("loss_type_taxonomy"):
        tax = section.get("loss_type_taxonomy") or {}
        for k, v in payload["loss_type_taxonomy"].items():
            if isinstance(v, dict):
                existing = tax.get(k) or {}
                existing.update(v)
                tax[k] = existing
            else:
                tax[k] = v
        section["loss_type_taxonomy"] = tax

    # Merge reason_l1 taxonomy
    if payload.get("reason_l1_taxonomy"):
        rl1 = section.get("reason_l1_taxonomy") or {}
        rl1.update(payload["reason_l1_taxonomy"])
        section["reason_l1_taxonomy"] = rl1

    # Append preprocessing rules (dedup)
    if payload.get("preprocessing_rules"):
        rules = section.get("preprocessing_rules") or []
        for r in payload["preprocessing_rules"]:
            if r and r not in rules:
                rules.append(r)
        section["preprocessing_rules"] = rules

    # Merge scenarios (upsert by scenario_id)
    if payload.get("scenarios"):
        existing = section.get("scenarios") or []
        by_id = {sc.get("scenario_id"): sc for sc in existing if isinstance(sc, dict) and sc.get("scenario_id")}
        for sc in payload["scenarios"]:
            if not isinstance(sc, dict):
                continue
            sid = sc.get("scenario_id")
            if not sid:
                continue
            by_id[sid] = {**by_id.get(sid, {}), **sc}
        section["scenarios"] = list(by_id.values())

    # Promote to "complete" if metabase_columns are populated AND at least
    # one column entry no longer says TODO
    cols = section.get("metabase_columns") or {}
    has_real_columns = any("TODO" not in str(v) for v in cols.values()) and bool(cols)
    if has_real_columns:
        section["status"] = "complete"

    # Drop the _kt_hint field once activated
    if section.get("status") == "complete" and "_kt_hint" in section:
        section.pop("_kt_hint", None)

    # Persist
    DOMAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DOMAIN_FILE, "w", encoding="utf-8") as f:
        json.dump(domain, f, indent=2, ensure_ascii=False)

    reload_domain()
    return section


def _resolve_queue_section(ticket: Dict) -> Tuple[str, dict]:
    """
    Map ticket → (queue_key, section_dict).
    Falls back to substring match against queue_aliases. Returns ("", {}) if unmatched.
    """
    queue = (ticket.get("queue") or ticket.get("queue_key") or "").strip().lower()
    sub_queue = (ticket.get("sub_queue") or "").strip().lower()
    candidates = [c for c in (queue, sub_queue) if c]
    queues = _DOMAIN.get("queues", {})

    # First pass: exact key or exact alias match
    for qkey, section in queues.items():
        aliases = [a.strip().lower() for a in section.get("queue_aliases", [])]
        for cand in candidates:
            if cand == qkey.lower() or cand in aliases:
                return qkey, section

    # Second pass: substring fuzzy match
    for qkey, section in queues.items():
        aliases = [a.strip().lower() for a in section.get("queue_aliases", [])]
        for cand in candidates:
            for alias in aliases + [qkey.lower()]:
                if alias and (cand in alias or alias in cand):
                    return qkey, section

    return "", {}


def _build_prompt(ticket: Dict, queue_key: str, section: dict) -> str:
    scan_taxonomy = _DOMAIN.get("_meta", {}).get("scan_taxonomy", {})
    scan_block = "\n".join(f"  - {name}: {desc}" for name, desc in scan_taxonomy.items())

    subject = ticket.get("subject", "")
    detail = (ticket.get("detail") or ticket.get("description") or
              ticket.get("full_description") or "")
    awbs = ticket.get("awb_numbers") or ticket.get("awbs") or []
    sub_queue = ticket.get("sub_queue") or ""
    queue = ticket.get("queue") or ticket.get("queue_key") or ""

    # Truncate description aggressively to keep Stage 0 cheap
    detail = detail[:2500]

    if section.get("status") == "complete":
        loss_taxonomy = section.get("loss_type_taxonomy", {})
        taxonomy_lines = []
        for ltype, info in loss_taxonomy.items():
            taxonomy_lines.append(
                f"### {ltype}\n"
                f"  Physical event : {info.get('physical_event','')}\n"
                f"  Trigger scans  : {info.get('trigger_scans','')}\n"
                f"  Captain words  : {', '.join(info.get('captain_signals', []))}\n"
                f"  Scenario family: {info.get('scenario_family','')}\n"
                f"  Sub-scenarios  : {', '.join(info.get('common_sub_scenarios', []))}"
            )
        taxonomy_block = "\n\n".join(taxonomy_lines)
        reason_l1_lines = "\n".join(
            f"  - {k}: {v}" for k, v in section.get("reason_l1_taxonomy", {}).items()
        )
        rules_block = "\n".join(f"  - {r}" for r in section.get("preprocessing_rules", []))

        return f"""You are the Stage-0 supply chain reasoner for Valmo (Meesho's logistics arm).

Job: read a ticket and OUTPUT a structured diagnosis of WHAT PHYSICALLY HAPPENED in the network.
You do NOT decide the SOP outcome. You only diagnose the physical event so the next stage can match it to the right SOP scenario.

## SCAN TAXONOMY (Valmo ops tracking)
{scan_block}

## QUEUE: {queue_key}  (status: complete domain knowledge)

## LOSS TYPE TAXONOMY for this queue
{taxonomy_block}

## REASON L1 TAXONOMY (Log10 classification this would map to)
{reason_l1_lines}

## PREPROCESSING RULES YOU MUST RESPECT
{rules_block}

## TICKET
Queue        : {queue}
Sub-queue    : {sub_queue}
Subject      : {subject}
AWBs         : {', '.join(awbs) if awbs else 'NONE PROVIDED'}
Description  :
{detail}

## YOUR OUTPUT (JSON ONLY — no markdown, no commentary)
{{
  "loss_type"              : "hardstop | shortage | misroute | pilot_lost_on_field | not_inscanned | delivered_unrecorded | tech_no_loss | tech_with_loss | unknown",
  "reason_l1_likely"       : "<one of the Reason L1 keys above, or empty>",
  "physical_event"         : "<one clear sentence describing what physically happened — written in supply chain ops language>",
  "captain_claim"          : "<one sentence: what the captain is claiming happened>",
  "critical_scans_to_check": ["INWARD_SCAN", "MANIFEST_SCAN"],
  "scan_logic"             : "<one sentence: the exact scan condition that decides this case>",
  "scenario_hint"          : "<most likely scenario_id(s) from sub-scenarios above, e.g. 'HS_1_1 or HS_1_2'>",
  "missing_info"           : ["awb", "scan_date_range"],
  "domain_confidence"      : "high | medium | low"
}}

Rules:
- Output ONLY the JSON object. No prose, no markdown.
- Diagnose from supply chain physics, not from what the captain wants.
- If the captain says "loss marked but I already delivered" → physical event is delivered_unrecorded, NOT hardstop.
- If the ticket is genuinely vague → loss_type="unknown", domain_confidence="low".
- If the captain reports a tech issue without any loss being marked → tech_no_loss.
- If both tech failure AND loss are mentioned → tech_with_loss.
"""

    # Placeholder queue — shallow classification only
    return f"""You are the Stage-0 reasoner for Valmo (Meesho's logistics arm).

This ticket is from a queue where detailed domain knowledge has NOT yet been loaded.
Produce a shallow but useful classification only.

## SCAN TAXONOMY (universal Valmo scans)
{scan_block}

## TICKET
Queue        : {queue}
Sub-queue    : {sub_queue}
Subject      : {subject}
AWBs         : {', '.join(awbs) if awbs else 'NONE PROVIDED'}
Description  :
{detail}

## OUTPUT (JSON ONLY)
{{
  "loss_type"              : "unknown",
  "reason_l1_likely"       : "",
  "physical_event"         : "<one sentence: what the captain is reporting, in plain ops language>",
  "captain_claim"          : "<one sentence: the captain's claim verbatim summary>",
  "critical_scans_to_check": [],
  "scan_logic"             : "Domain knowledge for this queue not loaded — defer to SOP retrieval.",
  "scenario_hint"          : "",
  "missing_info"           : [],
  "domain_confidence"      : "low"
}}

Rules:
- Output ONLY the JSON object.
- Keep physical_event concise and faithful to the ticket text.
"""


def assess(ticket: Dict) -> SituationAssessment:
    """Run Stage 0 — one Gemini call returning a structured assessment."""
    queue_key, section = _resolve_queue_section(ticket)

    if not section:
        logger.info(f"[Stage0] No queue match for queue={ticket.get('queue')!r}")
        return SituationAssessment(
            domain_confidence="low",
            queue_status="unknown",
            physical_event="",
            captain_claim="",
            scan_logic="No matching queue section in stage0_domain.json",
        )

    prompt = _build_prompt(ticket, queue_key, section)
    try:
        client = get_gemini_client()
        raw = client.generate_json(prompt, temperature=0.1)
    except Exception as e:
        logger.warning(f"[Stage0] Gemini call failed: {e}")
        return SituationAssessment(
            domain_confidence="low",
            queue_status=section.get("status", "unknown"),
            queue_key_matched=queue_key,
            scan_logic=f"Stage 0 call failed: {e}",
        )

    if not isinstance(raw, dict):
        raw = {}
    usage = raw.pop("_usage", {}) if isinstance(raw, dict) else {}

    return SituationAssessment(
        domain_confidence=str(raw.get("domain_confidence", "low") or "low"),
        queue_status=section.get("status", "unknown"),
        queue_key_matched=queue_key,
        physical_event=str(raw.get("physical_event", "") or ""),
        loss_type=str(raw.get("loss_type", "") or ""),
        reason_l1_likely=str(raw.get("reason_l1_likely", "") or ""),
        captain_claim=str(raw.get("captain_claim", "") or ""),
        critical_scans_to_check=list(raw.get("critical_scans_to_check") or []),
        scan_logic=str(raw.get("scan_logic", "") or ""),
        scenario_hint=str(raw.get("scenario_hint", "") or ""),
        missing_info=list(raw.get("missing_info") or []),
        raw=raw,
        usage=usage,
    )


def to_prompt_block(a: SituationAssessment) -> str:
    """Format the assessment as a context block injected into the main Gemini call."""
    if a.queue_status == "unknown" or not a.physical_event:
        return ""

    confidence_tag = {
        "high":   "HIGH — domain complete for this queue",
        "medium": "MEDIUM — partial domain knowledge",
        "low":    "LOW — limited domain knowledge, treat as hint only",
    }.get(a.domain_confidence, "LOW")

    lines = [
        "## STAGE 0 — SITUATION ASSESSMENT (pre-reasoned by supply chain analyzer)",
        f"Queue matched    : {a.queue_key_matched}  |  Domain confidence: {confidence_tag}",
        f"Physical event   : {a.physical_event}",
    ]
    if a.loss_type and a.loss_type != "unknown":
        lines.append(f"Loss type        : {a.loss_type}")
    if a.reason_l1_likely:
        lines.append(f"Reason L1 likely : {a.reason_l1_likely}")
    if a.captain_claim:
        lines.append(f"Captain claim    : {a.captain_claim}")
    if a.scenario_hint:
        lines.append(f"Scenario hint    : {a.scenario_hint}")
    if a.critical_scans_to_check:
        lines.append(f"Scans to verify  : {', '.join(a.critical_scans_to_check)}")
    if a.scan_logic:
        lines.append(f"Decision logic   : {a.scan_logic}")
    if a.missing_info:
        lines.append(f"Missing info     : {', '.join(a.missing_info)}")

    lines.append("")
    lines.append("Use this assessment as your starting diagnosis. Verify it against the SOP decision tree and query data below — override it only if the data clearly contradicts.")
    return "\n".join(lines)
