"""DEBUG TEMPORANEO (DA RIMUOVERE).

Cattura il battle_log runtime e lo salva in un file con formato:
LOG-HH-MM-SS.txt, separando le righe PLAYER e IA.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Iterable, List

_BASE_DIR = Path(__file__).resolve().parent
_TIMESTAMP = datetime.now().strftime("%H-%M-%S")
_LOG_PATH = _BASE_DIR / f"LOG-{_TIMESTAMP}.txt"

_PLAYER_RE = re.compile(r"\bPLAYER\b|\bplayer\b")
_AI_RE = re.compile(r"\bIA\b|\bAI\b|\bai\b")


class BattleLogCaptureList(list):
    """Lista compatibile con battle_log che salva snapshot su file ad ogni aggiornamento."""

    def append(self, item):
        super().append(item)
        self._flush_to_file()

    def extend(self, items: Iterable):
        super().extend(items)
        self._flush_to_file()

    def _flush_to_file(self) -> None:
        try:
            player_lines: List[str] = []
            ai_lines: List[str] = []

            for entry in self:
                line = str(entry)
                has_player = bool(_PLAYER_RE.search(line))
                has_ai = bool(_AI_RE.search(line))

                if has_player:
                    player_lines.append(line)
                if has_ai:
                    ai_lines.append(line)
                if not has_player and not has_ai:
                    # Come in frontend: righe comuni visibili a entrambi
                    player_lines.append(line)
                    ai_lines.append(line)

            content = [
                "DEBUG TEMPORANEO - rimuovere cartella debug in produzione",
                f"File: {_LOG_PATH.name}",
                "",
                "=== LOG PLAYER ===",
            ]
            content.extend(player_lines or ["(vuoto)"])
            content.extend(["", "=== LOG IA ==="])
            content.extend(ai_lines or ["(vuoto)"])

            _LOG_PATH.write_text("\n".join(content), encoding="utf-8")
        except Exception:
            # Debug non deve mai rompere il runtime principale.
            return


def create_battle_log_capture() -> BattleLogCaptureList:
    """Factory per battle_log con cattura automatica su file."""
    return BattleLogCaptureList()
