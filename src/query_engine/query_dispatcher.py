"""
VALMO L1 Agent — Query Dispatcher (v3)

Maps each SubQueue to the ordered list of Metabase queries to run.
Also holds the QUERY_CATALOG (SQL used in ad-hoc fallback mode).
"""

from typing import Dict, List

from src.models import SubQueue

# ─────────────────────────────────────────────
# QUERY CATALOG — 11 named SOP queries
# Used for ad-hoc SQL fallback when Metabase card IDs are not yet configured.
# ─────────────────────────────────────────────

QUERY_CATALOG: Dict[str, str] = {
    "get_shipment_scan_history": """
        SELECT awb, scan_time, status, location, hub_code
        FROM shipment_scans
        WHERE awb IN :awb_list
          AND scan_time BETWEEN :start_date AND :end_date
        ORDER BY scan_time DESC
    """,
    "get_loss_attribution": """
        SELECT awb, attribution_status, attributed_to, loss_type,
               evidence_available, recovered_from_fe, wrong_tagging, l1_contested,
               remarks, marked_date
        FROM loss_attribution
        WHERE awb IN :awb_list
          AND partner_id = :partner_id
        ORDER BY marked_date DESC
    """,
    "get_captain_waiver_eligibility": """
        SELECT partner_id, tenure_days, previous_waivers, invoice_count,
               current_pendency, eligible_for_waiver, waiver_criteria_met
        FROM captain_waiver_eligibility
        WHERE partner_id = :partner_id
    """,
    "get_payment_status": """
        SELECT partner_id, payment_cycle, status, processed_date,
               hold_reason, utr_number, amount
        FROM payment_records
        WHERE partner_id = :partner_id
          AND payment_cycle = :payment_cycle
    """,
    "get_invoice_status": """
        SELECT partner_id, payment_cycle, invoice_number, status,
               invoice_date, generated_date, signed_date, hold_reason, cn_date
        FROM invoice_records
        WHERE partner_id = :partner_id
          AND payment_cycle = :payment_cycle
    """,
    "get_shipment_count_reconciliation": """
        SELECT partner_id, payment_cycle,
               invoice_delivered, actual_delivered,
               invoice_picked,   actual_picked
        FROM shipment_reconciliation
        WHERE partner_id = :partner_id
          AND payment_cycle = :payment_cycle
    """,
    "get_debit_reasons": """
        SELECT partner_id, payment_cycle, cn_number, debit_type,
               debit_amount, reason_description, reversible,
               within_3_months, payment_processed
        FROM debit_records
        WHERE partner_id = :partner_id
          AND (cn_number = :cn_number OR payment_cycle = :payment_cycle)
        ORDER BY created_date DESC
        LIMIT 1
    """,
    "get_load_manifestation_trends": """
        SELECT hub_code, week_start, manifest_count, promised_load,
               week_over_week_change
        FROM load_manifestation_weekly
        WHERE hub_code = :hub_code
          AND week_start >= :start_date
        ORDER BY week_start DESC
        LIMIT 12
    """,
    "get_hub_performance_metrics": """
        SELECT hub_code, metric_date, active_routes,
               avg_daily_volume, capacity_utilisation
        FROM hub_performance
        WHERE hub_code = :hub_code
          AND metric_date >= :start_date
    """,
    "get_cod_pendency": """
        SELECT hub_code, cod_amount, last_updated
        FROM cod_pendency
        WHERE hub_code = :hub_code
    """,
    "get_cod_transaction_history": """
        SELECT hub_code, transaction_id, transaction_date, amount, status
        FROM cod_transactions
        WHERE hub_code = :hub_code
        ORDER BY transaction_date DESC
        LIMIT 10
    """,
}


# ─────────────────────────────────────────────
# SUB-QUEUE → QUERIES
# ─────────────────────────────────────────────

SUBQUEUE_QUERIES: Dict[SubQueue, List[str]] = {
    SubQueue.SHORTAGE_LOSS: [
        "get_loss_attribution",
        "get_shipment_scan_history",
        "get_captain_waiver_eligibility",
    ],
    SubQueue.HARDSTOP_LOSS: [
        "get_loss_attribution",
        "get_shipment_scan_history",
        "get_captain_waiver_eligibility",
    ],
    SubQueue.HARDSTOP_ALERT_EMAIL: [
        "get_shipment_scan_history",
        "get_loss_attribution",
        "get_captain_waiver_eligibility",
    ],
    SubQueue.DROP_IN_LOAD_VOLUME: [
        "get_load_manifestation_trends",
        "get_hub_performance_metrics",
    ],
    SubQueue.PROMISED_LOAD_NOT_MET: [
        "get_load_manifestation_trends",
        "get_hub_performance_metrics",
    ],
    SubQueue.FLUCTUATING_LOAD_VOLUME: [
        "get_load_manifestation_trends",
    ],
    SubQueue.PAYMENT_NOT_RECEIVED: [
        "get_payment_status",
        "get_invoice_status",
    ],
    SubQueue.INVOICE_NOT_RECEIVED: [
        "get_invoice_status",
        "get_payment_status",
    ],
    SubQueue.SHIPMENT_COUNT_MISMATCH: [
        "get_shipment_count_reconciliation",
    ],
    SubQueue.WRONG_DEBITS_CLARIFICATION: [
        "get_debit_reasons",
    ],
    SubQueue.WRONG_DEBITS_REVERSAL: [
        "get_debit_reasons",
    ],
    SubQueue.COD_NOT_REFLECTING: [
        "get_cod_pendency",
        "get_cod_transaction_history",
    ],
}


class QueryDispatcher:
    def get_queries(self, sub_queue: SubQueue) -> List[str]:
        return SUBQUEUE_QUERIES.get(sub_queue, [])
