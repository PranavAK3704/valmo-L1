"""
VALMO L1 Agent — Kapture Direct API Client

Uses the same API calls the Kapture browser makes (discovered via network tab).
No admin access needed — uses session cookies from bot login.

BASE URL: https://valmostagging.kapturecrm.com

KEY ENDPOINTS (all confirmed from network tab):
  GET  /nui/get-ticket-detail                          → basic ticket info
  GET  /nui/get-ticket-detail?data_type=additional_info&id=<task_id>&...
                                                        → full field values + email thread
  GET  /nui/get-ticket-detail?id=<task_id>&data_type=history&...
                                                        → action log + disposal record
  GET  /nui/tickets/assigned_to_me/...                 → ticket list page (HTML)

FIELD ID MAP (confirmed from additional_info fieldConfig):
  21975 = Sub Type        (Losses & Debits, Payments, etc.)
  26772 = Sub Sub Type    (Wrong loss is marked on me, etc.)
  21867 = Hub Code        (in Ticket Info object 3478)
  26926 = Please Describe Issue in Detail  ← TICKET BODY
  21871 = Subject Line
  37499 = Hub Code        (in Case Details object 5580)
  37500 = AWBs            (file attachment)
  37508 = Payment Cycle Start Date
  37524 = Payment Cycle End Date
  37509 = Enbolt ID
  37510 = Credit Note Number
  37501 = Previous Ticket Raised (Yes/No)

DISPOSAL TYPE CODES (confirmed from history):
  ETL = Escalated to L2
  US  = Unattended
  RES = Replied
  (need to confirm resolved code from a resolved ticket history)
"""

import logging
import re
import os
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

FIELD_SUB_TYPE     = "21975"
FIELD_SUB_SUB_TYPE = "26772"
FIELD_HUB_CODE     = "21867"
FIELD_BODY         = "26926"
FIELD_SUBJECT      = "21871"
FIELD_HUB_CODE_2   = "37499"
FIELD_AWBS         = "37500"
FIELD_PAY_START    = "37508"
FIELD_PAY_END      = "37524"
FIELD_PREV_TICKET  = "37501"

DISPOSITION_CODES = {
    "ETL": "Escalated to L2",
    "R":   "Resolved",
    "CL":  "Closed",
    "AUI": "Awaiting User Input",
    "RCA": "Awaiting RCA",
    "US":  "Unattended",
    "RES": "Replied",
}


class KaptureAPIClient:
    """
    Calls Kapture's internal API using session cookies from the bot's login.
    The browser agent logs in first, then passes its cookies here.
    This handles all READ operations — the browser agent handles WRITE (reply + dispose).
    """

    def __init__(self, base_url: str, session: Optional[requests.Session] = None):
        self._base = base_url.rstrip("/")
        self._s    = session or requests.Session()
        self._s.headers.update({
            "Accept":           "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer":          self._base,
        })

    def set_cookies_from_playwright(self, cookies: List[Dict]):
        """
        After Playwright logs in, call this to copy browser cookies to requests session.
        cookies = await page.context.cookies()
        """
        for c in cookies:
            self._s.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
        logger.info(f"[KAPTURE API] Loaded {len(cookies)} cookies from browser session")

    # ─────────────────────────────────────────────
    # TICKET LIST
    # ─────────────────────────────────────────────

    def get_assigned_ticket_ids(self) -> List[Dict]:
        """
        Reads the assigned_to_me ticket queue.
        Returns list of {task_id, ticket_id, subject, created_date}
        """
        # The list page is HTML — we read ticket IDs from the URL pattern in links
        # URL pattern: /nui/tickets/assigned_to_me/5/-1/0/detail/<task_id>/<ticket_id>
        url = f"{self._base}/nui/tickets/assigned_to_me"
        resp = self._s.get(url, timeout=30)
        resp.raise_for_status()

        tickets = []
        # Extract ticket IDs from href patterns in the HTML
        pattern = r'/detail/(\d+)/(\d+)'
        for m in re.finditer(pattern, resp.text):
            task_id, ticket_id = m.group(1), m.group(2)
            entry = {"task_id": task_id, "ticket_id": ticket_id}
            if entry not in tickets:
                tickets.append(entry)

        logger.info(f"[KAPTURE API] Found {len(tickets)} tickets in queue")
        return tickets

    # ─────────────────────────────────────────────
    # TICKET DETAIL
    # ─────────────────────────────────────────────

    def get_ticket_fields(self, task_id: str, ticket_id: str,
                          last_con_id: str = "0",
                          last_con_type: str = "E",
                          cdate: str = "") -> Dict:
        """
        Calls get-ticket-detail?data_type=additional_info
        Returns parsed ticket fields: sub_type, sub_sub_type, hub_code, body, AWBs, etc.

        URL pattern confirmed:
        /nui/get-ticket-detail?data_type=additional_info
            &id=<task_id>&<ticket_id>&last_con_type=E
            &cdate=<created_date>
        """
        params = {
            "data_type":      "additional_info",
            "id":             task_id,
            ticket_id:        "",           # ticket_id appears as a param key
            "last_con_type":  last_con_type,
            "cdate":          cdate,
        }
        # The actual URL from network tab uses ticket_id as second param
        url = (
            f"{self._base}/nui/get-ticket-detail"
            f"?data_type=additional_info&id={task_id}"
            f"&{ticket_id}&last_con_type={last_con_type}&cdate={cdate}"
        )
        resp = self._s.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "Success":
            logger.warning(f"[KAPTURE API] get_ticket_fields failed: {data.get('reason')}")
            return {}

        return self._parse_fields(data["response"])

    def _parse_fields(self, response: Dict) -> Dict:
        """Extracts structured fields from additional_info response."""
        result = {}
        existing = response.get("existing", {})

        # Find field values across all objects
        all_fields = {}
        for obj_id, obj_data in existing.items():
            for field_id, value in obj_data.get("fields", {}).items():
                all_fields[str(field_id)] = value

        result["sub_type"]     = all_fields.get(FIELD_SUB_TYPE, "")
        result["sub_sub_type"] = all_fields.get(FIELD_SUB_SUB_TYPE, "")
        result["hub_code"]     = (all_fields.get(FIELD_HUB_CODE, "") or
                                  all_fields.get(FIELD_HUB_CODE_2, "")).strip()
        result["body_html"]    = all_fields.get(FIELD_BODY, "")
        result["body"]         = _strip_html(result["body_html"])
        result["subject"]      = all_fields.get(FIELD_SUBJECT, "").strip()
        result["awb_file_url"] = all_fields.get(FIELD_AWBS, "")
        result["pay_start"]    = all_fields.get(FIELD_PAY_START, "")
        result["pay_end"]      = all_fields.get(FIELD_PAY_END, "")
        result["prev_ticket"]  = all_fields.get(FIELD_PREV_TICKET, "No")

        # Extract AWBs from body text (VL-prefix pattern)
        result["awb_list"] = _extract_awbs(result["body"])

        # Parse email thread
        emails = response.get("emails", [])
        result["emails"]         = emails
        result["captain_emails"] = [e for e in emails if e.get("conversationType") == "R"]
        result["agent_emails"]   = [e for e in emails if e.get("conversationType") == "S"]

        # First captain email body = the original complaint
        if result["captain_emails"]:
            result["original_complaint"] = _strip_html(
                result["captain_emails"][0].get("body", "")
            )
        elif result["body"]:
            result["original_complaint"] = result["body"]
        else:
            result["original_complaint"] = ""

        logger.info(
            f"[KAPTURE API] Parsed: sub_type='{result['sub_type']}' "
            f"sub_sub_type='{result['sub_sub_type']}' "
            f"hub='{result['hub_code']}' "
            f"awbs={result['awb_list']}"
        )
        return result

    # ─────────────────────────────────────────────
    # TICKET HISTORY
    # ─────────────────────────────────────────────

    def get_ticket_history(self, task_id: str, cdate: str = "") -> Dict:
        """
        Calls get-ticket-detail?data_type=history
        Returns disposal info: disposition_type, dispose_remarks, AWBs from remarks, assigned_to.

        URL pattern confirmed:
        /nui/get-ticket-detail?id=<task_id>&data_type=history
            &cdate=<created_date>&fetch_action_name=yes
        """
        url = (
            f"{self._base}/nui/get-ticket-detail"
            f"?id={task_id}&data_type=history"
            f"&cdate={cdate}&fetch_action_name=yes"
        )
        resp = self._s.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "Success":
            return {}

        return self._parse_history(data["response"])

    def _parse_history(self, response: Dict) -> Dict:
        """Extracts key facts from history response."""
        history = response.get("history", [])
        result = {
            "disposition_type":     response.get("dispositionType", ""),
            "disposition_label":    DISPOSITION_CODES.get(
                                        response.get("dispositionType", ""), "Unknown"),
            "last_disposed_time":   response.get("lastDisposedTime", ""),
            "is_reopened":          response.get("isReopned", False),
            "dispose_remarks":      "",
            "dispose_awbs":         [],
            "assigned_to_emp_id":   None,
            "assigned_to_name":     "",
            "l1_agent_name":        "",
            "l2_agent_name":        "",
            "created_date":         "",
        }

        for event in history:
            action = event.get("action", "")
            remark = event.get("remark", "")
            emp_id = event.get("empId", 0)

            if action == "CREATED":
                result["created_date"] = event.get("createDate", "")

            elif action == "DISPOSED":
                # Extract content between <dispose>...</dispose> tags
                m = re.search(r'<dispose>(.*?)<\/dispose>', remark, re.DOTALL)
                if m:
                    result["dispose_remarks"] = m.group(1).strip()
                    result["dispose_awbs"]    = _extract_awbs(result["dispose_remarks"])
                else:
                    result["dispose_remarks"] = _strip_html(remark)
                result["l1_agent_name"] = _extract_agent_name(remark)

            elif action == "MANUAL ASSIGNED" and event.get("substatus") == "ETL":
                # Escalated to L2 — the name after "assigned to" is the L2 agent
                m = re.search(r'assigned to ([^\t]+)\t', remark)
                if m:
                    result["l2_agent_name"] = m.group(1).strip()

            elif action == "EMPLOYEE REPLIED":
                m = re.search(r'^([^\t]+)\t replied', remark)
                if m:
                    result["l1_agent_name"] = m.group(1).strip()

        return result

    # ─────────────────────────────────────────────
    # COMBINED: FULL TICKET READ
    # ─────────────────────────────────────────────

    def read_full_ticket(self, task_id: str, ticket_id: str,
                         cdate: str = "") -> Dict:
        """
        Reads everything about a ticket in two API calls.
        Returns a unified dict ready to feed into the SOP engine.
        """
        fields  = self.get_ticket_fields(task_id, ticket_id, cdate=cdate)
        history = self.get_ticket_history(task_id, cdate=cdate)

        return {
            "task_id":           task_id,
            "ticket_id":         ticket_id,
            "sub_type":          fields.get("sub_type", ""),
            "sub_sub_type":      fields.get("sub_sub_type", ""),
            "hub_code":          fields.get("hub_code", ""),
            "subject":           fields.get("subject", ""),
            "body":              fields.get("body", ""),
            "original_complaint": fields.get("original_complaint", ""),
            "awb_list":          fields.get("awb_list", []) or history.get("dispose_awbs", []),
            "awb_file_url":      fields.get("awb_file_url", ""),
            "pay_start":         fields.get("pay_start", ""),
            "pay_end":           fields.get("pay_end", ""),
            "agent_emails":      fields.get("agent_emails", []),
            "captain_emails":    fields.get("captain_emails", []),
            # History fields
            "disposition_type":  history.get("disposition_type", ""),
            "disposition_label": history.get("disposition_label", ""),
            "dispose_remarks":   history.get("dispose_remarks", ""),
            "l1_agent_name":     history.get("l1_agent_name", ""),
            "l2_agent_name":     history.get("l2_agent_name", ""),
            "created_date":      history.get("created_date", ""),
            "last_disposed":     history.get("last_disposed_time", ""),
            "is_reopened":       history.get("is_reopened", False),
        }


# ─────────────────────────────────────────────
# TRAINING DATA EXTRACTOR
# ─────────────────────────────────────────────

class KaptureTrainingExtractor:
    """
    Pulls historical resolved tickets from Kapture API
    and converts them to training records for the SOP engine.
    
    Each record: {
        ticket_id, sub_type, sub_sub_type, hub_code, body,
        awb_list, dispose_remarks, disposition_label,
        l1_agent_reply (the actual email sent),
        was_escalated, was_resolved
    }
    """

    def __init__(self, api_client: KaptureAPIClient):
        self._api = api_client

    def extract_record(self, task_id: str, ticket_id: str,
                       cdate: str = "") -> Optional[Dict]:
        try:
            full = self._api.read_full_ticket(task_id, ticket_id, cdate)

            # Get the first agent email as the L1 reply
            l1_reply = ""
            if full["agent_emails"]:
                l1_reply = _strip_html(full["agent_emails"][0].get("body", ""))

            disp = full["disposition_label"]
            return {
                "ticket_id":        full["ticket_id"],
                "sub_type":         full["sub_type"],
                "sub_sub_type":     full["sub_sub_type"],
                "hub_code":         full["hub_code"],
                "body":             full["body"],
                "awb_list":         full["awb_list"],
                "dispose_remarks":  full["dispose_remarks"],
                "disposition":      disp,
                "l1_agent_reply":   l1_reply,
                "was_escalated":    "l2" in disp.lower() or disp == "ETL",
                "was_resolved":     disp in ("Resolved", "R", "CL"),
                "was_awaiting":     "awaiting" in disp.lower() or "AUI" in disp,
                "created_date":     full["created_date"],
            }
        except Exception as e:
            logger.error(f"[EXTRACTOR] Failed on ticket {ticket_id}: {e}")
            return None


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _strip_html(html: str) -> str:
    if not html:
        return ""
    try:
        return BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()
    except Exception:
        return re.sub(r'<[^>]+>', ' ', html).strip()

def _extract_awbs(text: str) -> List[str]:
    if not text:
        return []
    awbs = re.findall(r'VL[R0]?\d{11,13}', text, re.IGNORECASE)
    return list(dict.fromkeys([a.upper() for a in awbs]))

def _extract_agent_name(remark: str) -> str:
    m = re.search(r'Task disposed by ([^\t]+)\t', remark)
    if m:
        return m.group(1).strip()
    m = re.search(r'([A-Z][a-z]+ [A-Z][a-z]+)\s+replied', remark)
    if m:
        return m.group(1).strip()
    return ""
