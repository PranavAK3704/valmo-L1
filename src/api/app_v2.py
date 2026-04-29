"""
VALMO L1 Agent - Production API (v2)
Wires Kapture webhook + Metabase query engine into the main FastAPI app.

Startup logic:
  - If METABASE_URL is set → use MetabaseQueryEngine
  - Else if DB_URL is set  → use SQLQueryEngine
  - Else                   → use MockQueryEngine (dev)

Routes:
  POST /tickets/process          — direct ticket submission (any source)
  GET  /tickets/{id}/status      — resolution lookup
  POST /webhooks/kapture          — Kapture webhook receiver
  GET  /health
  GET  /metrics
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.models import IncomingTicket, AgentResponse, TicketPriority, ResolutionStatus
from src.agent import L1AgentOrchestrator

logger = logging.getLogger(__name__)

_resolution_store: Dict[str, AgentResponse] = {}
_metrics = {
    "tickets_processed": 0,
    "tickets_resolved": 0,
    "tickets_escalated": 0,
    "tickets_failed": 0,
    "avg_processing_time_ms": 0.0,
}
_start_time = time.time()


# ─────────────────────────────────────────────
# ENGINE FACTORY
# ─────────────────────────────────────────────

def _build_query_engine():
    if os.getenv("METABASE_URL"):
        from src.query_engine.metabase_engine import MetabaseQueryEngine
        logger.info("Query engine: Metabase")
        return MetabaseQueryEngine()
    elif os.getenv("DB_URL"):
        from src.query_engine.query_engine import SQLQueryEngine
        logger.info("Query engine: SQL (direct)")
        return SQLQueryEngine(os.environ["DB_URL"])
    else:
        from src.query_engine.query_engine import MockQueryEngine
        logger.warning("Query engine: Mock (no METABASE_URL or DB_URL set)")
        return MockQueryEngine()


# ─────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = _build_query_engine()
    app.state.agent = L1AgentOrchestrator(query_engine=engine)

    # Mount Kapture webhook router
    from src.integrations.kapture import create_kapture_router
    kapture_router = create_kapture_router(app.state.agent)
    app.include_router(kapture_router, prefix="/webhooks")
    logger.info("L1 Agent ready. Kapture webhook mounted at /webhooks/kapture")
    yield


app = FastAPI(
    title="VALMO L1 Operations Support Agent",
    version="2.0.0",
    description="Autonomous L1 agent with Kapture CRM + Metabase query integration",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ─────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────

class TicketRequest(BaseModel):
    ticket_id: str
    partner_id: str
    partner_name: str
    subject: str
    body: str
    channel: str = "portal"
    priority: str = "medium"
    metadata: Dict[str, Any] = {}


class TicketResponse(BaseModel):
    ticket_id: str
    partner_id: str
    status: str
    issue_type: Optional[str] = None
    response_text: Optional[str] = None
    escalation_reason: Optional[str] = None
    escalation_queue: Optional[str] = None
    confidence_score: float
    queries_executed: list
    processed_at: str


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _to_response_schema(r: AgentResponse) -> TicketResponse:
    return TicketResponse(
        ticket_id=r.ticket_id,
        partner_id=r.partner_id,
        status=r.status.value,
        issue_type=r.issue_type.value if r.issue_type else None,
        response_text=r.response_text,
        escalation_reason=r.escalation_reason.value if r.escalation_reason else None,
        escalation_queue=r.escalation_queue,
        confidence_score=round(r.confidence_score, 4),
        queries_executed=r.queries_executed,
        processed_at=r.processed_at.isoformat(),
    )


def _record_metrics(response: AgentResponse, elapsed_ms: float):
    _resolution_store[response.ticket_id] = response
    _metrics["tickets_processed"] += 1
    if response.status == ResolutionStatus.RESOLVED:
        _metrics["tickets_resolved"] += 1
    elif response.status == ResolutionStatus.ESCALATED:
        _metrics["tickets_escalated"] += 1
    else:
        _metrics["tickets_failed"] += 1
    n = _metrics["tickets_processed"]
    prev = _metrics["avg_processing_time_ms"]
    _metrics["avg_processing_time_ms"] = prev + (elapsed_ms - prev) / n


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.post("/tickets/process", response_model=TicketResponse)
async def process_ticket(payload: TicketRequest):
    agent: L1AgentOrchestrator = app.state.agent
    ticket = IncomingTicket(
        ticket_id=payload.ticket_id,
        partner_id=payload.partner_id,
        partner_name=payload.partner_name,
        subject=payload.subject,
        body=payload.body,
        created_at=datetime.utcnow(),
        channel=payload.channel,
        priority=TicketPriority(payload.priority),
        metadata=payload.metadata,
    )
    t0 = time.time()
    response = agent.process_ticket(ticket)
    _record_metrics(response, (time.time() - t0) * 1000)
    return _to_response_schema(response)


@app.get("/tickets/{ticket_id}/status", response_model=TicketResponse)
async def get_ticket_status(ticket_id: str):
    r = _resolution_store.get(ticket_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
    return _to_response_schema(r)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "uptime_seconds": round(time.time() - _start_time, 1)}


@app.get("/metrics")
async def metrics():
    n = max(_metrics["tickets_processed"], 1)
    return {
        **_metrics,
        "resolution_rate": round(_metrics["tickets_resolved"] / n, 3),
        "escalation_rate": round(_metrics["tickets_escalated"] / n, 3),
    }
