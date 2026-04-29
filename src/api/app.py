"""
VALMO L1 Agent - Production REST API
FastAPI application exposing the agent pipeline as an HTTP service.
Designed for deployment behind a load balancer with multiple workers.

Endpoints:
  POST /tickets/process     — process a single ticket
  GET  /tickets/{id}/status — get resolution status
  GET  /health              — health check
  GET  /metrics             — system metrics
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.models import IncomingTicket, AgentResponse, TicketPriority, ResolutionStatus
from src.agent import L1AgentOrchestrator
from src.query_engine.query_engine import SQLQueryEngine, MockQueryEngine

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# IN-MEMORY STATE (replace with Redis in prod)
# ─────────────────────────────────────────────

_resolution_store: Dict[str, AgentResponse] = {}
_metrics = {
    "tickets_processed": 0,
    "tickets_resolved": 0,
    "tickets_escalated": 0,
    "tickets_failed": 0,
    "avg_processing_time_ms": 0.0,
}


# ─────────────────────────────────────────────
# APP INIT
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the agent on startup."""
    db_url = os.getenv("DB_URL")
    if db_url:
        engine = SQLQueryEngine(db_url)
        logger.info("Using SQL query engine.")
    else:
        engine = MockQueryEngine()
        logger.warning("DB_URL not set. Using mock query engine.")
    app.state.agent = L1AgentOrchestrator(query_engine=engine)
    logger.info("L1 Agent initialized and ready.")
    yield

app = FastAPI(
    title="VALMO L1 Operations Support Agent",
    version="1.0.0",
    description="Autonomous logistics partner support ticket resolution system",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# REQUEST / RESPONSE SCHEMAS
# ─────────────────────────────────────────────

class TicketRequest(BaseModel):
    ticket_id: str = Field(..., example="T-2024-001")
    partner_id: str = Field(..., example="P001")
    partner_name: str = Field(..., example="Fast Logistics Ltd")
    subject: str = Field(..., example="Payment not received for Jan 2024")
    body: str = Field(..., example="We have not received payment for INR 45000 for cycle 2024-01.")
    channel: str = Field(default="portal", example="email")
    priority: str = Field(default="medium", example="medium")
    metadata: Dict[str, Any] = Field(default_factory=dict)


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


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float


_start_time = time.time()


# ─────────────────────────────────────────────
# DEPENDENCY
# ─────────────────────────────────────────────

def get_agent(request) -> L1AgentOrchestrator:
    return request.app.state.agent


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.post("/tickets/process", response_model=TicketResponse)
async def process_ticket(
    payload: TicketRequest,
    background_tasks: BackgroundTasks,
    request=None,
):
    """
    Process a partner support ticket through the L1 agent pipeline.
    Returns a resolution (respond or escalate) synchronously.
    """
    from fastapi import Request
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
    response: AgentResponse = agent.process_ticket(ticket)
    elapsed_ms = (time.time() - t0) * 1000

    # Store for async lookup
    _resolution_store[ticket.ticket_id] = response

    # Update metrics
    _metrics["tickets_processed"] += 1
    if response.status == ResolutionStatus.RESOLVED:
        _metrics["tickets_resolved"] += 1
    elif response.status == ResolutionStatus.ESCALATED:
        _metrics["tickets_escalated"] += 1
    else:
        _metrics["tickets_failed"] += 1

    prev_avg = _metrics["avg_processing_time_ms"]
    n = _metrics["tickets_processed"]
    _metrics["avg_processing_time_ms"] = prev_avg + (elapsed_ms - prev_avg) / n

    return TicketResponse(
        ticket_id=response.ticket_id,
        partner_id=response.partner_id,
        status=response.status.value,
        issue_type=response.issue_type.value if response.issue_type else None,
        response_text=response.response_text,
        escalation_reason=response.escalation_reason.value if response.escalation_reason else None,
        escalation_queue=response.escalation_queue,
        confidence_score=round(response.confidence_score, 4),
        queries_executed=response.queries_executed,
        processed_at=response.processed_at.isoformat(),
    )


@app.get("/tickets/{ticket_id}/status", response_model=TicketResponse)
async def get_ticket_status(ticket_id: str):
    """Retrieve the resolution status of a previously processed ticket."""
    response = _resolution_store.get(ticket_id)
    if not response:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
    return TicketResponse(
        ticket_id=response.ticket_id,
        partner_id=response.partner_id,
        status=response.status.value,
        issue_type=response.issue_type.value if response.issue_type else None,
        response_text=response.response_text,
        escalation_reason=response.escalation_reason.value if response.escalation_reason else None,
        escalation_queue=response.escalation_queue,
        confidence_score=round(response.confidence_score, 4),
        queries_executed=response.queries_executed,
        processed_at=response.processed_at.isoformat(),
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="ok",
        version="1.0.0",
        uptime_seconds=round(time.time() - _start_time, 1),
    )


@app.get("/metrics")
async def get_metrics():
    return {
        "metrics": _metrics,
        "resolution_rate": (
            _metrics["tickets_resolved"] / max(_metrics["tickets_processed"], 1)
        ),
        "escalation_rate": (
            _metrics["tickets_escalated"] / max(_metrics["tickets_processed"], 1)
        ),
    }
