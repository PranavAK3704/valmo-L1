"""
VALMO L1 Agent — Orchestrator (v3)

Pipeline:
  IncomingTicket
    → map Queue/SubQueue from Kapture fields
    → extract entities from body
    → check mandatory fields (if missing → NEEDS_INFO)
    → dispatch Metabase queries for this sub-queue
    → run SOP decision engine
    → generate response (auto-send or draft based on confidence)
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from src.models import (
    IncomingTicket, AgentResponse, Queue, SubQueue,
    ExtractedEntities, QueryResult, ResolutionStatus, ScenarioKey, DecisionOutput
)
from src.ingestion.entity_extractor import EntityExtractor, map_queue, map_sub_queue
from src.query_engine.query_dispatcher import QueryDispatcher
from src.decision_engine.sop_engine import DecisionEngine
from src.response_generator.response_generator import ResponseGenerator

logger = logging.getLogger(__name__)


class L1AgentOrchestrator:
    def __init__(self, query_engine=None):
        self._query_engine   = query_engine or self._default_engine()
        self._extractor      = EntityExtractor()
        self._dispatcher     = QueryDispatcher()
        self._decision_engine = DecisionEngine()
        self._response_gen   = ResponseGenerator()

    # ── public ────────────────────────────────────────────────────────────────

    def process_ticket(self, ticket: IncomingTicket) -> AgentResponse:
        logger.info(f"[AGENT] Processing ticket={ticket.ticket_id} "
                    f"queue={ticket.queue} sub_queue={ticket.sub_queue}")
        try:
            return self._run_pipeline(ticket)
        except Exception as e:
            logger.error(f"[AGENT] Pipeline error ticket={ticket.ticket_id}: {e}", exc_info=True)
            return AgentResponse(
                ticket_id=ticket.ticket_id, partner_id=ticket.partner_id,
                queue=ticket.queue, sub_queue=ticket.sub_queue,
                status=ResolutionStatus.FAILED,
                decision_trace=[f"Pipeline error: {e}"],
                processed_at=datetime.utcnow(),
            )

    # ── pipeline ──────────────────────────────────────────────────────────────

    def _run_pipeline(self, ticket: IncomingTicket) -> AgentResponse:
        # Step 1: map queue + sub_queue from Kapture fields (already pre-set)
        queue, sub_queue = self._resolve_queue(ticket)
        ticket.queue     = queue
        ticket.sub_queue = sub_queue

        # Step 2: extract entities from ticket body + Kapture custom fields
        entities = self._extractor.extract(ticket)
        logger.debug(f"[AGENT] entities={entities}")

        # Step 3: if mandatory fields are missing → request from captain
        if entities.missing_fields:
            logger.info(f"[AGENT] Missing fields {entities.missing_fields} → NEEDS_INFO")
            dummy_decision = DecisionOutput(
                scenario_key=ScenarioKey.MISSING_INFO_REQUEST,
                action="needs_info", template_key="missing_info_request",
            )
            return self._response_gen.generate(
                ticket.ticket_id, ticket.partner_id,
                queue, sub_queue, dummy_decision,
                missing_fields=entities.missing_fields,
            )

        # Step 4: fetch Metabase queries for this sub-queue
        query_names = self._dispatcher.get_queries(sub_queue)
        query_results = self._run_queries(query_names, entities, ticket)

        # Step 5: SOP decision
        decision = self._decision_engine.decide(entities, query_results, sub_queue)
        decision.queries_executed = query_names   # carry through for audit

        # Step 6: generate response (auto-send vs draft based on confidence)
        response = self._response_gen.generate(
            ticket.ticket_id, ticket.partner_id,
            queue, sub_queue, decision,
        )
        response.queries_executed = query_names
        response.processed_at     = datetime.utcnow()
        return response

    # ── helpers ───────────────────────────────────────────────────────────────

    def _resolve_queue(self, ticket: IncomingTicket):
        """
        Queue and sub-queue are pre-filled by Kapture.
        They arrive either as enum values (if already mapped) or as raw strings
        in ticket.metadata['kapture_group'] / ticket.metadata['kapture_issue_type'].
        """
        queue     = ticket.queue
        sub_queue = ticket.sub_queue

        # If still UNKNOWN, try to read raw Kapture field from metadata
        if queue == Queue.UNKNOWN:
            raw_q = ticket.metadata.get("kapture_group", "") or \
                    ticket.metadata.get("group", "")
            if raw_q:
                queue = map_queue(raw_q)

        if sub_queue == SubQueue.UNKNOWN:
            raw_sq = ticket.metadata.get("kapture_issue_type", "") or \
                     ticket.metadata.get("issue_type", "")
            if raw_sq:
                sub_queue = map_sub_queue(raw_sq)

        logger.info(f"[AGENT] Queue={queue} SubQueue={sub_queue}")
        return queue, sub_queue

    def _run_queries(
        self, query_names: List[str],
        entities: ExtractedEntities,
        ticket: IncomingTicket,
    ) -> List[QueryResult]:
        results = []
        params  = self._build_params(entities, ticket)
        for name in query_names:
            qr = self._query_engine.execute(name, params)
            results.append(qr)
            if not qr.success:
                logger.warning(f"[AGENT] Query {name} failed: {qr.error}")
        return results

    def _build_params(self, entities: ExtractedEntities, ticket: IncomingTicket) -> Dict[str, Any]:
        now = datetime.utcnow()
        start = entities.date_range[0] if entities.date_range else now - timedelta(days=30)
        end   = entities.date_range[1] if entities.date_range else now
        return {
            "partner_id":    ticket.partner_id,
            "awb_list":      entities.awb_numbers or [],
            "awb":           entities.awb_numbers[0] if entities.awb_numbers else None,
            "hub_code":      entities.hub_codes[0] if entities.hub_codes else None,
            "payment_cycle": entities.payment_cycle,
            "invoice_number": entities.invoice_number,
            "enbolt_id":     entities.enbolt_id,
            "cn_number":     entities.cn_number,
            "start_date":    start.strftime("%Y-%m-%d"),
            "end_date":      end.strftime("%Y-%m-%d"),
        }

    @staticmethod
    def _default_engine():
        import os
        if os.getenv("METABASE_URL"):
            from src.query_engine.metabase_engine import MetabaseQueryEngine
            return MetabaseQueryEngine()
        if os.getenv("DB_URL"):
            from src.query_engine.query_engine import SQLQueryEngine
            return SQLQueryEngine(os.environ["DB_URL"])
        from src.query_engine.mock_engine import MockQueryEngine
        return MockQueryEngine()
