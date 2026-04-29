"""
VALMO L1 Agent — SOP Registry & Decision Engine  (v3)

Every SOP scenario from Valmo_SOPs_Auto-Sync.xlsx is implemented here
as a deterministic resolver. Queue + SubQueue → correct resolver.
Each resolver examines Metabase query results and returns a DecisionOutput
with:
  - scenario_key  (which SOP path was taken)
  - template_key  (which published template to use)
  - confidence    (drives auto-send vs draft)
  - escalation details if needed

Escalation triggers (from SOPs):
  Loss queue, ANY sub-queue, reversal/waiver scenario → L2
  L1 contests attribution                             → L2
  Evidence mismatch                                   → L2
  Promised load breach / severe load anomaly          → L2
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

from src.models import (
    Queue, SubQueue, ScenarioKey, EscalationReason,
    ExtractedEntities, QueryResult, DecisionOutput
)
from src.decision_engine.sop_loader import get_sop_loader

logger = logging.getLogger(__name__)

# ── LIVE SOP DATA ─────────────────────────────────────────────────────────────
# Fetched from the same Google Sheet the Chrome extension uses.
# When you update the master sheet, the agent picks up changes within 1 hour.
# Falls back to bundled data/sop_database.json if sheet is unreachable.

def get_live_sops() -> Dict:
    """Returns the current live SOP database from Google Sheet."""
    return get_sop_loader().get_sops()

def log_sop_source():
    status = get_sop_loader().status()
    logger.info(
        f"[SOP ENGINE] Using SOPs from: {status['source']} | "
        f"{status['total_sops']} SOPs across {len(status['queues'])} queues | "
        f"Age: {status['age_minutes']}min"
    )


# ─────────────────────────────────────────────
# BASE RESOLVER
# ─────────────────────────────────────────────

class BaseResolver(ABC):
    @abstractmethod
    def resolve(self, entities: ExtractedEntities,
                query_results: List[QueryResult]) -> DecisionOutput:
        ...

    def _rows(self, qr_list: List[QueryResult], name: str) -> List[Dict]:
        for qr in qr_list:
            if qr.query_name == name and qr.success:
                return qr.data.get("rows", [])
        return []

    def _escalate(self, reason: EscalationReason, queue: str,
                  trace: List[str], confidence: float = 1.0) -> DecisionOutput:
        trace.append(f"→ ESCALATE: {reason.value} → {queue}")
        return DecisionOutput(
            scenario_key=ScenarioKey.ESCALATE_TO_L2,
            action="escalate",
            template_key="escalation_acknowledgment",
            confidence=confidence,
            escalation_reason=reason,
            escalation_queue=queue,
            decision_trace=trace,
        )


# ═════════════════════════════════════════════
# LOSSES & DEBITS
# ═════════════════════════════════════════════

class ShortageLossResolver(BaseResolver):
    """
    SOP: Shortage Loss (Shipment Shortage) — 2 scenarios from SOPs sheet

    Scenario A: Attribution still pending
      → L1 handles, close with pending-attribution message

    Scenario B: 100% attribution marked
      B1: Evidence sheet confirms loss on captain + L1 agrees   → close, loss stands
      B2: Evidence sheet confirms loss on captain + L1 contests  → escalate L2
      B3: Loss marked and captain qualifies for waiver            → escalate L2
      B4: Loss recovered from FE                                  → close, recovered
    """

    def resolve(self, entities, query_results):
        trace = ["ShortageLossResolver"]
        loss_rows   = self._rows(query_results, "get_loss_attribution")
        waiver_rows = self._rows(query_results, "get_captain_waiver_eligibility")
        scan_rows   = self._rows(query_results, "get_shipment_scan_history")

        if not loss_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA,
                                  "L2_LOSSES", trace)

        row    = loss_rows[0]
        status = row.get("attribution_status", "").lower()
        trace.append(f"attribution_status={status}")

        # Scenario A — attribution pending
        if status == "pending":
            trace.append("Scenario A: attribution pending → next billing cycle")
            return DecisionOutput(
                scenario_key=ScenarioKey.SHORTAGE_ATTRIBUTION_PENDING,
                action="respond",
                template_key="shortage_attribution_pending",
                template_variables={"awb": entities.awb_numbers[0] if entities.awb_numbers else ""},
                confidence=9.5,
                decision_trace=trace,
            )

        # Scenario B — attribution confirmed
        if status == "confirmed":
            evidence      = row.get("evidence_available", False)
            attributed_to = row.get("attributed_to", "").lower()
            recovered     = row.get("recovered_from_fe", False)

            # B4: loss recovered from FE
            if recovered:
                trace.append("B4: loss recovered from FE")
                return DecisionOutput(
                    scenario_key=ScenarioKey.SHORTAGE_LOSS_RECOVERED_FROM_FE,
                    action="respond",
                    template_key="shortage_loss_recovered_from_fe",
                    confidence=9.5,
                    decision_trace=trace,
                )

            # Check waiver eligibility
            waiver_eligible = self._check_waiver(waiver_rows, trace)

            if waiver_eligible:
                trace.append("B3: waiver eligible → escalate L2")
                return self._escalate(EscalationReason.WAIVER_APPROVAL_REQUIRED,
                                      "L2_LOSSES", trace)

            if evidence and attributed_to == "captain":
                # B1: loss marked correctly per evidence
                trace.append("B1: evidence confirms loss on captain → close")
                return DecisionOutput(
                    scenario_key=ScenarioKey.SHORTAGE_LOSS_MARKED_CORRECTLY,
                    action="respond",
                    template_key="shortage_loss_marked_correctly",
                    template_variables={"awb": entities.awb_numbers[0] if entities.awb_numbers else ""},
                    confidence=9.0,
                    decision_trace=trace,
                )

            if not evidence:
                # B2: L1 contests — evidence doesn't support loss on captain
                trace.append("B2: L1 contests attribution, no supporting evidence → escalate")
                return self._escalate(EscalationReason.L1_CONTESTS_ATTRIBUTION,
                                      "L2_LOSSES", trace, confidence=8.5)

        return self._escalate(EscalationReason.INCONSISTENT_DATA, "L2_LOSSES", trace)

    def _check_waiver(self, waiver_rows, trace):
        if not waiver_rows:
            return False
        r = waiver_rows[0]
        eligible        = r.get("eligible_for_waiver", False)
        prev_waivers    = r.get("previous_waivers", 1)
        criteria_met    = r.get("waiver_criteria_met", False)
        # Guardrail: <60 days tenure, 0 prior waivers, ≥1 invoice cycle, 0 current pendency
        result = eligible and prev_waivers == 0 and criteria_met
        trace.append(f"waiver_check: eligible={eligible} prev={prev_waivers} criteria={criteria_met} → {result}")
        return result


class HardstopLossResolver(BaseResolver):
    """
    SOP: Hardstop Loss — 2 scenarios (contesting loss; evidence shared but still attributed)

    Scenario 1.1: Loss rightly marked, no waiver → close
    Scenario 1.2: Loss rightly marked, waiver qualifies → escalate L2
    Scenario 2:   Wrong tagging by captain (processed after hardstop pre-alert) → re-route to HardstopAlertEmail flow
    Scenario 3:   L1 contests hardstop loss → escalate L2
    """

    def resolve(self, entities, query_results):
        trace = ["HardstopLossResolver"]
        loss_rows   = self._rows(query_results, "get_loss_attribution")
        waiver_rows = self._rows(query_results, "get_captain_waiver_eligibility")
        scan_rows   = self._rows(query_results, "get_shipment_scan_history")

        if not loss_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_LOSSES", trace)

        row    = loss_rows[0]
        status = row.get("attribution_status", "").lower()
        loss_type = row.get("loss_type", "").lower()
        trace.append(f"status={status} loss_type={loss_type}")

        if status == "pending":
            # Same pending path as shortage
            trace.append("Pending attribution → inform captain")
            return DecisionOutput(
                scenario_key=ScenarioKey.SHORTAGE_ATTRIBUTION_PENDING,
                action="respond",
                template_key="shortage_attribution_pending",
                confidence=9.0,
                decision_trace=trace,
            )

        wrong_tagging = row.get("wrong_tagging", False)
        if wrong_tagging:
            trace.append("Scenario 2: wrong tagging by captain → hardstop alert flow")
            return DecisionOutput(
                scenario_key=ScenarioKey.HARDSTOP_WRONG_TAGGING,
                action="respond",
                template_key="hardstop_alert_not_yet_marked",
                confidence=8.0,
                decision_trace=trace,
            )

        waiver_eligible = ShortageLossResolver._check_waiver(self, waiver_rows, trace)
        if waiver_eligible:
            trace.append("1.2: waiver eligible → escalate L2")
            return self._escalate(EscalationReason.WAIVER_APPROVAL_REQUIRED, "L2_LOSSES", trace)

        l1_contests = row.get("l1_contested", False)
        if l1_contests:
            trace.append("Scenario 3: L1 contests → escalate L2")
            return self._escalate(EscalationReason.L1_CONTESTS_ATTRIBUTION, "L2_LOSSES", trace)

        trace.append("1.1: loss rightly marked, no waiver → close")
        return DecisionOutput(
            scenario_key=ScenarioKey.HARDSTOP_LOSS_CORRECTLY_MARKED,
            action="respond",
            template_key="hardstop_loss_correctly_marked",
            confidence=9.0,
            decision_trace=trace,
        )


class HardstopAlertEmailResolver(BaseResolver):
    """
    SOP: I received hardstop pre-alert email — 3 scenarios

    Scenario 1: Pre-alert sent; shipment delivered/connected → no loss, close
    Scenario 2: Pre-alert sent; loss NOT yet marked; captain hasn't delivered/RTO'd → inform 7-day deadline
    Scenario 3: Pre-alert sent; loss IS marked; captain missed deadline → check waiver
                 waiver eligible → Scenario 1.2 of hardstop loss (escalate)
                 not eligible    → close, loss stands
    """

    def resolve(self, entities, query_results):
        trace = ["HardstopAlertEmailResolver"]
        loss_rows = self._rows(query_results, "get_loss_attribution")
        scan_rows = self._rows(query_results, "get_shipment_scan_history")
        waiver_rows = self._rows(query_results, "get_captain_waiver_eligibility")

        if not scan_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_LOSSES", trace)

        # Check scan status — delivered or connected?
        latest_scan = scan_rows[-1] if scan_rows else {}
        scan_status = latest_scan.get("status", "").lower()
        trace.append(f"latest_scan_status={scan_status}")

        if scan_status in ("delivered", "connected", "rto_connected"):
            trace.append("Scenario 1: shipment delivered/connected → no loss")
            return DecisionOutput(
                scenario_key=ScenarioKey.HARDSTOP_ALERT_DELIVERED,
                action="respond",
                template_key="hardstop_alert_delivered",
                confidence=9.5,
                decision_trace=trace,
            )

        # Loss marked?
        loss_marked = bool(loss_rows and loss_rows[0].get("attribution_status") == "confirmed")
        trace.append(f"loss_marked={loss_marked}")

        if not loss_marked:
            trace.append("Scenario 2: loss not yet marked, inform deadline")
            return DecisionOutput(
                scenario_key=ScenarioKey.HARDSTOP_ALERT_NOT_YET_MARKED,
                action="respond",
                template_key="hardstop_alert_not_yet_marked",
                confidence=9.0,
                decision_trace=trace,
            )

        # Loss marked — check waiver
        waiver_eligible = ShortageLossResolver._check_waiver(self, waiver_rows, trace)
        if waiver_eligible:
            return self._escalate(EscalationReason.WAIVER_APPROVAL_REQUIRED, "L2_LOSSES", trace)

        trace.append("Scenario 3: loss marked, deadline breached, no waiver → close")
        return DecisionOutput(
            scenario_key=ScenarioKey.HARDSTOP_ALERT_LOSS_BREACHED,
            action="respond",
            template_key="hardstop_alert_loss_breached",
            confidence=9.0,
            decision_trace=trace,
        )


# ═════════════════════════════════════════════
# ORDERS & PLANNING
# ═════════════════════════════════════════════

class DropInLoadVolumeResolver(BaseResolver):
    """
    SOP: Forward Leg – Drop in Load Volume
    Reviews manifestation trend. If drop is explainable by hub data → close.
    If drop is significant without explanation → escalate L2.
    """

    def resolve(self, entities, query_results):
        trace = ["DropInLoadVolumeResolver"]
        trend_rows = self._rows(query_results, "get_load_manifestation_trends")
        hub_rows   = self._rows(query_results, "get_hub_performance_metrics")

        if not trend_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_OPERATIONS", trace)

        changes = [float(r.get("week_over_week_change", 0)) for r in trend_rows]
        avg_change = sum(changes) / len(changes)
        max_drop   = min(changes)
        trace.append(f"avg_wow={avg_change:.1%} max_drop={max_drop:.1%}")

        if max_drop < -0.30:
            trace.append("Severe single-week drop >30% → escalate")
            return self._escalate(EscalationReason.LOAD_ANOMALY, "L2_OPERATIONS", trace)

        trace.append("Drop within explainable range → respond")
        return DecisionOutput(
            scenario_key=ScenarioKey.LOAD_DROP_EXPLAINABLE,
            action="respond",
            template_key="load_drop_explainable",
            template_variables={
                "hub_code": entities.hub_codes[0] if entities.hub_codes else "",
                "duration": entities.load_duration or "recent weeks",
                "avg_change_pct": f"{abs(avg_change):.0%}",
            },
            confidence=8.0,
            decision_trace=trace,
        )


class PromisedLoadNotMetResolver(BaseResolver):
    """
    SOP: Forward Leg – Promised Load Not Met
    Checks manifested vs promised. If promised load is not being met → escalate L2.
    """

    def resolve(self, entities, query_results):
        trace = ["PromisedLoadNotMetResolver"]
        trend_rows = self._rows(query_results, "get_load_manifestation_trends")

        if not trend_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_OPERATIONS", trace)

        promised = float(trend_rows[0].get("promised_load", 0))
        actual   = float(trend_rows[0].get("manifest_count", 0))
        trace.append(f"promised={promised} actual={actual}")

        if promised > 0 and actual < promised * 0.85:
            trace.append("Actual < 85% of promised → escalate")
            return self._escalate(EscalationReason.PROMISED_LOAD_BREACH, "L2_OPERATIONS", trace)

        trace.append("Within tolerance → respond")
        return DecisionOutput(
            scenario_key=ScenarioKey.LOAD_DROP_EXPLAINABLE,
            action="respond",
            template_key="load_drop_explainable",
            template_variables={
                "hub_code": entities.hub_codes[0] if entities.hub_codes else "",
                "duration": entities.load_duration or "recent period",
                "avg_change_pct": f"{abs((promised-actual)/max(promised,1)):.0%}",
            },
            confidence=7.5,
            decision_trace=trace,
        )


class FluctuatingLoadVolumeResolver(BaseResolver):
    """SOP: Forward Leg – Fluctuating Load Volume"""

    def resolve(self, entities, query_results):
        trace = ["FluctuatingLoadVolumeResolver"]
        trend_rows = self._rows(query_results, "get_load_manifestation_trends")

        if not trend_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_OPERATIONS", trace)

        changes = [abs(float(r.get("week_over_week_change", 0))) for r in trend_rows]
        avg_variance = sum(changes) / len(changes)
        trace.append(f"avg_variance={avg_variance:.1%}")

        if avg_variance > 0.35:
            trace.append("High variance → escalate for review")
            return self._escalate(EscalationReason.LOAD_ANOMALY, "L2_OPERATIONS", trace)

        trace.append("Normal fluctuation → respond")
        return DecisionOutput(
            scenario_key=ScenarioKey.LOAD_FLUCTUATION_NORMAL,
            action="respond",
            template_key="load_fluctuation_normal",
            template_variables={
                "hub_code": entities.hub_codes[0] if entities.hub_codes else "",
                "duration": entities.load_duration or "recent weeks",
            },
            confidence=8.0,
            decision_trace=trace,
        )


# ═════════════════════════════════════════════
# PAYMENTS
# ═════════════════════════════════════════════

class PaymentNotReceivedResolver(BaseResolver):
    """
    SOP: I have not received payment
    Checks payment + invoice status, maps to one of 14 possible payment states.
    """

    def resolve(self, entities, query_results):
        trace = ["PaymentNotReceivedResolver"]
        pay_rows = self._rows(query_results, "get_payment_status")
        inv_rows = self._rows(query_results, "get_invoice_status")

        if not pay_rows and not inv_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_PAYMENTS", trace)

        # Payment row
        pr = pay_rows[0] if pay_rows else {}
        ir = inv_rows[0] if inv_rows else {}

        pay_status = pr.get("status", "").lower()
        hold_reason = pr.get("hold_reason", "").lower()
        invoice_status = ir.get("status", "").lower()
        trace.append(f"pay_status={pay_status} hold_reason={hold_reason} invoice_status={invoice_status}")

        # Map to template
        scenario, key, tvars = self._map_payment_state(
            pay_status, hold_reason, invoice_status, pr, ir, entities
        )
        trace.append(f"→ scenario={scenario.value}")
        return DecisionOutput(
            scenario_key=scenario,
            action="respond",
            template_key=key,
            template_variables=tvars,
            confidence=8.8,
            decision_trace=trace,
        )

    def _map_payment_state(self, pay_status, hold_reason, invoice_status, pr, ir, e):
        cycle = e.payment_cycle or pr.get("payment_cycle", "xx–yy")
        inv_date  = ir.get("invoice_date", "[dd-mm-yyyy]")
        pay_date  = pr.get("processed_date", "[dd-mm-yyyy]")
        gen_date  = ir.get("generated_date", "[dd-mm-yyyy]")
        sign_date = ir.get("signed_date", "[dd-mm-yyyy]")
        cn_date   = ir.get("cn_date", "[dd-mm-yyyy]")

        if pay_status == "processed":
            return (ScenarioKey.PAYMENT_PROCESSED, "payment_processed",
                    {"invoice_date": inv_date, "payment_date": pay_date, "cycle": cycle})

        if invoice_status == "pending_signature":
            return (ScenarioKey.PAYMENT_PENDING_SIGN, "payment_pending_sign",
                    {"invoice_date": inv_date, "cycle": cycle})

        if hold_reason == "gst_defaulter":
            return (ScenarioKey.PAYMENT_GST_DEFAULTER, "payment_gst_defaulter",
                    {"cycle": cycle})

        if hold_reason == "cod_risk":
            return (ScenarioKey.PAYMENT_RISK_COD, "payment_risk_cod",
                    {"cycle": cycle})

        if hold_reason == "cod_shipment_risk":
            return (ScenarioKey.PAYMENT_RISK_COD_SHIPMENT, "payment_risk_cod_shipment",
                    {"cycle": cycle})

        if hold_reason == "gst_above_20l":
            return (ScenarioKey.PAYMENT_GST_ABOVE_20L, "payment_gst_above_20l",
                    {"cycle": cycle})

        if hold_reason == "hold_by_ops":
            return (ScenarioKey.PAYMENT_HOLD_BY_OPS, "payment_hold_by_ops",
                    {"invoice_date": gen_date, "signed_date": sign_date})

        if hold_reason == "onboarding":
            return (ScenarioKey.PAYMENT_ONBOARDING_ISSUE, "payment_onboarding_issue",
                    {"cycle": cycle})

        if hold_reason == "ff_vendor":
            return (ScenarioKey.PAYMENT_FF_VENDOR, "payment_ff_vendor",
                    {"cycle": cycle})

        if hold_reason == "grocery_defaulter":
            return (ScenarioKey.PAYMENT_GROCERY_DEFAULTER, "payment_grocery_defaulter",
                    {"cycle": cycle})

        if hold_reason in ("negative_balance", "hold_negative"):
            return (ScenarioKey.PAYMENT_HOLD_NEGATIVE, "payment_hold_negative",
                    {"cycle": cycle, "cn_date": cn_date})

        if hold_reason == "no_earnings":
            return (ScenarioKey.PAYMENT_NO_EARNINGS, "payment_no_earnings",
                    {"cycle": cycle, "cn_date": cn_date})

        if pay_status == "negative_balance":
            return (ScenarioKey.PAYMENT_NEGATIVE_BALANCE, "payment_negative_balance",
                    {"cycle": cycle, "cn_date": cn_date})

        if pay_status == "failed":
            return (ScenarioKey.PAYMENT_FAILED, "payment_failed",
                    {"invoice_date": gen_date, "payment_date": pay_date, "cycle": cycle})

        # Default: processed
        return (ScenarioKey.PAYMENT_PROCESSED, "payment_processed",
                {"invoice_date": inv_date, "payment_date": pay_date, "cycle": cycle})


class InvoiceNotReceivedResolver(BaseResolver):
    """SOP: I have not received invoice for e-signing"""

    def resolve(self, entities, query_results):
        trace = ["InvoiceNotReceivedResolver"]
        inv_rows = self._rows(query_results, "get_invoice_status")

        cycle = entities.payment_cycle or "xx–yy"

        if not inv_rows:
            trace.append("No invoice record → invoice not generated yet")
            return DecisionOutput(
                scenario_key=ScenarioKey.INVOICE_NOT_GENERATED,
                action="respond",
                template_key="invoice_not_generated",
                template_variables={"cycle": cycle},
                confidence=8.5,
                decision_trace=trace,
            )

        ir = inv_rows[0]
        status = ir.get("status", "").lower()
        hold_reason = ir.get("hold_reason", "").lower()
        trace.append(f"invoice_status={status} hold_reason={hold_reason}")

        # Re-use PaymentNotReceivedResolver's hold-reason mapping
        resolver = PaymentNotReceivedResolver()
        scenario, key, tvars = resolver._map_payment_state(
            status, hold_reason, status, {}, ir, entities
        )
        trace.append(f"→ {scenario.value}")
        return DecisionOutput(
            scenario_key=scenario, action="respond",
            template_key=key, template_variables=tvars,
            confidence=8.5, decision_trace=trace,
        )


class ShipmentCountMismatchResolver(BaseResolver):
    """
    SOP: Shipment count mismatch in invoice
    Delta=0 / Delta>0 (more delivered than invoiced) / Delta<0 (less)
    """

    def resolve(self, entities, query_results):
        trace = ["ShipmentCountMismatchResolver"]
        recon_rows = self._rows(query_results, "get_shipment_count_reconciliation")

        if not recon_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_PAYMENTS", trace)

        row   = recon_rows[0]
        cycle = entities.payment_cycle or row.get("payment_cycle", "<mention payment cycle>")
        inv_del  = int(row.get("invoice_delivered", 0))
        act_del  = int(row.get("actual_delivered", 0))
        inv_pick = int(row.get("invoice_picked", 0))
        act_pick = int(row.get("actual_picked", 0))
        delta_del  = act_del - inv_del
        delta_pick = act_pick - inv_pick
        trace.append(f"delta_del={delta_del} delta_pick={delta_pick}")

        tvars = {
            "cycle": cycle,
            "inv_del": inv_del, "act_del": act_del, "delta_del": delta_del,
            "inv_pick": inv_pick, "act_pick": act_pick, "delta_pick": delta_pick,
        }

        if delta_del == 0 and delta_pick == 0:
            scenario, key = ScenarioKey.SHIPMENT_COUNT_DELTA_ZERO, "shipment_count_delta_zero"
        elif delta_del > 0 or delta_pick > 0:
            scenario, key = ScenarioKey.SHIPMENT_COUNT_DELTA_POSITIVE, "shipment_count_delta_positive"
        else:
            scenario, key = ScenarioKey.SHIPMENT_COUNT_DELTA_NEGATIVE, "shipment_count_delta_negative"

        trace.append(f"→ {scenario.value}")
        return DecisionOutput(
            scenario_key=scenario, action="respond",
            template_key=key, template_variables=tvars,
            confidence=9.0, decision_trace=trace,
        )


class WrongDebitsClarificationResolver(BaseResolver):
    """SOP: Wrong debits – Clarification. Explains why debit was marked."""

    def resolve(self, entities, query_results):
        trace = ["WrongDebitsClarificationResolver"]
        debit_rows = self._rows(query_results, "get_debit_reasons")

        if not debit_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_PAYMENTS", trace)

        row = debit_rows[0]
        trace.append(f"debit_type={row.get('debit_type')}")
        return DecisionOutput(
            scenario_key=ScenarioKey.DEBIT_CLARIFICATION_PROVIDED,
            action="respond",
            template_key="debit_clarification_provided",
            template_variables={
                "cycle":       entities.payment_cycle or row.get("payment_cycle", ""),
                "cn_number":   entities.cn_number or row.get("cn_number", ""),
                "debit_type":  row.get("debit_type", ""),
                "debit_amount": row.get("debit_amount", ""),
                "reason":      row.get("reason_description", ""),
            },
            confidence=8.8,
            decision_trace=trace,
        )


class WrongDebitsReversalResolver(BaseResolver):
    """
    SOP: Wrong debits – Reversal.
    Guardrail: only last 3 months eligible. Once payment processed, no reversal.
    ALL reversal requests escalate to L2 — L1 cannot approve reversals.
    """

    def resolve(self, entities, query_results):
        trace = ["WrongDebitsReversalResolver"]
        debit_rows = self._rows(query_results, "get_debit_reasons")

        if not debit_rows:
            return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_PAYMENTS", trace)

        row = debit_rows[0]
        reversible      = row.get("reversible", False)
        within_3_months = row.get("within_3_months", True)
        payment_processed = row.get("payment_processed", False)
        trace.append(f"reversible={reversible} within_3m={within_3_months} payment_done={payment_processed}")

        if not within_3_months or payment_processed:
            trace.append("Not eligible for reversal (outside 3m or payment done) → close")
            return DecisionOutput(
                scenario_key=ScenarioKey.DEBIT_REVERSAL_NOT_ELIGIBLE,
                action="respond",
                template_key="debit_reversal_not_eligible",
                template_variables={
                    "cycle":      entities.payment_cycle or "",
                    "cn_number":  entities.cn_number or row.get("cn_number", ""),
                    "debit_type": row.get("debit_type", ""),
                },
                confidence=9.0,
                decision_trace=trace,
            )

        # Eligible — all reversals go to L2
        trace.append("Reversal eligible → escalate L2")
        return self._escalate(EscalationReason.REVERSAL_REQUEST, "L2_PAYMENTS", trace)


# ═════════════════════════════════════════════
# CASH HANDOVER
# ═════════════════════════════════════════════

class CODNotReflectingResolver(BaseResolver):
    """
    SOP: I have deposited the money but it is not reflecting in my COD pendency
    No COD pendency → close (last deposit info)
    Pendency exists → escalate to L2 for verification
    """

    def resolve(self, entities, query_results):
        trace = ["CODNotReflectingResolver"]
        pendency_rows = self._rows(query_results, "get_cod_pendency")
        txn_rows      = self._rows(query_results, "get_cod_transaction_history")

        # Check if pendency is 0
        total_pendency = sum(float(r.get("cod_amount", 0)) for r in pendency_rows)
        trace.append(f"total_cod_pendency={total_pendency}")

        if total_pendency == 0:
            # No pendency — find last deposit
            last_txn = txn_rows[0] if txn_rows else {}
            trace.append("No pendency → close with last deposit info")
            return DecisionOutput(
                scenario_key=ScenarioKey.COD_NO_PENDENCY,
                action="respond",
                template_key="cod_no_pendency",
                template_variables={
                    "hub_code":   entities.hub_codes[0] if entities.hub_codes else "",
                    "last_date":  last_txn.get("transaction_date", "[date]"),
                    "last_amount": last_txn.get("amount", "XX"),
                },
                confidence=9.2,
                decision_trace=trace,
            )

        # Pendency exists — L2 to verify deposit mapping
        trace.append("Pendency exists → escalate L2 for verification")
        return self._escalate(EscalationReason.MISSING_OPERATIONAL_DATA, "L2_COD", trace)


# ─────────────────────────────────────────────
# DECISION ENGINE  (router)
# ─────────────────────────────────────────────

RESOLVER_MAP: Dict[SubQueue, type] = {
    SubQueue.SHORTAGE_LOSS:              ShortageLossResolver,
    SubQueue.HARDSTOP_LOSS:              HardstopLossResolver,
    SubQueue.HARDSTOP_ALERT_EMAIL:       HardstopAlertEmailResolver,
    SubQueue.DROP_IN_LOAD_VOLUME:        DropInLoadVolumeResolver,
    SubQueue.PROMISED_LOAD_NOT_MET:      PromisedLoadNotMetResolver,
    SubQueue.FLUCTUATING_LOAD_VOLUME:    FluctuatingLoadVolumeResolver,
    SubQueue.PAYMENT_NOT_RECEIVED:       PaymentNotReceivedResolver,
    SubQueue.INVOICE_NOT_RECEIVED:       InvoiceNotReceivedResolver,
    SubQueue.SHIPMENT_COUNT_MISMATCH:    ShipmentCountMismatchResolver,
    SubQueue.WRONG_DEBITS_CLARIFICATION: WrongDebitsClarificationResolver,
    SubQueue.WRONG_DEBITS_REVERSAL:      WrongDebitsReversalResolver,
    SubQueue.COD_NOT_REFLECTING:         CODNotReflectingResolver,
}


class DecisionEngine:
    def decide(self, entities: ExtractedEntities,
               query_results: List[QueryResult],
               sub_queue: SubQueue) -> DecisionOutput:

        resolver_cls = RESOLVER_MAP.get(sub_queue)
        if resolver_cls is None:
            logger.warning(f"[DECISION] No resolver for {sub_queue}")
            return DecisionOutput(
                scenario_key=ScenarioKey.ESCALATE_TO_L2,
                action="escalate",
                template_key="escalation_acknowledgment",
                confidence=5.0,
                escalation_reason=EscalationReason.MISSING_OPERATIONAL_DATA,
                escalation_queue="L2_GENERAL",
                decision_trace=[f"No resolver for sub_queue={sub_queue}"],
            )

        logger.info(f"[DECISION] {resolver_cls.__name__} for {sub_queue}")
        return resolver_cls().resolve(entities, query_results)
