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
    # [DOCTRINE-LAYER] Punti con cui è stata fatta l'ultima mossa: una legione
    # può marciarne più del ritmo base, e il pannello deve dire quelli veri.
    last_points_per_turn: int = MOVEMENT_POINTS_PER_TURN
    progress_ratio: float = 1.0
    missing_ratio: float = 0.0
    last_from_pos: tuple[int, int] | None = None
    last_to_pos: tuple[int, int] | None = None


class MovementPointsSystem:
    """Gestisce costi terreno e ritardi turn-based per player/IA e per singole legioni."""

    def __init__(
        self,
        points_per_turn: int = MOVEMENT_POINTS_PER_TURN,
        terrain_costs: Dict[str, int] | None = None,
    ) -> None:
        self.points_per_turn = max(1, int(points_per_turn))
        self.terrain_costs: Dict[str, int] = dict(terrain_costs or TERRAIN_MOVEMENT_COSTS)
        self._states: Dict[Occupation, MovementState] = {
            Occupation.PLAYER: self._new_state(),
            Occupation.AI: self._new_state(),
        }
        # Nel sistema a legioni ogni legione marcia per conto suo: lo stato per
        # entità non basta più, serve un ritardo indipendente per ciascuna.
        self._legion_states: Dict[str, MovementState] = {}

    # ── Chiavi e stato per legione ─────────────────────────────────

    @staticmethod
    def legion_key(entity: Occupation, legion_id: str) -> str:
        """Chiave stabile per lo stato movimento di una singola legione."""
        return f"{entity.value}:{legion_id}"

    def _new_state(self) -> MovementState:
        """Stato a riposo: nessun blocco, ritmo di marcia base."""
        return MovementState(
            last_cost=self.points_per_turn, last_points_per_turn=self.points_per_turn
        )

    def _legion_state(self, legion_key: str) -> MovementState:
        state = self._legion_states.get(legion_key)
        if state is None:
            state = self._new_state()
            self._legion_states[legion_key] = state
        return state

    def prune_legions(self, active_keys: set[str]) -> None:
        """Elimina lo stato delle legioni non più in campo (annientate o richiamate)."""
        for key in [k for k in self._legion_states if k not in active_keys]:
            del self._legion_states[key]

    def terrain_cost(self, terrain: str) -> int:
        """Costo punti movimento per entrare in un terreno."""
        if terrain in self.terrain_costs:
            return max(1, int(self.terrain_costs[terrain]))
        return DEFAULT_TERRAIN_MOVEMENT_COST

    # ── Logica condivisa (usata sia per entità che per legione) ─────

    def _apply_move(
        self,
        state: MovementState,
        terrain: str,
        from_pos: tuple[int, int] | None,
        to_pos: tuple[int, int] | None,
        points_per_turn: int | None = None,
    ) -> Dict[str, int | str | float]:
        # [DOCTRINE-LAYER] La dottrina può dare più punti del ritmo base.
        # Senza il layer nessuno passa questo parametro.
        punti = max(1, int(points_per_turn or self.points_per_turn))
        cost = self.terrain_cost(terrain)
        extra_wait_turns = max(0, ceil(cost / punti) - 1)
        progress_ratio = min(1.0, punti / max(1, cost))
        missing_ratio = max(0.0, 1.0 - progress_ratio)

        state.last_terrain = terrain
        state.last_cost = cost
        state.last_points_per_turn = punti
        state.blocked_turns = extra_wait_turns
        state.display_blocked_turns = extra_wait_turns
        state.progress_ratio = progress_ratio
        state.missing_ratio = missing_ratio
        state.last_from_pos = from_pos
        state.last_to_pos = to_pos

        return {
            "cost": cost,
            "points_per_turn": punti,
            "extra_wait_turns": extra_wait_turns,
            "terrain": terrain,
            "progress_ratio": progress_ratio,
            "missing_ratio": missing_ratio,
        }

    def register_move(
        self,
        entity: Occupation,
        terrain: str,
        from_pos: tuple[int, int] | None = None,
        to_pos: tuple[int, int] | None = None,
    ) -> Dict[str, int | str | float]:
        """Registra la mossa di un'entità e aggiorna il ritardo turni."""
        return self._apply_move(self._states[entity], terrain, from_pos, to_pos)

    def register_legion_move(
        self,
        legion_key: str,
        terrain: str,
        from_pos: tuple[int, int] | None = None,
        to_pos: tuple[int, int] | None = None,
        points_per_turn: int | None = None,
    ) -> Dict[str, int | str | float]:
        """Registra la mossa di una singola legione e aggiorna il suo ritardo turni."""
        return self._apply_move(
            self._legion_state(legion_key), terrain, from_pos, to_pos, points_per_turn
        )

    def _apply_consume_block(self, state: MovementState) -> Dict[str, int | str | bool]:
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

    def consume_block_if_any(self, entity: Occupation) -> Dict[str, int | str | bool]:
        """Consuma un turno di blocco movimento dell'entità, se presente."""
        return self._apply_consume_block(self._states[entity])

    def consume_legion_block_if_any(self, legion_key: str) -> Dict[str, int | str | bool]:
        """Consuma un turno di blocco movimento della legione, se presente."""
        return self._apply_consume_block(self._legion_state(legion_key))

    def _apply_export(self, state: MovementState) -> Dict[str, int | str]:
        defense_penalty_active = state.blocked_turns > 0
        defense_factor = 1.0 - MOVEMENT_DEFENSE_PENALTY_RATIO if defense_penalty_active else 1.0
        return {
            "points_per_turn": state.last_points_per_turn,
            "base_points_per_turn": self.points_per_turn,
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

    def export_entity_state(self, entity: Occupation) -> Dict[str, int | str]:
        """Stato serializzabile del movimento per una entità."""
        return self._apply_export(self._states[entity])

    def export_legion_state(self, legion_key: str) -> Dict[str, int | str]:
        """Stato serializzabile del movimento per una singola legione."""
        return self._apply_export(self._legion_state(legion_key))

    def _apply_defense_modifier(self, state: MovementState) -> Dict[str, int | float | bool]:
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

    def get_defense_modifier(self, entity: Occupation) -> Dict[str, int | float | bool]:
        """Modificatore difensivo dell'entità dovuto a movimento incompleto."""
        return self._apply_defense_modifier(self._states[entity])

    def get_legion_defense_modifier(self, legion_key: str) -> Dict[str, int | float | bool]:
        """Modificatore difensivo della legione dovuto a movimento incompleto."""
        return self._apply_defense_modifier(self._legion_state(legion_key))

    def export_config(self) -> Dict[str, int | Dict[str, int]]:
        """Configurazione serializzabile globale del sistema movimento."""
        return {
            "points_per_turn": self.points_per_turn,
            "terrain_costs": dict(self.terrain_costs),
            "defense_penalty_ratio": MOVEMENT_DEFENSE_PENALTY_RATIO,
        }
