"""
Claude client — drop-in replacement for gemini_client.py.
Same interface: decide(), generate_json(), read_attachment().
"""
import base64
import json
import logging
import os
import re
import time

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5"

# Claude Sonnet 4.5 pricing (USD per 1M tokens)
PRICE_INPUT_PER_M  = 3.00
PRICE_OUTPUT_PER_M = 15.00
USD_TO_INR         = 84.0

def tokens_to_inr(input_tokens: int, output_tokens: int) -> float:
    cost_usd = (input_tokens * PRICE_INPUT_PER_M + output_tokens * PRICE_OUTPUT_PER_M) / 1_000_000
    return round(cost_usd * USD_TO_INR, 4)

SYSTEM_PROMPT = """You are a Valmo L1 support agent. Your job is to resolve tickets raised by delivery partners (captains).

You think and act exactly like a trained human L1 agent:
- You read the ticket carefully
- You check what the SOP says for this type of issue
- You look at the Metabase/Log10 query data provided
- You apply the SOP logic to reach a decision
- If you are genuinely unsure or the data is insufficient, you say so honestly

## Output Format
Always respond with ONLY a valid JSON object — no markdown, no extra text:

{
  "action": "respond" | "escalate" | "needs_info" | "stuck",
  "response_to_captain": "...",   // draft reply to captain (for action=respond or needs_info)
  "escalation_queue": "...",      // e.g. L2_LOSSES, L2_PAYMENTS, L2_OPERATIONS (for action=escalate)
  "escalation_reason": "...",     // why escalating (for action=escalate)
  "stuck_question": "...",        // your specific question for the trainer (for action=stuck)
  "missing_fields": ["..."],      // what info to request from captain (for action=needs_info)
  "confidence": 0-10,             // how confident you are (>=7 = auto-send, <7 = needs review)
  "scenario_identified": "...",   // which SOP scenario this maps to
  "reasoning": "..."              // brief explanation of your decision
}

## Rules
- NEVER make up data. If query results are empty or missing, say so.
- NEVER fill in amounts, dates, or AWBs that aren't in the provided data.
- If the SOP says escalate to L2 or L3, always escalate — do not try to resolve it yourself.
- If you don't have enough data to decide, use action=stuck and ask a specific question.
- Confidence < 7 means the response goes to trainer for review before sending.
- Write responses in a professional but friendly tone — same as a human support agent.
- VAGUE TICKETS: If the captain uses undefined terms like "suspicious shipment", "some issue", "problem with parcel" without explaining WHAT the suspicion or problem actually is — do NOT guess a scenario. Use action=needs_info and ask specifically what the suspicion/issue is.
- READ ALL SCENARIOS in the SOP, not just the first one that matches the keywords. A ticket about "not receiving evidence mail" maps to Scenario 1 (mails not sent to partner = L1→L3 escalation), NOT Scenario 5 (wrong email ID shared). Read carefully before deciding.
- If ANY scenario in the SOP says "direct L1 to L3 escalation", use action=escalate with escalation_queue=L3.
- CRITICAL — "delivered" in ALL loss/hardstop scenarios means delivered to the END CUSTOMER (last-mile: the FE/driver physically handed the package to the customer). It does NOT mean delivered to the hub.
- If the ticket mentions proof/attachments are shared (CCTV, photos, weight slips, etc.), note this in your reasoning and factor it into the decision.
"""


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    return json.loads(text)


class ClaudeClient:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in environment")
        self._client = anthropic.Anthropic(api_key=api_key)
        logger.info(f"[Claude] Initialized with model={MODEL}")

    def decide(self, ticket_context: str, retries: int = 3) -> dict:
        """
        Send ticket context to Claude and get a structured decision back.
        Returns parsed dict with action, response, confidence, etc.
        """
        for attempt in range(retries):
            try:
                response = self._client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": ticket_context}],
                )
                raw = response.content[0].text.strip()
                logger.debug(f"[Claude] Raw response: {raw[:500]}")
                result = _extract_json(raw)

                # Attach token usage
                try:
                    inp = response.usage.input_tokens or 0
                    out = response.usage.output_tokens or 0
                    result["_usage"] = {
                        "input_tokens": inp,
                        "output_tokens": out,
                        "cost_inr": tokens_to_inr(inp, out),
                    }
                except Exception:
                    result["_usage"] = {"input_tokens": 0, "output_tokens": 0, "cost_inr": 0.0}
                return result

            except json.JSONDecodeError as e:
                logger.warning(f"[Claude] JSON parse failed (attempt {attempt+1}): {e}")
                if attempt == retries - 1:
                    return {
                        "action": "stuck",
                        "stuck_question": f"Model returned unparseable response: {raw[:200]}",
                        "confidence": 0,
                        "reasoning": "JSON parse error",
                        "scenario_identified": "unknown",
                        "_usage": {"input_tokens": 0, "output_tokens": 0, "cost_inr": 0.0},
                    }
            except Exception as e:
                logger.error(f"[Claude] API error (attempt {attempt+1}): {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return {
                        "action": "stuck",
                        "stuck_question": f"Claude API error: {e}",
                        "confidence": 0,
                        "reasoning": "API error",
                        "scenario_identified": "unknown",
                        "_usage": {"input_tokens": 0, "output_tokens": 0, "cost_inr": 0.0},
                    }
        return {"action": "stuck", "confidence": 0, "reasoning": "exhausted retries",
                "scenario_identified": "unknown",
                "_usage": {"input_tokens": 0, "output_tokens": 0, "cost_inr": 0.0}}

    def generate_json(self, prompt: str, system_prompt: str = "", temperature: float = 0.1,
                      expect_list: bool = False, retries: int = 2):
        """
        Generic JSON generation call — used by comprehension & matching stages.
        Returns parsed dict or list depending on expect_list.
        """
        for attempt in range(retries):
            try:
                sys = system_prompt or "Respond with valid JSON only. No markdown, no extra text."
                response = self._client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    system=sys,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
                raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
                result = json.loads(raw)

                try:
                    inp = response.usage.input_tokens or 0
                    out = response.usage.output_tokens or 0
                    usage = {"input_tokens": inp, "output_tokens": out, "cost_inr": tokens_to_inr(inp, out)}
                    if isinstance(result, dict):
                        result["_usage"] = usage
                    else:
                        result = {"_list": result, "_usage": usage}
                except Exception:
                    pass
                return result
            except Exception as e:
                logger.warning(f"[Claude.generate_json] attempt {attempt+1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(1)
        return [] if expect_list else {}

    def read_attachment(self, url: str, filename: str = "") -> str:
        """
        Download a PDF/image from an S3 URL and extract text using Claude Vision.
        Returns extracted text or empty string on failure.
        """
        import urllib.request
        import tempfile
        import pathlib
        import mimetypes

        ext = pathlib.Path(filename or url.split("?")[0]).suffix.lower()
        SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        SUPPORTED_DOCS   = {".pdf"}

        if ext not in SUPPORTED_IMAGES | SUPPORTED_DOCS:
            return f"[Attachment type {ext} not supported for auto-reading]"

        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = tmp.name
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                file_bytes = resp.read()
            with open(tmp_path, "wb") as f:
                f.write(file_bytes)

            if ext in SUPPORTED_IMAGES:
                media_type_map = {
                    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp",
                }
                media_type = media_type_map.get(ext, "image/jpeg")
                b64 = base64.standard_b64encode(file_bytes).decode("utf-8")
                content = [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract all text, AWB numbers (format: VL followed by digits), "
                            "shipment IDs, amounts, dates, and any structured data from this image. "
                            "List all AWB/tracking numbers clearly. If it is a loss statement or shortage report, "
                            "extract: DC code, date range, shipment count, total loss amount, and each AWB listed."
                        ),
                    },
                ]
            else:
                # PDF — send as base64 document
                b64 = base64.standard_b64encode(file_bytes).decode("utf-8")
                content = [
                    {
                        "type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract all text, AWB numbers (format: VL followed by digits), "
                            "shipment IDs, amounts, dates, and any structured data from this document. "
                            "List all AWB/tracking numbers clearly."
                        ),
                    },
                ]

            response = self._client.messages.create(
                model=MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": content}],
            )

            try:
                pathlib.Path(tmp_path).unlink()
            except Exception:
                pass

            return response.content[0].text.strip()[:3000]

        except Exception as e:
            logger.warning(f"[Claude.read_attachment] Failed to read {filename or url[:60]}: {e}")
            return f"[Could not read attachment: {e}]"


# Singleton
_client: ClaudeClient | None = None

def get_claude_client() -> ClaudeClient:
    global _client
    if _client is None:
        _client = ClaudeClient()
    return _client


# Alias so agent_brain.py import works with zero changes if desired
get_gemini_client = get_claude_client
