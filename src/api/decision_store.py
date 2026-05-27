"""
SQLite-backed store for agent decisions.
Tracks every ticket the agent processes — used for dashboard metrics.
"""
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(__file__).parent.parent.parent / "data" / "decisions.db"

# SLA hours per queue (from SOPs)
SLA_HOURS = {
    "losses": 72, "ld": 72, "w- ld": 72, "shipment_shortage": 72,
    "payments": 12, "payment": 12,
    "orders": 24, "planning": 24,
    "cod": 48, "cash": 48,
}
DEFAULT_SLA_HOURS = 24
HUMAN_COST_PER_TICKET = 15  # Rs. estimated cost per human L1 resolution


def _get_sla(queue: str) -> int:
    q = (queue or "").lower()
    for k, v in SLA_HOURS.items():
        if k in q:
            return v
    return DEFAULT_SLA_HOURS


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id         TEXT NOT NULL,
            task_id           TEXT,         -- Kapture internal task ID for reply sending
            subject           TEXT,
            queue             TEXT,
            awbs              TEXT,         -- JSON array
            action            TEXT,         -- respond|escalate|needs_info|stuck
            scenario          TEXT,
            confidence        REAL,
            auto_send         INTEGER,      -- 0/1
            response_draft    TEXT,
            escalation_queue  TEXT,
            escalation_reason TEXT,
            stuck_question    TEXT,
            missing_fields    TEXT,         -- JSON array
            reasoning         TEXT,
            review_status     TEXT DEFAULT 'pending',  -- pending|approved|rejected|sent
            reviewer_note     TEXT,
            reviewed_at       TEXT,
            created_at        TEXT NOT NULL,
            resolved_at       TEXT,
            ticket_created_at TEXT,
            sla_hours         INTEGER,
            sla_breached      INTEGER DEFAULT 0,
            last_msg_time     TEXT,         -- last_conversation_time from Kapture (for multi-turn)
            thinking_steps    TEXT          -- JSON array of step-by-step reasoning trace
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ticket_id ON decisions(ticket_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON decisions(created_at)")
    # Migrations for existing DBs
    for col, definition in [
        ("task_id",             "TEXT"),
        ("last_msg_time",       "TEXT"),
        ("thinking_steps",      "TEXT"),
        ("description",         "TEXT"),
        ("clean_problem",       "TEXT"),
        ("ops_translation",     "TEXT"),
        ("scenario_matches",    "TEXT"),   # JSON array of top 3
        ("approved_scenario_id","TEXT"),
        ("approval_status",     "TEXT DEFAULT 'auto'"),  # pending_scenario|approved|auto
        ("input_tokens",        "INTEGER DEFAULT 0"),
        ("output_tokens",       "INTEGER DEFAULT 0"),
        ("gemini_cost_inr",     "REAL DEFAULT 0.0"),
        ("guardrail_triggered", "TEXT"),   # "" | "rule_1_unverified_claim" | "rule_2_family_mismatch"
        ("reviewer_corrected_scenario", "TEXT"),  # what reviewer said the scenario should have been
        ("reviewer_corrected_action",   "TEXT"),  # what reviewer said the action should have been
    ]:
        try:
            conn.execute(f"ALTER TABLE decisions ADD COLUMN {col} {definition}")
        except Exception:
            pass  # column already exists
    conn.commit()
    conn.close()


def save_decision(ticket: Dict, decision, usage: Dict = None) -> int:
    """Save a BrainDecision to the DB. Returns row id.
    usage = {"input_tokens": int, "output_tokens": int, "cost_inr": float}
    """
    now = datetime.now(timezone.utc).isoformat()
    sla = _get_sla(ticket.get("queue", ticket.get("queue_key", "")))

    # Detect SLA breach
    ticket_created = ticket.get("created_time") or ticket.get("created_at")
    sla_breached = 0
    if ticket_created:
        try:
            created_dt = datetime.fromisoformat(ticket_created.replace("Z", "+00:00"))
            elapsed_h = (datetime.now(timezone.utc) - created_dt).total_seconds() / 3600
            sla_breached = 1 if elapsed_h > sla else 0
        except Exception:
            pass

    # Full description for the dashboard's "Captain's Message" panel.
    # ONLY two safe sources: captain_problem (role-aware) or full_description
    # (canonical please_describe_issue). Do NOT fall back to ticket.detail,
    # description, or body — Kapture stores L1 dispose drafts under those
    # names. Do NOT fall back to subject — that's metadata, not the message.
    # If both safe sources are empty, store empty string. The dashboard will
    # render "(no captain text)" which is the correct signal that the captain
    # did not provide a problem statement.
    full_desc = (
        ticket.get("captain_problem") or
        ticket.get("full_description") or
        ""
    )

    u = usage or {}
    inp_tok = u.get("input_tokens", 0)
    out_tok = u.get("output_tokens", 0)
    cost_inr = u.get("cost_inr", 0.0)

    clean_problem = getattr(decision, "clean_problem", "") or ""

    guardrail = getattr(decision, "guardrail_triggered", "") or ""

    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO decisions
          (ticket_id, task_id, subject, description, queue, awbs, action, scenario, confidence,
           auto_send, response_draft, escalation_queue, escalation_reason,
           stuck_question, missing_fields, reasoning,
           review_status, created_at, ticket_created_at, sla_hours, sla_breached,
           last_msg_time, thinking_steps, input_tokens, output_tokens, gemini_cost_inr,
           clean_problem, guardrail_triggered)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        str(ticket.get("ticket_id", "")),
        str(ticket.get("task_id", "") or ""),
        ticket.get("subject", ""),
        full_desc,
        ticket.get("queue", ticket.get("queue_key", "")),
        json.dumps(ticket.get("awb_numbers", [])),
        decision.action,
        decision.scenario_identified,
        decision.confidence,
        1 if decision.auto_send else 0,
        decision.response_to_captain,
        decision.escalation_queue,
        decision.escalation_reason,
        decision.stuck_question,
        json.dumps(decision.missing_fields),
        decision.reasoning,
        "sent" if decision.auto_send else "pending",
        now,
        ticket_created,
        sla,
        sla_breached,
        ticket.get("last_conversation_time", ""),
        json.dumps(getattr(decision, "thinking_steps", [])),
        inp_tok, out_tok, cost_inr,
        clean_problem,
        guardrail,
    ))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def approve_decision(row_id: int, note: str = "") -> bool:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    row = conn.execute("SELECT * FROM decisions WHERE id=?", (row_id,)).fetchone()
    conn.execute("""
        UPDATE decisions
        SET review_status='approved', reviewer_note=?, reviewed_at=?, resolved_at=?
        WHERE id=? AND review_status='pending'
    """, (note, now, now, row_id))
    changed = conn.total_changes
    conn.commit(); conn.close()

    # RAG learning — feed approved decision back as a precedent
    if changed > 0 and row:
        try:
            from src.llm.sop_store import get_sop_store
            ticket_id = row["ticket_id"]
            rag_text = f"""RESOLVED EXAMPLE — {row['queue']} queue
Ticket: {ticket_id}
Problem: {row['clean_problem'] or row['subject']}
Scenario matched: {row['scenario']}
Action taken: {row['action']}
Response sent: {(row['response_draft'] or '')[:400]}
Reasoning: {(row['reasoning'] or '')[:300]}"""
            get_sop_store().add_knowledge(
                rag_text,
                source=f"resolved_{ticket_id}",
                content_type="resolved_precedent",
            )
        except Exception:
            pass

    return changed > 0


def reject_decision(row_id: int, note: str = "",
                    corrected_scenario: str = "", corrected_action: str = "") -> bool:
    """Mark a decision as rejected. corrected_scenario / corrected_action are
    optional — when reviewer provides them they feed the per-scenario
    flip-rate stats. Empty strings are stored as NULL so 'rejected with
    correction' counts only rows where reviewer actually disagreed with
    the scenario_id or action."""
    now = datetime.now(timezone.utc).isoformat()
    cs = (corrected_scenario or "").strip() or None
    ca = (corrected_action or "").strip() or None
    conn = get_conn()
    row = conn.execute("SELECT * FROM decisions WHERE id=?", (row_id,)).fetchone()
    conn.execute("""
        UPDATE decisions
        SET review_status='rejected', reviewer_note=?, reviewed_at=?,
            reviewer_corrected_scenario=?, reviewer_corrected_action=?
        WHERE id=? AND review_status='pending'
    """, (note, now, cs, ca, row_id))
    changed = conn.total_changes
    conn.commit(); conn.close()

    # ── Learning loop: reviewer-corrected rejections feed back as
    # CORRECTED PRECEDENTS so future similar tickets see "agent picked X,
    # reviewer said correct answer was Y". The prompt formatter routes
    # resolved_precedent chunks under "RESOLVED PRECEDENTS" with the
    # explicit precedence rule (SOP wins on conflict). The "CORRECTED
    # EXAMPLE" prefix lets the model recognise it as a calibration signal.
    if changed > 0 and row and cs:
        try:
            from src.llm.sop_store import get_sop_store
            ticket_id = row["ticket_id"]
            rag_text = f"""CORRECTED EXAMPLE — {row['queue']} queue
Ticket: {ticket_id}
Problem: {row['clean_problem'] or row['subject']}
Agent originally picked: scenario={row['scenario']} action={row['action']}
REVIEWER CORRECTED to: scenario={cs}{f' action={ca}' if ca else ''}
Reviewer note: {note or '(none provided)'}
Original agent reasoning: {(row['reasoning'] or '')[:300]}"""
            get_sop_store().add_knowledge(
                rag_text,
                source=f"rejected_corrected_{ticket_id}",
                content_type="resolved_precedent",
            )
        except Exception:
            pass

    return changed > 0


def get_flip_rates() -> list:
    """Per-scenario flip-rate stats. Counts decisions grouped by
    scenario_identified. flip_rate = rejected_with_correction / total."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            scenario AS scenario,
            COUNT(*) AS total,
            SUM(CASE WHEN review_status='approved' THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN review_status='rejected' THEN 1 ELSE 0 END) AS rejected,
            SUM(CASE WHEN review_status='rejected'
                       AND reviewer_corrected_scenario IS NOT NULL
                       AND reviewer_corrected_scenario != ''
                     THEN 1 ELSE 0 END) AS rejected_with_correction,
            SUM(CASE WHEN review_status='sent' THEN 1 ELSE 0 END) AS auto_sent,
            SUM(CASE WHEN review_status='pending' THEN 1 ELSE 0 END) AS pending
        FROM decisions
        WHERE scenario IS NOT NULL AND scenario != ''
        GROUP BY scenario
    """).fetchall()
    conn.close()
    out = []
    for r in rows:
        total = int(r["total"] or 0)
        rwc = int(r["rejected_with_correction"] or 0)
        out.append({
            "scenario": r["scenario"],
            "total":    total,
            "approved": int(r["approved"] or 0),
            "rejected": int(r["rejected"] or 0),
            "rejected_with_correction": rwc,
            "auto_sent": int(r["auto_sent"] or 0),
            "pending":   int(r["pending"] or 0),
            "flip_rate": round(rwc / total, 3) if total else 0.0,
        })
    # Sort flip_rate desc, then total desc as a tiebreak so high-volume
    # well-behaved scenarios show below high-flip ones
    out.sort(key=lambda x: (-x["flip_rate"], -x["total"]))
    return out


def mark_sent(row_id: int):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    conn.execute("UPDATE decisions SET review_status='sent', resolved_at=? WHERE id=?", (now, row_id))
    conn.commit(); conn.close()


def get_decisions(limit: int = 50, offset: int = 0, status_filter: str = "") -> List[Dict]:
    conn = get_conn()
    if status_filter:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE review_status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status_filter, limit, offset)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> Dict:
    conn = get_conn()

    total        = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    auto_sent    = conn.execute("SELECT COUNT(*) FROM decisions WHERE auto_send=1").fetchone()[0]
    escalated    = conn.execute("SELECT COUNT(*) FROM decisions WHERE action='escalate'").fetchone()[0]
    stuck        = conn.execute("SELECT COUNT(*) FROM decisions WHERE action='stuck'").fetchone()[0]
    needs_info   = conn.execute("SELECT COUNT(*) FROM decisions WHERE action='needs_info'").fetchone()[0]
    sla_breached = conn.execute("SELECT COUNT(*) FROM decisions WHERE sla_breached=1").fetchone()[0]
    approved     = conn.execute("SELECT COUNT(*) FROM decisions WHERE review_status='approved'").fetchone()[0]
    rejected     = conn.execute("SELECT COUNT(*) FROM decisions WHERE review_status='rejected'").fetchone()[0]
    pending      = conn.execute("SELECT COUNT(*) FROM decisions WHERE review_status='pending'").fetchone()[0]

    # Average confidence
    avg_conf_row = conn.execute("SELECT AVG(confidence) FROM decisions WHERE confidence > 0").fetchone()[0]
    avg_conf = round(avg_conf_row or 0, 1)

    # ART: avg minutes from created_at to resolved_at for resolved tickets
    art_rows = conn.execute("""
        SELECT created_at, resolved_at FROM decisions
        WHERE resolved_at IS NOT NULL AND created_at IS NOT NULL
    """).fetchall()
    art_minutes = 0.0
    if art_rows:
        deltas = []
        for r in art_rows:
            try:
                c = datetime.fromisoformat(r[0].replace("Z", "+00:00"))
                s = datetime.fromisoformat(r[1].replace("Z", "+00:00"))
                deltas.append((s - c).total_seconds() / 60)
            except Exception:
                pass
        if deltas:
            art_minutes = round(sum(deltas) / len(deltas), 1)

    # Queue breakdown
    queue_rows = conn.execute("""
        SELECT queue, COUNT(*) as cnt FROM decisions GROUP BY queue ORDER BY cnt DESC
    """).fetchall()

    # Action breakdown
    action_rows = conn.execute("""
        SELECT action, COUNT(*) as cnt FROM decisions GROUP BY action
    """).fetchall()

    # Guardrail breakdown — counts of decisions where a code-enforced
    # guardrail overrode the model output. Empty / NULL means no guardrail fired.
    try:
        guardrail_rows = conn.execute("""
            SELECT COALESCE(guardrail_triggered,'') AS g, COUNT(*) AS cnt
            FROM decisions
            WHERE COALESCE(guardrail_triggered,'') != ''
            GROUP BY g
        """).fetchall()
    except Exception:
        guardrail_rows = []
    guardrail_breakdown = [{"guardrail": r[0], "count": r[1]} for r in guardrail_rows]
    guardrail_total = sum(r["count"] for r in guardrail_breakdown)

    # Today's tickets
    today = datetime.now(timezone.utc).date().isoformat()
    today_count = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]

    # Gemini cost tracking
    cost_row = conn.execute(
        "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(gemini_cost_inr),0) FROM decisions"
    ).fetchone()
    total_input_tokens  = int(cost_row[0])
    total_output_tokens = int(cost_row[1])
    total_gemini_cost   = round(cost_row[2], 2)

    today_cost_row = conn.execute(
        "SELECT COALESCE(SUM(gemini_cost_inr),0) FROM decisions WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()
    today_gemini_cost = round(today_cost_row[0], 2)

    conn.close()

    auto_res_rate = round((auto_sent / total * 100) if total else 0, 1)
    sla_compliance = round(((total - sla_breached) / total * 100) if total else 0, 1)
    human_cost_equiv = total * HUMAN_COST_PER_TICKET
    roi_multiplier = round(human_cost_equiv / total_gemini_cost, 1) if total_gemini_cost > 0 else 0

    return {
        "total": total,
        "today": today_count,
        "auto_sent": auto_sent,
        "escalated": escalated,
        "stuck": stuck,
        "needs_info": needs_info,
        "pending_review": pending,
        "approved": approved,
        "rejected": rejected,
        "sla_breached": sla_breached,
        "avg_confidence": avg_conf,
        "art_minutes": art_minutes,
        "auto_resolution_rate": auto_res_rate,
        "sla_compliance": sla_compliance,
        "cost_saved_inr": human_cost_equiv - total_gemini_cost,
        "human_cost_equiv_inr": human_cost_equiv,
        "gemini_cost_total_inr": total_gemini_cost,
        "gemini_cost_today_inr": today_gemini_cost,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "roi_multiplier": roi_multiplier,
        "queue_breakdown": [{"queue": r[0] or "Unknown", "count": r[1]} for r in queue_rows],
        "action_breakdown": [{"action": r[0], "count": r[1]} for r in action_rows],
        "guardrails_total": guardrail_total,
        "guardrail_breakdown": guardrail_breakdown,
    }


# Initialise on import
init_db()
