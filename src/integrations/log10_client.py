"""
Log10 Integration — Shipment scan history verification.

Log10 uses phone number + OTP login (no password).
Session is persisted to data/.log10_session.json after first login.

Usage:
    from src.integrations.log10_client import Log10Client
    client = Log10Client()
    # First run: will prompt for OTP in terminal
    scans = await client.get_scan_history(page, awb="VL1234567890")
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LOG10_URL     = os.getenv("LOG10_URL", "https://log10.valmo.in")
SESSION_FILE  = Path(__file__).parent.parent.parent / "data" / ".log10_session.json"
PHONE_NUMBER  = os.getenv("LOG10_PHONE", "")


class Log10Client:
    """Playwright-based Log10 client with phone+OTP login."""

    def __init__(self):
        self._session: dict = self._load_session()

    # ── Session persistence ────────────────────────────────────────

    def _load_session(self) -> dict:
        try:
            return json.loads(SESSION_FILE.read_text())
        except Exception:
            return {}

    def _save_session(self, cookies: list, storage: dict = None):
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"cookies": cookies}
        if storage:
            payload["storage"] = storage
        SESSION_FILE.write_text(json.dumps(payload))
        self._session = payload
        logger.info("[Log10] Session saved")

    async def _restore_session(self, ctx) -> bool:
        """Restore cookies into browser context. Returns True if session was found."""
        if not self._session.get("cookies"):
            return False
        try:
            await ctx.add_cookies(self._session["cookies"])
            return True
        except Exception as e:
            logger.warning(f"[Log10] Could not restore session: {e}")
            return False

    # ── Login ──────────────────────────────────────────────────────

    async def login(self, page) -> bool:
        """
        Log in to Log10 via phone + OTP.
        OTP will be printed to console — user must type it in.
        After login, session is saved for future runs.
        """
        logger.info(f"[Log10] Navigating to {LOG10_URL}")
        await page.goto(LOG10_URL, wait_until="networkidle", timeout=30000)

        # Check if already logged in
        if await self._is_logged_in(page):
            logger.info("[Log10] Already logged in (session valid)")
            return True

        phone = PHONE_NUMBER or input("[Log10] Enter phone number: ").strip()
        if not phone:
            logger.error("[Log10] No phone number provided")
            return False

        # Find phone input and submit
        try:
            await page.fill('input[type="tel"], input[name="phone"], input[placeholder*="phone" i]', phone)
            await page.click('button[type="submit"], button:has-text("Send OTP"), button:has-text("Login")')
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.error(f"[Log10] Phone entry failed: {e}")
            return False

        # Wait for OTP input
        otp = input(f"[Log10] OTP sent to {phone}. Enter OTP: ").strip()
        if not otp:
            logger.error("[Log10] No OTP provided")
            return False

        try:
            await page.fill('input[type="text"][maxlength="6"], input[name="otp"], input[placeholder*="otp" i]', otp)
            await page.click('button[type="submit"], button:has-text("Verify"), button:has-text("Login")')
            await page.wait_for_timeout(3000)
        except Exception as e:
            logger.error(f"[Log10] OTP entry failed: {e}")
            return False

        if await self._is_logged_in(page):
            # Save session
            cookies = await page.context.cookies()
            self._save_session(cookies)
            logger.info("[Log10] Login successful, session saved")
            return True

        logger.error("[Log10] Login failed — OTP may be wrong or page structure changed")
        return False

    async def _is_logged_in(self, page) -> bool:
        """Check if current page looks like a logged-in state."""
        url = page.url
        return LOG10_URL in url and "login" not in url.lower() and "otp" not in url.lower()

    # ── Scan history ───────────────────────────────────────────────

    async def get_scan_history(self, page, awb: str) -> dict:
        """
        Search for a shipment AWB in Log10 and return scan events.

        Returns:
            {
                "awb": str,
                "found": bool,
                "scans": [{"event": str, "timestamp": str, "location": str, ...}],
                "lost_marked": bool,
                "last_scan_location": str,
            }
        """
        if not await self._is_logged_in(page):
            ok = await self.login(page)
            if not ok:
                return {"awb": awb, "found": False, "error": "Login failed", "scans": []}

        logger.info(f"[Log10] Searching AWB: {awb}")

        # Navigate to search — try common URL patterns
        search_url = f"{LOG10_URL}/shipment/{awb}"
        try:
            await page.goto(search_url, wait_until="networkidle", timeout=20000)
        except Exception:
            pass

        # Try search box if direct URL didn't work
        try:
            search_box = page.locator('input[placeholder*="AWB" i], input[placeholder*="track" i], input[placeholder*="shipment" i]').first
            if await search_box.count() > 0:
                await search_box.fill(awb)
                await search_box.press("Enter")
                await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning(f"[Log10] Search box error: {e}")

        # Extract scan data from page
        return await self._extract_scan_data(page, awb)

    async def _extract_scan_data(self, page, awb: str) -> dict:
        """Extract scan events from the current page."""
        try:
            data = await page.evaluate("""
                () => {
                    // Try to find scan table rows
                    const rows = Array.from(document.querySelectorAll('table tr, .scan-row, .timeline-item'));
                    return rows.map(r => r.innerText.trim()).filter(t => t.length > 5);
                }
            """)

            if not data:
                return {"awb": awb, "found": False, "scans": [], "lost_marked": False, "last_scan_location": ""}

            scans = []
            lost_marked = False
            for row_text in data:
                lower = row_text.lower()
                if "lost" in lower or "rto" in lower or "undelivered" in lower:
                    lost_marked = True
                scans.append({"raw": row_text})

            return {
                "awb": awb,
                "found": True,
                "scans": scans,
                "lost_marked": lost_marked,
                "last_scan_location": data[-1] if data else "",
                "total_events": len(scans),
            }

        except Exception as e:
            logger.error(f"[Log10] Data extraction failed: {e}")
            return {"awb": awb, "found": False, "error": str(e), "scans": []}

    # ── Convenience: check hardstop eligibility ────────────────────

    async def verify_hardstop_awbs(self, page, awbs: list) -> dict:
        """
        Check multiple AWBs for hardstop verification.
        Returns {awb: scan_result} for each AWB.
        Used by agent brain when processing W-LD / hardstop tickets.
        """
        results = {}
        for awb in awbs:
            results[awb] = await self.get_scan_history(page, awb)
        return results


# Singleton
_client: Optional[Log10Client] = None

def get_log10_client() -> Log10Client:
    global _client
    if _client is None:
        _client = Log10Client()
    return _client
