"""
Valmo L1 Agent — Dashboard server.
Run:  python run_dashboard.py
Open: http://localhost:8080
"""
import asyncio
import html as _html_mod
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
# Load .env relative to this file so it works regardless of CWD
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)
# Capture credential presence at load time (before any lazy evaluation)
_KAPTURE_READY = bool(os.getenv("KAPTURE_API_KEY") or os.getenv("KAPTURE_EMAIL") or os.getenv("EMAIL"))
if not _KAPTURE_READY and _env_path.exists():
    _raw = _env_path.read_text(errors="replace")
    _KAPTURE_READY = "KAPTURE_EMAIL=" in _raw or "KAPTURE_API_KEY=" in _raw

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from src.api.decision_store import (
    get_decisions, get_stats, approve_decision,
    reject_decision, get_conn,
)

app = FastAPI(title="Valmo L1 Agent Dashboard")

# Static files
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Mode state (in-memory; survives restarts via .env) ────────────
# Mode persistence delegates to src.api.mode (single source of truth — agent_brain
# and live_agent both read from there). The dashboard JS contract is unchanged:
# {"autonomous": bool} on the wire; canonical module stores the string form.
from src.api.mode import get_mode as _get_mode_str, set_mode as _set_mode_str

def _load_mode() -> bool:
    return _get_mode_str() == "autonomous"

def _save_mode(autonomous: bool):
    _set_mode_str("autonomous" if autonomous else "review")
    print(f"[Mode] dashboard toggle -> {'autonomous' if autonomous else 'review'}")

# ── Routes ────────────────────────────────────────────────────────

@app.get("/")
def dashboard():
    return FileResponse(str(STATIC_DIR / "dashboard.html"))

@app.get("/api/stats")
def stats():
    return get_stats()

@app.get("/api/decisions")
def decisions(filter: str = "", limit: int = 100, offset: int = 0):
    # filter can be a review_status OR an action
    conn = get_conn()
    if filter in ("pending", "approved", "rejected", "sent"):
        rows = conn.execute(
            "SELECT * FROM decisions WHERE review_status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (filter, limit, offset)
        ).fetchall()
    elif filter in ("respond", "escalate", "stuck", "needs_info"):
        rows = conn.execute(
            "SELECT * FROM decisions WHERE action=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (filter, limit, offset)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    conn.close()
    return {"decisions": [dict(r) for r in rows], "total": total}

class ReviewAction(BaseModel):
    note: str = ""
    corrected_scenario: str = ""   # optional — what reviewer thinks the scenario should have been
    corrected_action: str = ""     # optional — what reviewer thinks the action should have been

@app.get("/api/decisions/{decision_id}")
def get_decision(decision_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Decision not found")
    return dict(row)


@app.post("/api/decisions/{decision_id}/approve")
def approve(decision_id: int, body: ReviewAction):
    ok = approve_decision(decision_id, body.note)
    if not ok:
        raise HTTPException(400, "Decision not found or already reviewed")
    return {"status": "approved"}


class SendReplyRequest(BaseModel):
    dry_run: bool = True   # default to dry_run for safety


@app.post("/api/decisions/{decision_id}/send-reply")
async def send_reply_endpoint(decision_id: int, body: SendReplyRequest):
    """Send the agent's drafted reply back to Kapture via email."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Decision not found")
    d = dict(row)
    if d.get("action") != "respond":
        raise HTTPException(400, "Decision action is not 'respond'")
    if not d.get("response_draft"):
        raise HTTPException(400, "No response draft available")

    task_id   = d.get("task_id") or ""
    ticket_id = d.get("ticket_id", "")

    try:
        from playwright.async_api import async_playwright
        from scrape_tickets_v2 import login
        from src.api.kapture_reply import send_reply

        async def _do_send():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True, slow_mo=100)
                ctx     = await browser.new_context()
                page    = await ctx.new_page()
                await login(page)

                resolved_task_id = task_id

                # Fall back to live lookup if task_id wasn't stored
                if not resolved_task_id:
                    result = await page.evaluate(f"""
                        async () => {{
                            const r = await fetch('/api/version3/ticket/get-ticket-list', {{
                                method: 'POST',
                                headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                                body: 'query={ticket_id}&response_type=json&page_size=5&type=5&status=P&folder_id=-1&sort_by_column=last_conversation_time&sort_type=desc'
                            }});
                            return r.json();
                        }}
                    """)
                    for t in (result.get("response") or {}).get("tickets") or []:
                        if str(t.get("ticketId")) == str(ticket_id):
                            resolved_task_id = str(t.get("id", ""))
                            break
                    if not resolved_task_id:
                        await browser.close()
                        return False, f"Could not find task_id for ticket {ticket_id}"

                ok, msg = await send_reply(
                    page,
                    task_id   = resolved_task_id,
                    ticket_id = ticket_id,
                    body_text = d["response_draft"],
                    dry_run   = body.dry_run,
                )
                await browser.close()
                return ok, msg

        ok, msg = await _do_send()
        if ok and not body.dry_run:
            from src.api.decision_store import mark_sent
            mark_sent(decision_id)
        return {"status": "sent" if ok else "failed", "message": msg, "dry_run": body.dry_run}

    except Exception as e:
        raise HTTPException(500, f"Send failed: {e}")

def _reconstruct_thinking_steps(d: dict) -> list:
    """Build thinking steps for old decisions that predate step tracking."""
    steps = []
    awbs = json.loads(d.get("awbs") or "[]")
    queue = d.get("queue") or "Unknown"
    steps.append({"icon": "🔍", "label": "Read ticket",
                  "detail": f"Queue: {queue} | AWBs: {', '.join(awbs) if awbs else 'None'}",
                  "status": "done"})
    steps.append({"icon": "📖", "label": "Searched SOP knowledge base",
                  "detail": "Retrieved relevant SOP chunks for this ticket type",
                  "status": "done"})
    if awbs:
        steps.append({"icon": "📊", "label": "Ran Metabase queries",
                      "detail": f"Loss attribution + scan history for {len(awbs)} AWB(s)",
                      "status": "done"})
    else:
        steps.append({"icon": "📊", "label": "Metabase queries",
                      "detail": "No AWBs in ticket — data queries skipped",
                      "status": "warning"})
    if d.get("reasoning"):
        steps.append({"icon": "🤔", "label": "Gemini reasoning complete",
                      "detail": (d["reasoning"][:200] + "…") if len(d["reasoning"]) > 200 else d["reasoning"],
                      "status": "done"})
    action = d.get("action", "stuck")
    conf   = d.get("confidence", 0)
    if action == "respond":
        auto = " · AUTO-SEND" if d.get("auto_send") else " · Queued for review"
        steps.append({"icon": "✅", "label": f"Decision: RESPOND — confidence {conf}/10",
                      "detail": (d.get("scenario") or "SOP matched — draft ready") + auto,
                      "status": "done"})
    elif action == "escalate":
        steps.append({"icon": "🔺", "label": f"Decision: ESCALATE — confidence {conf}/10",
                      "detail": f"→ {d.get('escalation_queue') or 'L2'} | {(d.get('escalation_reason') or '')[:100]}",
                      "status": "done"})
    else:
        ql = queue.lower()
        if any(k in ql for k in ("ld", "loss", "hardstop", "w- ld")):
            upg = "Hey! 💡 If I had Log10 access, I could verify those scan timestamps and SOP compliance in seconds — no human needed."
        elif any(k in ql for k in ("shortage", "shipment_shortage")):
            upg = "Hey! 💡 I know the Shortage SOP. But to resolve this I need Log10 scan data to verify which node's evidence holds up. Wire me Log10 and I'll own this queue fully."
        elif any(k in ql for k in ("c_v", "m_v")):
            upg = "Hey! 💡 I have partial SOPs for this queue. Share the full SOP and I'll handle these autonomously."
        elif "consumable" in ql:
            upg = "Hey! 💡 I now have the Consumables SOP. AWB numbers are needed in the ticket for me to query Metabase and resolve this."
        else:
            upg = "Hey! 💡 I'm missing some key info to resolve this. Share the SOP or the missing data and I'll be fully autonomous here."
        steps.append({"icon": "🚫", "label": f"Blocked — {action}",
                      "detail": d.get("stuck_question") or "Missing information to resolve",
                      "status": "blocked", "upgrade": upg})
    return steps


@app.get("/api/decisions/{decision_id}/thinking")
def get_thinking(decision_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Decision not found")
    d = dict(row)
    steps = []
    if d.get("thinking_steps"):
        try:
            steps = json.loads(d["thinking_steps"])
        except Exception:
            pass
    if not steps:
        steps = _reconstruct_thinking_steps(d)
    return {"steps": steps, "decision_id": decision_id,
            "ticket_id": d.get("ticket_id"), "action": d.get("action"),
            "decision": d}


@app.post("/api/decisions/{decision_id}/reprocess")
def reprocess_decision(decision_id: int):
    """Re-run brain on a saved decision using current knowledge base. Replaces the saved record."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Decision not found")
    d = dict(row)

    try:
        from src.llm.agent_brain import get_agent_brain
        from src.query_engine.metabase_engine import MetabaseQueryEngine
        import json as _json

        awbs = _json.loads(d.get("awbs") or "[]")
        ticket = {
            "ticket_id": d["ticket_id"],
            "task_id":   d.get("task_id", ""),
            "subject":   d.get("subject", ""),
            "queue":     d.get("queue", ""),
            "queue_key": d.get("queue", ""),
            "detail":    d.get("description", "") or d.get("subject", ""),
            "description": d.get("description", ""),
            "awb_numbers": awbs,
            "hub_code":  "",
            "created_time": d.get("ticket_created_at", ""),
            "last_conversation_time": d.get("last_msg_time", ""),
        }

        engine = MetabaseQueryEngine()
        query_results = []
        if awbs:
            params = {"awb_list": awbs, "partner_id": ""}
            for qname in ["get_loss_attribution", "get_shipment_scan_history_single"]:
                try:
                    qr = engine.execute(qname, params)
                    query_results.append({"query_name": qname, "success": qr.success,
                                          "data": qr.data, "error": qr.error})
                except Exception as e:
                    query_results.append({"query_name": qname, "success": False,
                                          "data": {"rows": []}, "error": str(e)})

        brain    = get_agent_brain()
        decision = brain.process(ticket, query_results)

        # Overwrite the existing row in place
        now = datetime.now(timezone.utc).isoformat()
        _u = getattr(decision, 'usage', {}) or {}
        conn2 = get_conn()
        conn2.execute("""
            UPDATE decisions SET
              action=?, scenario=?, confidence=?, auto_send=?,
              response_draft=?, escalation_queue=?, escalation_reason=?,
              stuck_question=?, missing_fields=?, reasoning=?,
              thinking_steps=?, review_status=?, clean_problem=?,
              input_tokens=?, output_tokens=?, gemini_cost_inr=?
            WHERE id=?
        """, (
            decision.action, decision.scenario_identified, decision.confidence,
            1 if decision.auto_send else 0,
            decision.response_to_captain, decision.escalation_queue,
            decision.escalation_reason, decision.stuck_question,
            _json.dumps(decision.missing_fields), decision.reasoning,
            _json.dumps(getattr(decision, 'thinking_steps', [])),
            "sent" if decision.auto_send else "pending",
            getattr(decision, 'clean_problem', '') or '',
            _u.get("input_tokens", 0), _u.get("output_tokens", 0), _u.get("cost_inr", 0.0),
            decision_id,
        ))
        conn2.commit(); conn2.close()
        return {"status": "reprocessed", "action": decision.action,
                "confidence": decision.confidence, "auto_send": decision.auto_send}
    except Exception as e:
        raise HTTPException(500, f"Reprocess failed: {e}")


@app.post("/api/decisions/reprocess-all-stuck")
def reprocess_all_stuck():
    """Reprocess every stuck/needs_info decision in parallel (4 workers)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from src.llm.agent_brain import get_agent_brain
    from src.query_engine.metabase_engine import MetabaseQueryEngine
    import json as _json

    conn = get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM decisions WHERE action IN ('stuck','needs_info') ORDER BY id"
    ).fetchall()]
    conn.close()

    brain = get_agent_brain()

    def _reprocess_one(d):
        did = d["id"]
        try:
            awbs = _json.loads(d.get("awbs") or "[]")
            ticket = {
                "ticket_id": d["ticket_id"], "task_id": d.get("task_id", ""),
                "subject": d.get("subject", ""), "queue": d.get("queue", ""),
                "queue_key": d.get("queue", ""),
                "detail": d.get("description", "") or d.get("subject", ""),
                "description": d.get("description", ""),
                "awb_numbers": awbs, "hub_code": "",
                "created_time": d.get("ticket_created_at", ""),
                "last_conversation_time": d.get("last_msg_time", ""),
            }
            engine = MetabaseQueryEngine()
            query_results = []
            if awbs:
                params = {"awb_list": awbs, "partner_id": ""}
                for qname in ["get_loss_attribution", "get_shipment_scan_history_single"]:
                    try:
                        qr = engine.execute(qname, params)
                        query_results.append({"query_name": qname, "success": qr.success,
                                              "data": qr.data, "error": qr.error})
                    except Exception as e:
                        query_results.append({"query_name": qname, "success": False,
                                              "data": {"rows": []}, "error": str(e)})

            decision = brain.process(ticket, query_results)
            _u2 = getattr(decision, 'usage', {}) or {}
            c = get_conn()
            c.execute("""
                UPDATE decisions SET
                  action=?, scenario=?, confidence=?, auto_send=?,
                  response_draft=?, escalation_queue=?, escalation_reason=?,
                  stuck_question=?, missing_fields=?, reasoning=?,
                  thinking_steps=?, review_status=?, clean_problem=?,
                  input_tokens=?, output_tokens=?, gemini_cost_inr=?
                WHERE id=?
            """, (
                decision.action, decision.scenario_identified, decision.confidence,
                1 if decision.auto_send else 0,
                decision.response_to_captain, decision.escalation_queue,
                decision.escalation_reason, decision.stuck_question,
                _json.dumps(decision.missing_fields), decision.reasoning,
                _json.dumps(getattr(decision, 'thinking_steps', [])),
                "sent" if decision.auto_send else "pending",
                getattr(decision, 'clean_problem', '') or '',
                _u2.get("input_tokens", 0), _u2.get("output_tokens", 0), _u2.get("cost_inr", 0.0),
                did,
            ))
            c.commit(); c.close()
            return {"id": did, "old_action": d["action"],
                    "new_action": decision.action, "confidence": decision.confidence}
        except Exception as e:
            return {"id": did, "error": str(e)}

    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_reprocess_one, d): d["id"] for d in rows}
        for f in as_completed(futures):
            results.append(f.result())

    improved = sum(1 for r in results if r.get("new_action") in ("respond", "escalate")
                   and r.get("old_action") in ("stuck", "needs_info"))
    return {"processed": len(results), "improved": improved, "results": results}


@app.post("/api/decisions/reprocess-all")
def reprocess_all():
    """Reprocess ALL decisions with the current knowledge base — use after adding KT."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from src.llm.agent_brain import get_agent_brain
    from src.query_engine.metabase_engine import MetabaseQueryEngine
    import json as _json

    conn = get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM decisions ORDER BY id"
    ).fetchall()]
    conn.close()

    brain = get_agent_brain()
    brain.reload_knowledge()   # pull in latest KT before batch

    def _reprocess_one(d):
        did = d["id"]
        try:
            awbs = _json.loads(d.get("awbs") or "[]")
            ticket = {
                "ticket_id": d["ticket_id"], "task_id": d.get("task_id", ""),
                "subject": d.get("subject", ""), "queue": d.get("queue", ""),
                "queue_key": d.get("queue", ""),
                "detail": d.get("description", "") or d.get("subject", ""),
                "description": d.get("description", ""),
                "awb_numbers": awbs, "hub_code": "",
                "created_time": d.get("ticket_created_at", ""),
            }
            engine = MetabaseQueryEngine()
            query_results = []
            if awbs:
                params = {"awb_list": awbs, "partner_id": ""}
                for qname in ["get_loss_attribution", "get_shipment_scan_history_single"]:
                    try:
                        qr = engine.execute(qname, params)
                        query_results.append({"query_name": qname, "success": qr.success,
                                              "data": qr.data, "error": qr.error})
                    except Exception as e:
                        query_results.append({"query_name": qname, "success": False,
                                              "data": {"rows": []}, "error": str(e)})
            decision = brain.process(ticket, query_results)
            _u2 = getattr(decision, 'usage', {}) or {}
            c = get_conn()
            c.execute("""
                UPDATE decisions SET
                  action=?, scenario=?, confidence=?, auto_send=?,
                  response_draft=?, escalation_queue=?, escalation_reason=?,
                  stuck_question=?, missing_fields=?, reasoning=?,
                  thinking_steps=?, review_status=?, clean_problem=?,
                  input_tokens=?, output_tokens=?, gemini_cost_inr=?
                WHERE id=?
            """, (
                decision.action, decision.scenario_identified, decision.confidence,
                1 if decision.auto_send else 0,
                decision.response_to_captain, decision.escalation_queue,
                decision.escalation_reason, decision.stuck_question,
                _json.dumps(decision.missing_fields), decision.reasoning,
                _json.dumps(getattr(decision, 'thinking_steps', [])),
                "pending",
                getattr(decision, 'clean_problem', '') or '',
                _u2.get("input_tokens", 0), _u2.get("output_tokens", 0), _u2.get("cost_inr", 0.0),
                did,
            ))
            c.commit(); c.close()
            return {"id": did, "old_action": d["action"],
                    "new_action": decision.action, "confidence": decision.confidence}
        except Exception as e:
            return {"id": did, "error": str(e)}

    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_reprocess_one, d): d["id"] for d in rows}
        for f in as_completed(futures):
            results.append(f.result())

    improved = sum(1 for r in results
                   if r.get("new_action") in ("respond", "escalate")
                   and r.get("old_action") in ("stuck", "needs_info"))
    return {"processed": len(results), "improved": improved,
            "total": len(rows), "results": results}


@app.post("/api/decisions/{decision_id}/reject")
def reject(decision_id: int, body: ReviewAction):
    ok = reject_decision(
        decision_id, body.note,
        corrected_scenario=body.corrected_scenario,
        corrected_action=body.corrected_action,
    )
    if not ok:
        raise HTTPException(400, "Decision not found or already reviewed")
    return {
        "status": "rejected",
        "corrected_scenario": body.corrected_scenario or None,
        "corrected_action":   body.corrected_action or None,
    }


@app.get("/api/scenarios")
def list_scenarios():
    """Return all scenario IDs from sop_structured.json — used by the reject
    form to populate the 'Correct scenario' dropdown."""
    import json as _json
    sop_file = Path(__file__).parent / "data" / "sop_knowledge" / "sop_structured.json"
    try:
        themes = _json.loads(sop_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"Could not read sop_structured.json: {e}")
    scenarios = []
    for theme in themes:
        theme_id = theme.get("problem_theme", "")
        for sc in (theme.get("scenarios") or []):
            sid = sc.get("scenario_id")
            if not sid:
                continue
            scenarios.append({
                "scenario_id": sid,
                "label":       sc.get("label", ""),
                "theme":       theme_id,
                "queue":       theme.get("queue", ""),
            })
    scenarios.sort(key=lambda s: s["scenario_id"])
    return {"scenarios": scenarios, "count": len(scenarios)}


@app.get("/api/stats/flip-rates")
def stats_flip_rates(min_total: int = 0):
    """Per-scenario flip-rate stats. ?min_total=N filters out low-volume
    scenarios (default 0 = include all)."""
    from src.api.decision_store import get_flip_rates
    rows = get_flip_rates()
    if min_total > 0:
        rows = [r for r in rows if r["total"] >= min_total]
    return {"flip_rates": rows, "count": len(rows)}


@app.get("/api/scenario-audit/{scenario_id}")
def scenario_audit(scenario_id: str):
    """All knowledge + history the agent has about one scenario.

    Returns:
      sop_entry / theme          — entry from sop_structured.json (+ parent theme)
      stage0_compatibilities     — Stage 0 loss_types this scenario is compatible with
      stage0_taxonomy            — matching loss_type taxonomy entries from stage0_domain.json
      chunks                     — every ChromaDB chunk mentioning the scenario_id, grouped by content_type
      recent_decisions           — last 20 decisions where scenario_identified == this scenario
      flip_stats                 — flip-rate row for this scenario
    """
    import json as _json
    sid = (scenario_id or "").strip()
    if not sid:
        raise HTTPException(400, "scenario_id is required")

    # 1. sop_structured.json entry + parent theme
    sop_file = Path(__file__).parent / "data" / "sop_knowledge" / "sop_structured.json"
    try:
        themes = _json.loads(sop_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"Could not read sop_structured.json: {e}")
    sop_entry = None
    parent_theme = None
    for theme in themes:
        for sc in (theme.get("scenarios") or []):
            if sc.get("scenario_id") == sid:
                sop_entry = sc
                parent_theme = {k: v for k, v in theme.items() if k != "scenarios"}
                break
        if sop_entry:
            break

    # 2. Stage 0 compatibilities (from hardcoded scenario_families map)
    from src.llm.scenario_families import families_for
    compat = sorted(families_for(sid))

    # 3. Matching stage0_domain.json loss_type taxonomy entries
    stage0_file = Path(__file__).parent / "data" / "sop_knowledge" / "stage0_domain.json"
    stage0_taxonomy = {}
    try:
        s0 = _json.loads(stage0_file.read_text(encoding="utf-8"))
        for qkey, section in (s0.get("queues") or {}).items():
            lt_tax = section.get("loss_type_taxonomy") or {}
            for lt_name, lt_entry in lt_tax.items():
                if lt_name in compat:
                    stage0_taxonomy.setdefault(qkey, {})[lt_name] = lt_entry
    except Exception:
        pass

    # 4. ChromaDB chunks mentioning the scenario_id
    from src.llm.sop_store import get_sop_store
    raw_chunks = get_sop_store().find_chunks_mentioning(sid)
    chunks_by_type: dict = {}
    for c in raw_chunks:
        chunks_by_type.setdefault(c["content_type"], []).append(c)

    # 5. Last 20 decisions for this scenario
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, ticket_id, subject, queue, action, confidence, review_status,
               created_at, auto_send, guardrail_triggered,
               reviewer_corrected_scenario, reviewer_corrected_action, reviewer_note
        FROM decisions
        WHERE scenario = ?
        ORDER BY id DESC LIMIT 20
    """, (sid,)).fetchall()
    conn.close()
    recent = [dict(r) for r in rows]

    # 6. Flip-rate stats
    from src.api.decision_store import get_flip_rates
    flip = next((r for r in get_flip_rates() if r["scenario"] == sid), None)

    return {
        "scenario_id":           sid,
        "found_in_sop":          sop_entry is not None,
        "sop_entry":             sop_entry,
        "theme":                 parent_theme,
        "stage0_compatibilities": compat,
        "stage0_taxonomy":       stage0_taxonomy,
        "chunks_by_type":        chunks_by_type,
        "chunk_count":           len(raw_chunks),
        "recent_decisions":      recent,
        "flip_stats":            flip,
    }


class DeprecateBody(BaseModel):
    deprecated: bool = True


@app.post("/api/chunks/{chunk_id:path}/deprecate")
def deprecate_chunk(chunk_id: str, body: DeprecateBody):
    """Mark a ChromaDB chunk as deprecated (or undeprecate). retrieve()
    skips deprecated chunks but they stay in the collection — reversible."""
    from src.llm.sop_store import get_sop_store
    ok = get_sop_store().set_chunk_deprecated(chunk_id, body.deprecated)
    if not ok:
        raise HTTPException(404, f"Chunk {chunk_id!r} not found")
    return {"status": "ok", "chunk_id": chunk_id, "deprecated": body.deprecated}

class ModeUpdate(BaseModel):
    autonomous: bool

@app.get("/api/mode")
def get_mode():
    return {"autonomous": _load_mode()}

@app.post("/api/mode")
def set_mode(body: ModeUpdate):
    _save_mode(body.autonomous)
    return {"autonomous": body.autonomous}


# ── Admin: destructive ops + bulk processing ─────────────────────
# Wipe is gated behind a typed confirmation phrase. It's not real auth
# (anyone on the network can hit the endpoint), just a deliberate friction
# barrier so the button can't be hit accidentally.

WIPE_CONFIRM_PHRASE = "WIPE ALL DECISIONS"


class AdminWipeBody(BaseModel):
    confirm: str
    also_clear_stuck: bool = True
    also_clear_processed: bool = True


@app.post("/api/admin/wipe")
def admin_wipe(body: AdminWipeBody):
    """Wipe decisions.db. Caller must send exactly the confirmation phrase
    above. By default also clears stuck_queue.jsonl and live_processed.json
    so the agent re-processes any pending tickets next poll cycle."""
    if (body.confirm or "").strip() != WIPE_CONFIRM_PHRASE:
        raise HTTPException(
            400,
            f"Confirmation phrase mismatch. Send {{'confirm': '{WIPE_CONFIRM_PHRASE}'}} to proceed.",
        )

    summary = {}

    # 1. Wipe decisions table
    conn = get_conn()
    n_before = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    conn.execute("DELETE FROM decisions")
    conn.commit()
    summary["decisions_deleted"] = n_before
    conn.close()

    # 2. Stuck queue
    if body.also_clear_stuck:
        sq = Path(__file__).parent / "data" / "stuck_queue.jsonl"
        prev = 0
        if sq.exists():
            prev = sum(1 for line in sq.read_text(encoding="utf-8").splitlines() if line.strip())
            sq.write_text("", encoding="utf-8")
        summary["stuck_queue_cleared"] = prev
        # Also invalidate stuck-clusters cache
        try:
            from src.api.stuck_clusters import invalidate_cache
            invalidate_cache()
        except Exception:
            pass

    # 3. live_processed.json — clearing this means live_agent will reprocess
    if body.also_clear_processed:
        lp = Path(__file__).parent / "data" / "live_processed.json"
        prev_size = 0
        if lp.exists():
            try:
                prev_size = len(json.loads(lp.read_text(encoding="utf-8")))
            except Exception:
                pass
            lp.write_text("{}", encoding="utf-8")
        summary["live_processed_cleared"] = prev_size

    print(f"[Admin] WIPE executed: {summary}")
    return {"status": "ok", "summary": summary}


# ── Stuck queue ───────────────────────────────────────────────────
@app.get("/api/stuck")
def stuck_queue():
    stuck_file = Path(__file__).parent / "data" / "stuck_queue.jsonl"
    if not stuck_file.exists():
        return {"items": []}
    items = []
    for line in stuck_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try: items.append(json.loads(line))
            except: pass
    def _is_real_stuck(item):
        if item.get("answered"):
            return False
        reason = item.get("reasoning", "")
        question = item.get("question", "")
        # Filter out API error artifacts and parse error artifacts
        noise = ["API error", "unparseable", "NOT_FOUND", "models/gemini", "Model returned"]
        return not any(n.lower() in (reason + question).lower() for n in noise)
    return {"items": [i for i in items if _is_real_stuck(i)]}

class TrainerAnswer(BaseModel):
    ticket_id: str
    answer: str

@app.post("/api/stuck/answer")
def answer_stuck(body: TrainerAnswer):
    from src.llm.agent_brain import get_agent_brain
    from src.api.stuck_clusters import invalidate_cache
    get_agent_brain().answer_stuck(body.ticket_id, body.answer)
    invalidate_cache()   # cluster results stale once a question is answered
    return {"status": "answered"}


@app.get("/api/stuck/clusters")
def stuck_clusters(threshold: float = 0.35, window_days: int = 30, refresh: bool = False):
    """Cluster unanswered stuck questions from the last `window_days` by
    semantic similarity. Cached for 1h. `refresh=true` bypasses cache."""
    from src.api.stuck_clusters import get_clusters_cached
    return get_clusters_cached(
        threshold=threshold, window_days=window_days, force_refresh=refresh
    )


# ── KT Engine ────────────────────────────────────────────────────

KT_LOG       = Path(__file__).parent / "data" / "kt_log.jsonl"
KT_SOP_DIR   = Path(__file__).parent / "data" / "sop_knowledge"

class KTEntry(BaseModel):
    text: str
    category: str = "general"
    title: str = ""

@app.post("/api/kt/add")
def kt_add(body: KTEntry):
    from src.llm.sop_store import get_sop_store
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    source = f"kt_{body.category}_{ts}"
    # Add to live ChromaDB immediately (no restart needed)
    get_sop_store().add_knowledge(body.text, source=source, content_type="kt_addition")
    # Persist to .md so it survives restart + full reload
    KT_SOP_DIR.mkdir(parents=True, exist_ok=True)
    (KT_SOP_DIR / f"{source}.md").write_text(
        f"# {body.title or body.category}\n\n{body.text}\n", encoding="utf-8"
    )
    # Log entry
    entry = {
        "source": source, "category": body.category,
        "title": body.title or body.category,
        "text_preview": body.text[:200],
        "chars": len(body.text),
        "added_at": datetime.utcnow().isoformat(),
    }
    with open(KT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "added", "source": source}

@app.post("/api/sop/reload")
def sop_reload():
    """Reload SOP .md files (ChromaDB) AND Stage 0 domain — no restart needed."""
    from src.llm.sop_store import get_sop_store
    from src.llm import stage0
    store = get_sop_store()
    before = store._col.count()
    store.reload()
    after = store._col.count()
    stage0.reload_domain()
    return {"status": "reloaded", "chunks_before": before, "chunks_after": after,
            "stage0_queues": [q["queue_key"] + ":" + q["status"] for q in stage0.list_queues()]}


# ── Stage 0 KT Engine — structured per-queue domain knowledge ────

@app.get("/api/kt/queues")
def kt_queues():
    """List all queue sections in stage0_domain.json with status + counts."""
    from src.llm import stage0
    return {"queues": stage0.list_queues()}


@app.get("/api/kt/template/{queue_key}")
def kt_template(queue_key: str):
    """Return a structured KT JSON template for the queue (filled with current state)."""
    from src.llm import stage0
    return {"queue_key": queue_key, "template": stage0.get_template(queue_key)}


class ValidatePayload(BaseModel):
    payload: dict


@app.post("/api/kt/validate")
def kt_validate(body: ValidatePayload):
    """Lint a structured KT payload before saving. Returns {ok, errors, warnings}."""
    from src.llm import stage0
    return stage0.validate_payload(body.payload)


class StructuredKT(BaseModel):
    queue_key: str
    queue_aliases: list = []
    metabase_columns: dict = {}
    loss_type_taxonomy: dict = {}
    reason_l1_taxonomy: dict = {}
    preprocessing_rules: list = []
    scenarios: list = []     # optional new scenarios beyond sop_structured.json
    kt_note: str = ""        # free-form summary, also indexed in ChromaDB


@app.post("/api/kt/structured")
def kt_structured(body: StructuredKT):
    """
    Add structured domain knowledge for a queue. Updates stage0_domain.json
    in-place and reloads Stage 0 — no restart needed.

    Also indexes the kt_note (if provided) in ChromaDB so retrieval picks it up.
    """
    from src.llm import stage0
    from src.llm.sop_store import get_sop_store

    qkey = (body.queue_key or "").strip()
    if not qkey:
        raise HTTPException(400, "queue_key is required")

    section = stage0.upsert_queue(qkey, {
        "queue_aliases": body.queue_aliases,
        "metabase_columns": body.metabase_columns,
        "loss_type_taxonomy": body.loss_type_taxonomy,
        "reason_l1_taxonomy": body.reason_l1_taxonomy,
        "preprocessing_rules": body.preprocessing_rules,
        "scenarios": body.scenarios,
    })

    # Mirror as prose in ChromaDB so retrieval can surface it too
    if body.kt_note or body.metabase_columns or body.preprocessing_rules:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        source = f"kt_domain_{qkey}_{ts}"
        text_parts = [f"# Domain KT — {qkey}\n"]
        if body.kt_note:
            text_parts.append(body.kt_note + "\n")
        if body.metabase_columns:
            text_parts.append("## Metabase columns")
            for k, v in body.metabase_columns.items():
                text_parts.append(f"- **{k}**: {v}")
        if body.preprocessing_rules:
            text_parts.append("\n## Preprocessing rules")
            for r in body.preprocessing_rules:
                text_parts.append(f"- {r}")
        text = "\n".join(text_parts)
        try:
            get_sop_store().add_knowledge(text, source=source, content_type="kt_domain_activation")
            KT_SOP_DIR.mkdir(parents=True, exist_ok=True)
            (KT_SOP_DIR / f"{source}.md").write_text(text, encoding="utf-8")
            entry = {
                "source": source, "category": f"domain_{qkey}",
                "title": f"Stage 0 domain — {qkey}",
                "text_preview": text[:200], "chars": len(text),
                "added_at": datetime.utcnow().isoformat(),
            }
            with open(KT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            # Non-fatal — the structured section is already saved
            return {"status": "partial",
                    "section": section,
                    "warning": f"ChromaDB index failed: {e}"}

    return {"status": "ok", "queue_key": qkey, "section": section}


class FreeformKT(BaseModel):
    text: str
    queue_hint: str = ""    # optional — user's guess at which queue this applies to


@app.post("/api/kt/structured-from-text")
def kt_structured_from_text(body: FreeformKT):
    """
    Pranav-style KT: paste free-form text describing a queue's columns/scans/rules.
    Gemini parses it into structured fields and routes to /api/kt/structured.
    """
    from src.llm.gemini_client import get_gemini_client
    from src.llm import stage0 as _s0

    if not body.text.strip():
        raise HTTPException(400, "text is required")

    queues_known = [q["queue_key"] for q in _s0.list_queues()]
    queue_list = ", ".join(queues_known) or "losses_and_debits, payments, consumables, orders_and_planning, cash_handover"

    prompt = f"""You are parsing a free-form KT note from a domain expert into a structured queue update for a logistics support agent.

Available queue keys (pick exactly one): {queue_list}
User's queue hint (may be empty): "{body.queue_hint}"

KT NOTE:
\"\"\"
{body.text[:4000]}
\"\"\"

Output ONLY this JSON shape (no markdown):
{{
  "queue_key": "<one of the queue keys above>",
  "queue_aliases": ["..."],
  "metabase_columns": {{
    "<query_name_in_snake_case>": "<comma-separated column names + one-line meaning>"
  }},
  "loss_type_taxonomy": {{}},
  "reason_l1_taxonomy": {{}},
  "preprocessing_rules": ["..."],
  "kt_note": "<one-paragraph summary of the KT>"
}}

Rules:
- Pick queue_key strictly from the list above. If hint is empty, infer from the text.
- Keep metabase_columns keys snake_case and short (e.g. captain_payment_status_and_amount).
- Each column entry should mention WHICH columns matter and WHAT each means.
- Don't invent rules that aren't in the text.
- If the text doesn't fit any known queue, set queue_key to the closest match anyway.
"""

    try:
        parsed = get_gemini_client().generate_json(prompt, temperature=0.0)
    except Exception as e:
        raise HTTPException(500, f"Gemini parse failed: {e}")
    if not isinstance(parsed, dict) or not parsed.get("queue_key"):
        raise HTTPException(500, f"Could not parse KT into structured form: {parsed}")
    parsed.pop("_usage", None)

    # Route into the structured upsert
    section = _s0.upsert_queue(parsed["queue_key"], {
        "queue_aliases": parsed.get("queue_aliases") or [],
        "metabase_columns": parsed.get("metabase_columns") or {},
        "loss_type_taxonomy": parsed.get("loss_type_taxonomy") or {},
        "reason_l1_taxonomy": parsed.get("reason_l1_taxonomy") or {},
        "preprocessing_rules": parsed.get("preprocessing_rules") or [],
    })

    # Also index the original text + Gemini's note in ChromaDB
    from src.llm.sop_store import get_sop_store
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    source = f"kt_freeform_{parsed['queue_key']}_{ts}"
    md = f"# Domain KT — {parsed['queue_key']}\n\n{body.text}\n\n_Parsed summary:_ {parsed.get('kt_note','')}"
    try:
        get_sop_store().add_knowledge(md, source=source, content_type="kt_domain_activation")
        KT_SOP_DIR.mkdir(parents=True, exist_ok=True)
        (KT_SOP_DIR / f"{source}.md").write_text(md, encoding="utf-8")
        with open(KT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "source": source, "category": f"domain_{parsed['queue_key']}",
                "title": f"Stage 0 domain (freeform) — {parsed['queue_key']}",
                "text_preview": body.text[:200], "chars": len(body.text),
                "added_at": datetime.utcnow().isoformat(),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return {"status": "ok", "parsed": parsed, "section": section}


class GuidedKTBody(BaseModel):
    queue_hint: str = ""
    queue_aliases_text: str = ""
    issue_types_text: str = ""
    metabase_text: str = ""
    rules_text: str = ""


@app.post("/api/kt/guided-extract")
def kt_guided_extract(body: GuidedKTBody):
    """
    Interview-style KT extraction. Stakeholder fills 4 labeled English fields.
    Gemini returns: parsed JSON + plain-English summary + specific gap questions.
    Does NOT save — caller posts to /api/kt/guided-activate to commit.
    """
    from src.llm.gemini_client import get_gemini_client
    from src.llm import stage0 as _s0

    if not (body.queue_aliases_text + body.issue_types_text + body.metabase_text + body.rules_text).strip():
        raise HTTPException(400, "Fill at least one section before extracting")

    queues_known = [q["queue_key"] for q in _s0.list_queues()]
    queue_list = ", ".join(queues_known) or "losses_and_debits, payments, consumables, orders_and_planning, cash_handover"

    prompt = f"""You are interviewing a domain expert who is teaching an AI agent how a support queue works.
They've answered four labeled questions in plain English. Your job:
1. Extract a structured JSON for the agent.
2. Write a plain-English back-translation so they can verify what you understood.
3. Identify specific gaps as direct questions they should answer next.

Available queue keys (pick exactly one): {queue_list}
User's queue hint (may be empty): "{body.queue_hint}"

================== EXPERT ANSWERS ==================

[A — Queue identity / aliases]
{body.queue_aliases_text or '(blank)'}

[B — Types of issues handled in this queue, with how the captain phrases them and how to verify/respond]
{body.issue_types_text or '(blank)'}

[C — Metabase queries used: query name, columns, what each column means, what values trigger what action]
{body.metabase_text or '(blank)'}

[D — Pre-checks / rules the agent must always follow]
{body.rules_text or '(blank)'}

================== OUTPUT (JSON ONLY, no markdown) ==================
{{
  "parsed": {{
    "queue_key": "<one of: {queue_list}>",
    "queue_aliases": ["..."],
    "metabase_columns": {{
      "<query_name_snake_case>": "<columns + meaning + which values trigger which action>"
    }},
    "loss_type_taxonomy": {{
      "<issue_type_snake_case>": {{
        "physical_event": "one-line description",
        "trigger_scans": "what to check",
        "captain_signals": ["phrase1", "phrase2"],
        "scenario_family": "<family name>",
        "common_sub_scenarios": ["..."]
      }}
    }},
    "reason_l1_taxonomy": {{}},
    "preprocessing_rules": ["..."],
    "scenarios": []
  }},
  "english_summary": "<2-4 short paragraphs in plain English describing what you understood about this queue from their answers. Address them as 'you'.>",
  "gaps": [
    {{
      "section": "Queue identity | Issue types | Metabase | Rules",
      "question": "<a direct, specific question they should answer to fill this gap>"
    }}
  ]
}}

Rules:
- queue_key MUST be from the list above.
- Issue type keys must be snake_case and concrete (e.g. payment_pending, payment_on_hold, wrong_amount).
- For each metabase column entry, ALWAYS spell out: column names, what each means, AND which values map to which captain reply.
- For "gaps", flag ONLY missing things that block the agent from acting. Do NOT pad. Examples of real gaps:
  * Issue type listed but no captain signal phrases given.
  * Metabase column listed but no values/meanings explained.
  * No mention of what the agent should reply when status=X.
  * Rules section blank — ask if there are pre-checks or confirm there are none.
- If a section is genuinely complete, do NOT generate a gap for it.
- Phrase gap questions like a colleague: 'For the payment_on_hold case, what reply should the agent send to the captain?' — not template-y.
- english_summary must be honest about what's missing too — don't invent details the user didn't give.
"""

    try:
        result = get_gemini_client().generate_json(prompt, temperature=0.0)
    except Exception as e:
        raise HTTPException(500, f"Gemini parse failed: {e}")
    if not isinstance(result, dict):
        raise HTTPException(500, f"Bad parse output: {result}")
    result.pop("_usage", None)

    parsed = result.get("parsed") or {}
    if not parsed.get("queue_key"):
        raise HTTPException(500, "Could not infer queue_key from your answers — try filling the queue identity section.")

    # Lint the parsed payload so the UI can show errors/warnings without saving
    validation = _s0.validate_payload(parsed)

    return {
        "parsed": parsed,
        "english_summary": result.get("english_summary", ""),
        "gaps": result.get("gaps", []),
        "validation": validation,
        "ready_to_activate": validation.get("ok", False),
    }


class GuidedActivateBody(BaseModel):
    parsed: dict
    raw_answers: dict = {}   # the four text fields, archived as prose in ChromaDB


@app.post("/api/kt/guided-activate")
def kt_guided_activate(body: GuidedActivateBody):
    """Commit a guided-extract payload after the user has confirmed it."""
    from src.llm import stage0 as _s0
    from src.llm.sop_store import get_sop_store

    parsed = body.parsed or {}
    qkey = (parsed.get("queue_key") or "").strip()
    if not qkey:
        raise HTTPException(400, "parsed.queue_key is required")

    section = _s0.upsert_queue(qkey, {
        "queue_aliases": parsed.get("queue_aliases") or [],
        "metabase_columns": parsed.get("metabase_columns") or {},
        "loss_type_taxonomy": parsed.get("loss_type_taxonomy") or {},
        "reason_l1_taxonomy": parsed.get("reason_l1_taxonomy") or {},
        "preprocessing_rules": parsed.get("preprocessing_rules") or [],
        "scenarios": parsed.get("scenarios") or [],
    })

    # Archive raw answers + parsed result as prose in ChromaDB for retrieval support
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    source = f"kt_guided_{qkey}_{ts}"
    parts = [f"# Domain KT (guided) — {qkey}\n"]
    ra = body.raw_answers or {}
    for label, key in [
        ("Queue aliases",  "queue_aliases_text"),
        ("Issue types",    "issue_types_text"),
        ("Metabase",       "metabase_text"),
        ("Rules",          "rules_text"),
    ]:
        if ra.get(key):
            parts.append(f"## {label}\n{ra[key]}\n")
    md = "\n".join(parts)
    try:
        get_sop_store().add_knowledge(md, source=source, content_type="kt_domain_activation")
        KT_SOP_DIR.mkdir(parents=True, exist_ok=True)
        (KT_SOP_DIR / f"{source}.md").write_text(md, encoding="utf-8")
        with open(KT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "source": source, "category": f"domain_{qkey}",
                "title": f"Stage 0 domain (guided) — {qkey}",
                "text_preview": md[:200], "chars": len(md),
                "added_at": datetime.utcnow().isoformat(),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return {"status": "ok", "queue_key": qkey, "section": section}


class GuidedTestBody(BaseModel):
    parsed: dict
    ticket_ids: list = []   # explicit list to test
    auto_pick: int = 0      # if >0 and ticket_ids empty, auto-pick N recent tickets matching queue aliases


def _load_ticket_for_test(ticket_id: str):
    """Look up a ticket from DB → scraped cache. Returns ticket-shaped dict or None."""
    import re as _re
    AWB_RE = _re.compile(r'\b(VL[R]?\d{10,15})\b', _re.IGNORECASE)

    # 1. Decisions DB — has the original scraped fields
    conn = get_conn()
    row = conn.execute("SELECT * FROM decisions WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (ticket_id,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        try: awbs = json.loads(d.get("awbs") or "[]")
        except: awbs = []
        return {
            "ticket_id": ticket_id,
            "task_id": d.get("task_id") or "",
            "subject": d.get("subject") or "",
            "queue": d.get("queue") or "",
            "queue_key": d.get("queue") or "",
            "detail": d.get("description") or "",
            "awb_numbers": awbs,
            "created_time": d.get("ticket_created_at") or "",
        }

    # 2. Scraped cache
    for path in ["data/scraped_tickets_v2.jsonl", "data/scraped_tickets.jsonl"]:
        p = Path(path)
        if not p.exists(): continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                t = json.loads(line)
            except: continue
            if str(t.get("ticket_id", "")) != ticket_id:
                continue
            queue = t.get("queue_key") or t.get("queue") or ""
            raw_detail = t.get("full_description") or t.get("detail") or t.get("subject", "")
            detail = re.sub(r'<[^>]+>', ' ', raw_detail)
            detail = _html_mod.unescape(detail)
            detail = detail.replace(' ', ' ').replace('﻿', '').replace('​', '')
            detail = re.sub(r'[ \t]{3,}', '  ', detail).strip()
            subject = t.get("subject_line") or t.get("subject", "")[:120]
            awbs = list(set(AWB_RE.findall(detail + " " + subject)))
            awbs += (t.get("awbs_on_page") or [])
            return {
                "ticket_id": ticket_id, "task_id": str(t.get("task_id", "")),
                "subject": subject, "queue": queue, "queue_key": queue,
                "detail": detail, "awb_numbers": list(set(awbs)),
                "created_time": t.get("created_time", ""),
                "email": t.get("email", ""),
            }
    return None


def _auto_pick_tickets_for_queue(aliases: list, n: int) -> list:
    """Find recent ticket_ids whose queue matches any alias (case-insensitive substring)."""
    if not aliases or n <= 0:
        return []
    aliases_lc = [a.strip().lower() for a in aliases if a]
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT ticket_id, queue FROM decisions WHERE queue IS NOT NULL AND queue != '' "
        "ORDER BY id DESC LIMIT 200"
    ).fetchall()
    conn.close()
    picked = []
    for r in rows:
        q = (r["queue"] or "").lower()
        if any(a and (a in q or q in a) for a in aliases_lc):
            picked.append(r["ticket_id"])
            if len(picked) >= n:
                break
    return picked


@app.post("/api/kt/guided-test")
def kt_guided_test(body: GuidedTestBody):
    """
    Run a few real tickets through the brain using STAGED (not yet saved) domain knowledge.
    Returns per-ticket diagnosis so the stakeholder can verify the agent behaves correctly
    BEFORE activating the queue.
    """
    import copy
    from src.llm import stage0 as _s0
    from src.llm.agent_brain import get_agent_brain
    from src.query_engine.metabase_engine import MetabaseQueryEngine

    parsed = body.parsed or {}
    qkey = (parsed.get("queue_key") or "").strip()
    if not qkey:
        raise HTTPException(400, "parsed.queue_key is required")

    # Resolve target ticket_ids
    ticket_ids = [t for t in (body.ticket_ids or []) if t]
    if not ticket_ids and body.auto_pick > 0:
        ticket_ids = _auto_pick_tickets_for_queue(parsed.get("queue_aliases") or [qkey], body.auto_pick)
    if not ticket_ids:
        return {"results": [], "warning": "No tickets found for this queue. Paste ticket IDs manually."}

    # ── Stage the parsed domain in memory (deep snapshot for safe restore) ───
    original_domain = copy.deepcopy(_s0._DOMAIN)
    try:
        section = _s0._DOMAIN.setdefault("queues", {}).setdefault(qkey, {})
        # Merge parsed fields onto the in-memory section
        if parsed.get("queue_aliases"):
            section["queue_aliases"] = list({*(section.get("queue_aliases") or []), *parsed["queue_aliases"]})
        if parsed.get("metabase_columns"):
            section.setdefault("metabase_columns", {}).update(parsed["metabase_columns"])
        if parsed.get("loss_type_taxonomy"):
            section.setdefault("loss_type_taxonomy", {}).update(parsed["loss_type_taxonomy"])
        if parsed.get("reason_l1_taxonomy"):
            section.setdefault("reason_l1_taxonomy", {}).update(parsed["reason_l1_taxonomy"])
        if parsed.get("preprocessing_rules"):
            existing = section.get("preprocessing_rules") or []
            for r in parsed["preprocessing_rules"]:
                if r and r not in existing:
                    existing.append(r)
            section["preprocessing_rules"] = existing
        # Promote so Stage 0 uses the rich prompt path
        cols = section.get("metabase_columns") or {}
        if any("TODO" not in str(v) for v in cols.values()) and cols:
            section["status"] = "complete"

        # ── Run each ticket through the brain (no DB write) ────────────────
        brain = get_agent_brain()
        try:
            engine = MetabaseQueryEngine()
        except Exception:
            engine = None

        results = []
        for tid in ticket_ids:
            ticket = _load_ticket_for_test(tid)
            if not ticket:
                results.append({"ticket_id": tid, "error": "Not found in DB or scraped cache"})
                continue

            # Optional: run AWB queries if AWBs present and engine available
            query_results = []
            awbs = ticket.get("awb_numbers") or []
            if awbs and engine is not None:
                params = {"awb_list": awbs, "partner_id": ticket.get("email", "")}
                for qname in ["get_loss_attribution", "get_shipment_scan_history_single"]:
                    try:
                        qr = engine.execute(qname, params)
                        query_results.append({
                            "query_name": qname, "success": qr.success,
                            "data": qr.data, "error": qr.error,
                        })
                    except Exception as e:
                        query_results.append({
                            "query_name": qname, "success": False,
                            "data": {"rows": []}, "error": str(e),
                        })

            try:
                decision = brain.process(ticket, query_results)
                stage0_dump = getattr(decision, "stage0", None) or {}
                results.append({
                    "ticket_id": tid,
                    "subject": ticket.get("subject", ""),
                    "queue": ticket.get("queue", ""),
                    "awbs": awbs,
                    "stage0": {
                        "physical_event": stage0_dump.get("physical_event", "") if isinstance(stage0_dump, dict) else "",
                        "loss_type":      stage0_dump.get("loss_type", "")      if isinstance(stage0_dump, dict) else "",
                        "scenario_hint":  stage0_dump.get("scenario_hint", "")  if isinstance(stage0_dump, dict) else "",
                        "domain_confidence": stage0_dump.get("domain_confidence", "") if isinstance(stage0_dump, dict) else "",
                    },
                    "action": decision.action,
                    "scenario": decision.scenario_identified,
                    "confidence": decision.confidence,
                    "response": decision.response_to_captain or "",
                    "escalation_queue": decision.escalation_queue or "",
                    "escalation_reason": decision.escalation_reason or "",
                    "stuck_question": decision.stuck_question or "",
                    "reasoning": (decision.reasoning or "")[:600],
                })
            except Exception as e:
                results.append({"ticket_id": tid, "error": f"Brain failed: {e}"})

        return {"results": results, "staged_queue_key": qkey, "tickets_run": len(results)}
    finally:
        # Always restore — even on error — so disk-saved domain isn't affected
        _s0._DOMAIN = original_domain


@app.get("/api/learning/log")
def learning_log():
    """
    Exhaustive audit trail of everything the agent has learned.
    Three source types:
      - 'ticket'   : learned from an approved real ticket
      - 'trainer'  : manually added by trainer via KT engine / voice
      - 'sop'      : base SOP knowledge loaded at startup
    """
    entries = []

    # ── Source 1: ChromaDB — all non-base entries ──────────────────
    try:
        from src.llm.sop_store import get_sop_store
        store = get_sop_store()
        all_items = store._col.get(include=["documents", "metadatas"])
        docs      = all_items.get("documents", [])
        metas     = all_items.get("metadatas", [])

        for doc, meta in zip(docs, metas):
            src = meta.get("source", "")
            if src.startswith("resolved_"):
                # learned from an approved ticket
                parts = src.split("_")
                ticket_id = parts[1] if len(parts) > 1 else "?"
                scenario  = "_".join(parts[2:]) if len(parts) > 2 else "?"
                entries.append({
                    "type": "ticket",
                    "source_label": f"Ticket #{ticket_id}",
                    "scenario": scenario,
                    "summary": doc[:300],
                    "full_text": doc,
                    "applicable": _applicable_queues(doc),
                    "added_at": "",
                })
            elif src.startswith("kt_") or src.startswith("trainer_"):
                parts = src.split("_")
                category = parts[1] if len(parts) > 1 else "general"
                entries.append({
                    "type": "trainer",
                    "source_label": "Management / Trainer",
                    "scenario": category,
                    "summary": doc[:300],
                    "full_text": doc,
                    "applicable": _applicable_queues(doc),
                    "added_at": "",
                })
    except Exception as e:
        pass

    # ── Source 2: KT log — richer metadata ────────────────────────
    kt_by_source = {}
    if KT_LOG.exists():
        for line in KT_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
                kt_by_source[e.get("source", "")] = e
            except Exception:
                pass

    # Enrich trainer entries with KT log timestamps/titles
    for entry in entries:
        if entry["type"] == "trainer":
            src_key = entry.get("scenario", "")
            for k, v in kt_by_source.items():
                if src_key in k:
                    entry["added_at"]     = v.get("added_at", "")
                    entry["source_label"] = f"Trainer — {v.get('title', v.get('category', 'general'))}"
                    break

    # Add any KT log entries NOT already in ChromaDB (edge case)
    chroma_summaries = {e["summary"][:80] for e in entries}
    for src, v in kt_by_source.items():
        preview = v.get("text_preview", "")[:80]
        if preview not in chroma_summaries:
            entries.append({
                "type": "trainer",
                "source_label": f"Trainer — {v.get('title', v.get('category', 'general'))}",
                "scenario": v.get("category", "general"),
                "summary": v.get("text_preview", ""),
                "full_text": v.get("text_preview", ""),
                "applicable": [],
                "added_at": v.get("added_at", ""),
            })

    # Sort: ticket approvals first, then trainer, newest first
    def _sort_key(e):
        t = 0 if e["type"] == "ticket" else 1 if e["type"] == "trainer" else 2
        return (t, -(len(e.get("added_at") or "")))

    entries.sort(key=_sort_key)
    return {"entries": entries, "total": len(entries)}


def _applicable_queues(text: str) -> list:
    """Guess which queues/scenarios this knowledge applies to from text."""
    t = text.lower()
    tags = []
    if any(w in t for w in ["hardstop", "w- ld", "loss marked", "reversal"]): tags.append("W-LD / Hardstop")
    if any(w in t for w in ["shortage", "evidence", "cctv"]): tags.append("Shortage")
    if any(w in t for w in ["consumable", "flyer", "polybag", "docket", "packaging"]): tags.append("Consumables")
    if any(w in t for w in ["payment", "cod", "cash", "pendency"]): tags.append("Payments / COD")
    if any(w in t for w in ["order", "planning", "route", "allocation"]): tags.append("Orders")
    if any(w in t for w in ["meesho am", "seller dependency", "awaited instruction"]): tags.append("Seller Dependency")
    if any(w in t for w in ["suspicious", "vague", "unclear"]): tags.append("Vague Tickets")
    return tags or ["General"]


@app.get("/api/kt/list")
def kt_list(limit: int = 30):
    if not KT_LOG.exists():
        return {"entries": []}
    entries = []
    for line in KT_LOG.read_text(encoding="utf-8").splitlines():
        try: entries.append(json.loads(line))
        except: pass
    entries.sort(key=lambda x: x.get("added_at", ""), reverse=True)
    return {"entries": entries[:limit]}


# ── CXO View ──────────────────────────────────────────────────────

_REVERSAL_QUEUES = {"ld", "loss", "w- ld", "hardstop", "shipment_shortage"}
_CSAT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTtfp2EauVkBu1RILwErMMDs7mfwdzC1V9CdP0bf4ZjEsoe_QEr7o1slJm5tsMxNIqMK6vudtYjHCql"
    "/pubhtml?gid=1281163884&single=true"
)


def _is_reversal(queue: str) -> bool:
    q = (queue or "").lower()
    return any(k in q for k in _REVERSAL_QUEUES)


def _action_rs(action: str, is_rev: bool, conf: float) -> float:
    """Map action → Resolution Score using permutation simulation framework."""
    if action == "respond":
        base = 0.625 if is_rev else 0.50
        if conf >= 8:  base = min(base + 0.05, 1.0)
        elif conf < 6: base = max(base - 0.05, 0.0)
        return base
    elif action == "escalate":
        return 0.50
    elif action in ("stuck", "needs_info"):
        return 0.125
    return 0.30


def _fetch_satisfaction() -> dict:
    """Fetch data from the Google Sheet (SOP/CSAT) via CSV export."""
    csv_url = _CSAT_SHEET_URL.replace("/pubhtml?", "/pub?") + "&output=csv"
    try:
        import requests as req
        import csv, io
        r = req.get(csv_url, timeout=8)
        reader = csv.reader(io.StringIO(r.content.decode("utf-8", errors="replace")))
        rows = [row for row in reader if any(c.strip() for c in row)]
        header = rows[0] if rows else []
        data   = rows[1:] if len(rows) > 1 else []
        return {
            "available": True,
            "header": header,
            "rows": data[:40],
            "total_rows": len(data),
            "url": _CSAT_SHEET_URL,
        }
    except Exception as e:
        return {"available": False, "error": str(e), "url": _CSAT_SHEET_URL}



@app.post("/api/decisions/reenrich")
def reenrich_descriptions():
    """
    For tickets where description is NULL or subject is truncated (<=120 chars),
    log into Kapture via Playwright and fetch the full text using existing credentials.
    Runs synchronously — takes ~5s per ticket.
    """
    import asyncio, re as _re
    from playwright.async_api import async_playwright
    from scrape_tickets_v2 import login, _parse_additional_info

    conn = get_conn()
    rows = conn.execute("""
        SELECT id, task_id, ticket_id FROM decisions
        WHERE task_id IS NOT NULL AND task_id != ''
          AND (description IS NULL OR description = ''
               OR LENGTH(subject) <= 120)
        ORDER BY id DESC
    """).fetchall()
    conn.close()

    if not rows:
        return {"status": "done", "total": 0, "updated": 0}

    BASE = "https://valmostagging.kapturecrm.com"

    async def _fetch_all():
        updated = 0
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await login(page)

            for row in rows:
                row_id, task_id, ticket_id = row[0], row[1], row[2]
                try:
                    result = await page.evaluate(f"""
                        async () => {{
                            const base = '/api/version3/ticket/get-ticket-detail';
                            const [ticketResp, aiResp] = await Promise.all([
                                fetch(base + '?id={task_id}&ticket_id={ticket_id}&skip_unread_action=no&data_type=ticket').then(r=>r.json()),
                                fetch(base + '?id={task_id}&data_type=additional_info&status=C&last_con_id=0&last_con_type=O').then(r=>r.json()),
                            ]);
                            return {{ ticket: ticketResp, ai: aiResp }};
                        }}
                    """)

                    ticket_obj = {}
                    tr = result.get("ticket") or {}
                    tr_resp = tr.get("response") or tr
                    ticket_obj = tr_resp.get("ticket") or tr_resp

                    ai_raw = result.get("ai") or {}
                    ai_resp = ai_raw.get("response") or ai_raw
                    captured = {"additionalInfo": ai_resp}
                    parsed = _parse_additional_info(captured)

                    full_desc = parsed.get("please_describe_issue", "")
                    if full_desc:
                        full_desc = _re.sub(r'<[^>]+>', '', full_desc).strip().replace('\xa0', ' ')

                    full_subject = parsed.get("subject_line", "")

                    # Fallbacks
                    if not full_desc and isinstance(ticket_obj, dict):
                        raw = ticket_obj.get("detail", "")
                        if raw:
                            full_desc = _re.sub(r'<[^>]+>', '', str(raw)).strip().replace('\xa0', ' ')[:3000]
                    if not full_subject and isinstance(ticket_obj, dict):
                        full_subject = ticket_obj.get("taskTitle", "")

                    if full_desc or full_subject:
                        c = get_conn()
                        if full_desc:
                            c.execute("UPDATE decisions SET description=? WHERE id=?", (full_desc, row_id))
                        if full_subject:
                            c.execute("UPDATE decisions SET subject=? WHERE id=?", (full_subject, row_id))
                        c.commit(); c.close()
                        updated += 1

                except Exception:
                    pass

            await browser.close()
        return updated

    updated = asyncio.run(_fetch_all())
    return {"status": "done", "total": len(rows), "updated": updated}


# ── Health Check ──────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    """Check status of all integrations."""
    results = {}

    # DB
    try:
        conn = get_conn()
        n = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        conn.close()
        results["db"] = {"ok": True, "label": "Decision DB", "note": f"{n} tickets stored", "icon": "🗄️"}
    except Exception as e:
        results["db"] = {"ok": False, "label": "Decision DB", "note": str(e), "icon": "🗄️"}

    # ChromaDB / SOP store
    try:
        from src.llm.sop_store import get_sop_store
        store = get_sop_store()
        count = store._col.count() if hasattr(store, "_col") else -1
        results["chromadb"] = {"ok": True, "label": "SOP Knowledge Base", "note": f"{count} SOP chunks indexed", "icon": "📚"}
    except Exception as e:
        results["chromadb"] = {"ok": False, "label": "SOP Knowledge Base", "note": str(e), "icon": "📚"}

    # Gemini
    gemini_key = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    results["gemini"] = {
        "ok": gemini_key,
        "label": "Gemini 2.5 Flash (AI Brain)",
        "note": "Active — processing tickets" if gemini_key else "No API key set",
        "icon": "🧠",
    }

    # Kapture CRM — use module-level credential check (set at startup)
    kapture_key = _KAPTURE_READY
    results["kapture"] = {
        "ok": kapture_key,
        "label": "Kapture CRM",
        "note": "Credentials configured — ticket ingestion active" if kapture_key else "Awaiting credentials (set EMAIL + PASSWORD in .env)",
        "icon": "📋",
        "needs_access": not kapture_key,
    }

    # Metabase (shipment data warehouse)
    try:
        from src.query_engine.metabase_engine import MetabaseQueryEngine
        engine = MetabaseQueryEngine()
        session_ok = engine._session is not None and bool(engine._session._token)
        results["metabase"] = {
            "ok": session_ok,
            "label": "Metabase (Shipment DB)",
            "note": "Session active — AWB queries enabled" if session_ok else "Session expired — needs re-login (provide Metabase credentials)",
            "icon": "📊",
            "needs_access": not session_ok,
        }
    except Exception as e:
        results["metabase"] = {
            "ok": False,
            "label": "Metabase (Shipment DB)",
            "note": "Awaiting Metabase access credentials",
            "icon": "📊",
            "needs_access": True,
        }

    # Log10 (scan history)
    log10_session = Path("data/.log10_session.json")
    log10_has_session = log10_session.exists() and log10_session.stat().st_size > 10
    results["log10"] = {
        "ok": log10_has_session,
        "label": "Log10 (Scan History)",
        "note": "Session active — scan verification enabled" if log10_has_session else "Awaiting Log10 access (phone + OTP login required)",
        "icon": "🔍",
        "needs_access": not log10_has_session,
    }

    overall = all(v.get("ok") for v in results.values())
    return {"healthy": overall, "checks": results}


# ── Live Ticket Test ──────────────────────────────────────────────

_live_jobs: dict = {}   # job_id → {status, result, error}

class LiveTicketRequest(BaseModel):
    ticket_id: str

@app.post("/api/ticket/fetch-live")
async def fetch_live_ticket(body: LiveTicketRequest):
    """
    Fetch a ticket from Kapture by ticket_id, process through brain, return decision.
    Checks DB + scraped cache first. Falls back to live Playwright fetch.
    """
    import time, re as _re
    from src.llm.agent_brain import get_agent_brain
    from src.api.decision_store import save_decision

    ticket_id = body.ticket_id.strip()
    if not ticket_id:
        raise HTTPException(400, "ticket_id required")

    # ── 1. Check DB ───────────────────────────────────────────────
    conn = get_conn()
    row = conn.execute("SELECT * FROM decisions WHERE ticket_id=? ORDER BY id DESC", (ticket_id,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        try: d["thinking_steps"] = json.loads(d.get("thinking_steps") or "[]")
        except: d["thinking_steps"] = []
        return {"source": "db", "ticket_id": ticket_id, "decision": d}

    # ── 2. Check scraped cache ────────────────────────────────────
    AWB_RE = _re.compile(r'\b(VL[R]?\d{10,15})\b', _re.IGNORECASE)
    cached = None
    for path in ["data/scraped_tickets_v2.jsonl", "data/scraped_tickets.jsonl"]:
        p = Path(path)
        if not p.exists(): continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                t = json.loads(line)
                if str(t.get("ticket_id", "")) == ticket_id:
                    cached = t
                    break
            except: pass
        if cached: break

    if cached:
        queue = cached.get("queue_key") or cached.get("queue") or ""
        _raw_detail = cached.get("full_description") or cached.get("detail") or cached.get("subject", "")
        # Decode HTML entities and normalize whitespace left by old scraper
        detail = re.sub(r'<[^>]+>', ' ', _raw_detail)          # strip any residual tags
        detail = _html_mod.unescape(detail)                     # &amp; &nbsp; → & space
        detail = detail.replace('\u00a0', ' ').replace('\ufeff', '').replace('\u200b', '')
        detail = re.sub(r'[ \t]{3,}', '  ', detail).strip()    # collapse excessive whitespace
        subject = cached.get("subject_line") or cached.get("subject", "")[:120]
        hub_code = cached.get("hub_code_field") or ""
        awbs = list(set(AWB_RE.findall(detail + " " + subject)))
        awbs += (cached.get("awbs_on_page") or [])
        awbs = list(set(awbs))

        full_ticket = {
            "ticket_id": ticket_id, "task_id": str(cached.get("task_id", "")),
            "subject": subject, "queue": queue, "queue_key": queue,
            "detail": detail, "hub_code": hub_code,
            "awb_numbers": awbs,
            "created_time": cached.get("created_time", ""),
            "email": cached.get("email", ""), "phone": str(cached.get("phone", "")),
        }
        brain = get_agent_brain()
        decision = brain.process(full_ticket, [])
        usage = getattr(decision, "usage", {}) or {}
        row_id = save_decision(full_ticket, decision, usage)
        _c2 = get_conn()
        d = dict(_c2.execute("SELECT * FROM decisions WHERE id=?", (row_id,)).fetchone() or {})
        _c2.close()
        try: d["thinking_steps"] = json.loads(d.get("thinking_steps") or "[]")
        except: d["thinking_steps"] = []
        return {"source": "cache", "ticket_id": ticket_id, "hub_code": hub_code, "decision": d}

    # ── 3. Live fetch from Kapture via Playwright ─────────────────
    job_id = f"live_{ticket_id}_{int(time.time())}"
    _live_jobs[job_id] = {"status": "running", "ticket_id": ticket_id}

    async def _run_live():
        try:
            from playwright.async_api import async_playwright
            from scrape_tickets_v2 import login, extract_ticket, BASE_URL

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context()
                page = await ctx.new_page()
                await login(page)

                # Search for ticket in the list API
                search_result = await page.evaluate(f"""
                    async () => {{
                        const body = new URLSearchParams({{
                            sort_by_column: 'last_conversation_time', type: '7',
                            status: 'C', folder_id: '-1', query: '{ticket_id}',
                            page_no: '0', sort_type: 'desc', page_size: '10',
                            response_type: 'json', key_beautify: 'yes', isElasticSearch: 'true'
                        }});
                        const r = await fetch('/api/version3/ticket/get-ticket-list', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                            body: body.toString()
                        }});
                        return await r.json();
                    }}
                """)
                tickets = (search_result.get("response") or {}).get("tickets") or []
                if not tickets:
                    # try open queue too
                    search_result2 = await page.evaluate(f"""
                        async () => {{
                            const body = new URLSearchParams({{
                                sort_by_column: 'last_conversation_time', type: '7',
                                status: 'O', folder_id: '-1', query: '{ticket_id}',
                                page_no: '0', sort_type: 'desc', page_size: '10',
                                response_type: 'json', key_beautify: 'yes', isElasticSearch: 'true'
                            }});
                            const r = await fetch('/api/version3/ticket/get-ticket-list', {{
                                method: 'POST',
                                headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                                body: body.toString()
                            }});
                            return await r.json();
                        }}
                    """)
                    tickets = (search_result2.get("response") or {}).get("tickets") or []

                if not tickets:
                    _live_jobs[job_id] = {"status": "error", "ticket_id": ticket_id,
                                          "error": f"Ticket {ticket_id} not found in Kapture"}
                    await browser.close()
                    return

                t = tickets[0]
                task_id = str(t.get("id", ""))
                queue   = t.get("queueKey", "")
                subject = (t.get("subject") or t.get("detail", ""))[:120]

                detail_data = await extract_ticket(page, task_id, ticket_id)
                await browser.close()

            hub_code = detail_data.get("hub_code_field", "")
            full_desc = (detail_data.get("full_description") or
                         detail_data.get("page_text_snippet", "")[:1000])
            awbs = list(set(AWB_RE.findall(full_desc + " " + subject)))
            awbs += detail_data.get("awbs_on_page", [])
            awbs = list(set(awbs))

            full_ticket = {
                "ticket_id": ticket_id, "task_id": task_id,
                "subject": detail_data.get("subject_line") or subject,
                "queue": queue, "queue_key": queue, "detail": full_desc,
                "hub_code": hub_code, "awb_numbers": awbs,
                "created_time": t.get("createdTime", ""),
                "email": t.get("email", ""), "phone": str(t.get("phone", "")),
                "attachment_urls": detail_data.get("attachment_urls", []),
            }

            brain = get_agent_brain()
            decision = brain.process(full_ticket, [])
            usage = getattr(decision, "usage", {}) or {}
            from src.api.decision_store import save_decision as _save
            row_id = _save(full_ticket, decision, usage)

            _live_jobs[job_id] = {
                "status": "done",
                "ticket_id": ticket_id,
                "hub_code": hub_code,
                "attachment_urls": full_ticket["attachment_urls"],
                "awbs": awbs,
                "decision": {
                    "action": decision.action,
                    "scenario": decision.scenario_identified,
                    "confidence": decision.confidence,
                    "response_draft": decision.response_to_captain,
                    "escalation_queue": decision.escalation_queue,
                    "stuck_question": decision.stuck_question,
                    "reasoning": decision.reasoning,
                    "thinking_steps": getattr(decision, "thinking_steps", []),
                    "db_id": row_id,
                },
            }
        except Exception as e:
            _live_jobs[job_id] = {"status": "error", "ticket_id": ticket_id, "error": str(e)}

    asyncio.create_task(_run_live())
    return {"source": "live_fetch", "job_id": job_id, "status": "running",
            "message": "Fetching from Kapture — poll /api/ticket/job/{job_id}"}


@app.get("/api/ticket/job/{job_id}")
def poll_live_job(job_id: str):
    """Poll status of a live ticket fetch job."""
    result = _live_jobs.get(job_id)
    if result is None:
        raise HTTPException(404, "Job not found")
    return result


if __name__ == "__main__":
    print("\n  Valmo L1 Agent Dashboard")
    print("  Open http://localhost:8080 in your browser\n")
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)
