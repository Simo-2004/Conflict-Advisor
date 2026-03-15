"""
DEBUG TEMPORANEO - DA RIMUOVERE IN PRODUZIONE.

Questo modulo salva eventi di debug della forza esercito in JSON Lines.
Il file generato è: debug/strength_debug.log
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

_LOG_FILE = Path(__file__).resolve().parent / "strength_debug.log"


def log_strength_debug(event: str, payload: Dict[str, Any]) -> None:
    """Scrive un evento di debug in coda al file JSONL.

    Fail-safe: in caso di errore non interrompe mai il gioco.
    """
    try:
        record = {
            "debug_tag": "DEBUG_TEMP_REMOVE_ME",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "payload": payload,
        }
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return
