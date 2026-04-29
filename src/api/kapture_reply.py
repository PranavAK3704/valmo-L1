"""
Sends an email reply to a captain via Kapture CRM.

Uses a Playwright browser session (authenticated) to call the
/api/version3/ticket/send-email endpoint with multipart/form-data.

Usage:
    from src.api.kapture_reply import send_reply
    ok, msg = await send_reply(page, task_id, ticket_id, body_text)
"""
import logging
import os

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("KAPTURE_URL", "https://valmostagging.kapturecrm.com")


async def get_email_screen(page, task_id: str, ticket_id: str) -> dict:
    """Returns the pre-filled compose screen data (to, from, subject, body)."""
    result = await page.evaluate(f"""
        async () => {{
            const r = await fetch("/api/version3/ticket/get-send-email-screen", {{
                method: "POST",
                headers: {{"Content-Type": "application/x-www-form-urlencoded"}},
                body: "id={task_id}&ticket_id={ticket_id}&screen_type=reply&ignore_escape=yes"
            }});
            return r.json();
        }}
    """)
    return result.get("response") or {}


async def send_reply(
    page,
    task_id: str,
    ticket_id: str,
    body_text: str,
    subject: str = "",
    dry_run: bool = False,
) -> tuple[bool, str]:
    """
    Sends an email reply to the captain on a ticket.

    Args:
        page:       Authenticated Playwright page.
        task_id:    Kapture task ID (the 'id' field, not ticketId).
        ticket_id:  Kapture ticket ID.
        body_text:  Plain-text reply body (will be wrapped in <p> tags).
        subject:    Email subject. If empty, fetched from compose screen.
        dry_run:    If True, logs what would be sent but does NOT actually send.

    Returns:
        (success: bool, message: str)
    """
    # 1. Get the pre-filled compose data
    screen = await get_email_screen(page, task_id, ticket_id)
    from_addr = screen.get("from_address", "")
    to_addr   = screen.get("to", "")
    if not subject:
        subject = screen.get("subject", f"Re: Ticket #{ticket_id}")

    if not from_addr:
        return False, f"No email compose screen for ticket {ticket_id} — may not be an email channel."
    if not to_addr:
        logger.warning(f"[KaptureReply] No 'to' address for ticket {ticket_id}. "
                       "Reply will still be sent — Kapture uses the last sender.")

    # 2. Format body as HTML
    html_body = "".join(f"<p>{line}</p>" for line in body_text.strip().split("\n") if line.strip())
    if not html_body:
        html_body = f"<p>{body_text}</p>"

    logger.info(f"[KaptureReply] Sending reply to ticket {ticket_id} "
                f"from={from_addr} to={to_addr} subject='{subject}' "
                f"body_len={len(html_body)} dry_run={dry_run}")

    if dry_run:
        logger.info("[KaptureReply] DRY RUN — request not sent.")
        return True, "dry_run"

    # 3. POST the reply via page.evaluate (uses the authenticated browser session)
    js_from    = from_addr.replace("'", "\\'")
    js_to      = to_addr.replace("'", "\\'")
    js_subject = subject.replace("'", "\\'").replace("\n", " ")
    js_body    = html_body.replace("'", "\\'").replace("\n", " ")

    result = await page.evaluate(f"""
        async () => {{
            const formData = new FormData();
            formData.append('id',        '{task_id}');
            formData.append('ticket_id', '{ticket_id}');
            formData.append('from',      '{js_from}');
            formData.append('to',        '{js_to}');
            formData.append('body',      '{js_body}');
            formData.append('subject',   '{js_subject}');
            formData.append('cc',  '');
            formData.append('bcc', '');
            try {{
                const r = await fetch('/api/version3/ticket/send-email', {{
                    method: 'POST',
                    body: formData
                }});
                const json = await r.json();
                return {{ status: r.status, data: json }};
            }} catch(e) {{
                return {{ error: e.toString() }};
            }}
        }}
    """)

    if result.get("error"):
        logger.error(f"[KaptureReply] Fetch error: {result['error']}")
        return False, result["error"]

    status = result.get("status", 0)
    data   = result.get("data", {})

    if data.get("status") in ("success", "Success"):
        logger.info(f"[KaptureReply] ✓ Reply sent. Response: {data}")
        return True, "sent"
    else:
        reason = data.get("reason", str(data))
        logger.error(f"[KaptureReply] API failure: {reason}")
        return False, reason


async def dispose_ticket(
    page,
    task_id: str,
    ticket_id: str,
    reason: str = "Resolved by L1 AI agent",
    dry_run: bool = False,
) -> tuple[bool, str]:
    """
    Marks a Kapture ticket as resolved/disposed (status → Closed).

    Args:
        page:       Authenticated Playwright page.
        task_id:    Kapture internal task ID.
        ticket_id:  Kapture ticket ID.
        reason:     Disposition reason / closer note.
        dry_run:    If True, logs but does NOT actually close.

    Returns:
        (success: bool, message: str)
    """
    logger.info(f"[KaptureReply] Disposing ticket {ticket_id} (task={task_id}) "
                f"reason='{reason}' dry_run={dry_run}")

    if dry_run:
        return True, "dry_run — dispose not executed"

    js_reason = reason.replace("'", "\\'")

    result = await page.evaluate(f"""
        async () => {{
            const formData = new FormData();
            formData.append('id',         '{task_id}');
            formData.append('ticket_id',  '{ticket_id}');
            formData.append('status',     'C');
            formData.append('reason',     '{js_reason}');
            formData.append('type',       'close');
            try {{
                const r = await fetch('/api/version3/ticket/update-status', {{
                    method: 'POST',
                    body: formData
                }});
                const json = await r.json();
                return {{ status: r.status, data: json }};
            }} catch(e) {{
                return {{ error: e.toString() }};
            }}
        }}
    """)

    if result.get("error"):
        logger.error(f"[KaptureReply] Dispose fetch error: {result['error']}")
        return False, result["error"]

    data = result.get("data", {})
    if data.get("status") in ("success", "Success"):
        logger.info(f"[KaptureReply] ✓ Ticket {ticket_id} disposed/closed.")
        return True, "disposed"
    else:
        reason_msg = data.get("reason", str(data))
        logger.error(f"[KaptureReply] Dispose API failure: {reason_msg}")
        return False, reason_msg
