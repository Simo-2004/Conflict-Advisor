"""
War Advisor - AI Nightmare Difficulty

Profilo IA "incubo": l'ultimo gradino. Non è il difficile con numeri più alti,
è un avversario che gioca in due fasi e non sbaglia.

FASE ALVEARE (iniziale)
- si trincera attorno al proprio castello: fortifica e presidia le caselle
  IMMEDIATAMENTE adiacenti, non celle a caso;
- espande e accumula, senza mai esporsi in territorio nemico;
- converge sempre su chi supera la metà campo.

FASE ANNIENTAMENTO (irreversibile)
- quando il vantaggio è misurabile (esercito, territorio, economia) commuta
  e marcia sul castello nemico con tutto ciò che ha, senza più tornare indietro.

Vantaggi strutturali dichiarati:
- +20% di budget iniziale;
- +2% di rendimento sulle proprie miniere rispetto a quelle del player;
- presidi comprati con il budget extra, che NON indeboliscono la legione in campo.

Chirurgia:
- scelta unità senza rumore casuale, sulle sinergie reali col terreno;
- strategia rivalutata durante la partita e adattata a come gioca il player;
- non esita mai.
"""

import random
from typing import Any, Dict, List, Optional, Tuple

from engine import aggregate_army, apply_modifiers, compute_ranking
from gamecore.economy import STARTING_GRUX, calculate_army_cost, get_unit_costs

AI_NIGHTMARE_ID = "nightmare"

# ── Vantaggi strutturali ───────────────────────────────────────────
BUDGET_MULTIPLIER = 1.20        # +20% di budget iniziale
MINE_INCOME_MULTIPLIER = 1.02   # +2% sulle miniere rispetto al player

# ── Anello difensivo attorno al castello ───────────────────────────
CASTLE_RING_MAX_FORT_LEVEL = 4   # quanto alza le fortificazioni sull'anello
CASTLE_RING_TARGET_GARRISON = 2  # unità di presidio volute per casella dell'anello
CASTLE_RING_RESERVE_GRUX = 60    # non svuota le casse: sotto questa soglia non compra presidi
CASTLE_GARRISON_TARGET = 4       # presidi sul proprio castello: il massimo consentito

# ── Commutazione di fase ───────────────────────────────────────────
DOMINATION_MIN_TURN = 18         # non commuta prima di essersi costruita
DOMINATION_ARMY_RATIO = 1.6      # esercito almeno 1.6x quello del player
DOMINATION_CELL_RATIO = 1.25     # territorio almeno 1.25x
DOMINATION_GRUX_RATIO = 1.4      # economia almeno 1.4x

# ── Spinta verso il castello nemico (dipende dalla fase) ───────────
HIVE_CASTLE_PUSH_CHANCE = 0.04   # in fase alveare praticamente mai
HIVE_CASTLE_PUSH_MIN_UNITS = 10
HIVE_CASTLE_PUSH_FROM_TURN = 40

# ── Espansione ─────────────────────────────────────────────────────
ECONOMIC_TARGET_CHANCE = 0.74
STRATEGIC_TARGET_CHANCE = 0.94
# In fase alveare l'espansione resta nella propria metà campo: senza questo
# vincolo l'IA insegue il miglior obiettivo ovunque sia e finisce per marciare
# in linea retta dentro casa del player, esponendo la legione e — soprattutto —
# controllando poche celle, quindi pochi slot miniera e un'economia asfittica.
CONFINE_TO_OWN_HALF_IN_HIVE = True
# Penalità distanza sull'espansione: alta = cresce a macchia attorno a sé
# invece di puntare celle ghiotte ma lontane (default motore: 0.18).
EXPANSION_DISTANCE_PENALTY = 0.62

# ── Risposta alle incursioni ───────────────────────────────────────
INTRUDER_FOCUS_CHANCE = 1.0      # sempre
MAX_LEGIONS = 2
SECOND_LEGION_MIN_UNITS = 5

# ── Ritmo operativo ────────────────────────────────────────────────
TARGET_LOCK_TURNS = 2
FORTIFY_TURN_GATE = 1            # fortifica ogni turno
STRATEGY_REVIEW_EVERY = 5        # rivaluta la strategia ogni N turni

PHASE_HIVE = "alveare"
PHASE_ANNIHILATION = "annientamento"


class NightmareAIDifficultyPolicy:
    """Policy runtime IA: due fasi, nessuna esitazione, adattamento continuo."""

    castle_garrison_target = CASTLE_GARRISON_TARGET

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)
        self.phase: str = PHASE_HIVE
        self.phase_switch_turn: Optional[int] = None
        # Lettura del comportamento player, aggiornata dal motore ogni turno.
        self.player_profile: str = "sconosciuto"

    # ── Vantaggi strutturali ───────────────────────────────────────

    def budget_multiplier(self) -> float:
        return BUDGET_MULTIPLIER

    def mine_income_multiplier(self) -> float:
        return MINE_INCOME_MULTIPLIER

    def confine_expansion_to_own_half(self) -> bool:
        """In fase alveare non si espande oltre la metà campo; in annientamento sì."""
        if not CONFINE_TO_OWN_HALF_IN_HIVE:
            return False
        return self.phase != PHASE_ANNIHILATION

    def expansion_distance_penalty(self) -> float:
        """Quanto pesa la distanza nella scelta degli obiettivi di espansione."""
        if self.phase == PHASE_ANNIHILATION:
            return 0.18   # in offensiva la distanza non è più un problema
        return EXPANSION_DISTANCE_PENALTY

    def castle_ring_plan(self) -> Dict[str, int]:
        """Parametri dell'anello difensivo attorno al castello."""
        return {
            "max_fort_level": CASTLE_RING_MAX_FORT_LEVEL,
            "target_garrison": CASTLE_RING_TARGET_GARRISON,
            "reserve_grux": CASTLE_RING_RESERVE_GRUX,
        }

    # ── Ritmo operativo ────────────────────────────────────────────

    def target_lock_turns(self) -> int:
        return TARGET_LOCK_TURNS

    def fortify_turn_gate(self) -> int:
        return FORTIFY_TURN_GATE

    def max_legions(self) -> int:
        return MAX_LEGIONS

    def second_legion_min_units(self) -> int:
        return SECOND_LEGION_MIN_UNITS

    def should_skip_turn(self, turn: int) -> bool:
        """Non esita mai."""
        return False

    def should_review_strategy(self, turn: int) -> bool:
        return turn % STRATEGY_REVIEW_EVERY == 0

    # ── Fase e lettura del player ──────────────────────────────────

    def update_phase(
        self,
        *,
        turn: int,
        ai_army: int,
        player_army: int,
        ai_cells: int,
        player_cells: int,
        ai_grux: int,
        player_grux: int,
        player_intruding: bool,
    ) -> str:
        """Aggiorna fase e profilo del player. La fase annientamento è definitiva."""
        # Lettura di come sta giocando il player.
        if player_intruding:
            self.player_profile = "aggressivo"
        elif player_army >= max(1, ai_army):
            self.player_profile = "militarista"
        elif player_cells >= max(1, ai_cells):
            self.player_profile = "espansivo"
        else:
            self.player_profile = "passivo"

        if self.phase == PHASE_ANNIHILATION:
            return self.phase
        if turn < DOMINATION_MIN_TURN:
            return self.phase

        army_ok = ai_army >= max(1, player_army) * DOMINATION_ARMY_RATIO
        cells_ok = ai_cells >= max(1, player_cells) * DOMINATION_CELL_RATIO
        grux_ok = ai_grux >= max(1, player_grux) * DOMINATION_GRUX_RATIO

        # Serve superiorità militare più almeno un secondo asse: non basta
        # essere ricchi, e non basta avere truppe senza territorio o casse.
        if army_ok and (cells_ok or grux_ok):
            self.phase = PHASE_ANNIHILATION
            self.phase_switch_turn = turn

        return self.phase

    def is_annihilating(self) -> bool:
        return self.phase == PHASE_ANNIHILATION

    def strategy_bias(self) -> Dict[str, float]:
        """Pesi per la scelta strategia, in base a fase e comportamento player."""
        if self.phase == PHASE_ANNIHILATION:
            return {"offense": 1.0, "defense": 0.0}
        if self.player_profile == "aggressivo":
            return {"offense": 0.15, "defense": 1.0}
        if self.player_profile == "militarista":
            return {"offense": 0.45, "defense": 0.75}
        return {"offense": 0.6, "defense": 0.4}

    # ── Decisioni tattiche ─────────────────────────────────────────

    def should_focus_intruder(self, *, turn: int, intruder_count: int) -> bool:
        # In fase annientamento non si fa distrarre: punta il castello.
        if self.phase == PHASE_ANNIHILATION:
            return False
        return intruder_count > 0

    def should_push_castle(
        self,
        *,
        turn: int,
        distance: Optional[int],
        legion_size: int,
    ) -> bool:
        if distance is None:
            return False
        if self.phase == PHASE_ANNIHILATION:
            return True   # nessun ripensamento: si va e basta
        if turn < HIVE_CASTLE_PUSH_FROM_TURN:
            return False
        if legion_size < HIVE_CASTLE_PUSH_MIN_UNITS:
            return False
        return self.rng.random() < HIVE_CASTLE_PUSH_CHANCE

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
        # Fase annientamento: unico obiettivo, il castello.
        if self.phase == PHASE_ANNIHILATION and enemy_castle:
            return enemy_castle

        # Difesa di casa: raggio d'allerta il più ampio dei profili.
        if player_pos and own_castle:
            player_to_own_castle = abs(player_pos[0] - own_castle[0]) + abs(player_pos[1] - own_castle[1])
            if player_to_own_castle <= 4:
                return player_pos

        dist_castle: Optional[int] = None
        if enemy_castle:
            dist_castle = abs(ai_pos[0] - enemy_castle[0]) + abs(ai_pos[1] - enemy_castle[1])
            if self.should_push_castle(turn=turn, distance=dist_castle, legion_size=legion_size):
                return enemy_castle

        economic_targets = economic_targets or []
        if economic_targets and self.rng.random() < ECONOMIC_TARGET_CHANCE:
            top_k = economic_targets[: min(4, len(economic_targets))]
            return self.rng.choice(top_k)

        if strategic_targets and self.rng.random() < STRATEGIC_TARGET_CHANCE:
            top_k = strategic_targets[: min(3, len(strategic_targets))]
            _, chosen_cell = self.rng.choice(top_k)
            return (chosen_cell.row, chosen_cell.col)

        # Niente più da conquistare in casa: in fase alveare si stringe attorno
        # al castello invece di partire all'avventura.
        if self.phase != PHASE_ANNIHILATION:
            return own_castle or player_pos

        if player_pos:
            return player_pos

        return enemy_castle

    def should_leave_garrison(self, *, is_castle: bool, is_strategic: bool, current_strength: int, available: int) -> bool:
        if available <= 0:
            return False
        if is_castle:
            return current_strength < 3
        if is_strategic:
            return current_strength < 2
        return False

    def should_start_research(self, turn: int) -> bool:
        return True

    def mine_attempts(self, available_slots: int, turn: int) -> int:
        # Non salta mai una miniera disponibile.
        return min(2, max(0, available_slots))

    def should_recruit(self, *, grux_balance: int, turn: int) -> bool:
        return True


def _unit_synergy_score(
    unit: Dict[str, Any],
    terrain: str,
    terrain_modifiers: Dict[str, dict],
) -> float:
    """Punteggio chirurgico: resa reale dell'unità sul terreno, senza rumore."""
    attrs = unit["attributes"]
    mods = terrain_modifiers.get(terrain, {})
    total = 0.0
    for attr, val in attrs.items():
        mod = mods.get(attr, 1.0)
        if mod == "CRITICAL":
            effective = val * 0.5 if val < 0.5 else val
        else:
            effective = min(1.0, val * float(mod))
        total += effective

    # Premia le unità che pesano dove conta davvero in combattimento,
    # con gli stessi pesi usati dal motore per il valore di battaglia.
    combat_weight = (
        attrs["U1_attack"] * 24
        + attrs["U2_defense"] * 20
        + attrs["U5_discipline"] * 14
        + attrs["U3_mobility"] * 12
    ) / 70.0
    return total + combat_weight


def build_ai_army_nightmare(
    data: Dict[str, Any],
    ai_terrain: str,
    weather: Optional[str],
    n_units: int = 3,
    budget: int = STARTING_GRUX,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Costruzione chirurgica: budget maggiorato, nessuna casualità, massimo valore."""
    all_units: List[Dict] = data["units"]
    terrain_modifiers: Dict[str, dict] = data["terrain"]
    strategies_list: List[Dict] = data["strategies"]
    affinities_data: Dict = data.get("unit_affinities", {})
    unit_costs = get_unit_costs(all_units)

    nightmare_budget = int(budget * BUDGET_MULTIPLIER)

    # Nessun rumore: ordina per resa reale e riempie il budget partendo dal meglio,
    # senza fermarsi al primo che non ci sta (così sfrutta ogni grux disponibile).
    scored = sorted(
        all_units,
        key=lambda u: _unit_synergy_score(u, ai_terrain, terrain_modifiers),
        reverse=True,
    )

    selected_ids: List[str] = []
    running_cost = 0
    target_units = max(3, n_units + 1)
    for unit in scored:
        cost = unit_costs[unit["id"]]
        if running_cost + cost > nightmare_budget:
            continue
        selected_ids.append(unit["id"])
        running_cost += cost
        if len(selected_ids) >= target_units:
            break

    # Se avanza budget, raddoppia sull'unità migliore che ci sta ancora.
    for unit in scored:
        cost = unit_costs[unit["id"]]
        if running_cost + cost <= nightmare_budget:
            selected_ids.append(unit["id"])
            running_cost += cost
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
        "remaining_grux": max(0, nightmare_budget - total_cost),
        "troop_status": "Fresche",
        "army_vector": army_vector,
        "modified_vector": modified_vector,
        "critical_warnings": warnings,
        "strategy": ranking[0],
        "ranking": ranking,
    }
