"""
Operating mode for the live agent — single source of truth.

Two values:
  - "review"     : every decision goes to dashboard for human approval
  - "autonomous" : high-confidence respond decisions auto-send

Stored in data/.mode (single line). Default = "review" (safe).
"""

from pathlib import Path

MODE_FILE = Path(__file__).parent.parent.parent / "data" / ".mode"
VALID_MODES = {"review", "autonomous"}


def get_mode() -> str:
    try:
        v = MODE_FILE.read_text(encoding="utf-8").strip().lower()
        return v if v in VALID_MODES else "review"
    except Exception:
        return "review"


def set_mode(mode: str) -> str:
    mode = (mode or "").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODE_FILE.write_text(mode, encoding="utf-8")
    return mode
