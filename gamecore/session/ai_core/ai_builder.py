"""
War Advisor - AI Army Builder

Smistamento: ogni difficoltà ha il proprio costruttore d'esercito e la propria
policy runtime, qui c'è solo la tabella che li mette in fila e i nomi che il
frontend mostra nel selettore.
"""

from typing import Any, Dict, List, Optional

from gamecore.economy import STARTING_GRUX
from .ai_easy_difficulty import AI_EASY_ID, EasyAIDifficultyPolicy, build_ai_army_easy
from .ai_hard_difficulty import AI_HARD_ID, HardAIDifficultyPolicy, build_ai_army_hard
from .ai_nightmare_difficulty import (
    AI_NIGHTMARE_ID,
    NightmareAIDifficultyPolicy,
    build_ai_army_nightmare,
)
from .ai_normal_difficulty import AI_NORMAL_ID, NormalAIDifficultyPolicy, build_ai_army_normal

# L'ordine determina anche l'ordine nel selettore difficoltà del frontend.
AI_DIFFICULTY_LABELS: Dict[str, str] = {
    AI_EASY_ID: "Facile",
    AI_NORMAL_ID: "Normale",
    AI_HARD_ID: "Difficile",
    AI_NIGHTMARE_ID: "Incubo",
}


def normalize_ai_difficulty(difficulty: Optional[str]) -> str:
    """Normalizza la difficoltà richiesta (fallback: easy)."""
    key = (difficulty or AI_EASY_ID).strip().lower()
    if key in AI_DIFFICULTY_LABELS:
        return key
    return AI_EASY_ID


def get_available_ai_difficulties() -> List[str]:
    return list(AI_DIFFICULTY_LABELS.keys())


def get_ai_difficulty_labels() -> Dict[str, str]:
    return AI_DIFFICULTY_LABELS.copy()


def build_ai_policy(difficulty: Optional[str], seed: Optional[int] = None):
    """Costruisce la policy runtime in base alla difficoltà."""
    normalized = normalize_ai_difficulty(difficulty)
    if normalized == AI_NIGHTMARE_ID:
        return NightmareAIDifficultyPolicy(seed=seed)
    if normalized == AI_HARD_ID:
        return HardAIDifficultyPolicy(seed=seed)
    if normalized == AI_NORMAL_ID:
        return NormalAIDifficultyPolicy(seed=seed)
    return EasyAIDifficultyPolicy(seed=seed)


def build_ai_army(
    data: Dict[str, Any],
    ai_terrain: str,
    weather: Optional[str],
    n_units: int = 3,
    budget: int = STARTING_GRUX,
    seed: Optional[int] = None,
    difficulty: str = AI_EASY_ID,
) -> Dict[str, Any]:
    """Dispatcher costruzione esercito IA in base alla difficoltà."""
    costruttori = {
        AI_EASY_ID: build_ai_army_easy,
        AI_NORMAL_ID: build_ai_army_normal,
        AI_HARD_ID: build_ai_army_hard,
        AI_NIGHTMARE_ID: build_ai_army_nightmare,
    }
    # `normalize_ai_difficulty` ripiega su easy, quindi la chiave c'è sempre.
    return costruttori[normalize_ai_difficulty(difficulty)](
        data=data,
        ai_terrain=ai_terrain,
        weather=weather,
        n_units=n_units,
        budget=budget,
        seed=seed,
    )
