"""
VALMO L1 Agent — Live SOP Loader

Fetches SOPs from the published Google Sheet URL in config.js.
This is the SAME source the Chrome extension uses, so when you update
the master Google Sheet, the agent automatically picks up changes on next restart.

SOP Sheet URL (from config.js):
  https://docs.google.com/spreadsheets/d/e/2PACX-1vTtfp2EauVkBu1RILwErMMDs7mfwdzC1V9CdP0bf4ZjEsoe_QEr7o1slJm5tsMxNIqMK6vudtYjHCql/pub?gid=1281163884&single=true&output=csv

Templates Sheet URL (from config.js):
  https://docs.google.com/spreadsheets/d/e/2PACX-1vRNGnSVBmO7sU79z_zNfAa9N2S0yUSDR6yyOBTtnEi_m-XGBV6eBK0H9DJMuaDp_l0YA4enSjTKzNsk/pub?gid=0&single=true&output=csv

HOW IT WORKS:
  1. At agent startup, fetch the CSV from Google Sheets
  2. Parse into SOP records (scenario, process, escalateTo, inputs, keywords)
  3. Pass to sop_engine.py which uses them for matching
  4. If fetch fails → fall back to bundled sop_database.json (last known good)
  5. Re-fetch every RELOAD_INTERVAL_HOURS (default: 1 hour) so live updates apply

COLUMN NAMES (detected from sop_database.json structure):
  The sheet has: keywords, scenario, process, escalateTo, inputs
  Plus queue grouping (Losses & Debits / Payments / Orders & Load)
"""

import csv
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

SOP_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTtfp2EauVkBu1RILwErMMDs7mfwdzC1V9CdP0bf4ZjEsoe_QEr7o1slJm5tsMxNIqMK6vudtYjHCql"
    "/pub?gid=1281163884&single=true&output=csv"
)

TEMPLATES_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRNGnSVBmO7sU79z_zNfAa9N2S0yUSDR6yyOBTtnEi_m-XGBV6eBK0H9DJMuaDp_l0YA4enSjTKzNsk"
    "/pub?gid=0&single=true&output=csv"
)

# Fallback: bundled JSON (same folder as this file)
FALLBACK_JSON = Path(__file__).parent.parent.parent / "data" / "sop_database.json"

RELOAD_INTERVAL_HOURS = 1


class SOPLoader:
    """
    Loads and caches SOPs from the live Google Sheet.
    Falls back to bundled JSON if the sheet is unreachable.
    Auto-reloads every hour so updates to the master sheet propagate automatically.
    """

    def __init__(self, sheet_url: str = SOP_SHEET_URL):
        self._url         = sheet_url
        self._sops:  Dict = {}
        self._loaded_at:  float = 0.0
        self._source:     str   = "not loaded"

    def get_sops(self) -> Dict[str, List[Dict]]:
        """Returns SOPs dict. Reloads from sheet if cache is stale."""
        age_hours = (time.time() - self._loaded_at) / 3600
        if not self._sops or age_hours > RELOAD_INTERVAL_HOURS:
            self._load()
        return self._sops

    def _load(self):
        """Try live sheet first, fall back to bundled JSON."""
        try:
            self._load_from_sheet()
            logger.info(f"[SOP LOADER] Loaded {self._count()} SOPs from Google Sheet")
        except Exception as e:
            logger.warning(f"[SOP LOADER] Sheet fetch failed ({e}) — using fallback JSON")
            self._load_from_fallback()

    def _load_from_sheet(self):
        resp = requests.get(self._url, timeout=15)
        resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(resp.text))
        rows   = [r for r in reader if any(v.strip() for v in r.values())]

        if not rows:
            raise ValueError("Sheet returned empty CSV")

        cols = list(rows[0].keys())
        logger.info(f"[SOP LOADER] Sheet columns: {cols}")

        self._sops  = self._parse_rows(rows)
        self._loaded_at = time.time()
        self._source    = "Google Sheet (live)"

    def _parse_rows(self, rows: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Parses CSV rows into the same structure as sop_database.json:
        { "Losses & Debits": [...], "Payments": [...], "Orders & Load": [...] }

        Handles two possible sheet layouts:
          Layout A: has a "queue" or "category" column → group by that
          Layout B: no queue column → infer from keywords/scenario text
        """
        result: Dict[str, List] = {}

        # Detect column names (case-insensitive)
        sample = rows[0]
        col_map = {k.lower().strip(): k for k in sample.keys()}

        queue_col    = col_map.get("queue") or col_map.get("category") or col_map.get("type")
        scenario_col = col_map.get("scenario") or col_map.get("title") or col_map.get("name")
        process_col  = col_map.get("process") or col_map.get("steps") or col_map.get("procedure")
        escalate_col = col_map.get("escalateto") or col_map.get("escalate_to") or col_map.get("escalation")
        inputs_col   = col_map.get("inputs") or col_map.get("required_inputs") or col_map.get("input")
        keywords_col = col_map.get("keywords") or col_map.get("tags")

        for row in rows:
            scenario = row.get(scenario_col, "").strip() if scenario_col else ""
            process  = row.get(process_col,  "").strip() if process_col  else ""
            if not scenario and not process:
                continue

            # Determine queue
            if queue_col:
                queue = row.get(queue_col, "Others").strip()
            else:
                queue = _infer_queue(scenario, process)

            # Parse keywords
            raw_kw = row.get(keywords_col, "") if keywords_col else ""
            if isinstance(raw_kw, str):
                keywords = [k.strip() for k in raw_kw.replace(",", "\n").splitlines() if k.strip()]
            else:
                keywords = []

            sop = {
                "scenario":   scenario,
                "process":    process,
                "escalateTo": row.get(escalate_col, "").strip() if escalate_col else "",
                "inputs":     row.get(inputs_col,   "").strip() if inputs_col   else "",
                "keywords":   keywords,
            }

            result.setdefault(queue, []).append(sop)

        return result

    def _load_from_fallback(self):
        """Load from bundled sop_database.json (same file the extension ships with)."""
        if FALLBACK_JSON.exists():
            with open(FALLBACK_JSON) as f:
                self._sops = json.load(f)
            self._loaded_at = time.time()
            self._source    = f"fallback JSON ({FALLBACK_JSON.name})"
            logger.info(f"[SOP LOADER] Loaded {self._count()} SOPs from fallback JSON")
        else:
            logger.error("[SOP LOADER] No fallback JSON found — SOPs empty!")
            self._sops = {}

    def _count(self) -> int:
        return sum(len(v) for v in self._sops.values())

    @property
    def source(self) -> str:
        return self._source

    def status(self) -> Dict:
        return {
            "source":      self._source,
            "queues":      list(self._sops.keys()),
            "total_sops":  self._count(),
            "loaded_at":   time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._loaded_at)),
            "age_minutes": round((time.time() - self._loaded_at) / 60, 1),
        }


def _infer_queue(scenario: str, process: str) -> str:
    """Infer queue from scenario/process text if no queue column exists."""
    text = (scenario + " " + process).lower()
    if any(w in text for w in ["loss", "debit", "shortage", "hardstop", "attribution"]):
        return "Losses & Debits"
    if any(w in text for w in ["payment", "invoice", "esign", "credit note"]):
        return "Payments"
    if any(w in text for w in ["load", "volume", "manifestation", "promised", "orders"]):
        return "Orders & Load"
    if any(w in text for w in ["cod", "cash", "cms", "handover"]):
        return "Cash Deposit / COD Process"
    return "Others"


# ─────────────────────────────────────────────
# COPY FALLBACK JSON from extension zip
# ─────────────────────────────────────────────

def install_fallback_json():
    """
    Copies sop_database.json from the extension into the agent's data/ folder.
    Run once on setup. After that, the live sheet takes over.
    """
    src = Path("/tmp/unified-ext/unified-extension/data/sop_database.json")
    dst = FALLBACK_JSON
    dst.parent.mkdir(parents=True, exist_ok=True)

    if src.exists():
        import shutil
        shutil.copy(src, dst)
        logger.info(f"[SOP LOADER] Installed fallback JSON from extension: {dst}")
    else:
        logger.warning(f"[SOP LOADER] Extension JSON not found at {src}")


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────

_loader: Optional[SOPLoader] = None

def get_sop_loader() -> SOPLoader:
    global _loader
    if _loader is None:
        _loader = SOPLoader()
    return _loader
