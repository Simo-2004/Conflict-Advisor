"""
gamecore.session — Gestione della sessione di gioco per War Advisor.

Esporta:
    GameSession  — sessione di gioco (player + IA + mappa + turni + battaglie)
    SessionState — enum ACTIVE / GAME_OVER
    build_ai_army — costruisce l'esercito dell'IA
"""

from .session            import GameSession, SessionState
from .ai_core.ai_builder import build_ai_army
from .abilities          import DOMAIN_ENGINEERING_ID

__all__ = [
    "GameSession",
    "SessionState",
    "build_ai_army",
    "DOMAIN_ENGINEERING_ID",
]
