"""
Scenario → Stage 0 loss_type family mapping.

Used by the Stage 0 family-lock guardrail in agent_brain.process().
When Stage 0 diagnoses a loss_type with high confidence, the main reasoning
call MUST pick a scenario compatible with that loss_type. If it doesn't,
the guardrail overrides to stuck.

Source of truth: stage0_domain.json::loss_type_taxonomy.common_sub_scenarios
and sop_structured.json scenario IDs. Hardcoded here (not extracted at
runtime) to keep the check deterministic and free of file I/O on hot path.

A scenario maps to a SET of loss_types because some HS_* scenarios are
shared across multiple Stage 0 categories (HS_8_1/8_2 fits both
not_inscanned and pilot_lost_on_field, HS_10/11 fit both misroute and
hardstop, etc.).
"""

from typing import Set

# All L&D loss_types Stage 0 can emit
L_AND_D_LOSS_TYPES: Set[str] = {
    "hardstop", "shortage", "misroute",
    "pilot_lost_on_field", "not_inscanned", "delivered_unrecorded",
    "tech_no_loss", "tech_with_loss",
}

# Wildcard set — scenarios that should never trigger the guardrail
# (e.g. fallback "ticket too vague" responses)
_ALL_LD = L_AND_D_LOSS_TYPES | {"non_ld"}

SCENARIO_TO_FAMILY: dict[str, Set[str]] = {
    # ── Hardstop pure SLA-breach ─────────────────────────────────────
    "HS_1_1":    {"hardstop"},
    "HS_1_2":    {"hardstop"},
    "HS_2":      {"hardstop"},
    "HS_3":      {"hardstop"},
    "HS_4":      {"hardstop"},
    "HS_5":      {"hardstop"},
    "HS_6":      {"hardstop"},
    "HS_WAIVER": {"hardstop"},

    # ── Delivered but not recorded ───────────────────────────────────
    "HS_7": {"delivered_unrecorded", "hardstop"},

    # ── HS_8 family (overlapping Stage 0 categories) ─────────────────
    "HS_8_1": {"not_inscanned", "pilot_lost_on_field", "hardstop"},
    "HS_8_2": {"not_inscanned", "pilot_lost_on_field", "hardstop"},

    # ── Seller dependency ────────────────────────────────────────────
    "HS_9_1": {"hardstop"},
    "HS_9_2": {"hardstop"},

    # ── Misroute family ──────────────────────────────────────────────
    "HS_10":   {"misroute", "hardstop"},
    "HS_11_1": {"misroute", "hardstop"},
    "HS_11_2": {"misroute", "hardstop"},

    # ── Shortage family ──────────────────────────────────────────────
    # Real IDs in sop_structured.json are SL_* (theme=shortage_loss).
    # Stage 0 may still emit "SS_*" hint labels in its scenario_hint field,
    # but the main reasoning call picks from sop_structured.json so the IDs
    # the brain actually produces are SL_*.
    "SL_1": {"shortage"},
    "SL_2": {"shortage"},
    "SL_3": {"shortage"},
    "SL_4": {"shortage"},
    "SL_5": {"shortage"},

    # ── Tech scenarios ───────────────────────────────────────────────
    "TECH_1": {"tech_no_loss"},
    "TECH_2": {"tech_with_loss"},

    # ── Standalone pilot ─────────────────────────────────────────────
    "PILOT_1": {"pilot_lost_on_field", "hardstop"},

    # ── Non-L&D queues. Stage 0 won't fire with high confidence here
    # (placeholder domains) — sentinel "non_ld" so the L&D check never
    # false-flags them.
    "CMS_1":      {"non_ld"},
    "COD_1":      {"non_ld"}, "COD_2":      {"non_ld"},
    "CON_1":      {"non_ld"}, "CON_2":      {"non_ld"},
    "CON_3":      {"non_ld"}, "CON_4":      {"non_ld"},
    "CON_PAY_1":  {"non_ld"}, "CON_PAY_1b": {"non_ld"},
    "CON_PAY_2":  {"non_ld"}, "CON_PAY_3":  {"non_ld"},
    "CON_QC_1":   {"non_ld"}, "CON_QC_2":   {"non_ld"},
    "FNF_1":      {"non_ld"}, "FNF_2":      {"non_ld"},
    "INV_1":      {"non_ld"},
    "OP_1":       {"non_ld"}, "OP_2":       {"non_ld"},
    "OP_3":       {"non_ld"}, "OP_4":       {"non_ld"},
    "OP_5":       {"non_ld"}, "OP_6":       {"non_ld"}, "OP_7": {"non_ld"},
    "PAY_1":      {"non_ld"},
    "RZP_1":      {"non_ld"},
    "SCM_1":      {"non_ld"},
    # SL_1..SL_5 are defined above as {"shortage"} — do NOT re-declare them here.
    # They are the real shortage scenario IDs in sop_structured.json.
    "WD_1":       {"non_ld"},

    # ── Fallback "ticket too vague" — compatible with any diagnosis.
    # The agent declining to commit to a scenario is never a family mismatch.
    "VAGUE_1": set(_ALL_LD),
}


def families_for(scenario_id: str) -> Set[str]:
    """Return the set of loss_types this scenario is compatible with.
    Unknown scenarios return an empty set — caller treats empty as 'do not flag'."""
    return SCENARIO_TO_FAMILY.get((scenario_id or "").strip(), set())


def family_mismatch(scenario_id: str, stage0_loss_type: str) -> bool:
    """
    True iff Stage 0 diagnosed a specific L&D loss_type but the chosen scenario
    is mapped to a DIFFERENT family. Returns False (no mismatch) for:
      - empty / unknown stage0 loss_type
      - scenario_id not in our mapping (unknown scenario — don't false-flag)
      - scenario_id whose family set contains the stage0 loss_type
    """
    lt = (stage0_loss_type or "").strip()
    if not lt or lt == "unknown":
        return False
    if lt not in L_AND_D_LOSS_TYPES:
        return False  # Stage 0 emitted something outside the known taxonomy
    compatible = families_for(scenario_id)
    if not compatible:
        return False  # unknown scenario — be conservative, don't flag
    return lt not in compatible


def describe_families(scenario_id: str) -> str:
    """Short human-readable description for the stuck_question text."""
    fams = families_for(scenario_id)
    if not fams:
        return "unknown"
    return "/".join(sorted(fams))
