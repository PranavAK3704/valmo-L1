"""
VALMO L1 Agent — Entity Extraction (v4)

Changes from v3:
  - Kapture fields: reads sub_type (queue) + sub_sub_type (sub-queue) from webform
  - Added Sub Sub Type values from the actual Kapture webform dropdown
  - AWB extraction: VL-prefix order numbers extracted from free text
  - Date range: always 3 months constant (start = today-90d, end = today)
"""

import re
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from src.models import IncomingTicket, ExtractedEntities, Queue, SubQueue

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# QUEUE MAP  (Kapture: Sub Type field)
# ─────────────────────────────────────────────

_QUEUE_MAP: Dict[str, Queue] = {
    "losses & debits":    Queue.LOSSES_AND_DEBITS,
    "losses and debits":  Queue.LOSSES_AND_DEBITS,
    "orders & planning":  Queue.ORDERS_AND_PLANNING,
    "orders and planning": Queue.ORDERS_AND_PLANNING,
    "payments":           Queue.PAYMENTS,
    "cash handover":      Queue.CASH_HANDOVER,
}


# ─────────────────────────────────────────────
# SUB-QUEUE MAP  (Kapture: Sub Sub Type field)
# These are the actual dropdown values from the captain self-serve portal.
# ─────────────────────────────────────────────

_SUBQUEUE_MAP: Dict[str, SubQueue] = {
    # Losses & Debits — exact webform values
    "shortage loss":                                SubQueue.SHORTAGE_LOSS,
    "wrong loss is marked on me":                   SubQueue.HARDSTOP_LOSS,
    "hardstop loss":                                SubQueue.HARDSTOP_LOSS,
    "i received hardstop alert email":              SubQueue.HARDSTOP_ALERT_EMAIL,
    "hardstop pre-alert email":                     SubQueue.HARDSTOP_ALERT_EMAIL,
    "i received hardstop pre-alert email":          SubQueue.HARDSTOP_ALERT_EMAIL,

    # Orders & Planning
    "forward leg - drop in load volume":            SubQueue.DROP_IN_LOAD_VOLUME,
    "forward leg – drop in load volume":            SubQueue.DROP_IN_LOAD_VOLUME,
    "drop in load volume":                          SubQueue.DROP_IN_LOAD_VOLUME,
    "forward leg - promised load not met":          SubQueue.PROMISED_LOAD_NOT_MET,
    "forward leg – promised load not met":          SubQueue.PROMISED_LOAD_NOT_MET,
    "promised load not met":                        SubQueue.PROMISED_LOAD_NOT_MET,
    "forward leg - fluctuating load volume":        SubQueue.FLUCTUATING_LOAD_VOLUME,
    "forward leg – fluctuating load volume":        SubQueue.FLUCTUATING_LOAD_VOLUME,
    "fluctuating load volume":                      SubQueue.FLUCTUATING_LOAD_VOLUME,

    # Payments
    "i have not received payment":                  SubQueue.PAYMENT_NOT_RECEIVED,
    "payment not received":                         SubQueue.PAYMENT_NOT_RECEIVED,
    "i have not received invoice for e-signing":    SubQueue.INVOICE_NOT_RECEIVED,
    "invoice not received":                         SubQueue.INVOICE_NOT_RECEIVED,
    "there is shipment count mismatch in my invoice": SubQueue.SHIPMENT_COUNT_MISMATCH,
    "shipment count mismatch":                      SubQueue.SHIPMENT_COUNT_MISMATCH,
    "wrong debits are marked in my invoice - clarification": SubQueue.WRONG_DEBITS_CLARIFICATION,
    "wrong debits are marked in my invoice – clarification": SubQueue.WRONG_DEBITS_CLARIFICATION,
    "wrong debits - clarification":                 SubQueue.WRONG_DEBITS_CLARIFICATION,
    "wrong debits are marked in my invoice - reversal": SubQueue.WRONG_DEBITS_REVERSAL,
    "wrong debits are marked in my invoice – reversal": SubQueue.WRONG_DEBITS_REVERSAL,
    "wrong debits - reversal":                      SubQueue.WRONG_DEBITS_REVERSAL,

    # Cash Handover
    "i have deposited the money but it is not reflecting": SubQueue.COD_NOT_REFLECTING,
    "i have deposited the money, but it is not reflecting in my cod pendency": SubQueue.COD_NOT_REFLECTING,
    "cod not reflecting":                           SubQueue.COD_NOT_REFLECTING,
    "cash deposit not reflecting":                  SubQueue.COD_NOT_REFLECTING,
}


def map_queue(raw: str) -> Queue:
    return _QUEUE_MAP.get(raw.strip().lower(), Queue.UNKNOWN)


def map_sub_queue(raw: str) -> SubQueue:
    return _SUBQUEUE_MAP.get(raw.strip().lower(), SubQueue.UNKNOWN)


# ─────────────────────────────────────────────
# MANDATORY FIELDS PER SUB-QUEUE
# ─────────────────────────────────────────────

MANDATORY_FIELDS: Dict[SubQueue, List[str]] = {
    SubQueue.SHORTAGE_LOSS:              ["awb_numbers"],
    SubQueue.HARDSTOP_LOSS:              ["awb_numbers"],
    SubQueue.HARDSTOP_ALERT_EMAIL:       ["awb_numbers"],
    SubQueue.DROP_IN_LOAD_VOLUME:        ["hub_codes"],
    SubQueue.PROMISED_LOAD_NOT_MET:      ["hub_codes"],
    SubQueue.FLUCTUATING_LOAD_VOLUME:    ["hub_codes"],
    SubQueue.PAYMENT_NOT_RECEIVED:       ["payment_cycle"],
    SubQueue.INVOICE_NOT_RECEIVED:       ["payment_cycle"],
    SubQueue.SHIPMENT_COUNT_MISMATCH:    ["payment_cycle"],
    SubQueue.WRONG_DEBITS_CLARIFICATION: ["payment_cycle", "cn_number"],
    SubQueue.WRONG_DEBITS_REVERSAL:      ["payment_cycle", "cn_number"],
    SubQueue.COD_NOT_REFLECTING:         ["hub_codes"],
}


# ─────────────────────────────────────────────
# EXTRACTION PATTERNS
# ─────────────────────────────────────────────

# VL-prefix Valmo order numbers (e.g. VL0083594017709)
# Also standard AWB patterns
VL_AWB_RE    = re.compile(r'\bVL\d{11,13}\b')
STD_AWB_RE   = re.compile(r'\b[A-Z]{2,4}\d{8,14}\b')

HUB_RE       = re.compile(r'\bHub\s*(?:Code)?\s*:?\s*([A-Z]{2,6})\b', re.I)
HUB_INLINE_RE = re.compile(r'\b([A-Z]{3,5})\s+(?:hub|Hub)\b')
AMOUNT_RE    = re.compile(r'(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d{1,2})?)', re.I)
CYCLE_RE     = re.compile(r'\b(\d{4}-W\d{1,2}|\d{4}-\d{2}|week\s+\d+|w\d{1,2}[\s/]\d{4})\b', re.I)
INVOICE_RE   = re.compile(r'\binvoice\s*(?:no\.?|number|#)?\s*:?\s*([A-Z0-9\-/]+)', re.I)
ENBOLT_RE    = re.compile(r'\benbolt\s*(?:id|#)?\s*:?\s*([A-Z0-9\-]+)', re.I)
CN_RE        = re.compile(r'\bCN\s*(?:no\.?|number|#)?\s*:?\s*([A-Z0-9\-/]+)', re.I)
LOAD_DUR_RE  = re.compile(r'\b(1|2|3)\s+(?:week|month)s?\b|\b(one|two|three)\s+(?:week|month)s?\b', re.I)

# Date range: always 3 months constant
DATE_RANGE_MONTHS = 3


class EntityExtractor:

    def extract(self, ticket: IncomingTicket) -> ExtractedEntities:
        # Combine subject + body; strip HTML tags
        text = re.sub(r'<[^>]+>', ' ', f"{ticket.subject}\n{ticket.body}")

        awbs       = self._extract_awbs(text)
        hub_codes  = self._extract_hubs(text)
        amounts    = self._extract_amounts(text)
        cycle      = self._first(CYCLE_RE, text)
        invoice_no = self._first(INVOICE_RE, text)
        enbolt_id  = self._first(ENBOLT_RE, text)
        cn_number  = self._first(CN_RE, text)
        load_dur   = self._first(LOAD_DUR_RE, text)

        # Pull from Kapture custom fields if not found in text
        meta = ticket.metadata.get("custom_fields", {}) or {}
        if not cycle:
            cycle = meta.get("payment_cycle") or meta.get("billing_cycle") \
                    or ticket.metadata.get("payment_cycle")
        if not invoice_no:
            invoice_no = meta.get("invoice_number") or ticket.metadata.get("invoice_number")
        if not enbolt_id:
            enbolt_id = meta.get("enbolt_id") or ticket.metadata.get("enbolt_id")
        if not cn_number:
            cn_number = meta.get("cn_number") or ticket.metadata.get("credit_note_number")
        if not hub_codes:
            raw_hub = meta.get("hub_code") or ticket.metadata.get("hub_code")
            if raw_hub and raw_hub.upper() != "N/A":
                hub_codes = [raw_hub.upper()]

        # AWBs from Kapture dedicated field (comma/space separated)
        kapture_awbs_raw = meta.get("awbs") or ticket.metadata.get("awbs") or ""
        if kapture_awbs_raw and kapture_awbs_raw.upper() != "N/A":
            for a in re.split(r'[\s,;]+', kapture_awbs_raw):
                a = a.strip()
                if a and a not in awbs:
                    awbs.append(a)

        # Date range: always 3 months constant
        today = datetime.utcnow().date()
        date_range = (
            datetime.combine(today - timedelta(days=90), datetime.min.time()),
            datetime.combine(today, datetime.min.time()),
        )

        entities = ExtractedEntities(
            awb_numbers=awbs,
            hub_codes=hub_codes,
            amounts=amounts,
            payment_cycle=cycle,
            invoice_number=invoice_no,
            enbolt_id=enbolt_id,
            cn_number=cn_number,
            date_range=date_range,
            load_duration=load_dur,
            raw={"text": text[:500], "meta": meta},
        )
        entities.missing_fields = self._check_mandatory(ticket.sub_queue, entities)
        return entities

    # ── helpers ──────────────────────────────────────────────────────────────

    def _extract_awbs(self, text: str) -> List[str]:
        """
        Extract AWBs from two patterns (both present in Valmo tickets):
          1. VL-prefixed order numbers  e.g. VL0083594017709
          2. Standard AWB pattern       e.g. XY123456789
        Deduplicates and preserves order.
        """
        found = []
        seen = set()
        for m in VL_AWB_RE.findall(text):
            if m not in seen:
                found.append(m)
                seen.add(m)
        for m in STD_AWB_RE.findall(text):
            if m not in seen and not m.startswith("VL"):
                found.append(m)
                seen.add(m)
        return found

    def _extract_hubs(self, text: str) -> List[str]:
        codes = set()
        for m in HUB_RE.findall(text):
            if m and m.upper() != "N/A":
                codes.add(m.upper())
        for m in HUB_INLINE_RE.findall(text):
            if m and m.upper() != "N/A":
                codes.add(m.upper())
        return list(codes)

    def _extract_amounts(self, text: str) -> List[float]:
        out = []
        for raw in AMOUNT_RE.findall(text):
            try:
                out.append(float(raw.replace(",", "")))
            except ValueError:
                pass
        return out

    def _first(self, pattern: re.Pattern, text: str) -> Optional[str]:
        m = pattern.search(text)
        if not m:
            return None
        g = m.group(1) if m.lastindex else m.group(0)
        return g.strip() if g else None

    def _check_mandatory(self, sub_queue: SubQueue,
                         e: ExtractedEntities) -> List[str]:
        required = MANDATORY_FIELDS.get(sub_queue, [])
        missing = []
        for field in required:
            val = getattr(e, field, None)
            if not val:
                missing.append(field)
        return missing
