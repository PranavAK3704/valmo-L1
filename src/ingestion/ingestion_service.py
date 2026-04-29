"""
VALMO L1 Agent - Ticket Ingestion & Entity Extraction
Stage 1 of the pipeline: parse raw ticket → structured ExtractedEntities.

Uses a rules-based NLP approach (no external LLM at runtime).
A trained scikit-learn classifier is loaded for issue-type prediction.
Regex + gazetteer patterns handle entity extraction.
"""

import re
import json
import pickle
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

import numpy as np

from src.models import (
    IncomingTicket, ExtractedEntities, IssueType, TicketPriority
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# PATTERNS
# ─────────────────────────────────────────────

AWB_PATTERN         = re.compile(r'\b[A-Z]{2,4}\d{8,14}\b')
HUB_CODE_PATTERN    = re.compile(r'\b([A-Z]{3,5})-?HUB\b|\bHUB[:\s]+([A-Z]{3,5})\b', re.IGNORECASE)
AMOUNT_PATTERN      = re.compile(r'(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d{1,2})?)', re.IGNORECASE)
DATE_PATTERN        = re.compile(
    r'\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4}-\d{2}-\d{2}|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s*\d{4})\b',
    re.IGNORECASE
)
PAYMENT_CYCLE_PATTERN = re.compile(
    r'(?:cycle|billing\s+cycle|payment\s+cycle)[:\s]+([A-Za-z0-9\-\/]+)',
    re.IGNORECASE
)
CAPTAIN_ID_PATTERN  = re.compile(r'\bCAP[-_]?(\d{4,10})\b|\bcaptain\s+id[:\s]+(\d{4,10})\b', re.IGNORECASE)


# ─────────────────────────────────────────────
# KEYWORD CLASSIFIER (deterministic fallback)
# ─────────────────────────────────────────────

ISSUE_KEYWORD_MAP = {
    IssueType.SHORTAGE_LOSS_DISPUTE: [
        "shortage loss", "short delivery", "missing shipment", "shortage dispute",
        "shortage claim", "loss dispute", "lost shipment"
    ],
    IssueType.HARDSTOP_LOSS_DISPUTE: [
        "hardstop", "hard stop", "hardstop loss", "hardstop dispute"
    ],
    IssueType.PAYMENT_NOT_RECEIVED: [
        "payment not received", "payment pending", "amount not credited",
        "not received payment", "payment missing", "funds not received",
        "payment not processed"
    ],
    IssueType.INVOICE_NOT_GENERATED: [
        "invoice not generated", "no invoice", "invoice missing",
        "invoice not raised", "invoice not created"
    ],
    IssueType.SHIPMENT_COUNT_MISMATCH: [
        "shipment count", "count mismatch", "shipment mismatch",
        "wrong count", "incorrect count", "count discrepancy"
    ],
    IssueType.DEBIT_CLARIFICATION: [
        "debit clarification", "explain debit", "debit reason",
        "why was i debited", "debit query", "debit details"
    ],
    IssueType.DEBIT_REVERSAL: [
        "debit reversal", "reverse debit", "debit reversal request",
        "refund debit", "incorrect debit"
    ],
    IssueType.DROP_IN_LOAD_VOLUME: [
        "drop in load", "load volume dropped", "load drop",
        "reduced loads", "load reduction", "declining load"
    ],
    IssueType.FLUCTUATING_LOAD_VOLUME: [
        "fluctuating load", "load fluctuation", "inconsistent load",
        "load variation", "varying load volume"
    ],
    IssueType.COD_NOT_REFLECTING: [
        "cod not reflecting", "cod deposit", "cod pending",
        "cash on delivery not credited", "cod not received",
        "cod balance", "cod remittance"
    ],
}


def _keyword_classify(text: str) -> Tuple[IssueType, float]:
    """Deterministic keyword-based classifier. Returns (issue_type, confidence)."""
    text_lower = text.lower()
    scores: dict[IssueType, int] = {}
    for issue_type, keywords in ISSUE_KEYWORD_MAP.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count:
            scores[issue_type] = count
    if not scores:
        return IssueType.UNKNOWN, 0.0
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    confidence = min(scores[best] / max(total, 1), 1.0)
    return best, confidence


# ─────────────────────────────────────────────
# ML CLASSIFIER (trained model, optional)
# ─────────────────────────────────────────────

class MLClassifier:
    """
    Wraps a trained scikit-learn text classifier for issue type prediction.
    Falls back to keyword classifier if model file is absent.
    """

    MODEL_PATH = Path("models/issue_classifier.pkl")
    VECTORIZER_PATH = Path("models/issue_vectorizer.pkl")

    def __init__(self):
        self._model = None
        self._vectorizer = None
        self._load()

    def _load(self):
        if self.MODEL_PATH.exists() and self.VECTORIZER_PATH.exists():
            try:
                with open(self.MODEL_PATH, "rb") as f:
                    self._model = pickle.load(f)
                with open(self.VECTORIZER_PATH, "rb") as f:
                    self._vectorizer = pickle.load(f)
                logger.info("ML classifier loaded from disk.")
            except Exception as e:
                logger.warning(f"Could not load ML classifier: {e}. Using keyword fallback.")
        else:
            logger.info("No trained ML classifier found. Using keyword classifier.")

    def predict(self, text: str) -> Tuple[IssueType, float]:
        if self._model is None or self._vectorizer is None:
            return _keyword_classify(text)
        try:
            features = self._vectorizer.transform([text])
            label = self._model.predict(features)[0]
            proba = self._model.predict_proba(features)[0]
            confidence = float(np.max(proba))
            issue_type = IssueType(label)
            return issue_type, confidence
        except Exception as e:
            logger.warning(f"ML prediction failed: {e}. Falling back to keyword.")
            return _keyword_classify(text)


# ─────────────────────────────────────────────
# ENTITY EXTRACTOR
# ─────────────────────────────────────────────

class EntityExtractor:
    """Extracts structured entities from raw ticket text."""

    def extract_awbs(self, text: str) -> List[str]:
        return list(set(AWB_PATTERN.findall(text)))

    def extract_hub_codes(self, text: str) -> List[str]:
        matches = HUB_CODE_PATTERN.findall(text)
        codes = []
        for m in matches:
            code = m[0] or m[1]
            if code:
                codes.append(code.upper())
        return list(set(codes))

    def extract_amounts(self, text: str) -> List[float]:
        raw = AMOUNT_PATTERN.findall(text)
        amounts = []
        for r in raw:
            try:
                amounts.append(float(r.replace(",", "")))
            except ValueError:
                pass
        return amounts

    def extract_dates(self, text: str) -> Optional[tuple]:
        matches = DATE_PATTERN.findall(text)
        if not matches:
            return None
        parsed = []
        for m in matches:
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
                try:
                    parsed.append(datetime.strptime(m, fmt))
                    break
                except ValueError:
                    continue
        if len(parsed) >= 2:
            return (min(parsed), max(parsed))
        elif len(parsed) == 1:
            return (parsed[0], parsed[0])
        return None

    def extract_payment_cycle(self, text: str) -> Optional[str]:
        m = PAYMENT_CYCLE_PATTERN.search(text)
        return m.group(1) if m else None

    def extract_captain_id(self, text: str) -> Optional[str]:
        m = CAPTAIN_ID_PATTERN.search(text)
        if m:
            return m.group(1) or m.group(2)
        return None


# ─────────────────────────────────────────────
# INGESTION SERVICE
# ─────────────────────────────────────────────

class TicketIngestionService:
    """
    Orchestrates ticket ingestion:
    1. Normalize raw ticket text
    2. Classify issue type (ML → keyword fallback)
    3. Extract entities
    4. Return ExtractedEntities
    """

    def __init__(self):
        self._classifier = MLClassifier()
        self._extractor = EntityExtractor()

    def _normalize_text(self, ticket: IncomingTicket) -> str:
        """Merge subject + body; strip HTML tags; collapse whitespace."""
        combined = f"{ticket.subject}\n\n{ticket.body}"
        combined = re.sub(r'<[^>]+>', ' ', combined)      # strip HTML
        combined = re.sub(r'\s+', ' ', combined).strip()
        return combined

    def process(self, ticket: IncomingTicket) -> ExtractedEntities:
        logger.info(f"[INGESTION] Processing ticket {ticket.ticket_id}")
        text = self._normalize_text(ticket)

        issue_type, confidence = self._classifier.predict(text)
        logger.debug(f"[INGESTION] Classified as {issue_type} (conf={confidence:.2f})")

        extractor = self._extractor
        entities = ExtractedEntities(
            issue_type=issue_type,
            confidence=confidence,
            awb_numbers=extractor.extract_awbs(text),
            date_range=extractor.extract_dates(text),
            hub_codes=extractor.extract_hub_codes(text),
            amounts=extractor.extract_amounts(text),
            payment_cycle=extractor.extract_payment_cycle(text),
            captain_id=extractor.extract_captain_id(text),
            raw_entities={"normalized_text": text},
        )
        logger.info(
            f"[INGESTION] Entities: awbs={entities.awb_numbers}, "
            f"hubs={entities.hub_codes}, amounts={entities.amounts}"
        )
        return entities
