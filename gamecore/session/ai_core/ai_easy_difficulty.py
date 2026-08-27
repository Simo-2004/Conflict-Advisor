"""
War Advisor - AI Easy Difficulty

Profilo IA "easy" con comportamento più indulgente:
- esercito iniziale ridotto
- pressione strategica/castello meno aggressiva
- reclute/miniere/ricerche non sempre eseguite
- garrisoning più raro
"""

import random
from typing import Any, Dict, List, Optional, Tuple

from engine import aggregate_army, apply_modifiers, compute_ranking
from gamecore.economy import STARTING_GRUX, calculate_army_cost, get_unit_costs

AI_EASY_ID = "easy"

# ── Spinta verso il castello nemico ────────────────────────────────
# L'aggressione è l'UNICO asse che scala al contrario della difficoltà.
# Il profilo "facile" è il più avventato: si lancia presto verso il castello
# con una legione ancora piccola, ed è proprio questo a renderlo facile —
# un esercito debole che si espone lontano da casa è comodo da distruggere.
CASTLE_PUSH_FROM_TURN = 4    # parte quasi subito
CASTLE_PUSH_RANGE = 13       # tutta la mappa: attacca da qualunque distanza
CASTLE_PUSH_MIN_UNITS = 2    # non aspetta di essere pronta
CASTLE_PUSH_CHANCE = 0.62    # spinta frequente
CASTLE_ADJACENT_CHANCE = 0.88  # a ridosso del castello attacca quasi sempre

# ── Risposta alle incursioni ───────────────────────────────────────
MAX_LEGIONS = 1              # nessuna seconda legione difensiva
INTRUDER_FOCUS_CHANCE = 0.0  # ignora chi entra in casa: continua la sua corsa

# ── Ritmo operativo ────────────────────────────────────────────────
TARGET_LOCK_TURNS = 3        # cambia obiettivo di rado: sembra più indeciso
FORTIFY_TURN_GATE = 3        # fortifica un turno su tre

# ── Difesa del castello ────────────────────────────────────────────
CASTLE_GARRISON_TARGET = 1   # presidi sul proprio castello (tetto di gioco: 4)


class EasyAIDifficultyPolicy:
    """Policy runtime per rendere il comportamento IA meno oppressivo."""

    castle_garrison_target = CASTLE_GARRISON_TARGET

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)

    def target_lock_turns(self) -> int:
        return TARGET_LOCK_TURNS

    def fortify_turn_gate(self) -> int:
        return FORTIFY_TURN_GATE

    def max_legions(self) -> int:
        return MAX_LEGIONS

    def should_focus_intruder(self, *, turn: int, intruder_count: int) -> bool:
        """L'IA facile non reagisce alle incursioni: resta sulla sua corsa."""
        return False

    def should_push_castle(
        self,
        *,
        turn: int,
        distance: Optional[int],
        legion_size: int,
    ) -> bool:
        """True se l'IA deve puntare il castello nemico invece di espandersi."""
        if distance is None:
            return False
        if turn < CASTLE_PUSH_FROM_TURN:
            return False
        if legion_size < CASTLE_PUSH_MIN_UNITS:
            return False
        if distance > CASTLE_PUSH_RANGE:
            return False
        return self.rng.random() < CASTLE_PUSH_CHANCE

    def should_skip_turn(self, turn: int) -> bool:
        if turn <= 2:
            return False
        return self.rng.random() < 0.14

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
        if player_pos and own_castle:
            player_to_own_castle = abs(player_pos[0] - own_castle[0]) + abs(player_pos[1] - own_castle[1])
            if player_to_own_castle <= 2:
                return player_pos

        # Spinta offensiva sul castello: valutata prima dell'espansione economica,
        # altrimenti l'IA rimanda l'assalto all'infinito.
        dist_castle: Optional[int] = None
        if enemy_castle:
            dist_castle = abs(ai_pos[0] - enemy_castle[0]) + abs(ai_pos[1] - enemy_castle[1])
            if self.should_push_castle(turn=turn, distance=dist_castle, legion_size=legion_size):
                return enemy_castle

        economic_targets = economic_targets or []
        if economic_targets and self.rng.random() < 0.64:
            top_k = economic_targets[: min(3, len(economic_targets))]
            return self.rng.choice(top_k)

        if strategic_targets and self.rng.random() < 0.78:
            top_k = strategic_targets[: min(3, len(strategic_targets))]
            _, chosen_cell = self.rng.choice(top_k)
            return (chosen_cell.row, chosen_cell.col)

        if player_pos and self.rng.random() < 0.32:
            return player_pos

        if enemy_castle and dist_castle is not None:
            if dist_castle <= 2 and self.rng.random() < CASTLE_ADJACENT_CHANCE:
                return enemy_castle
            if dist_castle > 2 and strategic_targets and self.rng.random() < 0.8:
                _, chosen_cell = strategic_targets[0]
                return (chosen_cell.row, chosen_cell.col)

        if player_pos:
            return player_pos

        if enemy_castle:
            return enemy_castle

        return None

    def should_leave_garrison(self, *, is_castle: bool, is_strategic: bool, current_strength: int, available: int) -> bool:
        if available <= 0:
            return False
        if is_castle:
            return current_strength < 2 and self.rng.random() < 0.55
        if is_strategic:
            return current_strength < 1 and self.rng.random() < 0.35
        return False

    def should_start_research(self, turn: int) -> bool:
        if turn <= 3:
            return self.rng.random() < 0.35
        return self.rng.random() < 0.22

    def mine_attempts(self, available_slots: int, turn: int) -> int:
        if available_slots <= 0:
            return 0
        if self.rng.random() < 0.4:
            return 0
        return min(1, available_slots)

    def recruit_sharpness(self) -> float:
        """A zero: sceglie a caso fra le truppe che può permettersi.

        Il punteggio esiste, l'IA facile non lo guarda. Ne esce un'armata
        varia ma senza criterio — più debole di quando comprava sempre la
        truppa migliore, ed è esattamente il punto.
        """
        return 0.0

    def should_recruit(self, *, grux_balance: int, turn: int) -> bool:
        base_chance = 0.45 if turn <= 8 else 0.38
        if grux_balance >= 120:
            base_chance += 0.1
        return self.rng.random() < base_chance


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


def build_ai_army_easy(
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

    easy_budget = max(70, int(budget * rng.uniform(0.42, 0.58)))
    easy_unit_target = max(1, min(2, n_units - 1))

    unit_scores: List[Tuple[float, Dict]] = []
    for unit in all_units:
        score = _score_unit_on_terrain(unit["attributes"], ai_terrain, terrain_modifiers)
        score += rng.uniform(-0.32, 0.32)
        unit_scores.append((score, unit))

    unit_scores.sort(key=lambda x: x[0], reverse=True)
    candidate_pool = unit_scores[: max(3, len(unit_scores) // 2)]

    selected_ids: List[str] = []
    running_cost = 0
    shuffled_pool = candidate_pool[:]
    rng.shuffle(shuffled_pool)
    for _, unit in shuffled_pool:
        unit_cost = unit_costs[unit["id"]]
        if running_cost + unit_cost > easy_budget:
            continue
        selected_ids.append(unit["id"])
        running_cost += unit_cost
        if len(selected_ids) >= easy_unit_target:
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
        "remaining_grux": max(0, easy_budget - total_cost),
        "troop_status": "Fresche",
        "army_vector": army_vector,
        "modified_vector": modified_vector,
        "critical_warnings": warnings,
        "strategy": ranking[0],
        "ranking": ranking,
    }
