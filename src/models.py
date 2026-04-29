"""
VALMO L1 Agent — Core Data Models (v4)

Key changes from v3:
  - Confidence is out of 10 (not 0-1), threshold at 5
  - CONFIDENCE_AUTO_SEND = 5  (>= 5 → auto-send, < 5 → draft to L2 reviewer)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List

# Confidence out of 10. >= 5 → auto-send to partner. < 5 → send to L2 reviewer.
CONFIDENCE_AUTO_SEND = 5.0
CONFIDENCE_MAX       = 10.0


class Queue(str, Enum):
    LOSSES_AND_DEBITS   = "Losses & Debits"
    ORDERS_AND_PLANNING = "Orders & Planning"
    PAYMENTS            = "Payments"
    CASH_HANDOVER       = "Cash Handover"
    UNKNOWN             = "Unknown"


class SubQueue(str, Enum):
    # Losses & Debits
    SHORTAGE_LOSS            = "Shortage Loss"
    HARDSTOP_LOSS            = "Hardstop Loss"
    HARDSTOP_ALERT_EMAIL     = "I received hardstop alert email"
    # Orders & Planning
    DROP_IN_LOAD_VOLUME      = "Forward Leg - Drop in Load Volume"
    PROMISED_LOAD_NOT_MET    = "Forward Leg - Promised Load Not Met"
    FLUCTUATING_LOAD_VOLUME  = "Forward Leg - Fluctuating Load Volume"
    # Payments
    PAYMENT_NOT_RECEIVED     = "I have not received payment"
    INVOICE_NOT_RECEIVED     = "I have not received invoice for e-signing"
    SHIPMENT_COUNT_MISMATCH  = "There is shipment count mismatch in my invoice"
    WRONG_DEBITS_CLARIFICATION = "Wrong debits are marked in my invoice - Clarification"
    WRONG_DEBITS_REVERSAL    = "Wrong debits are marked in my invoice - Reversal"
    # Cash Handover
    COD_NOT_REFLECTING       = "I have deposited the money but it is not reflecting"
    UNKNOWN                  = "Unknown"


class ScenarioKey(str, Enum):
    SHORTAGE_ATTRIBUTION_PENDING     = "shortage_attribution_pending"
    SHORTAGE_LOSS_MARKED_CORRECTLY   = "shortage_loss_marked_correctly"
    SHORTAGE_LOSS_MARKED_INCORRECTLY = "shortage_loss_marked_incorrectly"
    SHORTAGE_WAIVER_ELIGIBLE         = "shortage_waiver_eligible"
    SHORTAGE_LOSS_RECOVERED_FROM_FE  = "shortage_loss_recovered_from_fe"
    HARDSTOP_LOSS_CORRECTLY_MARKED   = "hardstop_loss_correctly_marked"
    HARDSTOP_WAIVER_ELIGIBLE         = "hardstop_waiver_eligible"
    HARDSTOP_WRONG_TAGGING           = "hardstop_wrong_tagging"
    HARDSTOP_L1_CONTESTS             = "hardstop_l1_contests"
    HARDSTOP_ALERT_DELIVERED         = "hardstop_alert_delivered"
    HARDSTOP_ALERT_NOT_YET_MARKED    = "hardstop_alert_not_yet_marked"
    HARDSTOP_ALERT_LOSS_BREACHED     = "hardstop_alert_loss_breached"
    LOAD_DROP_EXPLAINABLE            = "load_drop_explainable"
    LOAD_DROP_ESCALATE               = "load_drop_escalate"
    PROMISED_LOAD_BREACH             = "promised_load_breach"
    LOAD_FLUCTUATION_NORMAL          = "load_fluctuation_normal"
    LOAD_FLUCTUATION_ESCALATE        = "load_fluctuation_escalate"
    PAYMENT_PROCESSED                = "payment_processed"
    PAYMENT_PENDING_SIGN             = "payment_pending_sign"
    PAYMENT_HOLD_NEGATIVE            = "payment_hold_negative"
    PAYMENT_NO_EARNINGS              = "payment_no_earnings"
    PAYMENT_GST_DEFAULTER            = "payment_gst_defaulter"
    PAYMENT_RISK_COD                 = "payment_risk_cod"
    PAYMENT_RISK_COD_SHIPMENT        = "payment_risk_cod_shipment"
    PAYMENT_GST_ABOVE_20L            = "payment_gst_above_20l"
    PAYMENT_HOLD_BY_OPS              = "payment_hold_by_ops"
    PAYMENT_ONBOARDING_ISSUE         = "payment_onboarding_issue"
    PAYMENT_FF_VENDOR                = "payment_ff_vendor"
    PAYMENT_GROCERY_DEFAULTER        = "payment_grocery_defaulter"
    PAYMENT_NEGATIVE_BALANCE         = "payment_negative_balance"
    PAYMENT_FAILED                   = "payment_failed"
    INVOICE_NOT_GENERATED            = "invoice_not_generated"
    SHIPMENT_COUNT_DELTA_ZERO        = "shipment_count_delta_zero"
    SHIPMENT_COUNT_DELTA_POSITIVE    = "shipment_count_delta_positive"
    SHIPMENT_COUNT_DELTA_NEGATIVE    = "shipment_count_delta_negative"
    DEBIT_CLARIFICATION_PROVIDED     = "debit_clarification_provided"
    DEBIT_REVERSAL_ELIGIBLE          = "debit_reversal_eligible"
    DEBIT_REVERSAL_NOT_ELIGIBLE      = "debit_reversal_not_eligible"
    COD_NO_PENDENCY                  = "cod_no_pendency"
    COD_PENDENCY_EXISTS              = "cod_pendency_exists"
    ESCALATE_TO_L2                   = "escalate_to_l2"
    MISSING_INFO_REQUEST             = "missing_info_request"
    NO_SOP_MATCH                     = "no_sop_match"   # direct escalate — no matching SOP


class EscalationReason(str, Enum):
    WAIVER_APPROVAL_REQUIRED = "waiver_approval_required"
    L1_CONTESTS_ATTRIBUTION  = "l1_contests_attribution"
    EVIDENCE_MISMATCH        = "evidence_mismatch"
    REVERSAL_REQUEST         = "reversal_request"
    MISSING_OPERATIONAL_DATA = "missing_operational_data"
    INCONSISTENT_DATA        = "inconsistent_data"
    LOAD_ANOMALY             = "load_anomaly"
    PROMISED_LOAD_BREACH     = "promised_load_breach"
    NO_SOP_MATCH             = "no_sop_match"
    QUERY_FAILED             = "query_failed"


class ResolutionStatus(str, Enum):
    AUTO_SENT  = "auto_sent"    # confidence >= 5, reply sent directly to partner
    DRAFT      = "draft"        # confidence < 5, sent to L2 reviewer
    ESCALATED  = "escalated"    # routed to L2 (reversal / waiver / contested)
    NEEDS_INFO = "needs_info"   # mandatory fields missing, requested from captain
    FAILED     = "failed"       # pipeline / query error


@dataclass
class IncomingTicket:
    ticket_id:    str
    partner_id:   str
    partner_name: str
    subject:      str
    body:         str
    created_at:   datetime
    queue:        Queue    = Queue.UNKNOWN
    sub_queue:    SubQueue = SubQueue.UNKNOWN
    channel:      str      = "portal"
    attachments:  List[str]       = field(default_factory=list)
    metadata:     Dict[str, Any]  = field(default_factory=dict)


@dataclass
class ExtractedEntities:
    awb_numbers:    List[str]       = field(default_factory=list)
    hub_codes:      List[str]       = field(default_factory=list)
    amounts:        List[float]     = field(default_factory=list)
    payment_cycle:  Optional[str]   = None
    invoice_number: Optional[str]   = None
    enbolt_id:      Optional[str]   = None
    cn_number:      Optional[str]   = None
    date_range:     Optional[tuple] = None   # always 3-month window
    load_duration:  Optional[str]   = None
    missing_fields: List[str]       = field(default_factory=list)
    raw:            Dict[str, Any]  = field(default_factory=dict)


@dataclass
class QueryResult:
    query_name:    str
    success:       bool
    data:          Dict[str, Any] = field(default_factory=dict)
    error:         Optional[str]  = None
    executed_at:   datetime       = field(default_factory=datetime.utcnow)
    rows_returned: int            = 0
    attempts:      int            = 1   # tracks retry count


@dataclass
class DecisionOutput:
    scenario_key:       ScenarioKey
    action:             str              # "respond" | "escalate" | "needs_info"
    template_key:       str
    template_variables: Dict[str, Any]         = field(default_factory=dict)
    confidence:         float                  = 10.0  # out of 10
    escalation_reason:  Optional[EscalationReason] = None
    escalation_queue:   Optional[str]          = None
    decision_trace:     List[str]              = field(default_factory=list)
    queries_executed:   List[str]              = field(default_factory=list)


@dataclass
class AgentResponse:
    ticket_id:         str
    partner_id:        str
    queue:             Queue
    sub_queue:         SubQueue
    status:            ResolutionStatus
    scenario_key:      Optional[ScenarioKey]       = None
    response_text:     Optional[str]               = None
    is_draft:          bool                        = False
    escalation_reason: Optional[EscalationReason]  = None
    escalation_queue:  Optional[str]               = None
    decision_trace:    List[str]                   = field(default_factory=list)
    queries_executed:  List[str]                   = field(default_factory=list)
    confidence:        float                       = 0.0   # out of 10
    processed_at:      datetime                    = field(default_factory=datetime.utcnow)
