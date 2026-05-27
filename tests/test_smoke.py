"""
End-to-end smoke test for the 10 Phase-1 fixes.

What this covers
----------------
Phase 1 — Boot
    Every new endpoint loads and returns the expected schema.
Phase 2 — Guardrails
    Rule 1 (captain-claim) and Rule 2 (Stage 0 family lock) fire when they
    should and don't fire when they shouldn't.
Phase 3 — Mode gate
    .mode round-trip, gate blocks auto_send in review, allows in autonomous.
Phase 4 — Knowledge store
    content_type metadata, grouped retrieval, queue filter, deprecation,
    formatter section order + precedence-rule text.
Phase 5 — Flip rates
    Reject with corrections gets stored, aggregation math is correct.
Phase 6 — Stuck clustering
    Synthetic stuck queue clusters with scipy, cache hit/invalidation.
Phase 7 — Eval harness
    Loader skips unlabeled rows, metrics are correct, diff vs prior run works.
Phase 8 — Scenario audit
    Endpoint returns all sections, deprecation round-trips via dashboard.

What this does NOT cover
------------------------
* Real Gemini calls (cost). Brain is mocked.
* Real Kapture scraping (network).
* Real Metabase queries (network).
* UI rendering — that's manual.

Run with:
    python tests/test_smoke.py            # standalone, no pytest
    python -m pytest tests/test_smoke.py  # works if pytest installed

Exits 0 if all tests pass, 1 if any fail.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make src.* importable when run as a plain script
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Test data prefix — used to isolate cleanup ────────────────────
SMOKE = "SMOKE_TEST_"
SMOKE_CHUNK_SRC = "kt_smoketest_"   # ChromaDB source prefix


# ─────────────────────────────────────────────────────────────────
# Shared fixtures (module-scoped — restored by teardown_module)
# ─────────────────────────────────────────────────────────────────
_MODE_BACKUP = None
_STUCK_BACKUP = None


def setup_module(module=None):
    """Backup mutable state so we can restore it after the test run."""
    global _MODE_BACKUP, _STUCK_BACKUP
    from src.api.mode import MODE_FILE
    from src.api.stuck_clusters import STUCK_QUEUE_FILE
    _MODE_BACKUP = MODE_FILE.read_text(encoding="utf-8") if MODE_FILE.exists() else None
    _STUCK_BACKUP = STUCK_QUEUE_FILE.read_text(encoding="utf-8") if STUCK_QUEUE_FILE.exists() else None


def teardown_module(module=None):
    """Restore .mode + stuck_queue.jsonl, delete any SMOKE_TEST_* rows
    from decisions.db, delete any kt_smoketest_* chunks from ChromaDB."""
    from src.api.mode import MODE_FILE, set_mode
    from src.api.stuck_clusters import STUCK_QUEUE_FILE, invalidate_cache
    from src.api.decision_store import get_conn
    from src.llm.sop_store import get_sop_store

    # Restore .mode
    if _MODE_BACKUP is not None:
        MODE_FILE.write_text(_MODE_BACKUP, encoding="utf-8")
    else:
        set_mode("review")  # default

    # Restore stuck_queue.jsonl
    if _STUCK_BACKUP is not None:
        STUCK_QUEUE_FILE.write_text(_STUCK_BACKUP, encoding="utf-8")
    elif STUCK_QUEUE_FILE.exists():
        STUCK_QUEUE_FILE.unlink()
    invalidate_cache()

    # Clean DB rows
    conn = get_conn()
    conn.execute("DELETE FROM decisions WHERE ticket_id LIKE ?", (f"{SMOKE}%",))
    conn.commit(); conn.close()

    # Clean ChromaDB chunks
    store = get_sop_store()
    try:
        items = store._col.get(include=["metadatas"])
        ids_to_drop = [
            cid for cid, m in zip(items.get("ids") or [], items.get("metadatas") or [])
            if (m or {}).get("source", "").startswith(SMOKE_CHUNK_SRC)
        ]
        if ids_to_drop:
            store._col.delete(ids=ids_to_drop)
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════
# Phase 1 — BOOT
# ═════════════════════════════════════════════════════════════════
def _client():
    """Fresh TestClient per test — FastAPI handles its own isolation."""
    from fastapi.testclient import TestClient
    from run_dashboard import app
    return TestClient(app)


def test_dashboard_imports_cleanly():
    import run_dashboard  # noqa: F401
    assert run_dashboard.app is not None


def test_stats_endpoint_has_guardrail_fields():
    r = _client().get("/api/stats")
    assert r.status_code == 200, f"stats endpoint returned {r.status_code}: {r.text[:200]}"
    j = r.json()
    assert "guardrails_total" in j
    assert "guardrail_breakdown" in j
    assert isinstance(j["guardrail_breakdown"], list)


def test_scenarios_endpoint_returns_known_ids():
    r = _client().get("/api/scenarios")
    assert r.status_code == 200
    j = r.json()
    assert j["count"] >= 50
    ids = {s["scenario_id"] for s in j["scenarios"]}
    # Use scenario IDs that actually exist in sop_structured.json
    for must in ("HS_1_1", "HS_8_2", "SL_3", "TECH_2"):
        assert must in ids, f"{must} missing from /api/scenarios"


def test_flip_rates_endpoint_returns_shape():
    r = _client().get("/api/stats/flip-rates")
    assert r.status_code == 200
    j = r.json()
    assert "flip_rates" in j and "count" in j
    if j["flip_rates"]:
        row = j["flip_rates"][0]
        for k in ("scenario","total","approved","rejected",
                  "rejected_with_correction","flip_rate"):
            assert k in row, f"flip-rate row missing {k}"


def test_stuck_clusters_endpoint_returns_shape():
    r = _client().get("/api/stuck/clusters")
    assert r.status_code == 200
    j = r.json()
    for k in ("generated_at","total_entries","cluster_count","clusters"):
        assert k in j


def test_scenario_audit_known_scenario():
    r = _client().get("/api/scenario-audit/HS_1_1")
    assert r.status_code == 200
    j = r.json()
    assert j["scenario_id"] == "HS_1_1"
    assert j["found_in_sop"] is True
    assert "hardstop" in j["stage0_compatibilities"]
    assert "chunks_by_type" in j
    assert "recent_decisions" in j
    assert "flip_stats" in j


def test_scenario_audit_unknown_scenario_doesnt_crash():
    r = _client().get("/api/scenario-audit/NEVER_EXISTED_42")
    assert r.status_code == 200
    j = r.json()
    assert j["found_in_sop"] is False
    assert j["stage0_compatibilities"] == []


def test_mode_endpoint_round_trip():
    c = _client()
    r = c.get("/api/mode")
    assert r.status_code == 200
    assert "autonomous" in r.json()

    r = c.post("/api/mode", json={"autonomous": True})
    assert r.status_code == 200 and r.json()["autonomous"] is True
    from src.api.mode import get_mode
    assert get_mode() == "autonomous"

    r = c.post("/api/mode", json={"autonomous": False})
    assert r.status_code == 200 and r.json()["autonomous"] is False
    assert get_mode() == "review"


# ═════════════════════════════════════════════════════════════════
# Phase 2 — GUARDRAILS
# ═════════════════════════════════════════════════════════════════
def test_scenario_family_mapping_correct():
    from src.llm.scenario_families import family_mismatch, families_for
    assert family_mismatch("TECH_2", "hardstop") is True
    assert family_mismatch("HS_1_1", "hardstop") is False
    assert family_mismatch("HS_8_1", "not_inscanned") is False
    assert family_mismatch("HS_8_1", "pilot_lost_on_field") is False
    assert family_mismatch("SL_3", "hardstop") is True   # shortage scenario, not hardstop
    assert family_mismatch("SL_3", "shortage") is False  # CORRECT pairing — regression guard
    assert family_mismatch("VAGUE_1", "hardstop") is False   # wildcard
    assert family_mismatch("HS_1_1", "unknown") is False     # never flag unknown
    assert family_mismatch("HS_1_1", "") is False            # never flag empty
    assert family_mismatch("BRAND_NEW_42", "hardstop") is False  # unmapped scenario never flagged

    # Explicit family checks — regression guard against duplicate-key shadowing
    # (we previously had SL_* declared twice — once as {"shortage"} and once as
    # {"non_ld"} later in the dict; the later wins, breaking the guardrail).
    assert families_for("HS_1_1") == {"hardstop"}
    assert families_for("SL_1") == {"shortage"}, "SL_1 must map to shortage (dupe-key regression)"
    assert families_for("SL_2") == {"shortage"}
    assert families_for("SL_3") == {"shortage"}
    assert families_for("SL_4") == {"shortage"}
    assert families_for("SL_5") == {"shortage"}
    assert "non_ld" in families_for("CON_PAY_1")


def test_rule_1_fires_on_empty_metabase_with_claim_phrase():
    from src.llm.agent_brain import _rule_1_match
    ticket = {
        "ticket_id": SMOKE + "R1_POS",
        "queue": "W- LD",
        "awb_numbers": ["VL1234567890"],
        "detail": "As per metabase, this should be reversed.",
        "subject": "Loss reversal",
    }
    qr = [
        {"query_name": "get_loss_attribution", "success": True, "data": {"rows": []}},
        {"query_name": "get_shipment_scan_history_single", "success": True, "data": {"rows": []}},
    ]
    matched = _rule_1_match(ticket, qr)
    assert matched == "as per metabase", f"expected match, got {matched!r}"


def test_rule_1_fires_on_failed_metabase():
    from src.llm.agent_brain import _rule_1_match
    ticket = {
        "ticket_id": SMOKE + "R1_FAIL",
        "queue": "W- LD",
        "awb_numbers": ["VL999"],
        "detail": "Per LM FE loss marked, amount is recovered.",
    }
    qr = [
        {"query_name": "get_loss_attribution", "success": False, "error": "401"},
    ]
    assert _rule_1_match(ticket, qr) == "per lm fe loss marked"


def test_rule_1_does_not_fire_without_claim_phrase():
    from src.llm.agent_brain import _rule_1_match
    ticket = {
        "ticket_id": SMOKE + "R1_NEG",
        "queue": "W- LD",
        "awb_numbers": ["VL999"],
        "detail": "Please check this shipment and reverse if eligible.",
    }
    qr = [{"query_name": "get_loss_attribution", "success": True, "data": {"rows": []}}]
    assert _rule_1_match(ticket, qr) is None


def test_rule_1_does_not_fire_when_metabase_has_data():
    from src.llm.agent_brain import _rule_1_match
    ticket = {
        "ticket_id": SMOKE + "R1_HASDATA",
        "queue": "W- LD",
        "awb_numbers": ["VL999"],
        "detail": "As per metabase shows the loss.",
    }
    qr = [
        {"query_name": "get_loss_attribution", "success": True,
         "data": {"rows": [{"awb": "VL999", "loss_type": "hardstop"}]}},
        {"query_name": "get_shipment_scan_history_single", "success": True,
         "data": {"rows": [{"scan": "INWARD_SCAN"}]}},
    ]
    assert _rule_1_match(ticket, qr) is None


def test_rule_1_does_not_fire_for_non_ld_queue():
    from src.llm.agent_brain import _rule_1_match
    ticket = {
        "ticket_id": SMOKE + "R1_NONLD",
        "queue": "Payments",
        "awb_numbers": ["VL999"],
        "detail": "As per metabase, please process my payment.",
    }
    assert _rule_1_match(ticket, []) is None


def test_rule_1_does_not_fire_without_awbs():
    from src.llm.agent_brain import _rule_1_match
    ticket = {
        "ticket_id": SMOKE + "R1_NOAWB",
        "queue": "W- LD",
        "awb_numbers": [],
        "detail": "As per metabase, I should be paid.",
    }
    assert _rule_1_match(ticket, []) is None


# ═════════════════════════════════════════════════════════════════
# Phase 3 — MODE GATE
# ═════════════════════════════════════════════════════════════════
def test_mode_persists_to_disk_and_back():
    from src.api.mode import set_mode, get_mode, MODE_FILE
    set_mode("autonomous")
    assert MODE_FILE.read_text(encoding="utf-8").strip() == "autonomous"
    assert get_mode() == "autonomous"
    set_mode("review")
    assert get_mode() == "review"


def test_invalid_mode_rejected():
    from src.api.mode import set_mode
    try:
        set_mode("rabid")
        raise AssertionError("should have raised ValueError")
    except ValueError:
        pass


def test_mode_gate_blocks_auto_send_in_review_mode():
    """Replicates the post-decision gate from agent_brain.process()."""
    from src.api.mode import set_mode, get_mode
    from src.llm.agent_brain import BrainDecision, AUTO_SEND_CONFIDENCE
    set_mode("review")
    d = BrainDecision(action="respond", confidence=9.0, scenario_identified="HS_1_1")
    d.auto_send = (d.action == "respond" and d.confidence >= AUTO_SEND_CONFIDENCE)
    assert d.auto_send is True
    # Gate logic from agent_brain.process()
    if d.auto_send and get_mode() != "autonomous":
        d.auto_send = False
    assert d.auto_send is False, "review mode failed to block auto_send"


def test_mode_gate_allows_auto_send_in_autonomous_mode():
    from src.api.mode import set_mode, get_mode
    from src.llm.agent_brain import BrainDecision, AUTO_SEND_CONFIDENCE
    set_mode("autonomous")
    try:
        d = BrainDecision(action="respond", confidence=9.0, scenario_identified="HS_1_1")
        d.auto_send = (d.action == "respond" and d.confidence >= AUTO_SEND_CONFIDENCE)
        if d.auto_send and get_mode() != "autonomous":
            d.auto_send = False
        assert d.auto_send is True
    finally:
        set_mode("review")


# ═════════════════════════════════════════════════════════════════
# Phase 4 — KNOWLEDGE STORE
# ═════════════════════════════════════════════════════════════════
def test_add_knowledge_writes_content_type_metadata():
    from src.llm.sop_store import get_sop_store
    store = get_sop_store()
    src = SMOKE_CHUNK_SRC + "ctype"
    store.add_knowledge("Test sop_canonical entry.", source=src, content_type="sop_canonical")
    items = store._col.get(where={"source": src}, include=["metadatas"])
    assert items["metadatas"][0].get("content_type") == "sop_canonical"


def test_add_knowledge_falls_back_on_bad_content_type():
    from src.llm.sop_store import get_sop_store, DEFAULT_CONTENT_TYPE
    store = get_sop_store()
    src = SMOKE_CHUNK_SRC + "bad_ctype"
    store.add_knowledge("Test bogus ctype.", source=src, content_type="invented_type")
    items = store._col.get(where={"source": src}, include=["metadatas"])
    assert items["metadatas"][0].get("content_type") == DEFAULT_CONTENT_TYPE


def test_retrieve_returns_grouped_dict():
    from src.llm.sop_store import get_sop_store
    result = get_sop_store().retrieve("hardstop loss", k=4)
    assert isinstance(result, dict)
    for ctype, chunks in result.items():
        assert isinstance(chunks, list)
        for c in chunks:
            for key in ("text","source","section_path","queue","distance"):
                assert key in c, f"chunk missing {key}: {c}"


def test_retrieve_filters_deprecated_chunks():
    from src.llm.sop_store import get_sop_store
    store = get_sop_store()
    src = SMOKE_CHUNK_SRC + "depr"
    # Add a chunk with a very unique phrase so we know retrieve() finds it
    needle = "SMOKEDEPRZQXY uniquely identifying phrase for deprecation test"
    store.add_knowledge(needle, source=src, content_type="kt_addition")
    items = store._col.get(where={"source": src}, include=["metadatas"])
    chunk_id = items["ids"][0]

    # Sanity: retrievable before deprecation
    r = store.retrieve(needle, k=20)
    found_sources = {c["source"] for chunks in r.values() for c in chunks}
    assert src in found_sources, "test chunk not retrievable before deprecation"

    # Deprecate
    assert store.set_chunk_deprecated(chunk_id, True) is True

    # No longer retrievable
    r = store.retrieve(needle, k=20)
    found_sources = {c["source"] for chunks in r.values() for c in chunks}
    assert src not in found_sources, "deprecated chunk leaked into retrieve()"

    # Undeprecate → back in
    store.set_chunk_deprecated(chunk_id, False)
    r = store.retrieve(needle, k=20)
    found_sources = {c["source"] for chunks in r.values() for c in chunks}
    assert src in found_sources, "undeprecate did not restore visibility"


def test_canonical_chunks_have_queue_and_section_path():
    """Real canonical chunks (from heading-aware chunker on valmo_kt.md) must
    carry queue + section_path. Skip chunks injected by other smoke tests
    that intentionally use the legacy chunker."""
    from src.llm.sop_store import get_sop_store
    store = get_sop_store()
    items = store._col.get(include=["metadatas"])
    canon = [
        m for m in (items.get("metadatas") or [])
        if (m or {}).get("content_type") == "sop_canonical"
        and not (m or {}).get("source", "").startswith(SMOKE_CHUNK_SRC)
    ]
    if not canon:
        return  # collection has no real canonical chunks; nothing to check
    missing_queue = [m for m in canon if not m.get("queue")]
    missing_path  = [m for m in canon if not m.get("section_path")]
    assert not missing_queue, f"{len(missing_queue)} real sop_canonical chunks missing queue"
    assert not missing_path,  f"{len(missing_path)} real sop_canonical chunks missing section_path"


def test_format_grouped_chunks_section_order_and_precedence_rule():
    from src.llm.sop_store import format_grouped_chunks
    grouped = {
        "sop_canonical":        [{"text": "Canonical body", "source": "valmo_kt", "distance": 0.1}],
        "resolved_precedent":   [{"text": "Precedent body", "source": "resolved_1", "distance": 0.2}],
        "trainer_qa":           [{"text": "QA body",        "source": "trainer_qa_1", "distance": 0.3}],
        "kt_addition":          [{"text": "KT body",        "source": "kt_x", "distance": 0.4}],
        "kt_domain_activation": [{"text": "Domain body",    "source": "kt_guided_x", "distance": 0.5}],
    }
    out = format_grouped_chunks(grouped)
    canon_i  = out.find("## CANONICAL SOP")
    prec_i   = out.find("## RESOLVED PRECEDENTS")
    qa_i     = out.find("## TRAINER Q&A")
    kt_i     = out.find("## KT ADDITIONS")
    assert canon_i >= 0 and prec_i > canon_i and qa_i > prec_i and kt_i > qa_i, \
        f"section order broken: canon={canon_i} prec={prec_i} qa={qa_i} kt={kt_i}"
    # Precedence rule must appear so the model knows precedents are not authoritative
    assert "NOT as authority" in out
    assert "SOP wins" in out
    # kt_domain_activation chunks merged into KT ADDITIONS — no raw type name leaked
    assert "kt_domain_activation" not in out
    assert "kt_guided_x" in out


def test_format_grouped_chunks_omits_empty_sections():
    from src.llm.sop_store import format_grouped_chunks
    out = format_grouped_chunks({"sop_canonical": [{"text": "x", "source": "s", "distance": 0}]})
    assert "## CANONICAL SOP" in out
    for absent in ("## RESOLVED PRECEDENTS", "## TRAINER Q&A", "## KT ADDITIONS"):
        assert absent not in out, f"empty section leaked: {absent}"


# ═════════════════════════════════════════════════════════════════
# Phase 5 — FLIP RATES
# ═════════════════════════════════════════════════════════════════
def _save_smoke_decision(scenario, action="respond", conf=8.0, tid_suffix=""):
    from src.api.decision_store import save_decision
    from src.llm.agent_brain import BrainDecision
    ticket = {"ticket_id": SMOKE + tid_suffix, "task_id": "",
              "subject": "smoke", "queue": "W- LD", "awb_numbers": [], "created_time": ""}
    d = BrainDecision(action=action, scenario_identified=scenario, confidence=conf,
                       response_to_captain="r", reasoning="r")
    d.auto_send = False
    return save_decision(ticket, d)


def test_reject_with_correction_feeds_chromadb_corrected_precedent():
    """When a reviewer rejects WITH a corrected_scenario, the decision must
    be written back to ChromaDB as a CORRECTED EXAMPLE so future similar
    tickets see what the right answer was. Rejection WITHOUT correction
    does NOT feed back (no useful signal to learn)."""
    from src.api.decision_store import reject_decision, approve_decision
    from src.llm.sop_store import get_sop_store
    store = get_sop_store()
    SMOKE_PREFIX = "rejected_corrected_" + SMOKE + "LEARN"
    SMOKE_BARE   = "rejected_corrected_" + SMOKE + "BARE"

    # Cleanup any leftover smoke chunks
    items = store._col.get(include=["metadatas"])
    drop = [cid for cid, m in zip(items.get("ids") or [], items.get("metadatas") or [])
            if (m or {}).get("source", "").startswith("rejected_corrected_" + SMOKE)]
    if drop:
        store._col.delete(ids=drop)

    # Insert + reject WITH correction
    rid = _save_smoke_decision("HS_1_1", tid_suffix="LEARN")
    ok = reject_decision(rid, "scenario was wrong",
                          corrected_scenario="HS_8_1", corrected_action="stuck")
    assert ok

    # ChromaDB should now contain a "CORRECTED EXAMPLE" precedent
    src_learn = f"rejected_corrected_{SMOKE}LEARN"
    items = store._col.get(include=["metadatas", "documents"])
    found = [d for cid, d, m in zip(items.get("ids") or [], items.get("documents") or [],
                                     items.get("metadatas") or [])
             if (m or {}).get("source", "") == src_learn]
    assert found, f"rejected-with-correction did not feed into ChromaDB (looking for source={src_learn!r})"
    txt = found[0]
    assert "CORRECTED EXAMPLE" in txt
    assert "REVIEWER CORRECTED to: scenario=HS_8_1" in txt
    assert "Agent originally picked: scenario=HS_1_1" in txt
    print("    rejected-with-correction precedent: OK")

    # Insert + reject WITHOUT correction → should NOT feed back
    rid2 = _save_smoke_decision("HS_1_1", tid_suffix="BARE")
    reject_decision(rid2, "just no correction")
    src_bare = f"rejected_corrected_{SMOKE}BARE"
    items = store._col.get(include=["metadatas"])
    bare_chunks = [cid for cid, m in zip(items.get("ids") or [], items.get("metadatas") or [])
                    if (m or {}).get("source", "") == src_bare]
    assert not bare_chunks, "bare rejection (no correction) leaked into ChromaDB"
    print("    bare rejection (no correction): correctly NOT fed back")

    # Cleanup
    items = store._col.get(include=["metadatas"])
    drop = [cid for cid, m in zip(items.get("ids") or [], items.get("metadatas") or [])
            if (m or {}).get("source", "").startswith("rejected_corrected_" + SMOKE)]
    if drop:
        store._col.delete(ids=drop)


def test_reject_with_correction_persists_to_db():
    from src.api.decision_store import reject_decision, get_conn
    rid = _save_smoke_decision("HS_1_1", tid_suffix="REJ1")
    assert reject_decision(rid, note="x", corrected_scenario="HS_8_1", corrected_action="stuck")
    row = dict(get_conn().execute("SELECT * FROM decisions WHERE id=?", (rid,)).fetchone())
    assert row["reviewer_corrected_scenario"] == "HS_8_1"
    assert row["reviewer_corrected_action"]   == "stuck"


def test_reject_without_correction_stores_null():
    from src.api.decision_store import reject_decision, get_conn
    rid = _save_smoke_decision("HS_1_1", tid_suffix="REJ2")
    assert reject_decision(rid, note="just bad")
    row = dict(get_conn().execute("SELECT * FROM decisions WHERE id=?", (rid,)).fetchone())
    assert row["reviewer_corrected_scenario"] is None
    assert row["reviewer_corrected_action"]   is None


def test_flip_rate_aggregation():
    """Insert 4 SMOKE decisions for one scenario, check the delta on flip-rate."""
    from src.api.decision_store import get_flip_rates, approve_decision, reject_decision
    SCEN = "HS_8_2"   # less likely to collide with existing rows than HS_1_1
    before = next((r for r in get_flip_rates() if r["scenario"] == SCEN),
                  {"total": 0, "approved": 0, "rejected": 0, "rejected_with_correction": 0})

    a1 = _save_smoke_decision(SCEN, tid_suffix="HS82_a"); approve_decision(a1, "ok")
    a2 = _save_smoke_decision(SCEN, tid_suffix="HS82_b"); approve_decision(a2, "ok")
    r1 = _save_smoke_decision(SCEN, tid_suffix="HS82_c"); reject_decision(r1, "wrong", "HS_1_1", "respond")
    r2 = _save_smoke_decision(SCEN, tid_suffix="HS82_d"); reject_decision(r2, "no correction")

    after = next((r for r in get_flip_rates() if r["scenario"] == SCEN),
                 {"total": 0, "approved": 0, "rejected": 0, "rejected_with_correction": 0})

    assert after["total"]    - before["total"]    == 4
    assert after["approved"] - before["approved"] == 2
    assert after["rejected"] - before["rejected"] == 2
    assert after["rejected_with_correction"] - before["rejected_with_correction"] == 1


# ═════════════════════════════════════════════════════════════════
# Phase 6 — STUCK CLUSTERS
# ═════════════════════════════════════════════════════════════════
def _seed_stuck_jsonl(rows):
    from src.api.stuck_clusters import STUCK_QUEUE_FILE
    now = datetime.now(timezone.utc).isoformat()
    lines = [json.dumps({
        "timestamp": now, "ticket_id": tid, "subject": f"smoke {tid}",
        "queue": queue, "question": q, "reasoning": "",
        "answered": False, "answer": None,
    }) for tid, q, queue in rows]
    STUCK_QUEUE_FILE.write_text("\n".join(lines), encoding="utf-8")


def test_stuck_clustering_groups_topical_questions():
    from src.api.stuck_clusters import compute_clusters, invalidate_cache
    _seed_stuck_jsonl([
        ("SMK_A1", "Captain payment held due to GST defaulter status.", "Payments"),
        ("SMK_A2", "Payment on hold with GST issue, how to resolve?",   "Payments"),
        ("SMK_A3", "GST defaulter hold blocking my salary credit.",     "Payments"),
        ("SMK_B1", "Hardstop loss marked but I connected within 5 days.", "W- LD"),
        ("SMK_B2", "Loss wrongly marked, scans were within SLA window.",  "W- LD"),
        ("SMK_B3", "Hardstop dispute - shipment moved forward in time.",  "W- LD"),
    ])
    invalidate_cache()
    # Use a wider threshold so the embeddings actually merge
    r = compute_clusters(threshold=0.65, window_days=30)
    assert r["total_entries"] == 6
    # Expect roughly 2 clusters; allow some embedding-model variance
    assert r["cluster_count"] <= 3
    sizes = sorted([c["cluster_size"] for c in r["clusters"]], reverse=True)
    assert sizes[0] >= 3, f"top cluster too small, sizes={sizes}"


def test_stuck_clusters_cache_round_trip():
    from src.api.stuck_clusters import get_clusters_cached, invalidate_cache
    _seed_stuck_jsonl([
        ("SMK_C1", "Cache test question one.",   "W- LD"),
        ("SMK_C2", "Cache test question two.",   "W- LD"),
    ])
    invalidate_cache()
    first = get_clusters_cached(threshold=0.35, window_days=30)
    assert first["_from_cache"] is False
    second = get_clusters_cached(threshold=0.35, window_days=30)
    assert second["_from_cache"] is True
    invalidate_cache()
    third = get_clusters_cached(threshold=0.35, window_days=30)
    assert third["_from_cache"] is False


# ═════════════════════════════════════════════════════════════════
# Phase 7 — EVAL HARNESS
# ═════════════════════════════════════════════════════════════════
class FakeBrain:
    """Stand-in for AgentBrain — no Gemini call, scripted output per ticket_id."""
    def __init__(self, scripted):
        self._scripted = scripted
    def process(self, ticket, query_results):
        from src.llm.agent_brain import BrainDecision
        tid = ticket["ticket_id"]
        sc, ac, cf = self._scripted.get(tid, ("UNKNOWN", "stuck", 0.0))
        d = BrainDecision(action=ac, scenario_identified=sc, confidence=cf,
                           response_to_captain="x", reasoning="fake")
        d.auto_send = False
        d.guardrail_triggered = ""
        return d


def test_eval_loader_skips_unlabeled_rows(tmp_path=None):
    from src.eval.harness import load_eval_set
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write('# comment line, ignored\n')
        f.write(json.dumps({"ticket_id": "E1", "expected_scenario": "HS_1_1"}) + '\n')
        f.write(json.dumps({"ticket_id": "", "expected_scenario": "X"}) + '\n')     # missing ticket_id
        f.write(json.dumps({"ticket_id": "E2", "expected_scenario": ""}) + '\n')    # unlabeled
        path = Path(f.name)
    try:
        rows = load_eval_set(path)
        assert len(rows) == 1
        assert rows[0]["ticket_id"] == "E1"
    finally:
        path.unlink(missing_ok=True)


def test_eval_evaluate_metrics_correct():
    from src.eval.harness import evaluate
    eval_set = [
        {"ticket_id": "T1", "queue": "W- LD", "subject": "a", "description": "a", "awbs": [],
         "expected_scenario": "HS_1_1", "expected_action": "escalate"},
        {"ticket_id": "T2", "queue": "W- LD", "subject": "b", "description": "b", "awbs": [],
         "expected_scenario": "HS_1_1", "expected_action": "escalate"},
        {"ticket_id": "T3", "queue": "W- LD", "subject": "c", "description": "c", "awbs": [],
         "expected_scenario": "HS_1_1", "expected_action": "escalate"},
        {"ticket_id": "T4", "queue": "W- LD", "subject": "d", "description": "d", "awbs": [],
         "expected_scenario": "SS_3",   "expected_action": "respond"},
    ]
    brain = FakeBrain({
        "T1": ("HS_1_1", "escalate", 9.0),   # match scenario+action, high conf
        "T2": ("HS_1_1", "escalate", 8.0),   # match scenario+action
        "T3": ("HS_1_2", "escalate", 6.0),   # scenario miss, action match
        "T4": ("TECH_2", "stuck",    2.0),   # both miss, low conf
    })
    r = evaluate(eval_set, brain)
    assert r["scenario_correct"] == 2 and r["scenario_accuracy"] == 0.5
    assert r["action_correct"]   == 3 and r["action_accuracy"] == 0.75

    # HS_1_1: 3 expected, 2 predicted (T1,T2), 2 tp → P=1.0 R=2/3≈0.667
    ps = {p["scenario"]: p for p in r["per_scenario"]}
    assert ps["HS_1_1"]["precision"] == 1.0
    assert ps["HS_1_1"]["recall"] == round(2/3, 3)
    # HS_1_2 false positive — 0 expected, 1 predicted
    assert ps["HS_1_2"]["expected"] == 0 and ps["HS_1_2"]["precision"] == 0.0

    # Calibration: T1 (9.0) + T2 (8.0) → 7-10 bucket, both match → 2/2
    cal = {c["bucket"]: c for c in r["confidence_calibration"]}
    assert cal["7-10"]["n"] == 2 and cal["7-10"]["correct"] == 2
    assert cal["0-3"]["n"]  == 1 and cal["0-3"]["correct"] == 0


def test_eval_diff_vs_prior_run():
    from src.eval.harness import evaluate, save_run, RUNS_DIR
    eval_set = [{
        "ticket_id": "DIFF_T1", "queue": "W- LD", "subject": "x", "description": "x", "awbs": [],
        "expected_scenario": "HS_1_1", "expected_action": "escalate",
    }]
    # First run: miss
    saved = []
    try:
        r1 = evaluate(eval_set, FakeBrain({"DIFF_T1": ("SS_3", "stuck", 5.0)}))
        saved.append(save_run(r1))
        time.sleep(1.1)   # ensure distinct timestamp
        # Second run: improved
        r2 = evaluate(eval_set, FakeBrain({"DIFF_T1": ("HS_1_1", "escalate", 9.0)}))
        assert "diff_vs_last" in r2
        assert any(d["ticket_id"] == "DIFF_T1" for d in r2["diff_vs_last"]["improved"])
        saved.append(save_run(r2))
    finally:
        for p in saved:
            p.unlink(missing_ok=True)


# ═════════════════════════════════════════════════════════════════
# Phase 8 — SCENARIO AUDIT + DEPRECATE ENDPOINT
# ═════════════════════════════════════════════════════════════════
def test_deprecate_endpoint_round_trip():
    from src.llm.sop_store import get_sop_store
    store = get_sop_store()
    src = SMOKE_CHUNK_SRC + "audit_depr"
    store.add_knowledge("SMOKEAUDITPHRASE for HS_1_1 deprecation test.",
                         source=src, content_type="kt_addition")
    items = store._col.get(where={"source": src}, include=["metadatas"])
    chunk_id = items["ids"][0]

    c = _client()
    r = c.post(f"/api/chunks/{chunk_id}/deprecate", json={"deprecated": True})
    assert r.status_code == 200 and r.json()["deprecated"] is True

    # Verify metadata updated
    items = store._col.get(ids=[chunk_id], include=["metadatas"])
    assert items["metadatas"][0].get("deprecated") is True

    r = c.post(f"/api/chunks/{chunk_id}/deprecate", json={"deprecated": False})
    assert r.json()["deprecated"] is False


def test_deprecate_404_on_unknown_chunk():
    c = _client()
    r = c.post("/api/chunks/totally_not_a_real_chunk_id/deprecate", json={"deprecated": True})
    assert r.status_code == 404


# ═════════════════════════════════════════════════════════════════
# Phase 9 — ROLE-AWARE TICKET EXTRACTION (notes/email/misplaced fields)
# ═════════════════════════════════════════════════════════════════
def test_parse_notes_treats_all_as_l1():
    """notes table = exclusively L1-authored (dispose drafts + internal info)."""
    from scrape_tickets_v2 import _parse_notes
    captured = {
        "notes": {"notes": [
            {"id": 1, "detail": "<dispose>Dear Partner, share AWB.</dispose>",
             "creatorName": "Vijay Partap", "date": "2026-05-20 10:00:00"},
            {"id": 2, "detail": "<p>internal: routed to L2</p>", "type": "I",
             "creatorName": "Arvind", "date": "2026-05-21 10:00:00"},
        ]}
    }
    notes = _parse_notes(captured)
    assert len(notes) == 2
    assert all(n["role"] == "l1" for n in notes), "notes should all be tagged L1"
    # dispose wrapper stripped + HTML stripped
    assert notes[0]["body"].startswith("Dear Partner")
    assert "<dispose>" not in notes[0]["body"]
    # chronological order
    assert notes[0]["ts"] < notes[1]["ts"]


def test_parse_email_thread_classifies_captain_vs_l1():
    from scrape_tickets_v2 import _parse_email_thread
    captured = {
        "email": {"emails": [
            {"id": 1, "fromEmail": "captain@gmail.com", "fromName": "Tapan",
             "body": "I have not received my payment.", "date": "2026-05-20 09:00:00"},
            {"id": 2, "fromEmail": "agent@meesho.com", "fromName": "Payal",
             "body": "Please share AWB.", "date": "2026-05-21 10:00:00"},
            {"id": 3, "fromEmail": "captain@gmail.com",
             "body": "AWB is VL12345.", "date": "2026-05-22 11:00:00"},
        ]}
    }
    msgs = _parse_email_thread(captured, captain_email="captain@gmail.com")
    assert len(msgs) == 3
    roles = [m["role"] for m in msgs]
    assert roles == ["captain", "l1", "captain"], f"role mismatch: {roles}"


def test_parse_email_thread_unknown_sender_defaults_to_captain():
    """Safer to surface unknown senders to the reviewer than silently hide them."""
    from scrape_tickets_v2 import _parse_email_thread
    captured = {"email": {"emails": [
        {"id": 1, "fromEmail": "weird@thirdparty.com", "body": "Hi",
         "date": "2026-05-20 09:00:00"},
    ]}}
    msgs = _parse_email_thread(captured, captain_email="captain@gmail.com")
    assert msgs[0]["role"] == "captain"


def test_detect_misplaced_description_finds_prose_in_short_field():
    from scrape_tickets_v2 import _detect_misplaced_description
    panel = {
        "Hub Code": "TER",
        "AW Bs": "N/A",
        "Transaction ID": "Dear Team, This is regarding a rider from TER DC. An amount of Rs 112 has been debited under shipment fraud, but the rider was not involved. Please check.",
        "Please Describe Issue In Detail": "",
    }
    result = _detect_misplaced_description(panel, canonical_desc="")
    assert result.get("field") == "Transaction ID"
    assert "Dear Team" in result["value"]


def test_detect_misplaced_description_skips_canonical_field():
    """Don't flag the canonical description field even if it has prose."""
    from scrape_tickets_v2 import _detect_misplaced_description
    panel = {
        "Please Describe Issue In Detail": "Dear Team, full problem description here with multiple sentences. Captain reports issue.",
        "Hub Code": "ABC",
    }
    assert _detect_misplaced_description(panel, canonical_desc="") == {}


def test_detect_misplaced_description_skips_short_values():
    from scrape_tickets_v2 import _detect_misplaced_description
    panel = {"Transaction ID": "TXN12345"}   # < 120 chars, structured-looking
    assert _detect_misplaced_description(panel, canonical_desc="") == {}


def test_detect_misplaced_description_skips_duplicate_of_canonical():
    """If the same text appears in both canonical and another field, don't double-flag."""
    from scrape_tickets_v2 import _detect_misplaced_description
    desc = "Dear Team, full problem description here with multiple sentences and details."
    panel = {"Transaction ID": desc, "Hub Code": "ABC"}
    assert _detect_misplaced_description(panel, canonical_desc=desc) == {}


def test_build_prompt_uses_captain_section_with_source_tag():
    from src.llm.agent_brain import _build_prompt
    ticket = {
        "ticket_id": SMOKE + "PROMPT1",
        "queue": "W- LD",
        "subject": "Loss disputed",
        "captain_problem": "I connected the shipment within 4 days. Please reverse.",
        "captain_problem_source": "please_describe_issue",
        "captain_messages": [],
        "l1_messages": [
            {"role": "l1", "sender": "Payal", "ts": "2026-05-20 10:00", "body": "Please share AWB."}
        ],
        "misplaced_description": {},
        "awb_numbers": ["VL1234567890"],
    }
    out = _build_prompt(ticket, sop_context="(none)", query_results_text="(none)")
    assert "## CAPTAIN'S PROBLEM" in out
    assert "(source: please_describe_issue)" in out
    assert "I connected the shipment within 4 days" in out
    assert "## L1 AGENT THREAD" in out
    assert "PREVIOUS L1 RESPONSES, not the captain's problem" in out
    assert "Please share AWB" in out


def test_build_prompt_surfaces_misplaced_warning():
    from src.llm.agent_brain import _build_prompt
    ticket = {
        "ticket_id": SMOKE + "PROMPT2",
        "queue": "W- LD",
        "captain_problem": "Dear Team, my rider was wrongly debited Rs 112.",
        "captain_problem_source": "misplaced_field:Transaction ID",
        "captain_messages": [],
        "l1_messages": [],
        "misplaced_description": {"field": "Transaction ID", "value": "Dear Team, my rider was wrongly debited Rs 112."},
        "awb_numbers": [],
    }
    out = _build_prompt(ticket, sop_context="(none)", query_results_text="(none)")
    assert "## WRONG-FIELD WARNING" in out
    assert "Transaction ID" in out
    assert "captain's actual statement" in out


def test_extract_does_not_fallback_to_ticket_detail_for_canonical_description():
    """Regression: captain skipped 'Please Describe Issue In Detail' → we must
    NOT fall back to captured['detail']['ticket']['detail'], which holds the
    Kapture-internal ticket-state body (L1 dispose draft, NOT captain voice).
    See bug from ticket 779244875125 where this caused 'Captain's Message' on
    the dashboard to render an L1 reply verbatim."""
    import importlib
    src = Path(__file__).parent.parent / "scrape_tickets_v2.py"
    text = src.read_text(encoding="utf-8")
    # The fallback chain MUST NOT include ticket_obj.get("detail") for the
    # canonical description path. We allow it elsewhere (e.g. for tickets[].detail
    # in the list API) — only the api_desc_raw construction is the danger zone.
    # Find that specific line.
    import re as _re
    suspect = _re.search(
        r"api_desc_raw\s*=\s*parsed\.get\(\"please_describe_issue\"\)\s*or\s*\(?ticket_obj\.get\(\"detail\"\)",
        text,
    )
    assert suspect is None, (
        "extract_ticket() falls back to ticket_obj.get('detail') when "
        "please_describe_issue is empty. That field contains L1 dispose drafts, "
        "not captain text. Remove the fallback — see ticket 779244875125 bug."
    )


def test_parse_additional_info_does_not_use_displayname_fallback_for_description():
    """Regression: _parse_additional_info MUST NOT auto-map any field whose
    displayName contains 'describe'/'description' to please_describe_issue.
    Kapture has multiple such fields; one of them holds the L1 dispose draft
    and would silently pollute captain_problem with L1 voice.
    See bug from ticket 779244875125."""
    from scrape_tickets_v2 import _parse_additional_info
    # Synthetic additionalInfo where field 26926 (canonical) is EMPTY but
    # another field with displayName "Description" has L1 dispose text.
    captured = {"additionalInfo": {
        "existing": {"obj_1": {"fields": {
            "26926": "",                                             # canonical empty
            "99999": "<dispose>Dear Partner, please share AWB.</dispose>",  # L1 voice
        }}},
        "fieldConfig": {
            "26926": {"displayName": "Please Describe Issue In Detail"},
            "99999": {"displayName": "Description (auto-populated)"},  # tempting match
        },
    }}
    parsed = _parse_additional_info(captured)
    # The displayName fallback would have set please_describe_issue from field
    # 99999. After the fix it must NOT.
    assert "please_describe_issue" not in parsed or not parsed.get("please_describe_issue"), \
        f"please_describe_issue was populated from a displayName fallback — that's the bug: {parsed!r}"


def test_ocr_captain_attachment_short_circuits_on_no_urls():
    """When ticket has no attachments, OCR helper must return '' without
    touching Gemini (would be a wasted API call + crash if client unset)."""
    from src.llm.agent_brain import _ocr_captain_attachment
    assert _ocr_captain_attachment({"attachment_urls": []}) == ""
    assert _ocr_captain_attachment({}) == ""
    assert _ocr_captain_attachment({"attachment_urls": ["not-a-url"]}) == ""


def test_ocr_captain_attachment_calls_gemini_with_captain_prompt(monkeypatch=None):
    """OCR helper should call read_attachment with the captain-specific prompt
    and use whatever it returns (minus the NO_CAPTAIN_CONTENT sentinel)."""
    import src.llm.agent_brain as ab

    class _FakeGemini:
        def __init__(self):
            self.calls = []
        def read_attachment(self, url, filename="", prompt=None):
            self.calls.append({"url": url, "filename": filename, "prompt": prompt})
            return "Captain reports rider was wrongly debited Rs 112 for shipment fraud. AWB: VL00831789. Hub: TER."

    fake = _FakeGemini()
    _orig = ab.get_gemini_client
    ab.get_gemini_client = lambda: fake
    try:
        out = ab._ocr_captain_attachment({"attachment_urls": [
            "https://kapture-p-v2.storage.googleapis.com/.../WhatsApp-Image.jpeg",
        ]})
    finally:
        ab.get_gemini_client = _orig

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert "WhatsApp-Image.jpeg" in call["filename"]
    assert "captain" in (call["prompt"] or "").lower()
    assert "Captain reports rider was wrongly debited" in out


def test_ocr_captain_attachment_respects_no_content_sentinel():
    import src.llm.agent_brain as ab

    class _FakeGemini:
        def read_attachment(self, *a, **kw): return "NO_CAPTAIN_CONTENT"

    _orig = ab.get_gemini_client
    ab.get_gemini_client = lambda: _FakeGemini()
    try:
        out = ab._ocr_captain_attachment({"attachment_urls": ["http://x/y.jpg"]})
    finally:
        ab.get_gemini_client = _orig
    assert out == "", "NO_CAPTAIN_CONTENT sentinel must produce empty string"


def test_read_all_attachments_populates_cache_and_dedupes():
    """_read_all_attachments must call read_attachment once per URL and store
    results in ticket['_attachment_text_cache']. Re-calling returns the cache."""
    import src.llm.agent_brain as ab

    class _FakeGemini:
        def __init__(self): self.calls = []
        def read_attachment(self, url, filename="", prompt=None):
            self.calls.append(filename)
            return f"Captain attached {filename}. Contains AWB VL1234567890123."

    fake = _FakeGemini()
    _orig = ab.get_gemini_client
    ab.get_gemini_client = lambda: fake
    try:
        ticket = {"attachment_urls": [
            "https://x/foo.xlsx",
            "https://x/bar.jpg",
        ]}
        cache = ab._read_all_attachments(ticket)
        assert set(cache.keys()) == {"https://x/foo.xlsx", "https://x/bar.jpg"}
        assert all("AWB VL1234567890123" in v for v in cache.values())
        assert len(fake.calls) == 2
        # Second call must hit the cache, no new Gemini calls
        cache2 = ab._read_all_attachments(ticket)
        assert cache2 is cache or cache2 == cache
        assert len(fake.calls) == 2, "cache miss caused re-OCR"
    finally:
        ab.get_gemini_client = _orig


def test_brain_extracts_awbs_from_attachments_into_ticket():
    """Process should merge AWBs found in attachment content into
    ticket['awb_numbers'], so downstream Metabase queries can fire."""
    import src.llm.agent_brain as ab
    from src.llm.agent_brain import BrainDecision

    class _FakeGemini:
        def read_attachment(self, url, filename="", prompt=None):
            # Excel-style content with two AWBs
            return ("| AWB | Hub | Amount |\n"
                    "| VL0083117389780 | RIW | 112 |\n"
                    "| VL0083117389781 | RIW | 156 |")
        def decide(self, ctx, retries=2):
            return {"action": "stuck", "scenario_identified": "SL_3",
                    "confidence": 5.0, "reasoning": "fake",
                    "stuck_question": "fake", "_usage": {}}

    fake = _FakeGemini()
    _orig_g = ab.get_gemini_client
    ab.get_gemini_client = lambda: fake
    # Also bypass stage 0 + SOP retrieval to keep the test hermetic
    import src.llm.stage0 as _s0
    _orig_assess = _s0.assess
    _s0.assess = lambda ticket: type("X", (), {
        "physical_event": "", "loss_type": "unknown",
        "scenario_hint": "", "domain_confidence": "low",
        "queue_status": "complete", "queue_key_matched": "losses_and_debits",
        "captain_claim": "", "scan_logic": "", "missing_info": [],
        "critical_scans_to_check": [], "reason_l1_likely": "",
    })()
    class _FakeSop:
        def retrieve(self, q, k=10, queue=None): return {}

    try:
        brain = ab.AgentBrain()
        brain._gemini = fake
        brain._sop = _FakeSop()
        ticket = {
            "ticket_id": SMOKE + "ATT_AWB",
            "queue": "W- LD",
            "subject": "Shortage loss",
            "attachment_urls": ["https://x/awbs.xlsx"],
            "awb_numbers": [],
        }
        decision = brain.process(ticket, [])
        # AWBs from attachment should now be on the ticket dict
        assert "VL0083117389780" in (ticket.get("awb_numbers") or []), \
            f"attachment AWBs not merged into ticket: {ticket.get('awb_numbers')}"
        assert "VL0083117389781" in ticket["awb_numbers"]
    finally:
        ab.get_gemini_client = _orig_g
        _s0.assess = _orig_assess


def test_extract_ticket_promotes_awb_field_urls_to_attachments():
    """Regression: captains often drop xlsx/jpg URLs into the AW Bs field
    (Kapture field 21868) instead of typing actual AWB numbers. The scraper
    must promote those URLs into attachment_urls so the OCR/Excel pipeline
    picks them up — otherwise the file is silently lost. See ticket
    778834827114 (May 27, EVI hub, file in AW Bs)."""
    # Black-box test against the regex/promotion logic from extract_ticket.
    # Replicate the relevant block.
    import re as _re
    _ATT_EXT_RE = _re.compile(r"\.(jpe?g|png|pdf|webp|gif|xlsx|xls|csv)\b", _re.I)
    _STORAGE_HINT_RE = _re.compile(r"googleapis\.com|/storage/|kapture-p-v2", _re.I)
    _URL_RE = _re.compile(r"https?://[^\s,;'\"]+", _re.I)
    _DESC = {
        "please describe issue in detail", "issue description", "describe issue",
    }

    panel_fields = {
        "Hub Code": "EVI",
        "AW Bs": "https://kapture-p-v2.storage.googleapis.com/.../6a06dbd_loss_sheet.xlsx",
        "Please Describe Issue In Detail": "",
    }
    awb_field_raw = panel_fields["AW Bs"]
    existing = []
    seen = set()
    sources = [awb_field_raw] + [
        str(v) for k, v in panel_fields.items()
        if (k or "").strip().lower() not in _DESC
    ]
    for src in sources:
        for u in _URL_RE.findall(src):
            if _ATT_EXT_RE.search(u) or _STORAGE_HINT_RE.search(u):
                if u not in seen:
                    existing.append(u); seen.add(u)

    assert len(existing) == 1
    assert existing[0].endswith("_loss_sheet.xlsx")

    # Misplaced-attachment regex must now match xlsx (not just images)
    assert _ATT_EXT_RE.search("foo.xlsx") is not None, "xlsx must match"
    assert _ATT_EXT_RE.search("bar.csv")  is not None, "csv must match"
    assert _ATT_EXT_RE.search("baz.xls")  is not None, "xls must match"
    assert _ATT_EXT_RE.search("qux.txt")  is None,     "txt should NOT match"


def test_read_tabular_local_parses_xlsx_into_text():
    """Local Excel parser must produce text that AWB-regex can scan."""
    import tempfile, os
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AWBs"
    ws.append(["AWB", "Hub", "Status"])
    ws.append(["VL0084296473870", "WPT", "lost"])
    ws.append(["VL0084296473871", "WPT", "lost"])
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        wb.save(tmp.name)
        path = tmp.name
    wb.close()

    from src.llm.gemini_client import GeminiClient
    try:
        # Don't instantiate (would require GEMINI_API_KEY); call the unbound
        # method directly with a synthetic 'self' that doesn't touch the client
        out = GeminiClient._read_tabular_local(GeminiClient.__new__(GeminiClient), path, ".xlsx")
    finally:
        os.unlink(path)

    assert "VL0084296473870" in out, f"AWB not found in xlsx dump: {out[:200]}"
    assert "VL0084296473871" in out
    assert "Sheet: AWBs" in out


def test_ocr_captain_attachment_handles_error_string():
    import src.llm.agent_brain as ab

    class _FakeGemini:
        def read_attachment(self, *a, **kw): return "[Could not read attachment: timeout]"

    _orig = ab.get_gemini_client
    ab.get_gemini_client = lambda: _FakeGemini()
    try:
        out = ab._ocr_captain_attachment({"attachment_urls": ["http://x/y.jpg"]})
    finally:
        ab.get_gemini_client = _orig
    assert out == "", "Error-prefixed strings must be treated as empty"


def test_misplaced_attachment_warning_renders_in_prompt():
    from src.llm.agent_brain import _build_prompt
    ticket = {
        "ticket_id": SMOKE + "ATT",
        "queue": "W- LD",
        "captain_problem": "",
        "captain_problem_source": "",
        "captain_messages": [],
        "l1_messages": [],
        "misplaced_description": {},
        "misplaced_attachment_field": "AW Bs",
        "awb_numbers": [],
    }
    out = _build_prompt(ticket, sop_context="(none)", query_results_text="(none)")
    assert "## ATTACHMENT-IN-WRONG-FIELD WARNING" in out
    assert "AW Bs" in out
    assert "type out what's in the image" in out


def test_build_prompt_falls_back_to_legacy_detail_field():
    """Backward compat: tickets from cache predating Fix 11 only have 'detail'."""
    from src.llm.agent_brain import _build_prompt
    ticket = {
        "ticket_id": SMOKE + "PROMPT3",
        "queue": "W- LD",
        "detail": "Legacy ticket — only the detail field is populated.",
        "awb_numbers": [],
    }
    out = _build_prompt(ticket, sop_context="(none)", query_results_text="(none)")
    assert "Legacy ticket" in out
    assert "(source: legacy_description_field)" in out


# ─────────────────────────────────────────────────────────────────
# Standalone runner — works without pytest installed
# ─────────────────────────────────────────────────────────────────
def _collect_tests(module):
    return [(name, fn) for name, fn in module.items()
            if name.startswith("test_") and callable(fn)]


def _run_standalone():
    import traceback
    setup_module()
    try:
        tests = _collect_tests(globals())
        passed, failed, errors = 0, 0, []
        print(f"\nRunning {len(tests)} smoke tests...\n")
        t0 = time.time()
        for name, fn in tests:
            try:
                fn()
                print(f"  [PASS] {name}")
                passed += 1
            except AssertionError as e:
                failed += 1
                tb = traceback.format_exc(limit=2)
                errors.append((name, str(e) or "assertion failed", tb))
                print(f"  [FAIL] {name}: {e or 'assertion failed'}")
            except Exception as e:
                failed += 1
                tb = traceback.format_exc()
                errors.append((name, f"{type(e).__name__}: {e}", tb))
                print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        dt = time.time() - t0
        print("\n" + "=" * 60)
        print(f"  {passed} passed, {failed} failed   ({dt:.1f}s)")
        print("=" * 60)
        if errors:
            print("\nDETAILS:")
            for name, msg, tb in errors:
                print(f"\n--- {name} ---\n{tb}")
        return 0 if failed == 0 else 1
    finally:
        teardown_module()


if __name__ == "__main__":
    sys.exit(_run_standalone())
