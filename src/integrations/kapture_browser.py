"""
VALMO L1 Agent — Kapture Browser Automation (v1)

Operates Kapture like a human L1 agent using Playwright.
Based on actual HTML selectors extracted from screenshots.

WHAT IT DOES (full autonomous loop):
  1. Logs into valmostagging.kapturecrm.com
  2. Polls "Assigned To Me" queue every 60s
  3. Opens each new ticket → reads subject, body, sub_type, sub_sub_type, hub, AWBs
  4. Passes ticket to L1AgentOrchestrator → gets AgentResponse
  5. Clicks Quick Actions → Compose Email → types reply → clicks Send
  6. Clicks Dispose ticket icon → fills form:
       Select Queue      ← from AgentResponse.queue
       Assign To         ← bot account name
       Remarks           ← decision trace summary
       Disposition Type  ← Resolved / Escalated to L2 / Awaiting User Input / Awaiting RCA
  7. Clicks SUBMIT

SELECTORS (confirmed from screenshots):
  Quick Actions btn   : button[aria-label="Ticket Quick Actions"]
  Compose Email       : from Quick Actions menu → "Compose Email" option
  Reply body          : email composer content-editable area
  Send button         : button[aria-label="Send"] (Name="Send" from inspector)
  Dispose ticket icon : button.kaptour-tab-dispose-ticket  (title="Dispose ticket")
  Ticket Dispose form : form#ticket-dispose-form
  Select Queue        : first MuiSelect in dispose form
  Assign To           : second MuiSelect in dispose form
  Remarks             : textarea[placeholder="Add remark"]
  Disposition Type    : MuiSelect with "Disposition Type" label
  SUBMIT              : button[aria-label="Dispose this ticket"]

INSTALL:
  pip install playwright
  playwright install chromium
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Optional, List

from src.models import (
    IncomingTicket, AgentResponse, Queue, SubQueue,
    ResolutionStatus, CONFIDENCE_AUTO_SEND
)
from src.ingestion.entity_extractor import map_queue, map_sub_queue

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DISPOSITION TYPE MAPPING
# ─────────────────────────────────────────────

# Maps AgentResponse.status → exact string in Kapture's Disposition Type dropdown
DISPOSITION_MAP = {
    ResolutionStatus.AUTO_SENT:  "Resolved",
    ResolutionStatus.DRAFT:      "Awaiting RCA",       # low confidence → human reviews
    ResolutionStatus.ESCALATED:  "Escalated to L2",
    ResolutionStatus.NEEDS_INFO: "Awaiting User Input",
    ResolutionStatus.FAILED:     "Awaiting RCA",
}

# Maps Queue enum → exact string in Kapture's Select Queue dropdown
QUEUE_LABEL_MAP = {
    Queue.LOSSES_AND_DEBITS:   "Losses and Debits",
    Queue.ORDERS_AND_PLANNING: "Orders and Planning",
    Queue.PAYMENTS:            "Payments",
    Queue.CASH_HANDOVER:       "Cash Handover",
    Queue.UNKNOWN:             "Losses and Debits",    # safe fallback
}


# ─────────────────────────────────────────────
# TICKET READER
# ─────────────────────────────────────────────

async def read_ticket_from_page(page) -> dict:
    """
    Reads all ticket data from an open Kapture ticket detail page.
    Extracts the fields visible in the DETAILS tab.
    """
    data = {}

    # Subject from page heading
    try:
        data["subject"] = await page.locator("h2, h3, .ticket-subject, [class*='subject']").first.inner_text()
    except:
        data["subject"] = ""

    # Ticket ID from the detail panel (shown as blue link "773126131848")
    try:
        ticket_id_el = page.locator("text=Ticket ID").locator("..").locator("a, span[style*='color']")
        data["ticket_id"] = (await ticket_id_el.first.inner_text()).strip()
    except:
        # Fall back to URL
        url = page.url
        m = re.search(r'/detail/(\d+)/(\d+)', url)
        data["ticket_id"] = m.group(2) if m else ""

    # Partner name
    try:
        name_row = page.locator("text=Name").locator("..").locator("td, div").last
        data["partner_name"] = (await name_row.inner_text()).strip()
    except:
        data["partner_name"] = "Unknown"

    # Email
    try:
        email_row = page.locator("text=Email").locator("..").locator("td, div").last
        data["partner_email"] = (await email_row.inner_text()).strip()
    except:
        data["partner_email"] = ""

    # Sub Type and Sub Sub Type — shown in breadcrumb: Web Form > Captain > Losses > ...
    # Also visible in the dispose form breadcrumb: "Web Form > Captain > Losse ×"
    try:
        breadcrumb = await page.locator("[class*='breadcrumb'], [class*='folder'], [class*='path']").first.inner_text()
        parts = [p.strip() for p in re.split(r'[>→/]', breadcrumb) if p.strip()]
        # Usually: Web Form > Captain > <Queue> > <Sub-queue>
        data["sub_type"]     = parts[2] if len(parts) > 2 else ""
        data["sub_sub_type"] = parts[3] if len(parts) > 3 else ""
    except:
        data["sub_type"]     = ""
        data["sub_sub_type"] = ""

    # Ticket body — the most recent message in the conversation
    try:
        # The conversation thread: get the first (oldest) message body
        msgs = await page.locator("[class*='message-body'], [class*='email-body'], [class*='ticket-body'], [class*='description']").all()
        if msgs:
            data["body"] = (await msgs[0].inner_text()).strip()
        else:
            data["body"] = ""
    except:
        data["body"] = ""

    # Hub code — from Ticket Information section or custom fields
    try:
        hub_section = await page.locator("text=Hub").locator("..").inner_text()
        m = re.search(r'\b([A-Z]{2,5})\b', hub_section)
        data["hub_code"] = m.group(1) if m else ""
    except:
        data["hub_code"] = ""

    logger.info(f"[BROWSER] Read ticket {data.get('ticket_id')} "
                f"sub_type='{data.get('sub_type')}' "
                f"sub_sub_type='{data.get('sub_sub_type')}'")
    return data


def ticket_data_to_model(data: dict) -> IncomingTicket:
    """Converts raw page data dict → IncomingTicket model."""
    return IncomingTicket(
        ticket_id=data.get("ticket_id", "unknown"),
        partner_id=data.get("partner_email", "unknown"),
        partner_name=data.get("partner_name", "Unknown"),
        subject=data.get("subject", ""),
        body=data.get("body", ""),
        created_at=datetime.utcnow(),
        queue=map_queue(data.get("sub_type", "")),
        sub_queue=map_sub_queue(data.get("sub_sub_type", "")),
        metadata={
            "hub_code": data.get("hub_code", ""),
            "kapture_sub_type": data.get("sub_type", ""),
            "kapture_sub_sub_type": data.get("sub_sub_type", ""),
        },
    )


# ─────────────────────────────────────────────
# REPLY VIA EMAIL COMPOSER
# ─────────────────────────────────────────────

async def send_reply(page, response_text: str):
    """
    Clicks Quick Actions → Compose Email → types reply → clicks Send.
    Based on screenshot: Quick Actions opens menu with 'Compose Email' option.
    """
    # Click Quick Actions (the dark circle bottom-right, aria-label confirmed)
    qa_btn = page.locator('button[aria-label="Ticket Quick Actions"]')
    await qa_btn.wait_for(state="visible", timeout=10000)
    await qa_btn.click()
    logger.info("[BROWSER] Clicked Quick Actions")

    # Wait for menu → click "Compose Email"
    await page.locator("text=Compose Email").wait_for(state="visible", timeout=5000)
    await page.locator("text=Compose Email").click()
    logger.info("[BROWSER] Clicked Compose Email")

    # Wait for email composer to appear
    await page.locator(".MuiGrid-root", has_text="Email Composer").wait_for(
        state="visible", timeout=10000
    )

    # Type into the email body (the large empty area below the toolbar)
    # It's a contenteditable div or textarea below the formatting toolbar
    body_area = page.locator(
        "[contenteditable='true'], textarea"
    ).filter(has_not_text="Add more").last
    await body_area.click()
    await body_area.fill(response_text)
    logger.info("[BROWSER] Typed reply into email body")

    # Click Send button (Name="Send" confirmed from inspector)
    send_btn = page.locator('button[aria-label="Send"], button:has-text("Send")').last
    await send_btn.wait_for(state="visible", timeout=5000)
    await send_btn.click()
    logger.info("[BROWSER] Clicked Send")

    # Brief wait for send to complete
    await page.wait_for_timeout(2000)


# ─────────────────────────────────────────────
# DISPOSE TICKET
# ─────────────────────────────────────────────

async def dispose_ticket(page, response: AgentResponse):
    """
    Clicks Dispose ticket icon → fills the Ticket Dispose form → clicks SUBMIT.

    Form fields (confirmed from screenshots):
      Select Queue      ← queue label
      Assign To         ← bot account (pre-filled, leave as-is or set to bot name)
      Remarks           ← short decision summary
      Disposition Type  ← Resolved / Escalated to L2 / Awaiting User Input / Awaiting RCA
      SUBMIT button
    """
    # Click the Dispose ticket icon (top-right icon bar, confirmed class + title)
    dispose_icon = page.locator(
        'button.kaptour-tab-dispose-ticket, '
        'button[title="Dispose ticket"], '
        'button[data-tracking="DISPOSE_TICKET"]'
    )
    await dispose_icon.wait_for(state="visible", timeout=10000)
    await dispose_icon.click()
    logger.info("[BROWSER] Clicked Dispose ticket icon")

    # Wait for Ticket Dispose modal
    await page.locator('text="Ticket Dispose"').wait_for(state="visible", timeout=8000)
    logger.info("[BROWSER] Dispose modal opened")

    # ── Select Queue ──────────────────────────────────────────────────────────
    queue_label = QUEUE_LABEL_MAP.get(response.queue, "Losses and Debits")
    # The queue breadcrumb is already pre-filled from the ticket's folder path.
    # If the Select Queue dropdown is empty or wrong, set it.
    queue_dropdown = page.locator('[class*="MuiSelect"]').first
    current_val = await queue_dropdown.inner_text()
    if queue_label.lower() not in current_val.lower():
        await queue_dropdown.click()
        await page.locator(f'li[role="option"]:has-text("{queue_label}")').click()
        logger.info(f"[BROWSER] Set queue to: {queue_label}")

    # ── Assign To ────────────────────────────────────────────────────────────
    # Leave as-is — it'll be pre-filled with the bot's account name since
    # the bot is the logged-in user. No change needed.

    # ── Remarks ──────────────────────────────────────────────────────────────
    remarks = _build_remarks(response)
    remarks_box = page.locator('textarea[placeholder="Add remark"]')
    await remarks_box.wait_for(state="visible", timeout=5000)
    await remarks_box.fill(remarks)
    logger.info("[BROWSER] Filled remarks")

    # ── Disposition Type ─────────────────────────────────────────────────────
    disposition = DISPOSITION_MAP.get(response.status, "Awaiting RCA")

    # Find the Disposition Type select — it's below the Remarks box
    # Label text "Disposition Type" is visible above it
    disp_dropdown = page.locator(
        ':below(:text("Disposition Type"))'
    ).locator('[class*="MuiSelect"]').first
    await disp_dropdown.click()
    await page.locator(f'li[role="option"]:has-text("{disposition}")').click()
    logger.info(f"[BROWSER] Set disposition to: {disposition}")

    # ── SUBMIT ────────────────────────────────────────────────────────────────
    submit_btn = page.locator(
        'button[aria-label="Dispose this ticket"], '
        'button[title="Dispose this ticket"], '
        'button[type="submit"][form="ticket-dispose-form"]'
    )
    await submit_btn.wait_for(state="visible", timeout=5000)
    await submit_btn.click()
    logger.info(f"[BROWSER] SUBMIT clicked — ticket disposed as '{disposition}'")

    # Wait for modal to close (ticket leaves queue)
    await page.wait_for_timeout(3000)


def _build_remarks(response: AgentResponse) -> str:
    """Builds the Remarks field content — short decision summary."""
    lines = [
        f"[L1 AGENT BOT] {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
        f"Sub-queue: {response.sub_queue}",
        f"Scenario:  {response.scenario_key}",
        f"Confidence: {response.confidence:.1f}/10",
        f"Queries: {', '.join(response.queries_executed) if response.queries_executed else 'none'}",
    ]
    if response.escalation_reason:
        lines.append(f"Escalation reason: {response.escalation_reason.value}")
    if response.decision_trace:
        lines.append("Trace: " + " | ".join(response.decision_trace[:3]))
    return "\n".join(lines)[:1000]  # Kapture may have a char limit


# ─────────────────────────────────────────────
# TICKET LIST READER
# ─────────────────────────────────────────────

async def get_open_ticket_urls(page, base_url: str) -> List[str]:
    """
    Reads the "Assigned To Me" ticket list and returns URLs of open tickets.
    URL pattern confirmed: /nui/tickets/assigned_to_me/5/-1/0/detail/<group_id>/<ticket_id>
    """
    list_url = f"{base_url}/nui/tickets/assigned_to_me"
    if page.url != list_url:
        await page.goto(list_url, wait_until="networkidle", timeout=30000)

    # Wait for ticket list to load
    await page.locator("[class*='ticket-list'], [class*='ticketList'], .MuiList-root").first.wait_for(
        state="visible", timeout=15000
    )

    # Find all ticket row links — they navigate to /detail/... URLs
    ticket_links = await page.locator("a[href*='/detail/']").all()
    urls = []
    for link in ticket_links:
        href = await link.get_attribute("href")
        if href and "/detail/" in href:
            full = href if href.startswith("http") else f"{base_url}{href}"
            if full not in urls:
                urls.append(full)

    logger.info(f"[BROWSER] Found {len(urls)} open tickets in queue")
    return urls


# ─────────────────────────────────────────────
# MAIN AGENT LOOP
# ─────────────────────────────────────────────

class KaptureBrowserAgent:
    """
    Full autonomous L1 agent using browser automation.

    Requires:
      KAPTURE_URL      e.g. https://valmostagging.kapturecrm.com
      KAPTURE_EMAIL    bot account email
      KAPTURE_PASSWORD bot account password
    """

    def __init__(self, orchestrator, poll_interval=60):
        self._orchestrator    = orchestrator
        self._poll_interval   = poll_interval
        self._base_url        = os.getenv("KAPTURE_URL",
                                "https://valmostagging.kapturecrm.com").rstrip("/")
        self._email           = os.getenv("KAPTURE_EMAIL", "")
        self._password        = os.getenv("KAPTURE_PASSWORD", "")
        self._processed       = set()   # ticket IDs already handled this session
        self._browser         = None
        self._page            = None

    async def start(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            # headless=True for production server, headless=False to watch it work
            self._browser = await pw.chromium.launch(
                headless=os.getenv("HEADLESS", "true").lower() == "true"
            )
            context = await self._browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            )
            self._page = await context.new_page()
            await self._login()
            await self._run_loop()

    async def _login(self):
        logger.info(f"[BROWSER] Logging into {self._base_url}")
        await self._page.goto(f"{self._base_url}/nui/login", wait_until="networkidle")

        # Fill email
        await self._page.locator(
            'input[type="email"], input[name="email"], input[placeholder*="email" i]'
        ).first.fill(self._email)

        # Fill password
        await self._page.locator(
            'input[type="password"]'
        ).first.fill(self._password)

        # Click login/submit
        await self._page.locator(
            'button[type="submit"], button:has-text("Login"), button:has-text("Sign in")'
        ).first.click()

        # Wait for dashboard to load
        await self._page.wait_for_url(f"{self._base_url}/nui/**", timeout=30000)
        logger.info("[BROWSER] Logged in successfully")

    async def _run_loop(self):
        logger.info(f"[BROWSER] Starting poll loop every {self._poll_interval}s")
        while True:
            try:
                await self._process_queue()
            except Exception as e:
                logger.error(f"[BROWSER] Loop error: {e}")
            await asyncio.sleep(self._poll_interval)

    async def _process_queue(self):
        ticket_urls = await get_open_ticket_urls(self._page, self._base_url)

        new_tickets = [u for u in ticket_urls
                       if self._extract_ticket_id(u) not in self._processed]

        if not new_tickets:
            logger.info("[BROWSER] No new tickets")
            return

        logger.info(f"[BROWSER] Processing {len(new_tickets)} new tickets")
        for url in new_tickets:
            await self._handle_ticket(url)

    async def _handle_ticket(self, url: str):
        ticket_id = self._extract_ticket_id(url)
        logger.info(f"[BROWSER] Opening ticket {ticket_id}")

        try:
            await self._page.goto(url, wait_until="networkidle", timeout=30000)
            await self._page.wait_for_timeout(2000)  # let dynamic content load

            # Read ticket from page
            raw = await read_ticket_from_page(self._page)
            ticket = ticket_data_to_model(raw)

            # Run SOP pipeline
            response = self._orchestrator.process_ticket(ticket)
            logger.info(f"[BROWSER] Ticket {ticket_id}: "
                        f"status={response.status} confidence={response.confidence}/10")

            # Send reply (if there is one)
            if response.response_text:
                await send_reply(self._page, response.response_text)

            # Dispose the ticket
            await dispose_ticket(self._page, response)

            self._processed.add(ticket_id)
            logger.info(f"[BROWSER] ✓ Ticket {ticket_id} disposed as {response.status}")

        except Exception as e:
            logger.error(f"[BROWSER] Error on ticket {ticket_id}: {e}")
            # Don't add to processed — will retry next poll

    def _extract_ticket_id(self, url: str) -> str:
        m = re.search(r'/detail/\d+/(\d+)', url)
        return m.group(1) if m else url


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

async def run_browser_agent(orchestrator, poll_interval=60):
    agent = KaptureBrowserAgent(orchestrator, poll_interval)
    await agent.start()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from src.agent import L1AgentOrchestrator
    from src.query_engine.mock_engine import MockQueryEngine
    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    orchestrator = L1AgentOrchestrator(MockQueryEngine())
    asyncio.run(run_browser_agent(orchestrator, poll_interval=60))
