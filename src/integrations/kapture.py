"""
VALMO L1 Agent — Kapture CRM Integration (v4)

Key changes from v3:
  - Field mapping: reads sub_type (queue) + sub_sub_type (sub-queue) from webform
  - These match the captain self-serve portal dropdown field names
  - Also accepts legacy group/issue_type as fallback
  - Confidence is out of 10: >= 5 auto-send, < 5 draft to L2 reviewer

INBOUND (webhook + polling):
  case.created / case.replied → IncomingTicket → L1 Agent

OUTBOUND:
  AUTO_SENT  → post public reply → mark resolved
  DRAFT      → post as internal note for L2 reviewer (below confidence 5)
  ESCALATED  → post ack reply → create L2 case → link note → mark escalated
  NEEDS_INFO → post public reply requesting missing fields

Env vars:
  KAPTURE_BASE_URL, KAPTURE_API_KEY
  KAPTURE_L2_LOSSES_GROUP, KAPTURE_L2_PAYMENTS_GROUP,
  KAPTURE_L2_OPERATIONS_GROUP, KAPTURE_L2_COD_GROUP, KAPTURE_L2_GENERAL_GROUP
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from src.models import (
    IncomingTicket, AgentResponse, Queue, SubQueue,
    ResolutionStatus, CONFIDENCE_AUTO_SEND
)
from src.ingestion.entity_extractor import map_queue, map_sub_queue

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# KAPTURE CLIENT
# ─────────────────────────────────────────────

class KaptureClient:
    def __init__(self, base_url=None, api_key=None, timeout=20):
        self._base = (base_url or os.environ["KAPTURE_BASE_URL"]).rstrip("/")
        self._key  = api_key  or os.environ["KAPTURE_API_KEY"]
        self._to   = timeout

    def _h(self):
        return {
            "X-Api-Key": self._key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _req(self, method, path, **kw):
        r = requests.request(method, f"{self._base}{path}",
                             headers=self._h(), timeout=self._to, **kw)
        r.raise_for_status()
        return r.json()

    def get_case(self, cid):
        return self._req("GET", f"/api/v1/cases/{cid}")

    def list_cases(self, status="open", page=1, per_page=50):
        return self._req("GET", "/api/v1/cases",
                         params={"status": status, "page": page, "per_page": per_page})

    def post_reply(self, cid, msg, reply_type="public"):
        return self._req("POST", f"/api/v1/cases/{cid}/replies",
                         json={"message": msg, "reply_type": reply_type})

    def post_note(self, cid, note):
        return self._req("POST", f"/api/v1/cases/{cid}/notes",
                         json={"note": note, "note_type": "internal"})

    def update_case(self, cid, status, assignee_group_id=None, tags=None):
        payload = {"status": status}
        if assignee_group_id:
            payload["group_id"] = assignee_group_id
        if tags:
            payload["tags"] = tags
        return self._req("PUT", f"/api/v1/cases/{cid}", json=payload)

    def create_case(self, subject, description, group_id,
                    priority="high", tags=None, parent_id=None):
        payload = {
            "subject":     subject,
            "description": description,
            "group_id":    group_id,
            "priority":    priority,
            "tags":        tags or ["l1_escalation", "auto_generated"],
        }
        if parent_id:
            payload["parent_case_id"] = parent_id
        return self._req("POST", "/api/v1/cases", json=payload)


# ─────────────────────────────────────────────
# INBOUND: WEBHOOK → IncomingTicket
# ─────────────────────────────────────────────

def _read_queue_fields(case: Dict[str, Any]):
    """
    Reads queue (Sub Type) and sub-queue (Sub Sub Type) from Kapture case.

    Priority:
      1. sub_type / sub_sub_type  — set by captain self-serve portal webform
      2. group / issue_type       — legacy / direct-create tickets
      3. category / sub_category  — alternate Kapture field names
    """
    raw_queue = (
        case.get("sub_type") or
        case.get("group") or
        case.get("category") or
        ""
    )
    raw_sub_queue = (
        case.get("sub_sub_type") or
        case.get("issue_type") or
        case.get("sub_category") or
        ""
    )
    return raw_queue, raw_sub_queue


def kapture_webhook_to_ticket(payload: Dict[str, Any]) -> Optional[IncomingTicket]:
    event = payload.get("event", "")
    if event not in ("case.created", "case.replied"):
        logger.debug(f"[KAPTURE] Ignoring event={event}")
        return None

    case    = payload.get("case", {})
    contact = case.get("contact", {})

    body = case.get("description", "")
    if not body and event == "case.replied":
        replies = case.get("replies", [])
        if replies:
            body = replies[-1].get("message", "")

    raw_queue, raw_sub_queue = _read_queue_fields(case)
    queue     = map_queue(raw_queue)
    sub_queue = map_sub_queue(raw_sub_queue)

    logger.info(f"[KAPTURE] case={case.get('id')} "
                f"sub_type='{raw_queue}' sub_sub_type='{raw_sub_queue}' "
                f"→ queue={queue} sub_queue={sub_queue}")

    return IncomingTicket(
        ticket_id=str(case["id"]),
        partner_id=str(contact.get("id") or contact.get("email") or "unknown"),
        partner_name=contact.get("name", "Unknown Partner"),
        subject=case.get("subject", ""),
        body=body,
        created_at=_parse_dt(case.get("created_at")),
        queue=queue,
        sub_queue=sub_queue,
        channel=case.get("channel", "portal"),
        metadata={
            "kapture_case_id":    case["id"],
            "kapture_sub_type":   raw_queue,
            "kapture_sub_sub_type": raw_sub_queue,
            "kapture_tags":       case.get("tags", []),
            "custom_fields":      case.get("custom_fields", {}),
            # Pass through structured fields that may carry AWBs / hub codes
            "hub_code":           case.get("hub_code", ""),
            "awbs":               case.get("awbs", ""),
            "payment_cycle":      case.get("payment_cycle_start_date", ""),
            "credit_note_number": case.get("credit_note_number", ""),
            "enbolt_id":          case.get("enbolt_id", ""),
        },
    )


def kapture_case_to_ticket(case: Dict[str, Any]) -> IncomingTicket:
    contact = case.get("contact", {})
    raw_queue, raw_sub_queue = _read_queue_fields(case)
    return IncomingTicket(
        ticket_id=str(case["id"]),
        partner_id=str(contact.get("id") or contact.get("email") or "unknown"),
        partner_name=contact.get("name", "Unknown Partner"),
        subject=case.get("subject", ""),
        body=case.get("description", ""),
        created_at=_parse_dt(case.get("created_at")),
        queue=map_queue(raw_queue),
        sub_queue=map_sub_queue(raw_sub_queue),
        channel=case.get("channel", "portal"),
        metadata={
            "kapture_case_id":    case["id"],
            "kapture_sub_type":   raw_queue,
            "kapture_sub_sub_type": raw_sub_queue,
            "custom_fields":      case.get("custom_fields", {}),
            "hub_code":           case.get("hub_code", ""),
            "awbs":               case.get("awbs", ""),
            "payment_cycle":      case.get("payment_cycle_start_date", ""),
            "credit_note_number": case.get("credit_note_number", ""),
            "enbolt_id":          case.get("enbolt_id", ""),
        },
    )


def _parse_dt(raw):
    if not raw:
        return datetime.utcnow()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return datetime.utcnow()


# ─────────────────────────────────────────────
# L2 GROUP MAP
# ─────────────────────────────────────────────

def _l2_groups():
    return {
        "L2_LOSSES":     int(os.getenv("KAPTURE_L2_LOSSES_GROUP",     "2001")),
        "L2_PAYMENTS":   int(os.getenv("KAPTURE_L2_PAYMENTS_GROUP",   "2002")),
        "L2_OPERATIONS": int(os.getenv("KAPTURE_L2_OPERATIONS_GROUP", "2003")),
        "L2_COD":        int(os.getenv("KAPTURE_L2_COD_GROUP",        "2004")),
        "L2_GENERAL":    int(os.getenv("KAPTURE_L2_GENERAL_GROUP",    "2000")),
    }


# ─────────────────────────────────────────────
# OUTBOUND: AgentResponse → Kapture
# ─────────────────────────────────────────────

class KaptureResponsePublisher:
    def __init__(self, client: KaptureClient = None):
        self._c      = client or KaptureClient()
        self._groups = _l2_groups()

    def publish(self, response: AgentResponse) -> Dict[str, Any]:
        cid    = response.ticket_id
        result = {"case_id": cid, "actions": []}
        try:
            if response.status == ResolutionStatus.AUTO_SENT:
                result["actions"] += self._auto_send(cid, response)
            elif response.status == ResolutionStatus.DRAFT:
                result["actions"] += self._post_draft(cid, response)
            elif response.status == ResolutionStatus.ESCALATED:
                result["actions"] += self._escalate(cid, response)
            elif response.status == ResolutionStatus.NEEDS_INFO:
                result["actions"] += self._needs_info(cid, response)
        except Exception as e:
            logger.error(f"[KAPTURE] Publish error case={cid}: {e}")
            result["error"] = str(e)
        return result

    # ── AUTO-SENT: confidence >= 5/10 ────────────────────────────────────────
    def _auto_send(self, cid, r):
        actions = []
        self._c.post_reply(cid, r.response_text)
        actions.append({"type": "public_reply_posted"})
        self._c.post_note(cid, self._trace_note(r))
        actions.append({"type": "audit_note_posted"})
        self._c.update_case(cid, "resolved",
                            tags=["l1_auto_resolved",
                                  f"confidence_{r.confidence:.0f}_of_10"])
        actions.append({"type": "status→resolved"})
        logger.info(f"[KAPTURE] AUTO_SENT case={cid} confidence={r.confidence:.1f}/10")
        return actions

    # ── DRAFT: confidence < 5/10 → L2 reviewer ───────────────────────────────
    def _post_draft(self, cid, r):
        """
        Low confidence response. Posts as internal note so L2 reviewer
        can approve or edit before sending to the captain.
        """
        actions = []
        draft_note = (
            f"⚠️  DRAFT — REVIEW BEFORE SENDING\n"
            f"Confidence: {r.confidence:.1f}/10 (threshold: {CONFIDENCE_AUTO_SEND}/10)\n"
            f"Sub-queue: {r.sub_queue}\n"
            f"Scenario:  {r.scenario_key}\n\n"
            f"{'─'*50}\n"
            f"PROPOSED REPLY TO CAPTAIN:\n\n"
            f"{r.response_text}\n\n"
            f"{'─'*50}\n"
            f"DECISION TRACE:\n" +
            "\n".join(f"  {i+1}. {t}" for i, t in enumerate(r.decision_trace))
        )
        self._c.post_note(cid, draft_note)
        actions.append({
            "type": "draft_note_posted",
            "confidence": r.confidence,
            "note": "Below threshold — L2 review required before sending to captain",
        })
        logger.info(f"[KAPTURE] DRAFT case={cid} confidence={r.confidence:.1f}/10 → L2 reviewer")
        return actions

    # ── ESCALATED: create L2 case ─────────────────────────────────────────────
    def _escalate(self, cid, r):
        actions = []
        esc_queue = r.escalation_queue or "L2_GENERAL"
        group_id  = self._groups.get(esc_queue, self._groups["L2_GENERAL"])

        # Public ack to captain
        self._c.post_reply(cid, r.response_text)
        actions.append({"type": "ack_reply_posted"})

        # New L2 case
        l2 = self._c.create_case(
            subject=f"[L2] {r.sub_queue} — Case {cid}",
            description=self._l2_description(cid, r),
            group_id=group_id,
            priority="high",
            tags=["l1_escalation", esc_queue.lower()],
            parent_id=cid,
        )
        l2_id = l2.get("id", "UNKNOWN")
        actions.append({"type": "l2_case_created",
                        "l2_case_id": l2_id,
                        "queue": esc_queue})

        # Link note on original case
        self._c.post_note(cid,
            f"[L1 AGENT] Escalated to {esc_queue}\n"
            f"L2 Case ID: {l2_id}\n"
            f"Reason: {r.escalation_reason.value if r.escalation_reason else 'N/A'}\n\n"
            f"Decision Trace:\n" +
            "\n".join(f"  • {t}" for t in r.decision_trace)
        )
        actions.append({"type": "link_note_posted"})

        self._c.update_case(cid, "escalated",
                            assignee_group_id=group_id,
                            tags=["l1_escalated", esc_queue.lower()])
        actions.append({"type": "status→escalated"})
        logger.info(f"[KAPTURE] ESCALATED case={cid} → {esc_queue} l2={l2_id}")
        return actions

    # ── NEEDS_INFO: request missing fields from captain ───────────────────────
    def _needs_info(self, cid, r):
        self._c.post_reply(cid, r.response_text)
        logger.info(f"[KAPTURE] NEEDS_INFO reply posted case={cid}")
        return [{"type": "info_request_reply_posted"}]

    # ── helpers ───────────────────────────────────────────────────────────────
    def _trace_note(self, r):
        return "\n".join([
            "[L1 AGENT — AUDIT NOTE]",
            f"Status:     {r.status.value}",
            f"Queue:      {r.queue}",
            f"Sub-queue:  {r.sub_queue}",
            f"Scenario:   {r.scenario_key}",
            f"Confidence: {r.confidence:.1f}/10",
            f"Queries:    {', '.join(r.queries_executed)}",
            "",
            "Decision Trace:",
        ] + [f"  {i+1}. {t}" for i, t in enumerate(r.decision_trace)])

    def _l2_description(self, cid, r):
        return (
            f"Original Case: {cid}\n"
            f"Partner: {r.partner_id}\n"
            f"Queue: {r.queue} / {r.sub_queue}\n"
            f"Escalation Reason: {r.escalation_reason.value if r.escalation_reason else 'N/A'}\n"
            f"Queries Run: {', '.join(r.queries_executed)}\n\n"
            "Decision Trace:\n" +
            "\n".join(f"  {t}" for t in r.decision_trace)
        )


# ─────────────────────────────────────────────
# FASTAPI WEBHOOK ROUTER
# ─────────────────────────────────────────────

def create_kapture_router(agent_orchestrator):
    from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
    from fastapi.responses import JSONResponse

    router    = APIRouter()
    publisher = KaptureResponsePublisher()

    @router.post("/kapture")
    async def kapture_webhook(request: Request, background_tasks: BackgroundTasks):
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON")

        ticket = kapture_webhook_to_ticket(payload)
        if ticket is None:
            return JSONResponse({"status": "ignored"})

        async def _process():
            response = agent_orchestrator.process_ticket(ticket)
            result   = publisher.publish(response)
            logger.info(f"[WEBHOOK] ticket={ticket.ticket_id} "
                        f"status={response.status} "
                        f"confidence={response.confidence:.1f}/10 "
                        f"actions={result.get('actions', [])}")

        background_tasks.add_task(_process)
        return JSONResponse({"status": "accepted", "ticket_id": ticket.ticket_id})

    return router


# ─────────────────────────────────────────────
# POLLING CONSUMER
# ─────────────────────────────────────────────

class KapturePollingConsumer:
    def __init__(self, agent_orchestrator, poll_interval_sec=60, client=None):
        self._agent     = agent_orchestrator
        self._publisher = KaptureResponsePublisher()
        self._client    = client or KaptureClient()
        self._interval  = poll_interval_sec
        self._processed = set()

    def run_once(self):
        cases     = self._client.list_cases(status="open")
        case_list = cases if isinstance(cases, list) else cases.get("cases", [])
        count = 0
        for case in case_list:
            cid = str(case.get("id"))
            if cid in self._processed:
                continue
            ticket = kapture_case_to_ticket(case)
            self._publisher.publish(self._agent.process_ticket(ticket))
            self._processed.add(cid)
            count += 1
        logger.info(f"[POLL] Processed {count} tickets")
        return count

    def run_loop(self):
        import time
        logger.info(f"[POLL] Starting loop every {self._interval}s")
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"[POLL] Error: {e}")
            time.sleep(self._interval)
