"""
VALMO L1 Agent — Mock Query Engine (v3)
Returns deterministic test data for all 11 SOP queries.
Used in dev/test when no Metabase or DB URL is set.
"""
from typing import Dict, Any
from src.models import QueryResult


class MockQueryEngine:
    """Returns realistic mock data for every SOP query."""

    _BASE_MOCK: Dict[str, Dict[str, Any]] = {
        "get_loss_attribution": {"rows": [{
            "awb": "XY123456789", "attribution_status": "confirmed",
            "attributed_to": "captain", "loss_type": "shortage",
            "evidence_available": True, "recovered_from_fe": False,
            "wrong_tagging": False, "l1_contested": False,
            "remarks": "Loss confirmed per shortage SOP.", "marked_date": "2024-01-10",
        }]},
        "get_shipment_scan_history": {"rows": [{
            "awb": "XY123456789", "scan_time": "2024-01-09T14:00:00Z",
            "status": "pending", "location": "BLR_HUB", "hub_code": "BLR",
        }]},
        "get_captain_waiver_eligibility": {"rows": [{
            "partner_id": "P001", "tenure_days": 45,
            "previous_waivers": 0, "invoice_count": 2,
            "current_pendency": 0, "eligible_for_waiver": False,
            "waiver_criteria_met": False,
        }]},
        "get_payment_status": {"rows": [{
            "partner_id": "P001", "payment_cycle": "2024-W03",
            "status": "processed", "processed_date": "20-01-2024",
            "hold_reason": "", "utr_number": "UTR20240120001", "amount": 45000,
        }]},
        "get_invoice_status": {"rows": [{
            "partner_id": "P001", "payment_cycle": "2024-W03",
            "invoice_number": "INV-2024-001", "status": "signed",
            "invoice_date": "18-01-2024", "generated_date": "17-01-2024",
            "signed_date": "18-01-2024", "hold_reason": "", "cn_date": "17-01-2024",
        }]},
        "get_shipment_count_reconciliation": {"rows": [{
            "partner_id": "P001", "payment_cycle": "2024-W03",
            "invoice_delivered": 120, "actual_delivered": 118,
            "invoice_picked": 30,  "actual_picked": 30,
        }]},
        "get_debit_reasons": {"rows": [{
            "partner_id": "P001", "payment_cycle": "2024-W03",
            "cn_number": "CN-2024-005", "debit_type": "Shortage Loss",
            "debit_amount": "1500", "reason_description": "Shortage loss confirmed per SOP",
            "reversible": True, "within_3_months": True, "payment_processed": False,
        }]},
        "get_load_manifestation_trends": {"rows": [
            {"hub_code": "BLR", "week_start": "2024-01-15", "manifest_count": 80,
             "promised_load": 100, "week_over_week_change": -0.10},
            {"hub_code": "BLR", "week_start": "2024-01-08", "manifest_count": 89,
             "promised_load": 100, "week_over_week_change": -0.05},
            {"hub_code": "BLR", "week_start": "2024-01-01", "manifest_count": 94,
             "promised_load": 100, "week_over_week_change": 0.02},
        ]},
        "get_hub_performance_metrics": {"rows": [{
            "hub_code": "BLR", "metric_date": "2024-01-15",
            "active_routes": 8, "avg_daily_volume": 80, "capacity_utilisation": 0.72,
        }]},
        "get_cod_pendency": {"rows": []},   # no pendency by default
        "get_cod_transaction_history": {"rows": [{
            "hub_code": "BLR", "transaction_id": "TXN001",
            "transaction_date": "12-01-2024", "amount": "5000", "status": "settled",
        }]},
    }

    def __init__(self):
        import copy
        self._MOCK = copy.deepcopy(self._BASE_MOCK)

    def execute(self, query_name: str, params: Dict[str, Any]) -> QueryResult:
        data = self._MOCK.get(query_name, {"rows": []})
        return QueryResult(
            query_name=query_name, success=True,
            data=data, rows_returned=len(data.get("rows", [])),
        )
