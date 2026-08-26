"""
War Advisor - AI Hard Difficulty

Profilo IA "difficile": un gradino sopra il normale, non un salto.

Comportamento ad alveare. Tutto scala verso l'alto (esercito, reclute,
miniere, fortificazioni, presidi) TRANNE l'aggressione in territorio nemico,
che scala al contrario:

- non si sbilancia quasi mai verso il castello nemico: consolida ed espande
  il territorio attorno a sé, dove combatte in casa con le proprie difese;
- appena una legione player supera la metà campo l'IA "si imbestialisce":
  molla l'espansione e converge sull'intruso;
- in quella fase può schierare una seconda legione per la difesa.

È l'opposto del profilo facile, che si lancia subito lontano da casa con un
esercito piccolo — ed è proprio quell'esposizione a renderlo facile da battere.

Il margine verso l'alto resta volutamente ampio: la difficoltà "incubo"
occuperà lo spazio sopra questo profilo.
"""

import random
from typing import Any, Dict, List, Optional, Tuple

from engine import aggregate_army, apply_modifiers, compute_ranking
from gamecore.economy import STARTING_GRUX, calculate_army_cost, get_unit_costs

AI_HARD_ID = "hard"

# ── Spinta verso il castello nemico ────────────────────────────────
# Volutamente la PIÙ BASSA delle tre difficoltà: l'alveare non esce di casa.
# Tenta il castello solo a partita inoltrata e con un esercito schiacciante,
# cioè quando è una decisione sensata e non un suicidio.
CASTLE_PUSH_FROM_TURN = 40   # facile: 4 · normale: 10
CASTLE_PUSH_RANGE = 13
CASTLE_PUSH_MIN_UNITS = 8    # facile: 2 · normale: 4
CASTLE_PUSH_CHANCE = 0.08    # facile: 0.62 · normale: 0.34
CASTLE_ADJACENT_CHANCE = 0.45  # facile: 0.88 · normale: 0.70

# ── Espansione (l'alveare cresce attorno a sé) ─────────────────────
ECONOMIC_TARGET_CHANCE = 0.72  # normale: 0.52 — conquista tutto intorno
STRATEGIC_TARGET_CHANCE = 0.92

# ── Risposta alle incursioni ───────────────────────────────────────
INTRUDER_FOCUS_CHANCE = 0.95   # chi supera la metà campo diventa LA priorità
MAX_LEGIONS = 2                # può schierare una seconda legione per difendersi
SECOND_LEGION_MIN_UNITS = 6    # solo se l'esercito regge la divisione in due

# ── Ritmo operativo ────────────────────────────────────────────────
TARGET_LOCK_TURNS = 2        # come il normale: non zig-zaga
FORTIFY_TURN_GATE = 2        # fortifica un turno su due

# ── Difesa del castello ────────────────────────────────────────────
CASTLE_GARRISON_TARGET = 3   # presidi sul proprio castello (tetto di gioco: 4)


class HardAIDifficultyPolicy:
    """Policy runtime IA: più solida del normale, ancora lontana dall'ottimo."""

    castle_garrison_target = CASTLE_GARRISON_TARGET

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)

    def target_lock_turns(self) -> int:
        return TARGET_LOCK_TURNS

    def fortify_turn_gate(self) -> int:
        return FORTIFY_TURN_GATE

    def max_legions(self) -> int:
        return MAX_LEGIONS

    def second_legion_min_units(self) -> int:
        return SECOND_LEGION_MIN_UNITS

    def should_focus_intruder(self, *, turn: int, intruder_count: int) -> bool:
        """L'alveare si imbestialisce: chi entra in casa diventa la priorità."""
        if intruder_count <= 0:
            return False
        return self.rng.random() < INTRUDER_FOCUS_CHANCE

    def should_skip_turn(self, turn: int) -> bool:
        if turn <= 2:
            return False
        return self.rng.random() < 0.015   # normale: 0.04

    def should_push_castle(
        self,
        *,
        turn: int,
        distance: Optional[int],
        legion_size: int,
    ) -> bool:
        """True solo quando l'assalto è una scelta sensata, non una scommessa."""
        if distance is None:
            return False
        if turn < CASTLE_PUSH_FROM_TURN:
            return False
        if legion_size < CASTLE_PUSH_MIN_UNITS:
            return False
        if distance > CASTLE_PUSH_RANGE:
            return False

        chance = CASTLE_PUSH_CHANCE
        # Con un esercito davvero schiacciante vale la pena uscire dall'alveare.
        if legion_size >= CASTLE_PUSH_MIN_UNITS * 2:
            chance += 0.12
        return self.rng.random() < min(0.30, chance)

    def choose_target(
        self,
        *,
        ai_pos: Tuple[int, int],
        player_pos: Optional[Tuple[int, int]],
        own_castle: Optional[Tuple[int, int]],
        enemy_castle: Optional[Tuple[int, int]],
        strategic_targets: List[Tuple[float, Any]],
        economic_targets: Optional[List[Tuple[int, int]]] = None,
        turn: int = 0,
        legion_size: int = 0,
    ) -> Optional[Tuple[int, int]]:
        # Difesa del proprio castello: raggio di allerta più ampio del normale.
        if player_pos and own_castle:
            player_to_own_castle = abs(player_pos[0] - own_castle[0]) + abs(player_pos[1] - own_castle[1])
            if player_to_own_castle <= 3:
                return player_pos

        dist_castle: Optional[int] = None
        if enemy_castle:
            dist_castle = abs(ai_pos[0] - enemy_castle[0]) + abs(ai_pos[1] - enemy_castle[1])
            if self.should_push_castle(turn=turn, distance=dist_castle, legion_size=legion_size):
                return enemy_castle

        # L'alveare cresce: l'espansione ha la precedenza sull'avventura.
        economic_targets = economic_targets or []
        if economic_targets and self.rng.random() < ECONOMIC_TARGET_CHANCE:
            top_k = economic_targets[: min(4, len(economic_targets))]
            return self.rng.choice(top_k)

        if enemy_castle and dist_castle is not None:
            if dist_castle <= 2 and self.rng.random() < CASTLE_ADJACENT_CHANCE:
                return enemy_castle

        if strategic_targets and self.rng.random() < STRATEGIC_TARGET_CHANCE:
            top_k = strategic_targets[: min(3, len(strategic_targets))]
            _, chosen_cell = self.rng.choice(top_k)
            return (chosen_cell.row, chosen_cell.col)

        if player_pos and self.rng.random() < 0.50:
            return player_pos

        if enemy_castle:
            return enemy_castle

        if player_pos:
            return player_pos

        return None

    def should_leave_garrison(self, *, is_castle: bool, is_strategic: bool, current_strength: int, available: int) -> bool:
        if available <= 0:
            return False
        if is_castle:
            return current_strength < 2 and self.rng.random() < 0.50   # normale: 0.36
        if is_strategic:
            return current_strength < 1 and self.rng.random() < 0.30   # normale: 0.18
        return False

    def should_start_research(self, turn: int) -> bool:
        if turn <= 3:
            return self.rng.random() < 0.95
        return self.rng.random() < 0.90

    def mine_attempts(self, available_slots: int, turn: int) -> int:
        if available_slots <= 0:
            return 0
        if self.rng.random() < 0.40:   # normale: 0.52 di saltare
            return 0
        return min(1, available_slots)

    def recruit_sharpness(self) -> float:
        """Prende quasi sempre una fra le migliori: sbaglia di rado."""
        return 5.0

    def should_recruit(self, *, grux_balance: int, turn: int) -> bool:
        base_chance = 0.93 if turn <= 10 else 0.90
        if grux_balance >= 120:
            base_chance += 0.05
        return self.rng.random() < min(0.98, base_chance)


def _score_unit_on_terrain(unit_attrs: Dict[str, float], terrain: str, terrain_modifiers: Dict[str, dict]) -> float:
    mods = terrain_modifiers.get(terrain, {})
    total = 0.0
    for attr, val in unit_attrs.items():
        mod = mods.get(attr, 1.0)
        if mod == "CRITICAL":
            effective = val * 0.5 if val < 0.5 else val
        else:
            effective = min(1.0, val * float(mod))
        total += effective
    return total


def build_ai_army_hard(
    data: Dict[str, Any],
    ai_terrain: str,
    weather: Optional[str],
    n_units: int = 3,
    budget: int = STARTING_GRUX,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    rng = random.Random(seed)

    all_units: List[Dict] = data["units"]
    terrain_modifiers: Dict[str, dict] = data["terrain"]
    strategies_list: List[Dict] = data["strategies"]
    affinities_data: Dict = data.get("unit_affinities", {})
    unit_costs = get_unit_costs(all_units)

    # Budget quasi pieno e rumore ridotto: sceglie unità più adatte al terreno.
    hard_budget = max(140, int(budget * rng.uniform(0.88, 1.0)))
    hard_unit_target = max(3, min(4, n_units + 1))

    unit_scores: List[Tuple[float, Dict]] = []
    for unit in all_units:
        score = _score_unit_on_terrain(unit["attributes"], ai_terrain, terrain_modifiers)
        score += rng.uniform(-0.12, 0.12)   # normale: ±0.2
        unit_scores.append((score, unit))

    unit_scores.sort(key=lambda x: x[0], reverse=True)
    # Pool più stretta del normale (0.65): pesca tra le unità davvero migliori.
    candidate_pool = unit_scores[: max(3, int(len(unit_scores) * 0.5))]

    selected_ids: List[str] = []
    running_cost = 0
    for _, unit in candidate_pool:
        unit_cost = unit_costs[unit["id"]]
        if running_cost + unit_cost > hard_budget:
            continue
        selected_ids.append(unit["id"])
        running_cost += unit_cost
        if len(selected_ids) >= hard_unit_target:
            break

    if not selected_ids:
        cheapest_unit = min(all_units, key=lambda unit: unit_costs[unit["id"]])
        selected_ids = [cheapest_unit["id"]]

    total_cost = calculate_army_cost(selected_ids, unit_costs)

    army_vector = aggregate_army(selected_ids, all_units)
    modified_vector, warnings = apply_modifiers(
        army_vector=army_vector,
        terrain_name=ai_terrain,
        weather_name=weather,
        troop_status_name="Fresche",
        modifiers_data=data,
    )

    ranking = compute_ranking(
        army_vector=modified_vector,
        strategies_list=strategies_list,
        unit_ids=selected_ids,
        terrain_name=ai_terrain,
        weather_name=weather,
        affinities_data=affinities_data,
    )

    return {
        "units": selected_ids,
        "unit_costs": {unit_id: unit_costs[unit_id] for unit_id in selected_ids},
        "army_cost": total_cost,
        "remaining_grux": max(0, hard_budget - total_cost),
        "troop_status": "Fresche",
        "army_vector": army_vector,
        "modified_vector": modified_vector,
        "critical_warnings": warnings,
        "strategy": ranking[0],
        "ranking": ranking,
    }
