"""
War Advisor - AI Normal Difficulty

Profilo IA "normal" bilanciato:
- esercito iniziale più solido dell'easy
- ricerca abilità e reclutamento quasi sempre eseguiti
- presidio e costruzione miniere ancora non costanti
- pressione offensiva leggermente superiore all'easy
"""

import random
from typing import Any, Dict, List, Optional, Tuple

from engine import aggregate_army, apply_modifiers, compute_ranking
from gamecore.economy import STARTING_GRUX, calculate_army_cost, get_unit_costs

AI_NORMAL_ID = "normal"


class NormalAIDifficultyPolicy:
    """Policy runtime IA: più consistente dell'easy ma non ottimale."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)

    def should_skip_turn(self, turn: int) -> bool:
        if turn <= 2:
            return False
        return self.rng.random() < 0.04

    def choose_target(
        self,
        *,
        ai_pos: Tuple[int, int],
        player_pos: Optional[Tuple[int, int]],
        own_castle: Optional[Tuple[int, int]],
        enemy_castle: Optional[Tuple[int, int]],
        strategic_targets: List[Tuple[float, Any]],
        economic_targets: Optional[List[Tuple[int, int]]] = None,
    ) -> Optional[Tuple[int, int]]:
        if player_pos and own_castle:
            player_to_own_castle = abs(player_pos[0] - own_castle[0]) + abs(player_pos[1] - own_castle[1])
            if player_to_own_castle <= 2:
                return player_pos

        economic_targets = economic_targets or []
        if economic_targets and self.rng.random() < 0.52:
            top_k = economic_targets[: min(4, len(economic_targets))]
            return self.rng.choice(top_k)

        if enemy_castle:
            dist_castle = abs(ai_pos[0] - enemy_castle[0]) + abs(ai_pos[1] - enemy_castle[1])
            if dist_castle <= 2 and self.rng.random() < 0.72:
                return enemy_castle

        if strategic_targets and self.rng.random() < 0.88:
            top_k = strategic_targets[: min(3, len(strategic_targets))]
            _, chosen_cell = self.rng.choice(top_k)
            return (chosen_cell.row, chosen_cell.col)

        if player_pos and self.rng.random() < 0.45:
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
            return current_strength < 2 and self.rng.random() < 0.36
        if is_strategic:
            return current_strength < 1 and self.rng.random() < 0.18
        return False

    def should_start_research(self, turn: int) -> bool:
        if turn <= 3:
            return self.rng.random() < 0.9
        return self.rng.random() < 0.82

    def mine_attempts(self, available_slots: int, turn: int) -> int:
        if available_slots <= 0:
            return 0
        if self.rng.random() < 0.52:
            return 0
        return min(1, available_slots)

    def should_recruit(self, *, grux_balance: int, turn: int) -> bool:
        base_chance = 0.88 if turn <= 10 else 0.82
        if grux_balance >= 130:
            base_chance += 0.07
        return self.rng.random() < min(0.97, base_chance)


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


def build_ai_army_normal(
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

    normal_budget = max(95, int(budget * rng.uniform(0.76, 0.92)))
    normal_unit_target = max(2, min(3, n_units))

    unit_scores: List[Tuple[float, Dict]] = []
    for unit in all_units:
        score = _score_unit_on_terrain(unit["attributes"], ai_terrain, terrain_modifiers)
        score += rng.uniform(-0.2, 0.2)
        unit_scores.append((score, unit))

    unit_scores.sort(key=lambda x: x[0], reverse=True)
    candidate_pool = unit_scores[: max(4, int(len(unit_scores) * 0.65))]

    selected_ids: List[str] = []
    running_cost = 0
    for _, unit in candidate_pool:
        unit_cost = unit_costs[unit["id"]]
        if running_cost + unit_cost > normal_budget:
            continue
        selected_ids.append(unit["id"])
        running_cost += unit_cost
        if len(selected_ids) >= normal_unit_target:
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
        "remaining_grux": max(0, normal_budget - total_cost),
        "troop_status": "Fresche",
        "army_vector": army_vector,
        "modified_vector": modified_vector,
        "critical_warnings": warnings,
        "strategy": ranking[0],
        "ranking": ranking,
    }
