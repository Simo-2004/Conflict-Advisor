"""
War Advisor - Session Abilities

Gestisce ricerca/sblocco abilità della partita.
"""

from dataclasses import dataclass
from typing import Dict, Optional

DOMAIN_ENGINEERING_ID = "domain_engineering"
DOMAIN_ENGINEERING_NAME = "Costruzione Territoriale"
DOMAIN_ENGINEERING_TURNS = 40


@dataclass
class AbilityResearchState:
    """Stato ricerca di una singola abilità per un'entità."""

    ability_id: str
    name: str
    turns_required: int
    started_turn: Optional[int] = None

    def is_researching(self) -> bool:
        return self.started_turn is not None

    def turns_elapsed(self, current_turn: int) -> int:
        if self.started_turn is None:
            return 0
        return max(0, current_turn - self.started_turn)

    def turns_remaining(self, current_turn: int) -> int:
        if self.started_turn is None:
            return self.turns_required
        return max(0, self.turns_required - self.turns_elapsed(current_turn))

    def is_unlocked(self, current_turn: int) -> bool:
        return self.started_turn is not None and self.turns_elapsed(current_turn) >= self.turns_required

    def start(self, current_turn: int) -> bool:
        if self.started_turn is not None:
            return False
        self.started_turn = current_turn
        return True

    def to_dict(self, current_turn: int) -> Dict[str, object]:
        return {
            "id": self.ability_id,
            "name": self.name,
            "turns_required": self.turns_required,
            "started_turn": self.started_turn,
            "researching": self.is_researching(),
            "unlocked": self.is_unlocked(current_turn),
            "turns_remaining": self.turns_remaining(current_turn),
        }


def build_default_ability_states() -> Dict[str, AbilityResearchState]:
    """Set abilità base disponibile per la sessione."""
    return {
        DOMAIN_ENGINEERING_ID: AbilityResearchState(
            ability_id=DOMAIN_ENGINEERING_ID,
            name=DOMAIN_ENGINEERING_NAME,
            turns_required=DOMAIN_ENGINEERING_TURNS,
        )
    }
