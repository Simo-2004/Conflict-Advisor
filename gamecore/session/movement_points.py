"""
War Advisor - Movement Points

Sistema di costo movimento basato su punti per turno.

Regola base:
- Ogni armata dispone di 100 punti movimento per turno.
- Ogni terreno consuma un costo specifico.
- Se il costo supera 100, il surplus viene convertito in turni di ritardo
    (es. costo 220 => 3 turni totali di azione movimento: mossa attuale + 2 turni bloccati).
"""

from dataclasses import dataclass
from math import ceil
from typing import Dict

from gamecore.maps import Occupation

MOVEMENT_POINTS_PER_TURN: int = 100
MOVEMENT_DEFENSE_PENALTY_RATIO: float = 0.15

# Terreni effettivamente presenti nel gioco.
TERRAIN_MOVEMENT_COSTS: Dict[str, int] = {
    "Pianura": 100,
    "Foresta": 140,
    "Fiume": 160,
    "Palude": 180,
    "Montagna": 220,
}

DEFAULT_TERRAIN_MOVEMENT_COST: int = 100


@dataclass
class MovementState:
    """Stato runtime dei ritardi movimento per una singola entità."""

    blocked_turns: int = 0
    display_blocked_turns: int = 0
    last_terrain: str = "Pianura"
    last_cost: int = MOVEMENT_POINTS_PER_TURN
    progress_ratio: float = 1.0
    missing_ratio: float = 0.0
    last_from_pos: tuple[int, int] | None = None
    last_to_pos: tuple[int, int] | None = None


class MovementPointsSystem:
    """Gestisce costi terreno e ritardi turn-based per player/IA."""

    def __init__(
        self,
        points_per_turn: int = MOVEMENT_POINTS_PER_TURN,
        terrain_costs: Dict[str, int] | None = None,
    ) -> None:
        self.points_per_turn = max(1, int(points_per_turn))
        self.terrain_costs: Dict[str, int] = dict(terrain_costs or TERRAIN_MOVEMENT_COSTS)
        self._states: Dict[Occupation, MovementState] = {
            Occupation.PLAYER: MovementState(),
            Occupation.AI: MovementState(),
        }

    def terrain_cost(self, terrain: str) -> int:
        """Costo punti movimento per entrare in un terreno."""
        if terrain in self.terrain_costs:
            return max(1, int(self.terrain_costs[terrain]))
        return DEFAULT_TERRAIN_MOVEMENT_COST

    def register_move(
        self,
        entity: Occupation,
        terrain: str,
        from_pos: tuple[int, int] | None = None,
        to_pos: tuple[int, int] | None = None,
    ) -> Dict[str, int | str | float]:
        """Registra la mossa e aggiorna eventuale ritardo turni per il terreno scelto."""
        state = self._states[entity]
        cost = self.terrain_cost(terrain)
        extra_wait_turns = max(0, ceil(cost / self.points_per_turn) - 1)
        progress_ratio = min(1.0, self.points_per_turn / max(1, cost))
        missing_ratio = max(0.0, 1.0 - progress_ratio)

        state.last_terrain = terrain
        state.last_cost = cost
        state.blocked_turns = extra_wait_turns
        state.display_blocked_turns = extra_wait_turns
        state.progress_ratio = progress_ratio
        state.missing_ratio = missing_ratio
        state.last_from_pos = from_pos
        state.last_to_pos = to_pos

        return {
            "cost": cost,
            "points_per_turn": self.points_per_turn,
            "extra_wait_turns": extra_wait_turns,
            "terrain": terrain,
            "progress_ratio": progress_ratio,
            "missing_ratio": missing_ratio,
        }

    def consume_block_if_any(self, entity: Occupation) -> Dict[str, int | str | bool]:
        """Consuma un turno di blocco movimento se presente."""
        state = self._states[entity]
        if state.blocked_turns <= 0:
            state.display_blocked_turns = 0
            return {
                "blocked": False,
                "remaining_blocked_turns": 0,
                "display_blocked_turns": 0,
                "last_terrain": state.last_terrain,
                "last_cost": state.last_cost,
            }

        state.blocked_turns -= 1
        state.display_blocked_turns = 1
        return {
            "blocked": True,
            "remaining_blocked_turns": state.blocked_turns,
            "display_blocked_turns": state.display_blocked_turns,
            "last_terrain": state.last_terrain,
            "last_cost": state.last_cost,
        }

    def export_entity_state(self, entity: Occupation) -> Dict[str, int | str]:
        """Stato serializzabile del movimento per una entità."""
        state = self._states[entity]
        defense_penalty_active = state.blocked_turns > 0
        defense_factor = 1.0 - MOVEMENT_DEFENSE_PENALTY_RATIO if defense_penalty_active else 1.0
        return {
            "points_per_turn": self.points_per_turn,
            "blocked_turns": state.blocked_turns,
            "display_blocked_turns": state.display_blocked_turns,
            "last_terrain": state.last_terrain,
            "last_cost": state.last_cost,
            "progress_ratio": state.progress_ratio,
            "missing_ratio": state.missing_ratio,
            "last_from_pos": list(state.last_from_pos) if state.last_from_pos is not None else None,
            "last_to_pos": list(state.last_to_pos) if state.last_to_pos is not None else None,
            "defense_penalty_active": defense_penalty_active,
            "defense_penalty_ratio": MOVEMENT_DEFENSE_PENALTY_RATIO if defense_penalty_active else 0.0,
            "defense_factor": defense_factor,
        }

    def get_defense_modifier(self, entity: Occupation) -> Dict[str, int | float | bool]:
        """Restituisce il modificatore difensivo dovuto a movimento incompleto."""
        state = self._states[entity]
        active = state.blocked_turns > 0
        factor = 1.0 - MOVEMENT_DEFENSE_PENALTY_RATIO if active else 1.0
        return {
            "active": active,
            "factor": factor,
            "reduction_ratio": MOVEMENT_DEFENSE_PENALTY_RATIO if active else 0.0,
            "blocked_turns": state.blocked_turns,
            "last_terrain": state.last_terrain,
            "last_cost": state.last_cost,
        }

    def export_config(self) -> Dict[str, int | Dict[str, int]]:
        """Configurazione serializzabile globale del sistema movimento."""
        return {
            "points_per_turn": self.points_per_turn,
            "terrain_costs": dict(self.terrain_costs),
            "defense_penalty_ratio": MOVEMENT_DEFENSE_PENALTY_RATIO,
        }
