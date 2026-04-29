"""
VALMO L1 Agent - Escalation Service
Routes escalated tickets to the correct L2 queue.
Integrates with internal ticketing system (configurable).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any

from src.models import AgentResponse, EscalationReason

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# ESCALATION QUEUE DEFINITIONS
# ─────────────────────────────────────────────

ESCALATION_QUEUES: Dict[str, Dict[str, Any]] = {
    "L2_LOSS_DISPUTE": {
        "name": "L2 Loss Dispute Team",
        "sla_hours": 48,
        "priority_boost": True,
        "notification_group": "loss_dispute_ops@valmo.internal",
    },
    "L2_FINANCE": {
        "name": "L2 Finance Team",
        "sla_hours": 24,
        "priority_boost": False,
        "notification_group": "finance_ops@valmo.internal",
    },
    "L2_FINANCE_REVERSAL": {
        "name": "L2 Finance Reversal Team",
        "sla_hours": 24,
        "priority_boost": True,
        "notification_group": "finance_reversal@valmo.internal",
    },
    "L2_OPERATIONS": {
        "name": "L2 Operations Team",
        "sla_hours": 48,
        "priority_boost": False,
        "notification_group": "operations_l2@valmo.internal",
    },
    "L2_WAIVER_APPROVAL": {
        "name": "L2 Waiver Approval Team",
        "sla_hours": 24,
        "priority_boost": True,
        "notification_group": "waiver_approvals@valmo.internal",
    },
    "L2_GENERAL": {
        "name": "L2 General Support",
        "sla_hours": 72,
        "priority_boost": False,
        "notification_group": "l2_support@valmo.internal",
    },
}


@dataclass
class EscalationRecord:
    ticket_id: str
    partner_id: str
    escalation_reason: EscalationReason
    escalation_queue: str
    queue_name: str
    sla_hours: int
    escalated_at: datetime = field(default_factory=datetime.utcnow)
    escalation_ticket_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────
# ESCALATION SERVICE
# ─────────────────────────────────────────────

class EscalationService:
    """
    Handles escalation routing for tickets that cannot be resolved at L1.
    Supports pluggable backend (Freshdesk / Zendesk / internal CRM).
    """

    def __init__(self, backend=None):
        self._backend = backend or LoggingEscalationBackend()

    def escalate(self, response: AgentResponse) -> EscalationRecord:
        if response.escalation_queue not in ESCALATION_QUEUES:
            queue = "L2_GENERAL"
            logger.warning(
                f"[ESCALATION] Unknown queue '{response.escalation_queue}'. "
                f"Defaulting to {queue}."
            )
        else:
            queue = response.escalation_queue

        queue_config = ESCALATION_QUEUES[queue]
        record = EscalationRecord(
            ticket_id=response.ticket_id,
            partner_id=response.partner_id,
            escalation_reason=response.escalation_reason,
            escalation_queue=queue,
            queue_name=queue_config["name"],
            sla_hours=queue_config["sla_hours"],
            metadata={
                "decision_trace": response.decision_trace,
                "notification_group": queue_config["notification_group"],
            }
        )

        record.escalation_ticket_id = self._backend.submit(record)
        logger.info(
            f"[ESCALATION] ticket={record.ticket_id} → queue={queue} "
            f"(esc_ticket={record.escalation_ticket_id})"
        )
        return record


# ─────────────────────────────────────────────
# ESCALATION BACKENDS
# ─────────────────────────────────────────────

class LoggingEscalationBackend:
    """Dev/test backend — logs escalation and returns a mock ID."""
    def submit(self, record: EscalationRecord) -> str:
        logger.info(
            f"[ESC-BACKEND] Escalating {record.ticket_id} to {record.queue_name} "
            f"[SLA: {record.sla_hours}h | reason: {record.escalation_reason}]"
        )
        return f"ESC-{record.ticket_id}-{record.escalation_queue}"


class FreshdeskEscalationBackend:
    """
    Production backend for Freshdesk.
    Creates a new ticket in the appropriate Freshdesk group.
    """
    GROUP_ID_MAP = {
        "L2_LOSS_DISPUTE":      1001,
        "L2_FINANCE":           1002,
        "L2_FINANCE_REVERSAL":  1003,
        "L2_OPERATIONS":        1004,
        "L2_WAIVER_APPROVAL":   1005,
        "L2_GENERAL":           1000,
    }

    def __init__(self, api_key: str, domain: str):
        self._api_key = api_key
        self._domain = domain

    def submit(self, record: EscalationRecord) -> str:
        import requests, base64
        group_id = self.GROUP_ID_MAP.get(record.escalation_queue, 1000)
        payload = {
            "subject": f"[L2 Escalation] Ticket {record.ticket_id}",
            "description": (
                f"Partner: {record.partner_id}\n"
                f"Reason: {record.escalation_reason.value}\n"
                f"Queue: {record.escalation_queue}\n"
                f"Decision Trace:\n" +
                "\n".join(record.metadata.get("decision_trace", []))
            ),
            "group_id": group_id,
            "priority": 2,
            "status": 2,
            "tags": ["l1_escalation", record.escalation_queue],
        }
        creds = base64.b64encode(f"{self._api_key}:X".encode()).decode()
        resp = requests.post(
            f"https://{self._domain}.freshdesk.com/api/v2/tickets",
            json=payload,
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return str(resp.json().get("id", "UNKNOWN"))
