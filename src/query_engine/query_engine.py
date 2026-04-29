"""
VALMO L1 Agent - Query Execution Layer
Programmatic interface to internal operational data queries.
Each query is a named, parameterized function that executes against
the data warehouse and returns a typed QueryResult.

In production, these use SQLAlchemy to talk to the internal data store.
A MockQueryEngine is provided for local testing.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from src.models import QueryResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# QUERY CATALOG  (named operational queries)
# ─────────────────────────────────────────────

QUERY_CATALOG = {
    "get_shipment_scan_history": """
        SELECT awb, scan_type, scan_time, hub_code, status
        FROM shipment_scans
        WHERE awb = :awb
        ORDER BY scan_time ASC
    """,
    "get_loss_attribution": """
        SELECT awb, loss_type, attributed_to, attribution_status,
               attribution_date, evidence_available
        FROM loss_records
        WHERE awb = :awb
    """,
    "get_payment_status": """
        SELECT partner_id, payment_cycle, amount, status,
               processed_date, utr_number, bank_reference
        FROM payments
        WHERE partner_id = :partner_id
          AND payment_cycle = :payment_cycle
    """,
    "get_invoice_status": """
        SELECT partner_id, invoice_id, invoice_date, amount,
               status, billing_cycle
        FROM invoices
        WHERE partner_id = :partner_id
          AND billing_cycle = :billing_cycle
    """,
    "get_shipment_count_reconciliation": """
        SELECT partner_id, date_range_start, date_range_end,
               manifest_count, scan_count, delivered_count, discrepancy
        FROM shipment_reconciliation
        WHERE partner_id = :partner_id
          AND date_range_start >= :start_date
          AND date_range_end   <= :end_date
    """,
    "get_debit_reasons": """
        SELECT awb, debit_type, debit_amount, debit_date,
               reason_code, reason_description, reversible
        FROM debit_records
        WHERE partner_id = :partner_id
          AND awb = :awb
    """,
    "get_load_manifestation_trends": """
        SELECT partner_id, date, manifest_count, hub_code,
               route_code, week_over_week_change
        FROM load_manifest_trends
        WHERE partner_id = :partner_id
          AND date BETWEEN :start_date AND :end_date
        ORDER BY date ASC
    """,
    "get_hub_performance_metrics": """
        SELECT hub_code, date, pickup_sla, delivery_sla,
               rto_rate, loss_rate, shortage_rate
        FROM hub_metrics
        WHERE hub_code = :hub_code
          AND date BETWEEN :start_date AND :end_date
    """,
    "get_cod_pendency": """
        SELECT partner_id, awb, cod_amount, collection_date,
               pendency_days, remittance_status
        FROM cod_pendency
        WHERE partner_id = :partner_id
    """,
    "get_cod_transaction_history": """
        SELECT partner_id, transaction_date, amount, utr_number,
               bank_account, status, remittance_cycle
        FROM cod_transactions
        WHERE partner_id = :partner_id
          AND transaction_date BETWEEN :start_date AND :end_date
        ORDER BY transaction_date DESC
    """,
    "get_captain_waiver_eligibility": """
        SELECT captain_id, partner_id, eligible_for_waiver,
               previous_waivers, loss_count, waiver_criteria_met,
               last_waiver_date
        FROM captain_waiver_eligibility
        WHERE captain_id = :captain_id
    """,
}


# ─────────────────────────────────────────────
# BASE ENGINE
# ─────────────────────────────────────────────

class BaseQueryEngine(ABC):
    @abstractmethod
    def execute(self, query_name: str, params: Dict[str, Any]) -> QueryResult:
        ...


# ─────────────────────────────────────────────
# PRODUCTION ENGINE  (SQLAlchemy)
# ─────────────────────────────────────────────

class SQLQueryEngine(BaseQueryEngine):
    """
    Executes named queries against the internal data warehouse via SQLAlchemy.
    Connection pooling, timeouts, and retries are handled here.
    """

    def __init__(self, db_url: str, query_timeout_sec: int = 30):
        try:
            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import QueuePool
            self._text = text
            self._engine = create_engine(
                db_url,
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20,
                pool_timeout=30,
                connect_args={"connect_timeout": query_timeout_sec},
            )
            logger.info("SQLQueryEngine initialized.")
        except ImportError:
            raise RuntimeError("sqlalchemy is required for production mode. pip install sqlalchemy")

    def execute(self, query_name: str, params: Dict[str, Any]) -> QueryResult:
        if query_name not in QUERY_CATALOG:
            return QueryResult(
                query_name=query_name,
                success=False,
                error=f"Unknown query: {query_name}"
            )
        sql = QUERY_CATALOG[query_name]
        try:
            with self._engine.connect() as conn:
                result = conn.execute(self._text(sql), params)
                rows = [dict(r._mapping) for r in result.fetchall()]
                return QueryResult(
                    query_name=query_name,
                    success=True,
                    data={"rows": rows},
                    rows_returned=len(rows),
                )
        except Exception as e:
            logger.error(f"[QUERY] {query_name} failed: {e}")
            return QueryResult(query_name=query_name, success=False, error=str(e))


# ─────────────────────────────────────────────
# MOCK ENGINE  (for testing / dev)
# ─────────────────────────────────────────────

MOCK_DATA: Dict[str, Any] = {
    "get_shipment_scan_history": {
        "rows": [
            {"awb": "XY123456789", "scan_type": "pickup", "scan_time": "2024-01-10 09:00",
             "hub_code": "DEL", "status": "picked_up"},
            {"awb": "XY123456789", "scan_type": "in_transit", "scan_time": "2024-01-11 14:00",
             "hub_code": "BOM", "status": "in_transit"},
            {"awb": "XY123456789", "scan_type": "delivery", "scan_time": "2024-01-12 11:30",
             "hub_code": "BOM", "status": "delivered"},
        ]
    },
    "get_loss_attribution": {
        "rows": [
            {"awb": "XY123456789", "loss_type": "shortage", "attributed_to": "hub",
             "attribution_status": "pending", "attribution_date": None,
             "evidence_available": False}
        ]
    },
    "get_payment_status": {
        "rows": [
            {"partner_id": "P001", "payment_cycle": "2024-01", "amount": 45000.0,
             "status": "processed", "processed_date": "2024-01-15",
             "utr_number": "UTR20240115XYZ", "bank_reference": "BANK-REF-001"}
        ]
    },
    "get_invoice_status": {
        "rows": []  # No invoice found - triggers escalation
    },
    "get_shipment_count_reconciliation": {
        "rows": [
            {"partner_id": "P001", "date_range_start": "2024-01-01",
             "date_range_end": "2024-01-31", "manifest_count": 150,
             "scan_count": 148, "delivered_count": 145, "discrepancy": 2}
        ]
    },
    "get_debit_reasons": {
        "rows": [
            {"awb": "XY123456789", "debit_type": "shortage_loss", "debit_amount": 1200.0,
             "debit_date": "2024-01-20", "reason_code": "SL001",
             "reason_description": "Confirmed shortage at destination hub",
             "reversible": False}
        ]
    },
    "get_load_manifestation_trends": {
        "rows": [
            {"partner_id": "P001", "date": "2024-01-01", "manifest_count": 50,
             "hub_code": "DEL", "route_code": "DEL-BOM", "week_over_week_change": -0.15},
            {"partner_id": "P001", "date": "2024-01-08", "manifest_count": 42,
             "hub_code": "DEL", "route_code": "DEL-BOM", "week_over_week_change": -0.16},
        ]
    },
    "get_hub_performance_metrics": {
        "rows": [
            {"hub_code": "DEL", "date": "2024-01-10", "pickup_sla": 0.94,
             "delivery_sla": 0.91, "rto_rate": 0.07, "loss_rate": 0.02, "shortage_rate": 0.01}
        ]
    },
    "get_cod_pendency": {
        "rows": [
            {"partner_id": "P001", "awb": "XY123456789", "cod_amount": 5000.0,
             "collection_date": "2024-01-10", "pendency_days": 5, "remittance_status": "pending"}
        ]
    },
    "get_cod_transaction_history": {
        "rows": [
            {"partner_id": "P001", "transaction_date": "2024-01-05", "amount": 12000.0,
             "utr_number": "UTR20240105COD", "bank_account": "XXXXX1234",
             "status": "credited", "remittance_cycle": "2024-W01"}
        ]
    },
    "get_captain_waiver_eligibility": {
        "rows": [
            {"captain_id": "CAP12345", "partner_id": "P001", "eligible_for_waiver": True,
             "previous_waivers": 0, "loss_count": 1,
             "waiver_criteria_met": True, "last_waiver_date": None}
        ]
    },
}


class MockQueryEngine(BaseQueryEngine):
    """Returns deterministic mock data for testing without a database."""

    def execute(self, query_name: str, params: Dict[str, Any]) -> QueryResult:
        logger.debug(f"[MOCK QUERY] {query_name} params={params}")
        data = MOCK_DATA.get(query_name, {"rows": []})
        return QueryResult(
            query_name=query_name,
            success=True,
            data=data,
            rows_returned=len(data.get("rows", [])),
        )


# ─────────────────────────────────────────────
# QUERY DISPATCHER
# ─────────────────────────────────────────────

class QueryDispatcher:
    """
    High-level interface used by the decision engine.
    Selects and executes the correct queries for a given issue type.
    """

    # Maps issue type → list of queries to run (ordered)
    ISSUE_QUERY_MAP = {
        "shortage_loss_dispute":    ["get_shipment_scan_history", "get_loss_attribution"],
        "hardstop_loss_dispute":    ["get_shipment_scan_history", "get_loss_attribution"],
        "payment_not_received":     ["get_payment_status", "get_invoice_status"],
        "invoice_not_generated":    ["get_invoice_status", "get_payment_status"],
        "shipment_count_mismatch":  ["get_shipment_count_reconciliation", "get_shipment_scan_history"],
        "debit_clarification":      ["get_debit_reasons"],
        "debit_reversal":           ["get_debit_reasons"],
        "drop_in_load_volume":      ["get_load_manifestation_trends", "get_hub_performance_metrics"],
        "fluctuating_load_volume":  ["get_load_manifestation_trends"],
        "cod_not_reflecting":       ["get_cod_pendency", "get_cod_transaction_history"],
        "unknown":                  [],
    }

    def __init__(self, engine: BaseQueryEngine):
        self._engine = engine

    def run_queries_for_issue(
        self,
        issue_type: str,
        params: Dict[str, Any],
    ) -> List[QueryResult]:
        query_names = self.ISSUE_QUERY_MAP.get(issue_type, [])
        results = []
        for qname in query_names:
            result = self._engine.execute(qname, params)
            results.append(result)
            if not result.success:
                logger.warning(f"[DISPATCHER] Query {qname} failed: {result.error}")
        return results

    def run_single(self, query_name: str, params: Dict[str, Any]) -> QueryResult:
        return self._engine.execute(query_name, params)
