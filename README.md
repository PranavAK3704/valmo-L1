# Valmo L1 Agent

A digital L1 support agent for Valmo (Meesho's logistics arm). Reads tickets from Kapture CRM, reasons about supply-chain events using domain-aware Gemini calls, runs Metabase queries, and either drafts a reply or escalates with a specific question. The goal is to replace L1 humans queue-by-queue.

## Architecture

```
Kapture ticket
    → DOM/API extraction
    → Stage 0: Situation Assessment (Gemini, supply-chain reasoning)
    → SOP retrieval (ChromaDB + sop_structured.json)
    → Metabase queries (per-AWB)
    → Stage 1: Decision (Gemini → JSON: action, scenario, response, confidence)
    → Route: auto-send | review queue | escalate L2 | stuck (trainer)
```

## Status

| Queue | Status |
|---|---|
| Losses & Debits (W- LD) | activated — full Stage 0 domain |
| Payments (M_V) | placeholder — awaiting domain KT |
| Consumables (C_V) | placeholder — awaiting domain KT |
| Orders & Planning | placeholder — awaiting domain KT |
| Cash Handover | placeholder — awaiting domain KT |

## Quick start

```bash
# 1. Install deps
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
# fill in KAPTURE_*, METABASE_*, GEMINI_API_KEY

# 3. Run dashboard
python run_dashboard.py
# open http://localhost:8080

# 4. Optional — process a batch of L&D tickets
python _run_ld_batch.py
```

## Components

- `run_dashboard.py` — FastAPI server + dashboard at `:8080`
- `live_agent.py` — Kapture poller (fetches new tickets, runs them through brain)
- `scrape_tickets_v2.py` — Kapture scraper (Playwright)
- `batch_process_tickets.py` — generic batch runner
- `_run_ld_batch.py` — L&D demo batch (filters auto-disposed noise)
- `src/llm/agent_brain.py` — orchestrates Stage 0 + SOP + Gemini decision
- `src/llm/stage0.py` — situation assessment + domain KT upsert
- `src/llm/gemini_client.py` — Gemini 3 Flash client with system prompt
- `src/llm/sop_store.py` — ChromaDB-backed SOP retrieval
- `src/api/decision_store.py` — SQLite store for decisions
- `data/sop_knowledge/` — SOP markdown files + structured JSON + Stage 0 domain

## Adding domain knowledge for a queue

Open the dashboard → KT Engine tab → "Stage 0 Domain Onboarding" → JSON mode:
1. Pick the queue
2. Click "Load template"
3. Fill the slots (metabase_columns, preprocessing_rules, scenarios)
4. Click "Validate" — fixes errors before save
5. Click "Activate Queue"

Validates and merges into `data/sop_knowledge/stage0_domain.json` without restart.

## What's not in this repo

- `.env` — your credentials
- `data/decisions.db` — runtime ticket decisions (regenerated)
- `data/chroma_db/` — vector index (regenerated from `data/sop_knowledge/*.md`)
- `data/scraped_tickets*.jsonl` — real Kapture tickets (PII)
- `data/ground_truth.jsonl` — captured agent replies (PII)
- Logs and screenshots
