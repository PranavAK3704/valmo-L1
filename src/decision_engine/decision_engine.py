"""
VALMO L1 Agent - SOP Decision Engine
Applies deterministic operational rules to query results.
NO external LLM at runtime — all logic is rule-based per company SOP.

Architecture:
  Each IssueType has a dedicated resolver class.
  Each resolver examines QueryResult data and returns a DecisionOutput.
  The DecisionEngine acts as a router, dispatching to the right resolver.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

from src.models import (
    IssueType, ExtractedEntities, QueryResult,
    DecisionOutput, EscalationReason
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# BASE RESOLVER
# ─────────────────────────────────────────────

class BaseResolver(ABC):
    """Abstract base class for all issue-type resolvers."""

    @abstractmethod
    def resolve(
        self,
        entities: ExtractedEntities,
        query_results: List[QueryResult],
    ) -> DecisionOutput:
        ...

    def _get_rows(self, query_results: List[QueryResult], query_name: str) -> List[Dict]:
        for qr in query_results:
            if qr.query_name == query_name and qr.success:
                return qr.data.get("rows", [])
        return []

    def _escalate(self, reason: EscalationReason, trace: List[str], queue: str) -> DecisionOutput:
        trace.append(f"ESCALATE → {reason.value} → queue={queue}")
        return DecisionOutput(
            resolution_path="escalation",
            action="escalate",
            response_template_key="escalation_acknowledgment",
            escalation_reason=reason,
            escalation_queue=queue,
            decision_trace=trace,
        )


# ─────────────────────────────────────────────
# RESOLVERS — one per IssueType
# ─────────────────────────────────────────────

class ShortageLossResolver(BaseResolver):
    """
    SOP: Shortage Loss Disputes
    Rule 1: If attribution status = pending → inform next billing cycle
    Rule 2: If attribution confirmed + evidence = True → loss stands
    Rule 3: If attribution confirmed + evidence = False → escalate L2
    Rule 4: If captain eligible for one-time waiver → escalate for approval
    """

    def resolve(self, entities, query_results):
        trace = ["ShortageLossResolver.resolve()"]
        loss_rows = self._get_rows(query_results, "get_loss_attribution")

        if not loss_rows:
            return self._escalate(
                EscalationReason.MISSING_OPERATIONAL_DATA,
                trace, "L2_LOSS_DISPUTE"
            )

        row = loss_rows[0]
        attribution_status = row.get("attribution_status", "").lower()
        evidence_available = row.get("evidence_available", False)
        trace.append(f"attribution_status={attribution_status}, evidence={evidence_available}")

        if attribution_status == "pending":
            trace.append("Rule 1: Attribution pending → next billing cycle response")
            return DecisionOutput(
                resolution_path="shortage_loss_attribution_pending",
                action="respond",
                response_template_key="shortage_loss_attribution_pending",
                template_variables={
                    "awb": entities.awb_numbers[0] if entities.awb_numbers else "N/A",
                    "partner_id": entities.raw_entities.get("partner_id", "N/A"),
                },
                decision_trace=trace,
            )

        if attribution_status == "confirmed":
            if evidence_available:
                trace.append("Rule 2: Confirmed + evidence → loss stands")
                return DecisionOutput(
                    resolution_path="shortage_loss_confirmed",
                    action="respond",
                    response_template_key="shortage_loss_confirmed",
                    template_variables={
                        "awb": entities.awb_numbers[0] if entities.awb_numbers else "N/A",
                        "loss_type": row.get("loss_type", "shortage"),
                        "attributed_to": row.get("attributed_to", "hub"),
                    },
                    decision_trace=trace,
                )
            else:
                trace.append("Rule 3: Confirmed but no evidence → escalate L2")
                return self._escalate(
                    EscalationReason.L2_VERIFICATION_REQUIRED,
                    trace, "L2_LOSS_DISPUTE"
                )

        # Unknown status — escalate
        return self._escalate(EscalationReason.INCONSISTENT_DATA, trace, "L2_LOSS_DISPUTE")


class HardstopLossResolver(ShortageLossResolver):
    """Hardstop loss follows same SOP as shortage loss with a different template."""

    def resolve(self, entities, query_results):
        decision = super().resolve(entities, query_results)
        # Override template keys for hardstop-specific responses
        if decision.response_template_key == "shortage_loss_attribution_pending":
            decision.response_template_key = "hardstop_loss_attribution_pending"
        elif decision.response_template_key == "shortage_loss_confirmed":
            decision.response_template_key = "hardstop_loss_confirmed"
        return decision


class PaymentNotReceivedResolver(BaseResolver):
    """
    SOP: Payment Not Received
    Rule 1: Payment processed → inform partner of UTR + date
    Rule 2: Payment pending → inform of expected cycle
    Rule 3: No payment record → escalate
    """

    def resolve(self, entities, query_results):
        trace = ["PaymentNotReceivedResolver.resolve()"]
        payment_rows = self._get_rows(query_results, "get_payment_status")

        if not payment_rows:
            trace.append("No payment record found → escalate")
            return self._escalate(
                EscalationReason.MISSING_OPERATIONAL_DATA,
                trace, "L2_FINANCE"
            )

        row = payment_rows[0]
        status = row.get("status", "").lower()
        trace.append(f"payment_status={status}")

        if status == "processed":
            trace.append("Rule 1: Payment processed → inform partner")
            return DecisionOutput(
                resolution_path="payment_processed",
                action="respond",
                response_template_key="payment_already_processed",
                template_variables={
                    "payment_cycle": row.get("payment_cycle"),
                    "amount": row.get("amount"),
                    "processed_date": row.get("processed_date"),
                    "utr_number": row.get("utr_number"),
                    "bank_reference": row.get("bank_reference"),
                },
                decision_trace=trace,
            )

        if status in ("pending", "scheduled"):
            trace.append("Rule 2: Payment pending → inform of cycle")
            return DecisionOutput(
                resolution_path="payment_pending",
                action="respond",
                response_template_key="payment_pending",
                template_variables={
                    "payment_cycle": row.get("payment_cycle"),
                    "amount": row.get("amount"),
                },
                decision_trace=trace,
            )

        return self._escalate(EscalationReason.INCONSISTENT_DATA, trace, "L2_FINANCE")


class InvoiceNotGeneratedResolver(BaseResolver):
    """
    SOP: Invoice Not Generated
    Rule 1: Invoice exists → inform partner
    Rule 2: No invoice in current cycle → explain billing schedule
    Rule 3: Missing for multiple cycles → escalate
    """

    def resolve(self, entities, query_results):
        trace = ["InvoiceNotGeneratedResolver.resolve()"]
        invoice_rows = self._get_rows(query_results, "get_invoice_status")

        if invoice_rows:
            row = invoice_rows[0]
            status = row.get("status", "").lower()
            trace.append(f"Invoice found, status={status}")
            return DecisionOutput(
                resolution_path="invoice_exists",
                action="respond",
                response_template_key="invoice_status_info",
                template_variables={
                    "invoice_id": row.get("invoice_id"),
                    "invoice_date": row.get("invoice_date"),
                    "amount": row.get("amount"),
                    "billing_cycle": row.get("billing_cycle"),
                    "status": status,
                },
                decision_trace=trace,
            )

        # No invoice — check if it's a known billing cycle gap
        trace.append("No invoice found → next billing cycle response")
        return DecisionOutput(
            resolution_path="invoice_not_yet_generated",
            action="respond",
            response_template_key="invoice_not_generated_cycle",
            template_variables={
                "payment_cycle": entities.payment_cycle or "current",
                "partner_id": entities.raw_entities.get("partner_id", "N/A"),
            },
            decision_trace=trace,
        )


class ShipmentCountMismatchResolver(BaseResolver):
    """
    SOP: Shipment Count Mismatch
    Rule 1: Discrepancy ≤ 2 → within tolerance, explain
    Rule 2: Discrepancy > 2 → escalate for reconciliation
    """

    def resolve(self, entities, query_results):
        trace = ["ShipmentCountMismatchResolver.resolve()"]
        recon_rows = self._get_rows(query_results, "get_shipment_count_reconciliation")

        if not recon_rows:
            return self._escalate(
                EscalationReason.MISSING_OPERATIONAL_DATA,
                trace, "L2_OPERATIONS"
            )

        row = recon_rows[0]
        discrepancy = abs(row.get("discrepancy", 0))
        trace.append(f"discrepancy={discrepancy}")

        if discrepancy <= 2:
            trace.append("Rule 1: Discrepancy within tolerance")
            return DecisionOutput(
                resolution_path="count_within_tolerance",
                action="respond",
                response_template_key="shipment_count_within_tolerance",
                template_variables={
                    "manifest_count": row.get("manifest_count"),
                    "scan_count": row.get("scan_count"),
                    "delivered_count": row.get("delivered_count"),
                    "discrepancy": discrepancy,
                    "date_range_start": row.get("date_range_start"),
                    "date_range_end": row.get("date_range_end"),
                },
                decision_trace=trace,
            )

        trace.append("Rule 2: Discrepancy > 2 → escalate")
        return self._escalate(EscalationReason.L2_VERIFICATION_REQUIRED, trace, "L2_OPERATIONS")


class DebitClarificationResolver(BaseResolver):
    """
    SOP: Debit Clarification
    Rule 1: Debit record found → provide reason + details
    Rule 2: No record → escalate
    """

    def resolve(self, entities, query_results):
        trace = ["DebitClarificationResolver.resolve()"]
        debit_rows = self._get_rows(query_results, "get_debit_reasons")

        if not debit_rows:
            return self._escalate(
                EscalationReason.MISSING_OPERATIONAL_DATA,
                trace, "L2_FINANCE"
            )

        row = debit_rows[0]
        trace.append(f"debit_type={row.get('debit_type')}")
        return DecisionOutput(
            resolution_path="debit_clarification_provided",
            action="respond",
            response_template_key="debit_clarification",
            template_variables={
                "awb": row.get("awb"),
                "debit_type": row.get("debit_type"),
                "debit_amount": row.get("debit_amount"),
                "debit_date": row.get("debit_date"),
                "reason_description": row.get("reason_description"),
            },
            decision_trace=trace,
        )


class DebitReversalResolver(BaseResolver):
    """
    SOP: Debit Reversal
    Rule 1: reversible = True → escalate for approval (beyond L1)
    Rule 2: reversible = False → inform partner, cannot reverse
    """

    def resolve(self, entities, query_results):
        trace = ["DebitReversalResolver.resolve()"]
        debit_rows = self._get_rows(query_results, "get_debit_reasons")

        if not debit_rows:
            return self._escalate(
                EscalationReason.MISSING_OPERATIONAL_DATA,
                trace, "L2_FINANCE"
            )

        row = debit_rows[0]
        reversible = row.get("reversible", False)
        trace.append(f"reversible={reversible}")

        if reversible:
            return self._escalate(
                EscalationReason.DEBIT_REVERSAL_BEYOND_L1,
                trace, "L2_FINANCE_REVERSAL"
            )

        return DecisionOutput(
            resolution_path="debit_not_reversible",
            action="respond",
            response_template_key="debit_reversal_not_possible",
            template_variables={
                "awb": row.get("awb"),
                "debit_amount": row.get("debit_amount"),
                "reason_description": row.get("reason_description"),
            },
            decision_trace=trace,
        )


class LoadVolumeResolver(BaseResolver):
    """
    SOP: Drop / Fluctuating Load Volume
    Rule 1: Consistent week-over-week drop ≥ 10% → explain trend, suggest review
    Rule 2: Fluctuating (high variance) → explain market/seasonal patterns
    Rule 3: Sudden drop (>25% in one week) → escalate operations
    """

    def resolve(self, entities, query_results):
        trace = ["LoadVolumeResolver.resolve()"]
        trend_rows = self._get_rows(query_results, "get_load_manifestation_trends")

        if not trend_rows:
            return self._escalate(
                EscalationReason.MISSING_OPERATIONAL_DATA,
                trace, "L2_OPERATIONS"
            )

        changes = [float(r.get("week_over_week_change", 0)) for r in trend_rows]
        avg_change = sum(changes) / len(changes)
        max_drop = min(changes)
        trace.append(f"avg_wow_change={avg_change:.2%}, max_single_drop={max_drop:.2%}")

        if max_drop < -0.25:
            return self._escalate(
                EscalationReason.L2_VERIFICATION_REQUIRED,
                trace, "L2_OPERATIONS"
            )

        if avg_change < -0.10:
            template = "load_volume_drop_explanation"
        else:
            template = "load_volume_fluctuation_explanation"

        return DecisionOutput(
            resolution_path="load_volume_analysis",
            action="respond",
            response_template_key=template,
            template_variables={
                "avg_change_pct": f"{abs(avg_change):.1%}",
                "period_start": trend_rows[0].get("date"),
                "period_end": trend_rows[-1].get("date"),
            },
            decision_trace=trace,
        )


class CODNotReflectingResolver(BaseResolver):
    """
    SOP: COD Deposits Not Reflecting
    Rule 1: Pendency exists → inform partner of pending COD balance + days
    Rule 2: Recent transaction exists → inform of remittance details
    Rule 3: No data at all → escalate
    """

    def resolve(self, entities, query_results):
        trace = ["CODNotReflectingResolver.resolve()"]
        pendency_rows = self._get_rows(query_results, "get_cod_pendency")
        txn_rows = self._get_rows(query_results, "get_cod_transaction_history")

        if pendency_rows:
            row = pendency_rows[0]
            total_pending = sum(float(r.get("cod_amount", 0)) for r in pendency_rows)
            trace.append(f"COD pendency found, total_pending={total_pending}")
            return DecisionOutput(
                resolution_path="cod_pendency_exists",
                action="respond",
                response_template_key="cod_pendency_info",
                template_variables={
                    "total_pending_amount": total_pending,
                    "pendency_days": row.get("pendency_days"),
                    "remittance_status": row.get("remittance_status"),
                },
                decision_trace=trace,
            )

        if txn_rows:
            row = txn_rows[0]
            trace.append("Recent COD transaction found")
            return DecisionOutput(
                resolution_path="cod_recently_remitted",
                action="respond",
                response_template_key="cod_remittance_info",
                template_variables={
                    "transaction_date": row.get("transaction_date"),
                    "amount": row.get("amount"),
                    "utr_number": row.get("utr_number"),
                    "remittance_cycle": row.get("remittance_cycle"),
                },
                decision_trace=trace,
            )

        return self._escalate(
            EscalationReason.MISSING_OPERATIONAL_DATA,
            trace, "L2_FINANCE"
        )


class CaptainWaiverResolver(BaseResolver):
    """
    SOP: Captain Waiver Eligibility (sub-flow used by loss disputes)
    Rule 1: eligible = True, previous_waivers = 0 → escalate for approval
    Rule 2: not eligible → inform not eligible
    """

    def resolve(self, entities, query_results):
        trace = ["CaptainWaiverResolver.resolve()"]
        waiver_rows = self._get_rows(query_results, "get_captain_waiver_eligibility")

        if not waiver_rows:
            return self._escalate(
                EscalationReason.MISSING_OPERATIONAL_DATA,
                trace, "L2_OPERATIONS"
            )

        row = waiver_rows[0]
        eligible = row.get("eligible_for_waiver", False)
        previous_waivers = row.get("previous_waivers", 0)
        trace.append(f"eligible={eligible}, previous_waivers={previous_waivers}")

        if eligible and previous_waivers == 0:
            return self._escalate(
                EscalationReason.WAIVER_APPROVAL_REQUIRED,
                trace, "L2_WAIVER_APPROVAL"
            )

        return DecisionOutput(
            resolution_path="captain_waiver_not_eligible",
            action="respond",
            response_template_key="captain_waiver_not_eligible",
            template_variables={
                "captain_id": entities.captain_id or "N/A",
                "previous_waivers": previous_waivers,
            },
            decision_trace=trace,
        )


# ─────────────────────────────────────────────
# DECISION ENGINE  (router)
# ─────────────────────────────────────────────

class DecisionEngine:
    """
    Routes to the correct SOP resolver based on issue type.
    This is the main entry point for the decision layer.
    """

    RESOLVER_MAP = {
        IssueType.SHORTAGE_LOSS_DISPUTE:    ShortageLossResolver,
        IssueType.HARDSTOP_LOSS_DISPUTE:    HardstopLossResolver,
        IssueType.PAYMENT_NOT_RECEIVED:     PaymentNotReceivedResolver,
        IssueType.INVOICE_NOT_GENERATED:    InvoiceNotGeneratedResolver,
        IssueType.SHIPMENT_COUNT_MISMATCH:  ShipmentCountMismatchResolver,
        IssueType.DEBIT_CLARIFICATION:      DebitClarificationResolver,
        IssueType.DEBIT_REVERSAL:           DebitReversalResolver,
        IssueType.DROP_IN_LOAD_VOLUME:      LoadVolumeResolver,
        IssueType.FLUCTUATING_LOAD_VOLUME:  LoadVolumeResolver,
        IssueType.COD_NOT_REFLECTING:       CODNotReflectingResolver,
    }

    def decide(
        self,
        entities: ExtractedEntities,
        query_results: List[QueryResult],
    ) -> DecisionOutput:
        resolver_class = self.RESOLVER_MAP.get(entities.issue_type)
        if resolver_class is None:
            logger.warning(f"[DECISION] No resolver for {entities.issue_type}. Escalating.")
            return DecisionOutput(
                resolution_path="unknown_issue_type",
                action="escalate",
                response_template_key="escalation_acknowledgment",
                escalation_reason=EscalationReason.L2_VERIFICATION_REQUIRED,
                escalation_queue="L2_GENERAL",
                decision_trace=[f"No resolver for issue_type={entities.issue_type}"],
            )

        resolver = resolver_class()
        logger.info(f"[DECISION] Using resolver: {resolver_class.__name__}")
        return resolver.resolve(entities, query_results)
