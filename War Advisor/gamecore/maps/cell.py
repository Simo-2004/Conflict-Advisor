"""
War Advisor - Cell
Definisce le strutture dati di base per ogni cella della mappa di gioco.
"""

from dataclasses import dataclass, field
from enum import Enum


# ──────────────────────────────────────────────────────────
# COSTANTI
# ──────────────────────────────────────────────────────────

# Tipi di terreno (corrispondono esattamente a quelli in data/modifiers.json)
TERRAIN_TYPES: list = ["Pianura", "Foresta", "Montagna", "Fiume", "Palude"]


class Occupation(str, Enum):
    """Stato di occupazione di una cella."""
    NEUTRAL = "neutral"   # Non occupata
    PLAYER  = "player"    # Occupata dal giocatore
    AI      = "ai"        # Occupata dall'IA

    def opposite(self) -> "Occupation":
        """Restituisce l'avversario: PLAYER↔AI, NEUTRAL→NEUTRAL."""
        if self == Occupation.PLAYER:
            return Occupation.AI
        if self == Occupation.AI:
            return Occupation.PLAYER
        return Occupation.NEUTRAL


# ──────────────────────────────────────────────────────────
# CELLA
# ──────────────────────────────────────────────────────────

@dataclass
class Cell:
    """
    Singola cella della mappa di gioco.

    Attributi:
        row          -- riga nella griglia (0 = nord/alto)
        col          -- colonna nella griglia
        terrain      -- tipo di terreno (uno di TERRAIN_TYPES)
        occupation   -- chi occupa la cella
        is_strategic -- True se la cella è un obiettivo strategico
    """
    row: int
    col: int
    terrain: str           = "Pianura"
    occupation: Occupation = Occupation.NEUTRAL
    is_strategic: bool     = False

    def __post_init__(self) -> None:
        if self.terrain not in TERRAIN_TYPES:
            raise ValueError(
                f"Terreno non valido: '{self.terrain}'. "
                f"Valori ammessi: {TERRAIN_TYPES}"
            )

    def to_dict(self) -> dict:
        """Serializza la cella in un dizionario JSON-compatibile."""
        return {
            "row":          self.row,
            "col":          self.col,
            "terrain":      self.terrain,
            "occupation":   self.occupation.value,
            "is_strategic": self.is_strategic,
        }

    def __repr__(self) -> str:
        flag = "*" if self.is_strategic else " "
        return (
            f"Cell({self.row},{self.col} "
            f"terrain={self.terrain} "
            f"occ={self.occupation.value}{flag})"
        )
