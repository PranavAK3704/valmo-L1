"""
VALMO L1 Agent — Metabase Query Engine (v5)

Card IDs now wired from the actual Metabase URLs shared:
  177019 → valmo-lost-data-2k24         (loss attribution / hardstop)
  177020 → single-awb-tracking          (single AWB scan history)
  177021 → bulk-awb-tracking            (bulk AWB scan history)
  178175 → shortage                     (shortage data)
  178546 → lm-fe-loss-marked-awbs       (FE loss marked AWBs)
  177022 → orders-planning-view-perf    (load + hub performance)
  177096 → landing-volume               (landing/manifest volume)
  181227 → lm-capacity-cuts             (capacity cuts)
  177463 → lost-awbs-reasons            (loss reasons / debit reasons)
  177461 → captain-payment-status       (payment status + amount)
  178927 → cash-handover                (COD transaction history)
  179010 → valmo-lmdc-cod-pendency      (COD pendency)

URL parameter mapping (from the actual question URLs):
  177019: date_grain=day, filter_date=lost
  177020: interval=90, awb=<single AWB>
  177021: interval=90, awb=<comma-separated AWBs>
  177096: time_grain=day

All other cards: template-tag parameters read from /api/card/{id} on first call,
then cached so we know exactly what parameter names to send.

Auth: service account username+password
Retry: 3 attempts, 5s/15s/30s backoff, 200s timeout
"""

import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.models import QueryResult

logger = logging.getLogger(__name__)

MAX_RETRIES      = 3
RETRY_BACKOFF    = [5, 15, 30]
QUERY_TIMEOUT_S  = 200


# ─────────────────────────────────────────────
# CARD REGISTRY — wired from your Metabase URLs
# ─────────────────────────────────────────────

# Maps our internal query name → (card_id, {param_name: value_builder})
# Value builders receive the query params dict and return the value to send.
# "None" builder means we auto-detect from card metadata on first call.

CARD_REGISTRY: Dict[str, Dict] = {

    # ── LOSSES ────────────────────────────────────────────────────────────────

    "get_loss_attribution": {
        "card_id": 177019,
        "name": "valmo-lost-data-2k24",
        # actual tags: end_date, awb, attribution_changed, location, L1_Reason,
        #              start_date, reason, date_grain, leg, filter_date
        # NOTE: only awb + start_date + end_date needed; filter_date/date_grain cause 500
        "params": {
            "awb":        lambda p: ",".join(p.get("awb_list", [])) if p.get("awb_list") else None,
            "start_date": lambda p: _fmt_start(p),
            "end_date":   lambda p: _fmt_end(p),
        }
    },

    "get_shipment_scan_history_single": {
        "card_id": 177020,
        "name": "single-awb-tracking",
        # actual tags: interval, awb, consolidation_awb
        "params": {
            "interval": lambda p: "90",
            "awb":      lambda p: p.get("awb_list", [None])[0],
        }
    },

    "get_shipment_scan_history": {
        "card_id": 177021,
        "name": "bulk-awb-tracking",
        # actual tags: interval, awb, consolidation_awb
        "params": {
            "interval": lambda p: "90",
            "awb":      lambda p: ",".join(p.get("awb_list", [])) if p.get("awb_list") else None,
        }
    },

    "get_shortage_data": {
        "card_id": 178175,
        "name": "shortage",
        # actual tags: start_date, end_date, awb
        "params": {
            "awb":        lambda p: ",".join(p.get("awb_list", [])) if p.get("awb_list") else None,
            "start_date": lambda p: _fmt_start(p),
            "end_date":   lambda p: _fmt_end(p),
        }
    },

    "get_fe_loss_marked": {
        "card_id": 178546,
        "name": "lm-fe-loss-marked-awbs",
        # actual tags: fe_partner_id, start_date, end_date, fe_phone_number, awb
        "params": {
            "awb":           lambda p: ",".join(p.get("awb_list", [])) if p.get("awb_list") else None,
            "fe_partner_id": lambda p: p.get("partner_id"),
            "start_date":    lambda p: _fmt_start(p),
            "end_date":      lambda p: _fmt_end(p),
        }
    },

    # ── ORDERS & PLANNING ─────────────────────────────────────────────────────

    "get_load_manifestation_trends": {
        "card_id": 177022,
        "name": "orders-planning-view-performance",
        # actual tags: dc_code, user_pin  (no date params on this card)
        "params": {
            "dc_code":  lambda p: p.get("hub_codes", [None])[0] if p.get("hub_codes") else None,
            "user_pin": lambda p: p.get("partner_id"),
        }
    },

    "get_hub_performance_metrics": {
        "card_id": 177096,
        "name": "landing-volume",
        # actual tags: time_grain, start_date, End_date (capital E!), lmdc
        "params": {
            "time_grain": lambda p: "day",
            "lmdc":       lambda p: p.get("hub_codes", [None])[0] if p.get("hub_codes") else None,
            "start_date": lambda p: _fmt_start(p),
            "End_date":   lambda p: _fmt_end(p),
        }
    },

    "get_capacity_cuts": {
        "card_id": 181227,
        "name": "lm-capacity-cuts",
        # actual tags: start_date, end_date, dc_code, user_pin
        "params": {
            "dc_code":    lambda p: p.get("hub_codes", [None])[0] if p.get("hub_codes") else None,
            "user_pin":   lambda p: p.get("partner_id"),
            "start_date": lambda p: _fmt_start(p),
            "end_date":   lambda p: _fmt_end(p),
        }
    },

    # ── PAYMENTS & DEBITS ─────────────────────────────────────────────────────

    "get_debit_reasons": {
        "card_id": 177463,
        "name": "lost-awbs-reasons",
        # actual tags: awb, hub, cn_number
        "params": {
            "awb":       lambda p: ",".join(p.get("awb_list", [])) if p.get("awb_list") else None,
            "hub":       lambda p: p.get("hub_codes", [None])[0] if p.get("hub_codes") else None,
            "cn_number": lambda p: p.get("cn_number"),
        }
    },

    "get_payment_status": {
        "card_id": 177461,
        "name": "captain-payment-status-amount",
        # actual tags: start_date, end_date, hub_code, enbolt_id, invoice_number
        "params": {
            "hub_code":       lambda p: p.get("hub_codes", [None])[0] if p.get("hub_codes") else None,
            "enbolt_id":      lambda p: p.get("enbolt_id"),
            "invoice_number": lambda p: p.get("invoice_number"),
            "start_date":     lambda p: _fmt_start(p),
            "end_date":       lambda p: _fmt_end(p),
        }
    },

    # ── CASH HANDOVER ─────────────────────────────────────────────────────────

    "get_cod_transaction_history": {
        "card_id": 178927,
        "name": "cash-handover",
        # actual tags: dc_code, transaction_id, payment_partner, source
        "params": {
            "dc_code":        lambda p: p.get("hub_codes", [None])[0] if p.get("hub_codes") else None,
            "transaction_id": lambda p: p.get("transaction_id"),
        }
    },

    "get_cod_pendency": {
        "card_id": 179010,
        "name": "valmo-lmdc-cod-pendency",
        # actual tags: start_date, end_date, dc_code
        "params": {
            "dc_code":    lambda p: p.get("hub_codes", [None])[0] if p.get("hub_codes") else None,
            "start_date": lambda p: _fmt_start(p),
            "end_date":   lambda p: _fmt_end(p),
        }
    },

    # ── ALIASES (for backward compat with SOP engine) ─────────────────────────
    # These point to the same card but the SOP engine may call them by old name.
    "get_loss_attribution_bulk":       {"alias": "get_loss_attribution"},
    "get_captain_waiver_eligibility":  {"alias": "get_loss_attribution"},
    "get_invoice_status":              {"alias": "get_payment_status"},
    "get_shipment_count_reconciliation": {"alias": "get_shortage_data"},
}


# ─────────────────────────────────────────────
# DATE HELPERS
# ─────────────────────────────────────────────

def _fmt_start(p: Dict) -> Optional[str]:
    dr = p.get("date_range")
    if dr and dr[0]:
        return dr[0].strftime("%Y-%m-%d")
    return (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")

def _fmt_end(p: Dict) -> Optional[str]:
    dr = p.get("date_range")
    if dr and dr[1]:
        return dr[1].strftime("%Y-%m-%d")
    return datetime.utcnow().strftime("%Y-%m-%d")

def _fmt_date_range(p: Dict) -> str:
    """For filter_date param — Metabase may accept 'past90days' or a date range string."""
    return f"{_fmt_start(p)}~{_fmt_end(p)}"


# ─────────────────────────────────────────────
# SESSION MANAGER
# ─────────────────────────────────────────────

class MetabaseSession:
    """
    Supports two auth modes:
      1. Direct token (METABASE_SESSION_TOKEN) — for SSO/Google login accounts.
         Get token: Metabase → DevTools → Application → Cookies → metabase.SESSION
      2. Username + password — for service accounts with direct login.
    """
    TOKEN_TTL = 12 * 24 * 3600  # 12 days (for password auth only)

    def __init__(self, base_url: str, username: str = "", password: str = "",
                 session_token: str = ""):
        self._base          = base_url.rstrip("/")
        self._username      = username
        self._password      = password
        self._token         = session_token or None
        self._acquired_at   = time.time() if session_token else 0.0
        self._direct_token  = bool(session_token)   # True = don't re-auth
        self._card_tags:   Dict[int, List[str]] = {}

    def get_token(self) -> str:
        if self._direct_token:
            return self._token  # type: ignore
        if self._token is None or (time.time() - self._acquired_at) > self.TOKEN_TTL:
            self._authenticate()
        return self._token  # type: ignore

    def invalidate(self):
        if not self._direct_token:
            self._token = None
        else:
            logger.warning(
                "[METABASE] Session token expired. "
                "Re-login via Google, copy new metabase.SESSION cookie, update METABASE_SESSION_TOKEN in .env"
            )

    def headers(self) -> Dict[str, str]:
        return {
            "Content-Type":        "application/json",
            "X-Metabase-Session":  self.get_token(),
        }

    def _authenticate(self):
        resp = requests.post(
            f"{self._base}/api/session",
            json={"username": self._username, "password": self._password},
            timeout=30,
        )
        resp.raise_for_status()
        self._token       = resp.json()["id"]
        self._acquired_at = time.time()
        logger.info("[METABASE] Authenticated via username/password")

    def get_card_template_tags(self, base_url: str, card_id: int) -> List[str]:
        """
        Reads the card's template-tag names from /api/card/{id}.
        Cached — only called once per card per session.
        This tells us exactly which parameters the saved question accepts,
        so we don't send params it doesn't know about.
        """
        if card_id in self._card_tags:
            return self._card_tags[card_id]
        try:
            resp = requests.get(
                f"{base_url}/api/card/{card_id}",
                headers=self.headers(),
                timeout=30,
            )
            resp.raise_for_status()
            card_data = resp.json()
            # Template tags are in dataset_query.native.template-tags
            tags_raw = (
                card_data
                .get("dataset_query", {})
                .get("native", {})
                .get("template-tags", {})
            )
            tag_names = list(tags_raw.keys())
            self._card_tags[card_id] = tag_names
            logger.info(f"[METABASE] Card {card_id} template-tags: {tag_names}")
            return tag_names
        except Exception as e:
            logger.warning(f"[METABASE] Could not read template-tags for card {card_id}: {e}")
            return []


# ─────────────────────────────────────────────
# PARAMETER BUILDER
# ─────────────────────────────────────────────

def _build_params(card_def: Dict, query_params: Dict,
                  allowed_tags: List[str]) -> List[Dict]:
    """
    Builds the Metabase parameters array.
    Only includes params that:
      1. Have a non-None value from the builder
      2. Are in the card's actual template-tags (if we know them)
    """
    result = []
    param_type_map = {
        "date_grain":    "category",
        "filter_date":   "date/range",
        "interval":      "number",
        "awb":           "category",
        "partner_id":    "category",
        "hub_code":      "category",
        "billing_cycle": "category",
        "payment_cycle": "category",
        "start_date":    "date/single",
        "end_date":      "date/single",
        "time_grain":    "category",
        "cn_number":     "category",
    }

    for name, builder in card_def.get("params", {}).items():
        # Skip if card doesn't have this tag (and we know the tags)
        if allowed_tags and name not in allowed_tags:
            continue
        value = builder(query_params)
        if value is None or value == "" or value == []:
            continue
        result.append({
            "type":   param_type_map.get(name, "category"),
            "target": ["variable", ["template-tag", name]],
            "value":  str(value),
        })
    return result


# ─────────────────────────────────────────────
# RESULT NORMALISER
# ─────────────────────────────────────────────

def _normalise(raw: Dict) -> Tuple[List[Dict], int]:
    data = raw.get("data", {})
    cols = [
        c.get("display_name") or c.get("name") or f"col_{i}"
        for i, c in enumerate(data.get("cols", []))
    ]
    rows = [dict(zip(cols, row)) for row in data.get("rows", [])]
    return rows, len(rows)


# ─────────────────────────────────────────────
# METABASE QUERY ENGINE
# ─────────────────────────────────────────────

class MetabaseQueryEngine:
    """
    Production Metabase engine.
    Uses the 12 real card IDs from the Metabase question URLs.

    On startup with empty credentials → logs a warning and falls back to
    MockQueryEngine behaviour (so the rest of the pipeline doesn't crash).
    """

    def __init__(self, base_url=None, username=None, password=None, session_token=None):
        self._base  = (base_url or os.getenv("METABASE_URL", "")).rstrip("/")
        token       = session_token or os.getenv("METABASE_SESSION_TOKEN", "")
        user        = username or os.getenv("METABASE_USER", "")
        pwd         = password or os.getenv("METABASE_PASSWORD", "")

        self._ready = bool(self._base and (token or (user and pwd)))
        if not self._ready:
            logger.warning(
                "[METABASE] No credentials configured. "
                "Add METABASE_SESSION_TOKEN to .env "
                "(get it from Metabase DevTools → Cookies → metabase.SESSION). "
                "Queries will return empty results until this is set."
            )
            self._session = None
        else:
            self._session = MetabaseSession(self._base, user, pwd, session_token=token)
            auth_mode = "session token" if token else "username/password"
            logger.info(f"[METABASE] Engine ready → {self._base} (auth={auth_mode})")

    def execute(self, query_name: str, params: Dict[str, Any]) -> QueryResult:
        # Resolve alias
        card_def = CARD_REGISTRY.get(query_name, {})
        if "alias" in card_def:
            query_name = card_def["alias"]
            card_def   = CARD_REGISTRY.get(query_name, {})

        if not card_def or "card_id" not in card_def:
            return QueryResult(
                query_name=query_name, success=False,
                error=f"No card registered for query '{query_name}'"
            )

        if not self._ready:
            return QueryResult(
                query_name=query_name, success=False,
                error="Metabase credentials not configured — add to .env"
            )

        card_id = card_def["card_id"]

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = self._run_card(query_name, card_id, card_def, params)
                result.attempts = attempt
                return result

            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if code == 401:
                    logger.warning(f"[METABASE] 401 on attempt {attempt} — re-auth")
                    self._session.invalidate()
                else:
                    logger.warning(f"[METABASE] HTTP {code} attempt {attempt} for {query_name}")

                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF[attempt - 1])
                else:
                    return QueryResult(query_name=query_name, success=False,
                                       error=str(e), attempts=attempt)

            except requests.Timeout:
                logger.warning(f"[METABASE] Timeout attempt {attempt} for {query_name}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF[attempt - 1])
                else:
                    return QueryResult(query_name=query_name, success=False,
                                       error="Query timed out after 3 attempts",
                                       attempts=attempt)

            except Exception as e:
                logger.error(f"[METABASE] Error on {query_name}: {e}")
                return QueryResult(query_name=query_name, success=False,
                                   error=str(e), attempts=attempt)

        return QueryResult(query_name=query_name, success=False, error="Max retries exceeded")

    def _run_card(self, query_name: str, card_id: int,
                  card_def: Dict, params: Dict) -> QueryResult:
        # Read the card's actual template-tags so we only send valid params
        allowed_tags = self._session.get_card_template_tags(self._base, card_id)

        mb_params = _build_params(card_def, params, allowed_tags)

        url     = f"{self._base}/api/card/{card_id}/query"
        payload: Dict[str, Any] = {"ignore_cache": False}
        if mb_params:
            payload["parameters"] = mb_params

        sent_keys = [p["target"][1][1] for p in mb_params]
        logger.info(f"[METABASE] Card {card_id} ({card_def['name']}) params={sent_keys}")

        resp = requests.post(
            url, json=payload,
            headers=self._session.headers(),
            timeout=QUERY_TIMEOUT_S,
        )
        resp.raise_for_status()

        rows, count = _normalise(resp.json())
        logger.info(f"[METABASE] Card {card_id} → {count} rows")

        return QueryResult(
            query_name=query_name,
            success=True,
            data={"rows": rows, "card_id": card_id, "card_name": card_def["name"]},
            rows_returned=count,
        )

    def inspect_card(self, card_id: int) -> Dict:
        """
        Utility — call this once per card to see exactly what
        template-tags (parameter names) the saved question accepts.
        Use: engine.inspect_card(177019)
        """
        if not self._ready:
            return {"error": "Not configured"}
        tags = self._session.get_card_template_tags(self._base, card_id)
        return {"card_id": card_id, "template_tags": tags}
