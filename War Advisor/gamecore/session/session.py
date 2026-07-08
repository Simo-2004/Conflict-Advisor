"""
War Advisor - GameSession

Gestisce una partita dove l'obiettivo è conquistare il castello avversario.
Le armate sul campo possono lasciare guarnigioni per rallentare l'assalto e,
quando perdono uno scontro, si ritirano al proprio castello invece di sparire.
"""

import random
from enum import Enum
from collections import Counter, deque
from typing import Any, Dict, List, Optional, Tuple

from engine import aggregate_army, apply_modifiers, euclidean_distance
from gamecore.economy import MINE_YIELD_PER_ROUND, STARTING_GRUX, available_mine_slots, get_unit_costs
from gamecore.maps import GameMap, Occupation
from gamecore.session.abilities import DOMAIN_ENGINEERING_ID, build_default_ability_states
from gamecore.session.ai_core.ai_builder import (
    build_ai_policy,
    get_ai_difficulty_labels,
    normalize_ai_difficulty,
)
from gamecore.session.ai_core.ai_easy_difficulty import AI_EASY_ID
from gamecore.session.ai_core.ai_normal_difficulty import AI_NORMAL_ID
from gamecore.session.in_game_advisor import build_in_game_advisor_payload
from gamecore.session.movement_points import MovementPointsSystem

try:
    from debug.strength_debug import log_strength_debug
except Exception:
    def log_strength_debug(event: str, payload: Dict[str, Any]) -> None:
        return

try:
    from debug.battle_log_capture import create_battle_log_capture
except Exception:
    def create_battle_log_capture() -> List[str]:
        return []

PLAYER = Occupation.PLAYER
AI = Occupation.AI

AI_LEGION_NAMES = [
    "Falange Nera",
    "Corvo di Ferro",
    "Lupi Scarlatti",
    "Ariete d'Acciaio",
    "Ombre del Nord",
    "Legione del Drago",
    "Spade Vermiglie",
    "Guardia Ferrea",
    "Orda Grigia",
    "Legione della Tempesta",
    "Artigli Neri",
    "Falce Cremisi",
    "Legione Spezzata",
    "Vento di Guerra",
    "Fauci d'Acciaio",
]

PLAYER_CONTROL_MODE_OPTIONS = ["orders", "manual"]
PLAYER_CONTROL_MODES = set(PLAYER_CONTROL_MODE_OPTIONS)
PLAYER_MOVEMENT_ORDER_OPTIONS = [
    "advance_castle",
    "engage_ai",
    "expand_front",
    "defend_castle",
    "hold",
]
PLAYER_MOVEMENT_ORDERS = set(PLAYER_MOVEMENT_ORDER_OPTIONS)
PLAYER_BUILD_ORDER_OPTIONS = [
    "balanced",
    "economy",
    "fortify",
    "garrison",
    "none",
]
PLAYER_BUILD_ORDERS = set(PLAYER_BUILD_ORDER_OPTIONS)

CASTLE_BASE_HP = 220
CASTLE_HP_PER_UNIT = 8


class SessionState(str, Enum):
    ACTIVE    = "active"
    GAME_OVER = "game_over"


class GameSession:
    """
    Sessione di gioco completa.

    Attributi principali:
        player_units        — ID unità del giocatore
        player_strategy_id  — ID strategia confermata
        player_army         — vettore raw del giocatore
        player_modified     — vettore modificato per il terreno iniziale
        player_troop_status — stato truppe del giocatore

        ai_units            — ID unità dell'IA (scelte da ai_builder)
        ai_strategy_id/name — strategia ottimale dell'IA
        ai_army             — vettore raw dell'IA
        ai_modified         — vettore modificato per il terreno IA
        ai_troop_status     — stato truppe IA (sempre "Fresche" all'inizio)

        weather             — condizione meteo globale (opzionale)
        game_map            — istanza GameMap
        state               — SessionState corrente
        winner              — "player" | "ai" | None
        battle_log          — registro cronologico degli scontri
    """

    def __init__(
        self,
        *,
        # Player
        player_units: List[str],
        player_strategy_id: str,
        player_army: Dict[str, float],
        player_modified: Dict[str, float],
        player_troop_status: Optional[str],
        player_budget: int,
        player_army_cost: int,
        # AI (output di ai_builder.build_ai_army)
        ai_data: Dict[str, Any],
        # Ambiente
        weather: Optional[str],
        # Dati engine
        data: Dict[str, Any],
        player_home_terrain: str,
        # Mappa
        map_seed: Optional[int] = None,
        ai_difficulty: str = AI_EASY_ID,
    ) -> None:
        self.data = data
        self.units_map = {unit["id"]: unit for unit in self.data["units"]}
        self.strategies_map = {strategy["id"]: strategy for strategy in self.data["strategies"]}
        self.unit_costs = get_unit_costs(self.data["units"])
        self.player_home_terrain = player_home_terrain
        self.ai_home_terrain = "Montagna"

        # --- Giocatore ---
        self.player_units         = player_units
        self.player_strategy_id   = player_strategy_id
        self.player_army          = player_army
        self.player_modified      = player_modified
        self.player_troop_status  = player_troop_status
        self.player_army_cost     = player_army_cost

        # --- IA ---
        self.ai_units         = ai_data["units"]
        self.ai_strategy_id   = ai_data["strategy"]["id"]
        self.ai_strategy_name = ai_data["strategy"]["name"]
        self.ai_army          = ai_data["army_vector"]
        self.ai_modified      = ai_data["modified_vector"]
        self.ai_troop_status  = ai_data["troop_status"]
        self.ai_army_cost     = ai_data.get("army_cost", 0)

        # --- Ambiente ---
        self.weather = weather

        # --- Legioni (Nuovo Sistema) ---
        self.player_legions: Dict[str, Dict[str, Any]] = {}
        self.ai_legions: Dict[str, Dict[str, Any]] = {}
        self.next_legion_id: int = 1
        self.ai_legion_respawn_delay_turns: int = 2
        self.ai_last_legion_loss_turn: Optional[int] = None

        # --- Mappa ---
        self.game_map: GameMap = GameMap(seed=map_seed)

        # --- Stato ---
        self.state:      SessionState  = SessionState.ACTIVE
        self.winner:     Optional[str] = None
        self.battle_log: List[str]     = create_battle_log_capture()
        self.grux_balance: Dict[Occupation, int] = {
            PLAYER: player_budget,
            AI: ai_data.get("remaining_grux", STARTING_GRUX - self.ai_army_cost),
        }
        self.base_fortification_cost: int = 45
        self.ability_states: Dict[Occupation, Dict[str, Any]] = {
            PLAYER: build_default_ability_states(),
            AI: build_default_ability_states(),
        }
        self.recruit_cooldown_turns: int = 2
        self.last_recruit_turn: Dict[Occupation, Optional[int]] = {
            PLAYER: None,
            AI: None,
        }
        self.debug_ai_kill_switch: bool = False
        self.ai_difficulty: str = normalize_ai_difficulty(ai_difficulty)
        self.ai_policy = build_ai_policy(self.ai_difficulty, seed=map_seed)
        self.ai_policy_seed = map_seed
        self.movement_system = MovementPointsSystem()
        self.player_control_mode: str = "manual"
        self.player_orders: Dict[str, str] = {
            "movement_order": "advance_castle",
            "build_order": "balanced",
        }
        self.player_order_memory: Dict[str, Any] = {
            "last_direction": None,
            "straight_streak": 0,
        }
        self.player_auto_recruit: Dict[str, Any] = {
            "enabled": False,
            "unit_id": None,
            "unit_name": None,
            "turns_total": 0,
            "turns_remaining": 0,
            "attempted_turns": 0,
            "successful_recruits": 0,
            "last_result": "inactive",
        }
        # Rimosso il vecchio sistema a ordini. Il turno avanza con execute_turn() e muove le legioni.
        self.castle_hp_max: Dict[Occupation, int] = self._build_castle_hp_pool()
        self.castle_hp: Dict[Occupation, int] = dict(self.castle_hp_max)

    def _build_castle_hp_pool(self) -> Dict[Occupation, int]:
        player_max = CASTLE_BASE_HP + (len(self.player_units) * CASTLE_HP_PER_UNIT)
        ai_max = CASTLE_BASE_HP + (len(self.ai_units) * CASTLE_HP_PER_UNIT)
        return {
            PLAYER: player_max,
            AI: ai_max,
        }

    def _mine_income_for_count(self, mine_count: int) -> int:
        """Rendimento miniere a bande: pieno early, decrescente in late game."""
        if mine_count <= 0:
            return 0

        tier_1 = min(mine_count, 4)
        tier_2 = min(max(0, mine_count - 4), 4)
        tier_3 = min(max(0, mine_count - 8), 4)
        tier_4 = max(0, mine_count - 12)

        return (
            (tier_1 * MINE_YIELD_PER_ROUND)
            + (tier_2 * int(round(MINE_YIELD_PER_ROUND * 0.8)))
            + (tier_3 * int(round(MINE_YIELD_PER_ROUND * 0.6)))
            + (tier_4 * int(round(MINE_YIELD_PER_ROUND * 0.4)))
        )

    def _compute_castle_damage(self, attacker_strength: float, defender_score: float) -> int:
        """Danno inflitto al castello quando l'assalto supera la difesa statica."""
        overflow = max(0.0, attacker_strength - defender_score)
        raw_damage = (overflow * 0.12) + (attacker_strength * 0.02)
        return max(8, min(65, int(round(raw_damage))))

    # ──────────────────────────────────────────────────────────
    # LEGIONI
    # ──────────────────────────────────────────────────────────

    def _get_free_spawn_cell(self, entity: Occupation, start_pos: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """Trova una cella adiacente libera per spawnare una legione (o il castello stesso se vuoto)."""
        r, c = start_pos
        cell = self.game_map.get_cell(r, c)

        own_legions = self.player_legions if entity == PLAYER else self.ai_legions
        castle_has_legion = any(tuple(leg.get("pos", ())) == (r, c) for leg in own_legions.values())
        if not castle_has_legion and cell and cell.terrain != "Fiume":
            return (r, c)

        # Cerca adiacenti liberi
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            adj = self.game_map.get_cell(nr, nc)
            if adj and adj.terrain != "Fiume":
                if not any(tuple(leg.get("pos", ())) == (nr, nc) for leg in own_legions.values()):
                    return (nr, nc)
        return None

    def create_player_legion(self, name: str, units_dict: Dict[str, int], target: Optional[Tuple[int, int]]) -> Dict[str, Any]:
        if self.state != SessionState.ACTIVE:
            raise ValueError("Partita terminata.")
            
        # Verifica disponibilità truppe nella riserva
        from collections import Counter
        reserve_counts = Counter(self.player_units)
        
        for uid, qty in units_dict.items():
            if reserve_counts.get(uid, 0) < qty:
                raise ValueError(f"Non hai abbastanza unità di tipo {uid} nel castello.")
                
        # Rimuovi le truppe dalla riserva
        legion_units = []
        for uid, qty in units_dict.items():
            for _ in range(qty):
                self.player_units.remove(uid)
                legion_units.append(uid)
                
        # Spawn position
        castle_pos = self.game_map.castle_positions[PLAYER]
        spawn_pos = self._get_free_spawn_cell(PLAYER, castle_pos)
        if not spawn_pos:
            # Fallback al castello comunque (sovrapposizione)
            spawn_pos = castle_pos
            
        legion_id = f"L_{self.next_legion_id}"
        self.next_legion_id += 1
        
        self.player_legions[legion_id] = {
            "id": legion_id,
            "name": name,
            "units": legion_units,
            "pos": spawn_pos,
            "target": target,
            "path": [],
            "path_step": 0
        }
        
        self.battle_log.append(f"⚔️ PLAYER addestra la legione '{name}' e la invia verso {target if target else 'attesa'}.")
        
        # Aggiorna controllo mappa
        cell = self.game_map.get_cell(*spawn_pos)
        if cell and cell.occupation != PLAYER:
            cell.occupation = PLAYER
            
        return {
            "ok": True,
            "message": f"Legione {name} creata",
            "session": self.to_dict()
        }

    def recall_player_legion(self, legion_id: str) -> Dict[str, Any]:
        """Richiama una legione PLAYER: le sue unità tornano istantaneamente in riserva."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("Partita terminata.")

        legion = self.player_legions.get(legion_id)
        if legion is None:
            raise ValueError(f"Legione non trovata: {legion_id}")

        name = legion.get("name", legion_id)
        legion_units = legion.get("units", [])
        self.player_units.extend(legion_units)
        del self.player_legions[legion_id]

        log_entry = (
            f"[Turno {self.game_map.turn}] 🏳 PLAYER: Legione '{name}' richiamata "
            f"— {len(legion_units)} unità tornano in riserva."
        )
        self.battle_log.append(log_entry)

        return {
            "ok": True,
            "message": log_entry,
            "session": self.to_dict()
        }

    def retarget_player_legion(self, legion_id: str, target: Tuple[int, int]) -> Dict[str, Any]:
        """Assegna una nuova destinazione a una legione PLAYER già in campo."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("Partita terminata.")

        legion = self.player_legions.get(legion_id)
        if legion is None:
            raise ValueError(f"Legione non trovata: {legion_id}")

        target = (int(target[0]), int(target[1]))
        if self.game_map.get_cell(*target) is None:
            raise ValueError("Cella di destinazione fuori dai limiti della mappa.")

        legion["target"] = target
        name = legion.get("name", legion_id)

        log_entry = (
            f"[Turno {self.game_map.turn}] 🧭 PLAYER: Legione '{name}' ridiretta verso {target}."
        )
        self.battle_log.append(log_entry)

        return {
            "ok": True,
            "message": log_entry,
            "session": self.to_dict()
        }

    def _ensure_ai_legions_initialized(self) -> None:
        """Spawna una legione IA se assente, con cooldown dopo annientamento."""
        if self.ai_legions or not self.ai_units:
            return

        if self.ai_last_legion_loss_turn is not None:
            turns_since_loss = self.game_map.turn - self.ai_last_legion_loss_turn
            if turns_since_loss < self.ai_legion_respawn_delay_turns:
                return

        if self.debug_ai_kill_switch:
            return

        castle_pos = self.game_map.castle_positions[AI]
        spawn_pos = self._get_free_spawn_cell(AI, castle_pos) or castle_pos

        legion_id = f"AI_{self.next_legion_id}"
        self.next_legion_id += 1

        self.ai_legions[legion_id] = {
            "id": legion_id,
            "name": random.choice(AI_LEGION_NAMES),
            "units": list(self.ai_units),
            "pos": spawn_pos,
            "target": None,
            "path": [],
            "path_step": 0,
        }

        cell = self.game_map.get_cell(*spawn_pos)
        if cell is not None:
            cell.occupation = AI

    def _find_legion_at(self, entity: Occupation, pos: Tuple[int, int]) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Restituisce (id, legione) se l'entità ha una legione sulla posizione richiesta."""
        source = self.player_legions if entity == PLAYER else self.ai_legions
        for legion_id, legion in source.items():
            if tuple(legion.get("pos", ())) == pos:
                return legion_id, legion
        return None

    def _active_legion_positions(self, entity: Occupation) -> List[Tuple[int, int]]:
        """Posizioni correnti delle legioni attive di una entità (fallback: posizione armata legacy)."""
        source = self.player_legions if entity == PLAYER else self.ai_legions
        positions: List[Tuple[int, int]] = []
        for legion in source.values():
            pos = tuple(legion.get("pos", ()))
            if len(pos) == 2:
                positions.append((int(pos[0]), int(pos[1])))

        if positions:
            # Evita duplicati conservando ordine.
            seen: set[Tuple[int, int]] = set()
            unique_positions: List[Tuple[int, int]] = []
            for pos in positions:
                if pos in seen:
                    continue
                seen.add(pos)
                unique_positions.append(pos)
            return unique_positions

        fallback = self.game_map.positions.get(entity)
        if fallback is not None:
            return [fallback]
        return []

    def _collect_ai_economic_targets(self, ai_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Target economici/territoriali per l'IA (miniere, territori utili, espansione)."""
        scored: List[Tuple[float, Tuple[int, int]]] = []
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation == AI or cell.is_castle or cell.terrain == "Fiume":
                    continue

                pos = (cell.row, cell.col)
                distance = self._order_distance(ai_pos, pos)

                score = 0.0
                if cell.is_mine:
                    score += 4.2
                if cell.is_strategic:
                    score += 2.1
                if cell.terrain in {"Pianura", "Montagna"}:
                    score += 1.2
                if cell.occupation == PLAYER:
                    score += 0.5

                score -= distance * 0.18
                scored.append((score, pos))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [pos for _, pos in scored[:8]]

    def _step_toward(self, current_pos: Tuple[int, int], target_pos: Tuple[int, int]) -> Tuple[int, int]:
        """Calcola un passo ortogonale verso il target."""
        row, col = current_pos
        target_row, target_col = target_pos
        if row < target_row:
            row += 1
        elif row > target_row:
            row -= 1
        elif col < target_col:
            col += 1
        elif col > target_col:
            col -= 1
        return row, col

    def _bfs_next_step(
        self,
        start: Tuple[int, int],
        goal: Tuple[int, int],
        blocked: set,
    ) -> Optional[Tuple[int, int]]:
        """Primo passo del percorso più breve start->goal, evitando le celle in `blocked`."""
        start = tuple(start)
        goal = tuple(goal)
        if start == goal:
            return start

        rows, cols = self.game_map.rows, self.game_map.cols
        visited = {start}
        parent: Dict[Tuple[int, int], Tuple[int, int]] = {}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current == goal:
                break
            r, c = current
            for neighbor in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                nr, nc = neighbor
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue
                if neighbor in visited:
                    continue
                if neighbor in blocked and neighbor != goal:
                    continue
                visited.add(neighbor)
                parent[neighbor] = current
                queue.append(neighbor)

        if goal not in visited:
            return None

        step = goal
        while step in parent and parent[step] != start:
            step = parent[step]
        return step if step != start else None

    def _next_legion_step(
        self,
        current_pos: Tuple[int, int],
        target_pos: Tuple[int, int],
        mover: Occupation,
    ) -> Tuple[int, int]:
        """Passo verso il target evitando di attraversare il castello nemico come ostacolo,
        a meno che il castello non sia esso stesso la destinazione scelta (assalto esplicito)."""
        current_pos = tuple(current_pos)
        target_pos = tuple(target_pos)
        if current_pos == target_pos:
            return current_pos

        defender_castle = self.game_map.castle_positions.get(mover.opposite())
        blocked: set = set()
        if defender_castle is not None and tuple(defender_castle) != target_pos:
            blocked.add(tuple(defender_castle))

        next_step = self._bfs_next_step(current_pos, target_pos, blocked)
        if next_step is None:
            return current_pos
        return next_step

    def _pick_ai_legion_target(self, ai_legion: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        """Target IA: insegui legioni player, altrimenti espandi su obiettivi strategici e solo poi castello."""
        ai_pos = tuple(ai_legion.get("pos", ()))
        if len(ai_pos) != 2:
            return None

        player_pos: Optional[Tuple[int, int]] = None
        if self.player_legions:
            nearest = min(
                self.player_legions.values(),
                key=lambda legion: self._order_distance(ai_pos, tuple(legion.get("pos", ai_pos))),
            )
            nearest_pos = tuple(nearest.get("pos", ()))
            if len(nearest_pos) == 2:
                player_pos = nearest_pos

        own_castle = self.game_map.castle_positions.get(AI)
        enemy_castle = self.game_map.castle_positions.get(PLAYER)
        player_threatens_own_castle = False
        if player_pos is not None and own_castle is not None:
            player_threatens_own_castle = self._order_distance(player_pos, own_castle) <= 3
        player_distance = self._order_distance(ai_pos, player_pos) if player_pos is not None else None

        strategic_targets = self.game_map.get_strategic_targets(
            entity=AI,
            army_vector=self.ai_army,
            terrain_modifiers=self.data["terrain"],
        )
        economic_targets = self._collect_ai_economic_targets(ai_pos)

        policy_target = self.ai_policy.choose_target(
            ai_pos=ai_pos,
            player_pos=player_pos,
            own_castle=own_castle,
            enemy_castle=enemy_castle,
            strategic_targets=strategic_targets,
            economic_targets=economic_targets,
        )
        if policy_target is not None:
            chosen = tuple(policy_target)
            if (
                player_pos is not None
                and chosen == player_pos
                and not player_threatens_own_castle
                and player_distance is not None
                and player_distance > 3
                and economic_targets
            ):
                return economic_targets[0]
            return chosen

        if economic_targets:
            return economic_targets[0]

        if strategic_targets:
            # Evita corsa cieca al castello: preferisci tra i migliori target quello più vicino.
            top_candidates = strategic_targets[: min(5, len(strategic_targets))]
            _, best_cell = min(
                top_candidates,
                key=lambda item: self._order_distance(ai_pos, (item[1].row, item[1].col)),
            )
            return best_cell.row, best_cell.col

        return enemy_castle or player_pos

    def _ai_legion_target_lock_turns(self) -> int:
        """Numero turni minimi prima del retarget IA per evitare zig-zag e inseguimenti artificiali."""
        if self.ai_difficulty == AI_NORMAL_ID:
            return 2
        return 3

    def _apply_legion_castle_assault(
        self,
        attacker: Occupation,
        legion: Dict[str, Any],
        from_pos: Tuple[int, int],
        to_pos: Tuple[int, int],
        logs: List[str],
    ) -> None:
        """Assedio castello nel sistema legioni: usa HP castello, niente conquista istantanea."""
        defender = attacker.opposite()
        defender_castle = self.game_map.castle_positions.get(defender)
        if defender_castle != to_pos:
            return

        hp_before = self.castle_hp.get(defender, self.castle_hp_max.get(defender, CASTLE_BASE_HP))
        legion_unit_ids = legion.get("units", [])
        attacker_strength = max(20.0, sum(self._unit_battle_value(uid) for uid in legion_unit_ids))
        defender_score = 44.0 + (len(self._entity_units(defender)) * 1.2)
        damage = self._compute_castle_damage(attacker_strength, defender_score)
        hp_after = max(0, hp_before - damage)
        self.castle_hp[defender] = hp_after

        castle_cell = self.game_map.get_cell(*to_pos)
        if hp_after <= 0:
            if castle_cell is not None:
                castle_cell.occupation = attacker
            self.state = SessionState.GAME_OVER
            self.winner = attacker.value
            logs.append(
                f"🏰 {attacker.value.upper()} abbatte il castello ({to_pos}) "
                f"con {damage} danni (HP {hp_before}->{hp_after})."
            )
            return

        # Castello non distrutto: assalto respinto, le truppe rientrano subito al castello d'origine
        # (niente spam di assalti: il target viene azzerato, serve un nuovo ordine del giocatore/IA).
        own_castle = self.game_map.castle_positions.get(attacker)
        legion["pos"] = own_castle if own_castle is not None else from_pos
        legion["target"] = None
        if castle_cell is not None:
            castle_cell.occupation = defender
        from_cell = self.game_map.get_cell(*from_pos)
        if from_cell is not None:
            from_cell.occupation = attacker

        logs.append(
            f"🏰 Assalto respinto: {attacker.value.upper()} infligge {damage} danni "
            f"al castello (HP {hp_before}->{hp_after}) e le truppe rientrano al castello d'origine."
        )

    def _resolve_legion_clash_if_any(self, pos: Tuple[int, int], logs: List[str]) -> None:
        """Risoluzione semplificata scontro legione-vs-legione su una stessa cella."""
        player_entry = self._find_legion_at(PLAYER, pos)
        ai_entry = self._find_legion_at(AI, pos)
        if player_entry is None or ai_entry is None:
            return

        player_id, player_legion = player_entry
        ai_id, ai_legion = ai_entry
        player_power = max(1, len(player_legion.get("units", [])))
        ai_power = max(1, len(ai_legion.get("units", [])))
        cell = self.game_map.get_cell(*pos)

        if player_power == ai_power:
            del self.player_legions[player_id]
            del self.ai_legions[ai_id]
            self.ai_last_legion_loss_turn = self.game_map.turn
            if cell is not None and not cell.is_castle:
                cell.occupation = Occupation.NEUTRAL
            logs.append(
                f"⚔️ Scontro su {pos}: legioni annientate (PLAYER={player_power}, IA={ai_power})."
            )
            return

        if player_power > ai_power:
            winner = PLAYER
            loser_name = ai_legion.get("name", ai_id)
            del self.ai_legions[ai_id]
            self.ai_last_legion_loss_turn = self.game_map.turn
        else:
            winner = AI
            loser_name = player_legion.get("name", player_id)
            del self.player_legions[player_id]

        if cell is not None:
            cell.occupation = winner

        logs.append(
            f"⚔️ Scontro su {pos}: vince {winner.value.upper()} (eliminata legione '{loser_name}')."
        )

    # ──────────────────────────────────────────────────────────
    # MOSSA GIOCATORE (entry-point principale)
    # ──────────────────────────────────────────────────────────

    def player_move(
        self,
        to_row: int,
        to_col: int,
        leave_garrison: bool = False,
        garrison_unit_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Esegue la mossa del giocatore verso (to_row, to_col).

        Dopo la mossa del giocatore:
          - Se scatta battaglia, la risolve immediatamente.
          - Passa il turno all'IA e la fa muovere (con possibile secondo scontro).

        Returns:
            dict con:
                ok              — True se la mossa è valida
                message         — descrizione testuale
                battle_result   — risultato battaglia (se avvenuta), oppure None
                ai_move_result  — esito mossa IA (oppure None se partita finita)
                game_over       — True se la partita è terminata
                winner          — "player" | "ai" | None
                state           — stato sessione corrente
                map             — stato mappa serializzato
        """
        if self.state != SessionState.ACTIVE:
            return {
                "ok": False,
                "message": "La partita è già terminata.",
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        if leave_garrison and self._available_garrisons(PLAYER) <= 0:
            return {
                "ok": False,
                "message": "Non hai unità sufficienti: devi mantenere almeno una legione attiva con l'armata.",
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }
        if leave_garrison and garrison_unit_id and garrison_unit_id not in self.player_units:
            return {
                "ok": False,
                "message": "La truppa selezionata non è disponibile nell'armata attiva.",
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        block = self.movement_system.consume_block_if_any(PLAYER)
        if block.get("blocked"):
            blocked_message = self._build_movement_block_message(PLAYER, block)
            self.battle_log.append(blocked_message)

            self.game_map.end_turn()
            ai_result = self._ai_turn()

            if self.state == SessionState.ACTIVE:
                economy_logs = self._advance_round_economy()
                if economy_logs:
                    self.battle_log.extend(economy_logs)

            return {
                "ok": True,
                "skipped": True,
                "message": blocked_message,
                "battle_result": None,
                "ai_move_result": ai_result,
                "game_over": self.state == SessionState.GAME_OVER,
                "winner": self.winner,
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        # Con armata vuota il player può comunque riposizionarsi sul campo,
        # ma non può attaccare né conquistare territori.
        if len(self.player_units) == 0:
            relocation_result = self._move_player_without_troops(to_row, to_col)
            if not relocation_result["ok"]:
                return {
                    "ok": False,
                    "message": relocation_result["message"],
                    "state": self.state.value,
                    "map": self.game_map.to_dict(),
                }

            move_cost_info = self.movement_system.register_move(
                PLAYER,
                relocation_result["terrain"],
                from_pos=tuple(relocation_result["from_pos"]),
                to_pos=tuple(relocation_result["to_pos"]),
            )
            relocation_result["message"] += self._format_movement_cost_suffix(move_cost_info)
            self.battle_log.append(relocation_result["message"])

            # Passa il turno all'IA anche in modalità riposizionamento.
            self.game_map.end_turn()
            ai_result = self._ai_turn()

            if self.state == SessionState.ACTIVE:
                economy_logs = self._advance_round_economy()
                if economy_logs:
                    self.battle_log.extend(economy_logs)

            return {
                "ok": True,
                "message": relocation_result["message"],
                "battle_result": None,
                "ai_move_result": ai_result,
                "game_over": self.state == SessionState.GAME_OVER,
                "winner": self.winner,
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        move_result = self.game_map.move(PLAYER, (to_row, to_col), leave_garrison=leave_garrison)
        if not move_result["ok"]:
            return {
                "ok": False,
                "message": move_result["message"],
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        # Log persistente della mossa player per debug cronologico completo.
        move_cost_info = self.movement_system.register_move(
            PLAYER,
            move_result["terrain"],
            from_pos=tuple(move_result["from_pos"]),
            to_pos=tuple(move_result["to_pos"]),
        )
        move_result["message"] += self._format_movement_cost_suffix(move_cost_info)
        self.battle_log.append(move_result["message"])

        if leave_garrison and move_result.get("leave_garrison"):
            detach_result = self._detach_unit_to_garrison(
                entity=PLAYER,
                cell_pos=tuple(move_result["from_pos"]),
                unit_id=garrison_unit_id,
                auto=False,
            )
            move_result["message"] += f" — Distaccata: {detach_result['unit_name']}"
            self.battle_log[-1] = move_result["message"]

        battle_result: Optional[Dict] = None
        if move_result["battle"]:
            battle_result = self._resolve_encounter(
                move_result=move_result,
                attacker=PLAYER,
            )
            if self.state == SessionState.GAME_OVER:
                return {
                    "ok": True,
                    "message": move_result["message"],
                    "battle_result": battle_result,
                    "ai_move_result": None,
                    "game_over": True,
                    "winner": self.winner,
                    "state": self.state.value,
                    "map": self.game_map.to_dict(),
                }

        # Passa il turno all'IA
        self.game_map.end_turn()
        ai_result = self._ai_turn()

        if self.state == SessionState.ACTIVE:
            economy_logs = self._advance_round_economy()
            if economy_logs:
                self.battle_log.extend(economy_logs)

        return {
            "ok": True,
            "message": move_result["message"],
            "battle_result": battle_result,
            "ai_move_result": ai_result,
            "game_over": self.state == SessionState.GAME_OVER,
            "winner": self.winner,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
        }

    def _move_player_without_troops(self, to_row: int, to_col: int) -> Dict[str, Any]:
        """Permette il riposizionamento del player senza truppe, senza combattimento né conquista."""
        from_pos = self.game_map.positions.get(PLAYER)
        if from_pos is None:
            return {"ok": False, "message": "Posizione PLAYER non disponibile."}

        to_pos = (to_row, to_col)
        if not self.game_map.is_adjacent(from_pos, to_pos):
            return {"ok": False, "message": "La destinazione non è adiacente alla posizione corrente."}

        if not (0 <= to_row < self.game_map.rows and 0 <= to_col < self.game_map.cols):
            return {"ok": False, "message": "Destinazione fuori dalla mappa."}

        own_castle = self.game_map.get_castle_position(PLAYER)
        if to_pos == own_castle:
            return {
                "ok": False,
                "message": "La casella del castello è proibita al movimento.",
            }

        enemy_pos = self.game_map.positions.get(AI)
        if enemy_pos == to_pos:
            return {
                "ok": False,
                "message": "Armata senza truppe: non puoi ingaggiare direttamente l'armata nemica.",
            }

        self.game_map.positions[PLAYER] = to_pos
        dest_cell = self.game_map.get_cell(to_row, to_col)
        terrain = dest_cell.terrain if dest_cell is not None else "Sconosciuto"
        return {
            "ok": True,
            "terrain": terrain,
            "from_pos": from_pos,
            "to_pos": to_pos,
            "message": (
                f"[Turno {self.game_map.turn}] PLAYER si riposiziona -> ({to_row},{to_col}) "
                f"[{terrain}] senza truppe: nessuna conquista o attacco"
            ),
        }

    def _format_movement_cost_suffix(self, move_cost_info: Dict[str, Any]) -> str:
        """Ritorna un suffisso leggibile con costo movimento e ritardo eventuale."""
        cost = int(move_cost_info.get("cost", 0))
        points_per_turn = int(move_cost_info.get("points_per_turn", 100))
        extra_wait_turns = int(move_cost_info.get("extra_wait_turns", 0))
        if extra_wait_turns > 0:
            return (
                f" — Movimento: costo {cost}/{points_per_turn}"
                f" (rallentamento: +{extra_wait_turns} turno/i)"
            )
        return f" — Movimento: costo {cost}/{points_per_turn}"

    def _build_movement_block_message(self, entity: Occupation, block: Dict[str, Any]) -> str:
        """Messaggio di skip turno quando l'armata è rallentata dal terreno."""
        side = entity.value.upper()
        remaining = int(block.get("remaining_blocked_turns", 0))
        terrain = str(block.get("last_terrain") or "terreno difficile")
        cost = int(block.get("last_cost", self.movement_system.points_per_turn))
        if remaining > 0:
            return (
                f"[Turno {self.game_map.turn}] {side} rallentato su {terrain} "
                f"(costo {cost}): turno di movimento bloccato "
                f"({remaining} turno/i di ritardo residui)"
            )
        return (
            f"[Turno {self.game_map.turn}] {side} rallentato su {terrain} "
            f"(costo {cost}): ultimo turno di ritardo consumato"
        )

    # ──────────────────────────────────────────────────────────
    # TURNO IA (privato)
    # ──────────────────────────────────────────────────────────

    def _ai_turn(self) -> Dict[str, Any]:
        """
        Logica del turno IA:
          1. Se esistono celle strategiche non controllate dall'IA, prende quella
             con il punteggio di terreno più alto per il suo esercito.
          2. Se il giocatore è molto vicino (≤ 2 passi) e più vicino del target
             strategico, attacca direttamente.
          3. Esegue la mossa; se scatta battaglia la risolve.
          4. Passa il turno al giocatore (anche in caso di errori, via finally).
        """
        result: Dict[str, Any] = {"skipped": False, "ok": False, "message": ""}

        try:
            if self.state != SessionState.ACTIVE:
                result.update({"skipped": True, "reason": "partita terminata"})
                return result

            if self.debug_ai_kill_switch:
                result.update({
                    "skipped": True,
                    "ok": True,
                    "reason": "kill_switch_attivo",
                    "message": f"[Turno {self.game_map.turn}] 🧪 DEBUG: IA in pausa (kill switch attivo)",
                })
                return result

            if self.ai_policy.should_skip_turn(self.game_map.turn):
                result.update({
                    "skipped": True,
                    "ok": True,
                    "reason": "easy_ai_skip_turn",
                    "message": f"[Turno {self.game_map.turn}] IA esita e perde l'iniziativa.",
                })
                return result

            ai_pos = self.game_map.positions.get(AI)
            if ai_pos is None:
                result.update({"skipped": True, "reason": "IA eliminata"})
                return result

            ai_block = self.movement_system.consume_block_if_any(AI)
            if ai_block.get("blocked"):
                blocked_message = self._build_movement_block_message(AI, ai_block)
                self.battle_log.append(blocked_message)
                result.update(
                    {
                        "skipped": True,
                        "ok": True,
                        "reason": "movement_delay",
                        "message": blocked_message,
                    }
                )
                return result

            target_pos = self._compute_ai_target(ai_pos)
            if target_pos is None:
                result.update({"skipped": True, "reason": "nessun target disponibile"})
                return result

            next_move = self.game_map.best_move_toward(AI, target_pos)
            if next_move is None:
                result.update({"skipped": True, "reason": "nessuna mossa valida"})
                return result

            leave_garrison = self._should_ai_leave_garrison(ai_pos)
            if leave_garrison and self._available_garrisons(AI) <= 0:
                leave_garrison = False

            ai_move = self.game_map.move(AI, next_move, leave_garrison=leave_garrison)
            if leave_garrison and ai_move.get("leave_garrison"):
                detach_result = self._detach_unit_to_garrison(
                    entity=AI,
                    cell_pos=tuple(ai_move["from_pos"]),
                    unit_id=None,
                    auto=True,
                )
                if detach_result and ai_move.get("message"):
                    ai_move["message"] += f" — Distaccata: {detach_result['unit_name']}"

            if ai_move.get("ok"):
                ai_move_cost_info = self.movement_system.register_move(
                    AI,
                    ai_move.get("terrain", "Pianura"),
                    from_pos=tuple(ai_move["from_pos"]),
                    to_pos=tuple(ai_move["to_pos"]),
                )
                if ai_move.get("message"):
                    ai_move["message"] += self._format_movement_cost_suffix(ai_move_cost_info)

            if ai_move.get("ok") and ai_move.get("message"):
                self.battle_log.append(ai_move["message"])

            result["ok"]      = ai_move.get("ok", False)
            result["message"] = ai_move.get("message", "")

            if ai_move.get("battle"):
                result["battle_result"] = self._resolve_encounter(
                    move_result=ai_move,
                    attacker=AI,
                )

            return result

        finally:
            # Il turno torna sempre al giocatore, anche in caso di skip
            self.game_map.end_turn()

    def _compute_ai_target(
        self,
        ai_pos: Tuple[int, int],
    ) -> Optional[Tuple[int, int]]:
        """
        Determina la cella obiettivo dell'IA:
          - Se può minacciare il castello del giocatore, avanza verso il castello.
          - Altrimenti prende celle strategiche utili al suo esercito.
          - Se il giocatore è molto vicino, prova a intercettarlo.
        """
        player_pos = self.game_map.positions.get(PLAYER)
        enemy_castle = self.game_map.get_castle_position(PLAYER)
        own_castle = self.game_map.get_castle_position(AI)
        ai_cell = self.game_map.get_cell(*ai_pos)
        estimate_terrain = ai_cell.terrain if ai_cell is not None else "Pianura"

        strategic_targets = self.game_map.get_strategic_targets(
            entity=AI,
            army_vector=self.ai_army,
            terrain_modifiers=self.data["terrain"],
        )

        ai_strength_est = self._strength_breakdown(AI, estimate_terrain)["effective_strength"]
        player_strength_est = self._strength_breakdown(PLAYER, estimate_terrain)["effective_strength"]
        ai_has_advantage = ai_strength_est >= (player_strength_est * 1.08)

        easy_target = self.ai_policy.choose_target(
            ai_pos=ai_pos,
            player_pos=player_pos,
            own_castle=own_castle,
            enemy_castle=enemy_castle,
            strategic_targets=strategic_targets,
            economic_targets=self._collect_ai_economic_targets(ai_pos),
        )
        if easy_target is not None:
            return easy_target

        # Priorita difensiva: se il player e vicino al castello IA, intercetta.
        if player_pos and own_castle:
            player_to_own_castle = abs(player_pos[0] - own_castle[0]) + abs(player_pos[1] - own_castle[1])
            if player_to_own_castle <= 3:
                return player_pos

        if enemy_castle:
            dist_castle = abs(ai_pos[0] - enemy_castle[0]) + abs(ai_pos[1] - enemy_castle[1])
            if dist_castle <= 2:
                return enemy_castle
            if dist_castle <= 4 and ai_has_advantage and not strategic_targets:
                return enemy_castle

        targets = strategic_targets

        if targets:
            _, best_cell     = targets[0]
            strat_pos        = (best_cell.row, best_cell.col)
            dist_strat       = abs(ai_pos[0] - strat_pos[0]) + abs(ai_pos[1] - strat_pos[1])

            if player_pos:
                dist_player = abs(ai_pos[0] - player_pos[0]) + abs(ai_pos[1] - player_pos[1])
                if dist_player <= 2 and dist_player <= dist_strat and ai_has_advantage:
                    return player_pos

            return strat_pos

        # Nessun target strategico: carica il castello o il giocatore
        if ai_has_advantage:
            return enemy_castle or player_pos
        return player_pos or enemy_castle

    def _should_ai_leave_garrison(self, from_pos: Tuple[int, int]) -> bool:
        """L'IA lascia guarnigioni su castelli e punti strategici quando possibile."""
        cell = self.game_map.get_cell(*from_pos)
        if cell is None:
            return False
        available = self._available_garrisons(AI)
        if available <= 0:
            return False

        return self.ai_policy.should_leave_garrison(
            is_castle=cell.is_castle,
            is_strategic=cell.is_strategic,
            current_strength=cell.garrison_strength,
            available=available,
        )

    def _advance_round_economy(self) -> List[str]:
        """Accredita i grux delle miniere e fa gestire all'IA la propria economia."""
        logs: List[str] = []
        for entity in (PLAYER, AI):
            if entity == AI and self.debug_ai_kill_switch:
                continue
            mine_count = self.game_map.count_mines(entity)
            if mine_count > 0:
                linear_income = mine_count * MINE_YIELD_PER_ROUND
                income = self._mine_income_for_count(mine_count)
                self.grux_balance[entity] += income
                diminishing_note = ""
                if income < linear_income:
                    diminishing_note = f" (rendimenti decrescenti: -{linear_income - income})"
                logs.append(
                    f"[Turno {self.game_map.turn}] ⛏ {entity.value.upper()} incassa {income} grux da {mine_count} miniere{diminishing_note}"
                )

        if not self.debug_ai_kill_switch:
            logs.extend(self._auto_manage_ai_economy())
        logs.extend(self._run_player_auto_recruit())
        return logs

    def toggle_debug_ai_kill_switch(self) -> Dict[str, Any]:
        """DEBUG TEMPORANEO (DA RIMUOVERE): pausa/riprende totalmente l'IA."""
        self.debug_ai_kill_switch = not self.debug_ai_kill_switch
        status = "ATTIVO" if self.debug_ai_kill_switch else "DISATTIVO"
        log_entry = (
            f"[Turno {self.game_map.turn}] 🧪 DEBUG TEMPORANEO - KILL SWITCH IA {status} "
            f"(rimuovere in produzione)"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "enabled": self.debug_ai_kill_switch,
            "message": log_entry,
            "session": self.to_dict(),
        }

    def set_ai_difficulty(self, difficulty: str) -> Dict[str, Any]:
        """Aggiorna la difficoltà IA runtime e ricalcola la policy decisionale."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        normalized = normalize_ai_difficulty(difficulty)
        if normalized == self.ai_difficulty:
            return {
                "ok": True,
                "message": f"Difficoltà IA già impostata su {normalized}.",
                "state": self.state.value,
                "map": self.game_map.to_dict(),
                "session": self.to_dict(),
            }

        self.ai_difficulty = normalized
        self.ai_policy = build_ai_policy(self.ai_difficulty, seed=None)
        log_entry = f"[Turno {self.game_map.turn}] ⚙ Sistema: difficoltà IA impostata su {self.ai_difficulty.upper()}"
        self.battle_log.append(log_entry)

        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def _auto_manage_ai_economy(self) -> List[str]:
        """L'IA piazza miniere disponibili e recluta automaticamente se può permetterselo."""
        logs: List[str] = []
        if self.ai_policy.should_start_research(self.game_map.turn):
            self._start_ability_research(AI, DOMAIN_ENGINEERING_ID)

        ai_slots = self._available_mine_slots(AI)
        attempts = self.ai_policy.mine_attempts(ai_slots, self.game_map.turn)
        while attempts > 0 and ai_slots > 0:
            placed = self._place_best_ai_mine()
            if not placed:
                break
            logs.append(placed)
            ai_slots -= 1
            attempts -= 1

        # Fortificazione IA: più frequente a difficoltà normal.
        if self.grux_balance[AI] >= self.base_fortification_cost:
            fortify_turn_gate = 2 if self.ai_difficulty == AI_NORMAL_ID else 3
            if self.game_map.turn % fortify_turn_gate == 0:
                fort_log = self._place_best_ai_fortification()
                if fort_log:
                    logs.append(fort_log)

        can_recruit_now = self._can_recruit_now(AI)
        if can_recruit_now and self.ai_policy.should_recruit(grux_balance=self.grux_balance[AI], turn=self.game_map.turn):
            affordable_units = [unit for unit in self.data["units"] if self.unit_costs[unit["id"]] <= self.grux_balance[AI]]
            if affordable_units:
                best_unit = max(
                    affordable_units,
                    key=lambda unit: self._effective_unit_value_for_ai(unit),
                )
                self._recruit_unit(AI, best_unit["id"], auto=True)

        return logs

    def _can_recruit_now(self, entity: Occupation) -> bool:
        """True se l'entità può reclutare in questo turno (cooldown anti-spam)."""
        last_turn = self.last_recruit_turn.get(entity)
        if last_turn is None:
            return True
        return (self.game_map.turn - last_turn) >= self.recruit_cooldown_turns

    def _effective_unit_value_for_ai(self, unit: Dict[str, Any]) -> float:
        """Heuristica semplice per decidere la recluta dell'IA."""
        attrs = unit["attributes"]
        return (
            attrs["U1_attack"]
            + attrs["U2_defense"]
            + attrs["U3_mobility"]
            + attrs["U6_terrain_adapt"]
            + attrs["U7_range_power"]
        )

    def _entity_units(self, entity: Occupation) -> List[str]:
        return self.player_units if entity == PLAYER else self.ai_units

    def _available_garrisons(self, entity: Occupation) -> int:
        """Unità distaccabili: sempre almeno una legione resta con l'armata principale."""
        units = self._entity_units(entity)
        return max(0, len(units) - 1)

    def is_manual_control_enabled(self) -> bool:
        return self.player_control_mode == "manual"

    def set_player_orders(
        self,
        *,
        movement_order: Optional[str] = None,
        build_order: Optional[str] = None,
        control_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggiorna la configurazione ordini del player (modalità graduale manual/orders)."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        changed: List[str] = []

        if control_mode is not None:
            if control_mode not in PLAYER_CONTROL_MODES:
                raise ValueError(f"Modalità controllo non valida: {control_mode}")
            if control_mode != self.player_control_mode:
                self.player_control_mode = control_mode
                changed.append(f"modalità={control_mode}")

        if movement_order is not None:
            if movement_order not in PLAYER_MOVEMENT_ORDERS:
                raise ValueError(f"Ordine movimento non valido: {movement_order}")
            if movement_order != self.player_orders.get("movement_order"):
                self.player_orders["movement_order"] = movement_order
                changed.append(f"movimento={movement_order}")

        if build_order is not None:
            if build_order not in PLAYER_BUILD_ORDERS:
                raise ValueError(f"Ordine supporto non valido: {build_order}")
            if build_order != self.player_orders.get("build_order"):
                self.player_orders["build_order"] = build_order
                changed.append(f"supporto={build_order}")

        if changed:
            log_entry = f"[Turno {self.game_map.turn}] 🧭 PLAYER aggiorna ordini: " + ", ".join(changed)
            self.battle_log.append(log_entry)
        else:
            log_entry = f"[Turno {self.game_map.turn}] 🧭 Ordini PLAYER invariati"

        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    @staticmethod
    def _order_distance(a: Tuple[int, int], b: Tuple[int, int]) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    @staticmethod
    def _order_direction(from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> Tuple[int, int]:
        return (to_pos[0] - from_pos[0], to_pos[1] - from_pos[1])

    def _adjacent_positions(self, origin: Tuple[int, int]) -> List[Tuple[int, int]]:
        positions: List[Tuple[int, int]] = []
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = origin[0] + dr, origin[1] + dc
            if 0 <= nr < self.game_map.rows and 0 <= nc < self.game_map.cols:
                positions.append((nr, nc))
        return positions

    def _expand_direction_penalty(self, direction: Tuple[int, int]) -> float:
        last_direction = self.player_order_memory.get("last_direction")
        straight_streak = int(self.player_order_memory.get("straight_streak") or 0)
        if not isinstance(last_direction, tuple):
            return 0.0
        if direction != last_direction:
            return 0.0
        return min(1.8, 0.35 * max(0, straight_streak - 1))

    def _update_player_order_movement_memory(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> None:
        direction = self._order_direction(from_pos, to_pos)
        last_direction = self.player_order_memory.get("last_direction")
        if isinstance(last_direction, tuple) and direction == last_direction:
            streak = int(self.player_order_memory.get("straight_streak") or 0) + 1
        else:
            streak = 1
        self.player_order_memory["last_direction"] = direction
        self.player_order_memory["straight_streak"] = streak

    def _frontier_pressure_score(self, pos: Tuple[int, int]) -> float:
        pressure = 0.0
        for ar, ac in self._adjacent_positions(pos):
            adjacent_cell = self.game_map.get_cell(ar, ac)
            if adjacent_cell is None:
                continue
            if adjacent_cell.occupation != PLAYER:
                pressure += 0.68
                if adjacent_cell.is_strategic:
                    pressure += 0.42
        return pressure

    def _select_player_expand_move(self) -> Optional[Tuple[int, int]]:
        player_pos = self.game_map.positions.get(PLAYER)
        if player_pos is None:
            return None

        own_castle = self.game_map.get_castle_position(PLAYER)
        enemy_castle = self.game_map.get_castle_position(AI)
        ai_pos = self.game_map.positions.get(AI)

        current_enemy_castle_dist = self._order_distance(player_pos, enemy_castle) if enemy_castle else None
        current_own_castle_dist = self._order_distance(player_pos, own_castle) if own_castle else None

        candidates: List[Tuple[float, Tuple[int, int, int], Tuple[int, int]]] = []
        for candidate in self._adjacent_positions(player_pos):
            cell = self.game_map.get_cell(*candidate)
            if cell is None:
                continue

            score = 0.0

            if cell.occupation != PLAYER:
                score += 2.6
            else:
                score -= 0.8

            if cell.occupation == AI:
                score += 1.35

            if cell.is_strategic and cell.occupation != PLAYER:
                score += 2.25

            if cell.is_mine and cell.occupation != PLAYER:
                score += 1.1

            if cell.is_castle and cell.occupation == AI:
                score += 3.0

            score += self._frontier_pressure_score(candidate)

            move_cost = self.movement_system.terrain_cost(cell.terrain)
            if move_cost > self.movement_system.points_per_turn:
                score -= (move_cost - self.movement_system.points_per_turn) / 60.0

            if enemy_castle and current_enemy_castle_dist is not None:
                next_enemy_castle_dist = self._order_distance(candidate, enemy_castle)
                castle_delta = current_enemy_castle_dist - next_enemy_castle_dist
                score += max(-0.8, min(0.8, castle_delta * 0.25))

            if own_castle and current_own_castle_dist is not None:
                next_own_castle_dist = self._order_distance(candidate, own_castle)
                outward_delta = next_own_castle_dist - current_own_castle_dist
                score += max(-0.4, min(0.6, outward_delta * 0.15))

            if ai_pos is not None:
                next_ai_dist = self._order_distance(candidate, ai_pos)
                if next_ai_dist <= 1 and len(self.player_units) < len(self.ai_units):
                    score -= 0.75
                elif next_ai_dist <= 2:
                    score += 0.15

            direction = self._order_direction(player_pos, candidate)
            score -= self._expand_direction_penalty(direction)

            tie_rank = (
                0 if cell.occupation != PLAYER else 1,
                0 if (cell.is_strategic and cell.occupation != PLAYER) else 1,
                move_cost,
            )
            candidates.append((score, tie_rank, candidate))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][2]

    def _select_player_order_target(self) -> Optional[Tuple[int, int]]:
        movement_order = self.player_orders.get("movement_order", "advance_castle")
        player_pos = self.game_map.positions.get(PLAYER)
        ai_pos = self.game_map.positions.get(AI)
        own_castle = self.game_map.get_castle_position(PLAYER)
        enemy_castle = self.game_map.get_castle_position(AI)

        if movement_order == "hold":
            return None

        if movement_order == "engage_ai":
            return ai_pos or enemy_castle

        if movement_order == "defend_castle":
            if ai_pos and own_castle and self._order_distance(ai_pos, own_castle) <= 4:
                return ai_pos
            return own_castle or ai_pos or enemy_castle

        if movement_order == "expand_front":
            targets = self.game_map.get_strategic_targets(
                entity=PLAYER,
                army_vector=self.player_army,
                terrain_modifiers=self.data["terrain"],
            )
            if targets:
                _, cell = targets[0]
                return (cell.row, cell.col)
            return enemy_castle or ai_pos

        # default: advance_castle
        if enemy_castle is not None:
            return enemy_castle
        return ai_pos

    def _select_player_order_move(self) -> Optional[Tuple[int, int]]:
        movement_order = self.player_orders.get("movement_order", "advance_castle")
        if movement_order == "expand_front":
            expand_move = self._select_player_expand_move()
            if expand_move is not None:
                return expand_move

        target = self._select_player_order_target()
        if target is None:
            return None
        return self.game_map.best_move_toward(PLAYER, target)

    def _choose_player_order_mine_cell(self) -> Optional[Tuple[int, int]]:
        if self._available_mine_slots(PLAYER) <= 0:
            return None

        player_pos = self.game_map.positions.get(PLAYER)
        if player_pos is None:
            return None

        if not self._is_ability_unlocked(PLAYER, DOMAIN_ENGINEERING_ID):
            cell = self.game_map.get_cell(*player_pos)
            if cell and cell.occupation == PLAYER and not cell.is_castle and not cell.is_mine and cell.terrain != "Fiume":
                return player_pos
            return None

        ai_pos = self.game_map.positions.get(AI)
        best: Optional[Tuple[float, Tuple[int, int]]] = None
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != PLAYER or cell.is_castle or cell.is_mine or cell.terrain == "Fiume":
                    continue
                score = 0.0
                if cell.is_strategic:
                    score += 2.8
                if cell.terrain in {"Pianura", "Montagna"}:
                    score += 1.1
                if ai_pos is not None:
                    score -= self._order_distance((cell.row, cell.col), ai_pos) * 0.05
                score -= self._order_distance((cell.row, cell.col), player_pos) * 0.02
                if best is None or score > best[0]:
                    best = (score, (cell.row, cell.col))

        return best[1] if best else None

    def _choose_player_order_fortification_cell(self) -> Optional[Tuple[int, int]]:
        player_pos = self.game_map.positions.get(PLAYER)
        if player_pos is None:
            return None

        if not self._is_ability_unlocked(PLAYER, DOMAIN_ENGINEERING_ID):
            cell = self.game_map.get_cell(*player_pos)
            if cell and cell.occupation == PLAYER and not cell.is_castle:
                return player_pos
            return None

        best: Optional[Tuple[Tuple[int, int, int], Tuple[int, int]]] = None
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != PLAYER or cell.is_castle:
                    continue
                # Priorità: celle strategiche, poi livelli fortificazione più bassi.
                rank = (
                    0 if cell.is_strategic else 1,
                    cell.fortification_level,
                    self._order_distance((cell.row, cell.col), player_pos),
                )
                if best is None or rank < best[0]:
                    best = (rank, (cell.row, cell.col))

        return best[1] if best else None

    def _run_player_order_build_phase(self) -> List[str]:
        logs: List[str] = []
        build_order = self.player_orders.get("build_order", "balanced")

        if build_order == "none":
            return logs

        if build_order == "economy":
            plan = ["mine"]
        elif build_order == "fortify":
            plan = ["fortify"]
        elif build_order == "garrison":
            plan = ["garrison"]
        else:
            plan = ["mine", "fortify", "garrison"]

        for step in plan:
            try:
                if step == "mine":
                    mine_target = self._choose_player_order_mine_cell()
                    if mine_target is None:
                        continue
                    result = self.place_mine(mine_target[0], mine_target[1])
                    logs.append(result["message"])
                    break

                if step == "fortify":
                    fort_target = self._choose_player_order_fortification_cell()
                    if fort_target is None:
                        continue
                    result = self.place_fortification(fort_target[0], fort_target[1])
                    logs.append(result["message"])
                    break

                if step == "garrison":
                    if self._available_garrisons(PLAYER) <= 0:
                        continue
                    result = self.place_garrison_here(unit_id=None)
                    logs.append(result["message"])
                    break
            except ValueError:
                continue

        return logs

    def _pass_turn_without_player_move(self, message: str, build_logs: Optional[List[str]] = None) -> Dict[str, Any]:
        self.battle_log.append(message)

        self.game_map.end_turn()
        ai_result = self._ai_turn()

        if self.state == SessionState.ACTIVE:
            economy_logs = self._advance_round_economy()
            if economy_logs:
                self.battle_log.extend(economy_logs)

        result: Dict[str, Any] = {
            "ok": True,
            "skipped": True,
            "message": message,
            "battle_result": None,
            "ai_move_result": ai_result,
            "game_over": self.state == SessionState.GAME_OVER,
            "winner": self.winner,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "order_mode": True,
            "session": self.to_dict(),
        }
        if build_logs:
            result["build_logs"] = build_logs
        return result

    def execute_turn(self) -> dict:
        """Avanza il turno di tutte le legioni e risolve i conflitti."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("Partita terminata.")

        logs = []

        # 1. Movimento Legioni Player
        for _, legion in list(self.player_legions.items()):
            target = legion.get("target")
            target_pos = tuple(target) if target is not None else None
            current_pos = tuple(legion.get("pos", ()))
            if target_pos is None or len(current_pos) != 2 or len(target_pos) != 2:
                continue
            if current_pos == target_pos:
                continue

            next_pos = self._next_legion_step(current_pos, target_pos, PLAYER)
            if next_pos == current_pos:
                continue
            legion["pos"] = next_pos

            row, col = next_pos
            cell = self.game_map.get_cell(row, col)
            if cell and getattr(cell, "occupation", None) != PLAYER:
                cell.occupation = PLAYER
                logs.append(f"⚔️ La legione PLAYER '{legion['name']}' conquista la cella ({row},{col}).")

            self._apply_legion_castle_assault(PLAYER, legion, current_pos, next_pos, logs)
            if tuple(legion.get("pos", ())) != next_pos:
                continue

            self._resolve_legion_clash_if_any(next_pos, logs)
            if self.state != SessionState.ACTIVE:
                break

        # 2. Movimento Legioni IA
        ai_moved = False
        ai_skipped = False
        if self.state == SessionState.ACTIVE:
            self._ensure_ai_legions_initialized()
            if self.ai_policy.should_skip_turn(self.game_map.turn):
                ai_skipped = True
                logs.append(f"[Turno {self.game_map.turn}] IA esita e mantiene la posizione.")
            else:
                for _, legion in list(self.ai_legions.items()):
                    current_pos = tuple(legion.get("pos", ()))
                    if len(current_pos) != 2:
                        continue

                    target_pos = self._pick_ai_legion_target(legion)
                    if target_pos is None:
                        continue

                    lock_until = int(legion.get("target_lock_until", 0) or 0)
                    existing_target_raw = legion.get("target")
                    existing_target: Tuple[int, int] | Tuple[()] = ()
                    if isinstance(existing_target_raw, (list, tuple)) and len(existing_target_raw) == 2:
                        existing_target = (int(existing_target_raw[0]), int(existing_target_raw[1]))

                    if len(existing_target) == 2 and self.game_map.turn <= lock_until:
                        target_pos = existing_target
                    else:
                        legion["target"] = target_pos
                        legion["target_lock_until"] = self.game_map.turn + self._ai_legion_target_lock_turns()

                    next_pos = self._next_legion_step(current_pos, target_pos, AI)
                    if next_pos == current_pos:
                        continue

                    ai_moved = True
                    legion["pos"] = next_pos

                    row, col = next_pos
                    cell = self.game_map.get_cell(row, col)
                    if cell and getattr(cell, "occupation", None) != AI:
                        cell.occupation = AI
                        logs.append(f"🤖 La legione IA '{legion['name']}' conquista la cella ({row},{col}).")

                    self._apply_legion_castle_assault(AI, legion, current_pos, next_pos, logs)
                    if tuple(legion.get("pos", ())) != next_pos:
                        continue

                    self._resolve_legion_clash_if_any(next_pos, logs)
                    if self.state != SessionState.ACTIVE:
                        break

        if self.state == SessionState.ACTIVE and not ai_moved and not ai_skipped:
            logs.append("🤖 L'IA resta in attesa strategica.")

        # 3. Aggiorna economia (miniere e reclute)
        if self.state == SessionState.ACTIVE:
            econ_logs = self._advance_round_economy()
            if econ_logs:
                logs.extend(econ_logs)

        self.game_map.turn += 1
        self.battle_log.extend(logs)

        return {
            "ok": True,
            "message": "Turno eseguito.",
            "session": self.to_dict(),
            "logs": logs
        }

    def resolve_player_order_turn(self) -> Dict[str, Any]:
        """Esegue un turno completo secondo gli ordini impostati (player -> IA -> economia)."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")
        if self.player_control_mode != "orders":
            raise ValueError("Controllo manuale attivo: passa prima alla modalità ordini.")

        build_logs = self._run_player_order_build_phase()
        movement_order = self.player_orders.get("movement_order", "advance_castle")
        next_move = self._select_player_order_move()

        if next_move is None:
            wait_message = (
                f"[Turno {self.game_map.turn}] 🧭 PLAYER mantiene posizione "
                f"(ordine movimento: {movement_order})"
            )
            return self._pass_turn_without_player_move(wait_message, build_logs=build_logs)

        player_from_pos = self.game_map.positions.get(PLAYER)
        move_result = self.player_move(
            next_move[0],
            next_move[1],
            leave_garrison=False,
            garrison_unit_id=None,
        )

        if not move_result.get("ok", False):
            fallback_message = (
                f"[Turno {self.game_map.turn}] 🧭 Ordine PLAYER non eseguibile: "
                f"{move_result.get('message', 'mossa non valida')}"
            )
            return self._pass_turn_without_player_move(fallback_message, build_logs=build_logs)

        if player_from_pos is not None and not move_result.get("skipped", False):
            self._update_player_order_movement_memory(player_from_pos, next_move)

        move_result["order_mode"] = True
        move_result["session"] = self.to_dict()
        if build_logs:
            move_result["build_logs"] = build_logs
        return move_result

    def _detach_unit_to_garrison(
        self,
        entity: Occupation,
        cell_pos: Tuple[int, int],
        unit_id: Optional[str],
        auto: bool,
    ) -> Dict[str, Any]:
        """Distacca una specifica unità dall'armata e la assegna alla guarnigione della cella."""
        units = self._entity_units(entity)
        if self._available_garrisons(entity) <= 0:
            if auto:
                return {"unit_id": None, "unit_name": ""}
            raise ValueError("Non hai unità sufficienti per lasciare un presidio.")

        selected_unit_id: Optional[str] = unit_id
        if selected_unit_id is None:
            sorted_units = sorted(units, key=lambda uid: self._unit_battle_value(uid))
            selected_unit_id = sorted_units[0] if sorted_units else None

        if selected_unit_id is None or selected_unit_id not in units:
            if auto:
                return {"unit_id": None, "unit_name": ""}
            raise ValueError("La truppa selezionata non è disponibile per il presidio.")

        cell = self.game_map.get_cell(*cell_pos)
        if cell is None:
            if auto:
                return {"unit_id": None, "unit_name": ""}
            raise ValueError("Cella presidio non valida.")

        units.remove(selected_unit_id)
        cell.garrison_unit_ids.append(selected_unit_id)
        cell.garrison_strength = max(cell.garrison_strength, len(cell.garrison_unit_ids))
        self._recompute_entity_army_state(entity)

        unit_name = self.units_map.get(selected_unit_id, {}).get("name", selected_unit_id)
        return {
            "unit_id": selected_unit_id,
            "unit_name": unit_name,
        }

    def _empty_army_vector(self) -> Dict[str, float]:
        return {
            "U1_attack": 0.0,
            "U2_defense": 0.0,
            "U3_mobility": 0.0,
            "U4_stealth": 0.0,
            "U5_discipline": 0.0,
            "U6_terrain_adapt": 0.0,
            "U7_range_power": 0.0,
            "U8_support": 0.0,
        }

    def _recompute_entity_army_state(self, entity: Occupation) -> None:
        units = self._entity_units(entity)
        if units:
            army_vector = aggregate_army(units, self.data["units"])
        else:
            army_vector = self._empty_army_vector()
        home_terrain = self.player_home_terrain if entity == PLAYER else self.ai_home_terrain
        troop_status = self.player_troop_status if entity == PLAYER else self.ai_troop_status
        if units:
            modified, _ = apply_modifiers(
                army_vector=army_vector,
                terrain_name=home_terrain,
                weather_name=self.weather,
                troop_status_name=troop_status,
                modifiers_data=self.data,
            )
        else:
            modified = army_vector.copy()

        army_cost = sum(self.unit_costs.get(unit_id, 0) for unit_id in units)
        if entity == PLAYER:
            self.player_army = army_vector
            self.player_modified = modified
            self.player_army_cost = army_cost
        else:
            self.ai_army = army_vector
            self.ai_modified = modified
            self.ai_army_cost = army_cost

    def _apply_attacker_losses(self, attacker: Occupation, losses: int) -> Dict[str, Any]:
        units = self._entity_units(attacker)
        if losses <= 0 or not units:
            return {"losses": 0, "removed_units": [], "removed_text": ""}

        losses = min(losses, len(units))
        sorted_for_losses = sorted(units, key=lambda unit_id: self._unit_battle_value(unit_id))
        removed = sorted_for_losses[:losses]
        for unit_id in removed:
            units.remove(unit_id)

        self._recompute_entity_army_state(attacker)

        removed_counts: Dict[str, int] = dict(Counter(removed))
        removed_parts: List[str] = []
        for unit_id, count in sorted(removed_counts.items(), key=lambda item: (-item[1], item[0])):
            unit_name = self.units_map.get(unit_id, {}).get("name", unit_id)
            removed_parts.append(f"{count} {unit_name}")

        return {
            "losses": losses,
            "removed_units": removed,
            "removed_text": ", ".join(removed_parts),
        }

    def _calculate_losses_for_battle(
        self,
        units_before: int,
        own_strength: float,
        enemy_strength: float,
        *,
        fortification_level: int = 0,
        garrison_strength: int = 0,
    ) -> int:
        """Regola perdite condivisa: attrito progressivo, meno wipe istantanei."""
        if units_before <= 0:
            return 0

        if enemy_strength <= 0:
            return 0

        if own_strength <= 0:
            return units_before

        weaker_side = own_strength <= enemy_strength

        if weaker_side:
            disadvantage = 1.0 - min(1.0, own_strength / max(1.0, enemy_strength))
            loss_ratio = (
                0.30
                + (0.34 * disadvantage)
                + (0.03 * fortification_level)
                + (0.02 * garrison_strength)
            )
            loss_ratio = min(0.88, max(0.24, loss_ratio))
        else:
            pressure_ratio = min(1.0, enemy_strength / max(1.0, own_strength))
            loss_ratio = (
                0.05
                + (0.24 * pressure_ratio)
                + (0.02 * fortification_level)
                + (0.015 * garrison_strength)
            )
            loss_ratio = min(0.52, max(0.03, loss_ratio))

        losses = int(round(units_before * loss_ratio))

        catastrophic_gap = own_strength < (enemy_strength * 0.32)
        if units_before > 1:
            losses = max(1, losses)
            if catastrophic_gap and weaker_side:
                losses = min(units_before, losses)
            else:
                losses = min(units_before - 1, losses)
        else:
            losses = min(units_before, losses)
        return losses

    def _unit_battle_value(self, unit_id: str) -> float:
        """Valore base di una singola legione/unità in combattimento."""
        unit = self.units_map[unit_id]
        attrs = unit["attributes"]
        weighted = (
            attrs["U1_attack"] * 24
            + attrs["U2_defense"] * 20
            + attrs["U3_mobility"] * 12
            + attrs["U4_stealth"] * 10
            + attrs["U5_discipline"] * 14
            + attrs["U6_terrain_adapt"] * 10
            + attrs["U7_range_power"] * 8
            + attrs["U8_support"] * 6
        )
        return weighted

    def _garrison_unit_defense_value(self, unit_id: str, terrain: str) -> float:
        """Valore difensivo di una unità distaccata, modulato dal terreno corrente."""
        base_value = self._unit_battle_value(unit_id)
        attrs = self.units_map[unit_id]["attributes"]

        terrain_lower = terrain.lower()
        terrain_factor = 1.0 + (attrs["U6_terrain_adapt"] * 0.18)

        if terrain_lower == "foresta":
            terrain_factor += (attrs["U4_stealth"] * 0.08) + (attrs["U3_mobility"] * 0.04)
        elif terrain_lower == "palude":
            terrain_factor += (attrs["U6_terrain_adapt"] * 0.08) + (attrs["U3_mobility"] * 0.05)
        elif terrain_lower == "montagna":
            terrain_factor += (attrs["U2_defense"] * 0.08) + (attrs["U5_discipline"] * 0.04)
        elif terrain_lower == "pianura":
            terrain_factor += (attrs["U1_attack"] * 0.05) + (attrs["U7_range_power"] * 0.03)
        elif terrain_lower == "fiume":
            terrain_factor += (attrs["U3_mobility"] * 0.08) + (attrs["U6_terrain_adapt"] * 0.08)

        return base_value * terrain_factor

    def _army_composition(self, entity: Occupation) -> Dict[str, int]:
        """Composizione esercito per tipo unità (id -> conteggio)."""
        unit_ids = self.player_units if entity == PLAYER else self.ai_units
        return dict(Counter(unit_ids))

    def _format_composition(self, entity: Occupation) -> str:
        """Stringa leggibile della composizione in legioni."""
        composition = self._army_composition(entity)
        if not composition:
            return "nessuna legione"

        parts: List[str] = []
        for unit_id, count in sorted(composition.items(), key=lambda item: (-item[1], item[0])):
            unit_name = self.units_map.get(unit_id, {}).get("name", unit_id)
            parts.append(f"{count} legioni {unit_name}")
        return ", ".join(parts)

    def _format_battle_location(self, terrain: str) -> str:
        """Rende il tipo battaglia con preposizione naturale in base al terreno."""
        prepositions = {
            "foresta": "nella",
            "palude": "nella",
            "montagna": "sulla",
            "pianura": "sulla",
            "fiume": "sul",
        }
        terrain_lower = terrain.lower()
        preposition = prepositions.get(terrain_lower, "su")
        return f"⚔ Battaglia {preposition} {terrain_lower}"

    def _strategy_factor(self, entity: Occupation, terrain: str, modified_vector: Dict[str, float]) -> float:
        """Fattore tattico legato alla qualità della manovra scelta rispetto all'esercito corrente."""
        compatibility = self._strategy_compatibility(entity, modified_vector)

        # Impatto strategico intenzionalmente forte:
        # - strategia affine => moltiplicatore molto alto
        # - strategia disallineata => malus severo
        # - soglie critiche per premiare/penalizzare scelte estreme
        base_factor = 0.38 + ((compatibility ** 2.6) * 1.92)

        critical_bonus = 0.0
        if compatibility >= 0.88:
            critical_bonus += 0.22
        elif compatibility >= 0.78:
            critical_bonus += 0.12

        critical_malus = 0.0
        if compatibility <= 0.22:
            critical_malus += 0.22
        elif compatibility <= 0.32:
            critical_malus += 0.12

        factor = base_factor + critical_bonus - critical_malus
        return max(0.30, min(2.35, factor))

    def _strategy_compatibility(self, entity: Occupation, modified_vector: Dict[str, float]) -> float:
        """Compatibilità [0..1] tra esercito modificato e strategia corrente."""
        strategy_id = self.player_strategy_id if entity == PLAYER else self.ai_strategy_id
        strategy = next((s for s in self.data["strategies"] if s["id"] == strategy_id), None)
        if strategy is None:
            return 0.5

        distance = euclidean_distance(modified_vector, strategy["ideal_attributes"])
        return max(0.0, min(1.0, 1.0 - (distance / (8 ** 0.5))))

    def _current_army_terrain(self, entity: Occupation) -> str:
        """Terreno attuale dell'armata, fallback al terreno base se la posizione non è valida."""
        pos = self.game_map.positions.get(entity)
        if pos is not None:
            cell = self.game_map.get_cell(*pos)
            if cell is not None:
                return cell.terrain
        return self.player_home_terrain if entity == PLAYER else self.ai_home_terrain

    def set_player_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """Aggiorna la strategia corrente del player e logga snapshot forza attuale."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        strategy = self.strategies_map.get(strategy_id)
        if strategy is None:
            raise ValueError("Strategia non valida.")

        self.player_strategy_id = strategy_id
        terrain = self._current_army_terrain(PLAYER)
        breakdown = self._strength_breakdown(PLAYER, terrain)
        strength_now = breakdown["effective_strength"]

        log_entry = (
            f"[Turno {self.game_map.turn}] 🎯 PLAYER imposta strategia {strategy['name']} "
            f"→ forza attuale {strength_now} su {terrain}"
        )
        self.battle_log.append(log_entry)
        log_strength_debug(
            "strategy_change_strength_snapshot",
            {
                "debug_notice": "DEBUG TEMPORANEO - rimuovere cartella debug in produzione",
                "turn": self.game_map.turn,
                "entity": PLAYER.value,
                "strategy_id": strategy_id,
                "strategy_name": strategy["name"],
                "terrain": terrain,
                "strength_breakdown": breakdown,
            },
        )

        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def get_in_game_advisor(self) -> Dict[str, Any]:
        """Restituisce un report advisor in-battle basato sullo stato corrente del player."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        terrain_name = self._current_army_terrain(PLAYER)
        return build_in_game_advisor_payload(
            data=self.data,
            turn=self.game_map.turn,
            player_units=list(self.player_units),
            player_army=dict(self.player_army),
            player_strategy_id=self.player_strategy_id,
            troop_status_name=self.player_troop_status,
            terrain_name=terrain_name,
            weather_name=self.weather,
        )

    def _available_mine_slots(self, entity: Occupation) -> int:
        """Slot miniera disponibili in base alle celle controllate."""
        return available_mine_slots(
            controlled_cells=self.game_map.count_occupied(entity),
            existing_mines=self.game_map.count_mines(entity),
        )

    def _ability_state(self, entity: Occupation, ability_id: str) -> Optional[Any]:
        return self.ability_states.get(entity, {}).get(ability_id)

    def _is_ability_unlocked(self, entity: Occupation, ability_id: str) -> bool:
        ability = self._ability_state(entity, ability_id)
        if ability is None:
            return False
        return ability.is_unlocked(self.game_map.turn)

    def _start_ability_research(self, entity: Occupation, ability_id: str) -> Optional[str]:
        ability = self._ability_state(entity, ability_id)
        if ability is None:
            return None
        if ability.is_researching() or ability.is_unlocked(self.game_map.turn):
            return None
        ability.start(self.game_map.turn)
        side = entity.value.upper()
        log_entry = (
            f"[Turno {self.game_map.turn}] ⭐ {side} avvia ricerca Abilità: {ability.name} "
            f"({ability.turns_required} turni)"
        )
        self.battle_log.append(log_entry)
        return log_entry

    def research_player_ability(self, ability_id: str = DOMAIN_ENGINEERING_ID) -> Dict[str, Any]:
        """Avvia la ricerca di una abilità lato player."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        ability = self._ability_state(PLAYER, ability_id)
        if ability is None:
            raise ValueError("Abilità sconosciuta.")
        if ability.is_unlocked(self.game_map.turn):
            raise ValueError("Abilità già sbloccata.")
        if ability.is_researching():
            raise ValueError("Ricerca abilità già in corso.")

        log_entry = self._start_ability_research(PLAYER, ability_id)
        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def _can_build_on_cell(self, entity: Occupation, row: int, col: int) -> bool:
        """Prima dello sblocco abilità, costruzione consentita solo sulla cella armata."""
        cell = self.game_map.get_cell(row, col)
        if cell is None or cell.occupation != entity:
            return False

        if self._is_ability_unlocked(entity, DOMAIN_ENGINEERING_ID):
            return True

        army_pos = self.game_map.positions.get(entity)
        return army_pos == (row, col)

    def place_mine(self, row: int, col: int) -> Dict[str, Any]:
        """Piazza una miniera del giocatore su una casella controllata."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")
        if self._available_mine_slots(PLAYER) <= 0:
            raise ValueError("Non hai slot miniera disponibili. Serve più territorio controllato.")
        if not self._can_build_on_cell(PLAYER, row, col):
            raise ValueError("Costruzione non consentita su questa cella: senza Abilità puoi costruire solo sulla tua armata.")

        cell = self.game_map.place_mine(PLAYER, row, col)
        log_entry = f"[Turno {self.game_map.turn}] ⛏ PLAYER costruisce una miniera su ({row},{col})"
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "cell": cell.to_dict(),
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "player_grux": self.grux_balance[PLAYER],
        }

    def place_garrison_here(self, unit_id: Optional[str] = None) -> Dict[str, Any]:
        """Piazza immediatamente un presidio sulla casella corrente dell'armata player."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")
        if self._available_garrisons(PLAYER) <= 0:
            raise ValueError("Non hai unità sufficienti: devi mantenere almeno una legione attiva con l'armata.")

        player_pos = self.game_map.positions.get(PLAYER)
        if player_pos is None:
            raise ValueError("Posizione PLAYER non disponibile.")

        cell = self.game_map.get_cell(*player_pos)
        if cell is None or cell.occupation != PLAYER:
            raise ValueError("La cella corrente non è controllata dal PLAYER.")

        detach_result = self._detach_unit_to_garrison(
            entity=PLAYER,
            cell_pos=player_pos,
            unit_id=unit_id,
            auto=False,
        )
        cell.garrison_strength = max(cell.garrison_strength, len(cell.garrison_unit_ids))

        row, col = player_pos
        log_entry = (
            f"[Turno {self.game_map.turn}] 🛡 PLAYER piazza un presidio su ({row},{col}) "
            f"— Distaccata: {detach_result['unit_name']}"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "cell": cell.to_dict(),
            "state": self.state.value,
            "map": self.game_map.to_dict(),
        }

    def _fortification_cost(self, current_level: int) -> int:
        """Costo fortificazione con crescita forte sullo stack della stessa cella."""
        return int(round(self.base_fortification_cost * (1 + (current_level * 1.7))))

    def place_fortification(self, row: int, col: int) -> Dict[str, Any]:
        """Piazza una fortificazione PLAYER su una cella controllata, con costo crescente."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        cell = self.game_map.get_cell(row, col)
        if cell is None:
            raise ValueError("Cella fuori dalla mappa.")
        if cell.occupation != PLAYER:
            raise ValueError("Puoi fortificare solo celle controllate dal PLAYER.")
        if not self._can_build_on_cell(PLAYER, row, col):
            raise ValueError("Costruzione non consentita su questa cella: senza Abilità puoi costruire solo sulla tua armata.")
        if cell.is_castle:
            raise ValueError("Il castello centrale non è fortificabile.")

        current_level = cell.fortification_level
        cost = self._fortification_cost(current_level)
        if self.grux_balance[PLAYER] < cost:
            raise ValueError(f"Grux insufficienti per fortificare: servono {cost}, disponibili {self.grux_balance[PLAYER]}")

        self.grux_balance[PLAYER] -= cost
        cell = self.game_map.place_fortification(PLAYER, row, col)
        next_cost = self._fortification_cost(cell.fortification_level)

        log_entry = (
            f"[Turno {self.game_map.turn}] 🧱 PLAYER fortifica ({row},{col}) "
            f"→ livello {cell.fortification_level} (costo {cost} grux)"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "cell": cell.to_dict(),
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "player_grux": self.grux_balance[PLAYER],
            "next_fortification_cost": next_cost,
        }

    def _place_best_ai_mine(self) -> Optional[str]:
        """L'IA piazza una miniera sulla miglior cella controllata disponibile."""
        ai_can_build_anywhere = self._is_ability_unlocked(AI, DOMAIN_ENGINEERING_ID)
        ai_build_positions = set(self._active_legion_positions(AI))

        best_cell = None
        best_score = float("-inf")
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != AI or cell.is_castle or cell.is_mine or cell.terrain == "Fiume":
                    continue
                if not ai_can_build_anywhere and (cell.row, cell.col) not in ai_build_positions:
                    continue
                score = 2.0 if cell.is_strategic else 0.0
                if cell.terrain in {"Pianura", "Montagna"}:
                    score += 1.0
                if score > best_score:
                    best_score = score
                    best_cell = cell

        if best_cell is None:
            return None

        self.game_map.place_mine(AI, best_cell.row, best_cell.col)
        return f"[Turno {self.game_map.turn}] ⛏ IA costruisce una miniera su ({best_cell.row},{best_cell.col})"

    def _place_best_ai_fortification(self) -> Optional[str]:
        """L'IA fortifica la miglior cella controllata disponibile, rispettando costo e vincoli abilità."""
        ai_can_build_anywhere = self._is_ability_unlocked(AI, DOMAIN_ENGINEERING_ID)
        ai_build_positions = set(self._active_legion_positions(AI))

        player_anchor: Optional[Tuple[int, int]] = None
        if self.player_legions:
            first_player_legion = next(iter(self.player_legions.values()))
            pos = tuple(first_player_legion.get("pos", ()))
            if len(pos) == 2:
                player_anchor = (int(pos[0]), int(pos[1]))

        best: Optional[Tuple[float, Any, int]] = None
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != AI or cell.is_castle:
                    continue
                if not ai_can_build_anywhere and (cell.row, cell.col) not in ai_build_positions:
                    continue

                current_level = int(cell.fortification_level)
                cost = self._fortification_cost(current_level)
                if self.grux_balance[AI] < cost:
                    continue

                score = 0.0
                if cell.is_strategic:
                    score += 2.4
                if cell.is_mine:
                    score += 1.7
                score += max(0.0, 1.2 - (current_level * 0.45))

                if player_anchor is not None:
                    score += max(0.0, 1.4 - (self._order_distance((cell.row, cell.col), player_anchor) * 0.18))

                if best is None or score > best[0]:
                    best = (score, cell, cost)

        if best is None:
            return None

        _, cell, cost = best
        self.grux_balance[AI] -= cost
        placed = self.game_map.place_fortification(AI, cell.row, cell.col)
        return (
            f"[Turno {self.game_map.turn}] 🧱 IA fortifica ({placed.row},{placed.col}) "
            f"→ livello {placed.fortification_level} (costo {cost} grux)"
        )

    def recruit_player_unit(self, unit_id: str) -> Dict[str, Any]:
        """Compra una unità per il giocatore e aggiorna l'esercito."""
        log_entry = self._recruit_unit(PLAYER, unit_id, auto=False)
        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def start_player_auto_recruit(self, unit_id: str, turns: int) -> Dict[str, Any]:
        """Avvia il piano di autoreclutamento del player per un numero di turni."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")
        if unit_id not in self.unit_costs:
            raise ValueError(f"Unità sconosciuta: {unit_id}")

        turns_value = int(turns)
        if turns_value <= 0:
            raise ValueError("I turni di autoreclutamento devono essere almeno 1.")
        if turns_value > 40:
            raise ValueError("I turni di autoreclutamento non possono superare 40.")

        unit_name = self.units_map.get(unit_id, {}).get("name", unit_id)
        self.player_auto_recruit.update(
            {
                "enabled": True,
                "unit_id": unit_id,
                "unit_name": unit_name,
                "turns_total": turns_value,
                "turns_remaining": turns_value,
                "attempted_turns": 0,
                "successful_recruits": 0,
                "last_result": "scheduled",
            }
        )

        log_entry = (
            f"[Turno {self.game_map.turn}] 🤖 PLAYER avvia autoreclutamento: "
            f"{unit_name} per {turns_value} turni"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def stop_player_auto_recruit(self, reason: str = "manual") -> Dict[str, Any]:
        """Ferma il piano di autoreclutamento del player."""
        was_enabled = bool(self.player_auto_recruit.get("enabled"))
        unit_name = self.player_auto_recruit.get("unit_name") or "unità"

        self.player_auto_recruit["enabled"] = False
        self.player_auto_recruit["turns_remaining"] = 0
        self.player_auto_recruit["last_result"] = "stopped"

        if was_enabled:
            reason_label = "manuale" if reason == "manual" else reason
            log_entry = (
                f"[Turno {self.game_map.turn}] 🤖 PLAYER ferma autoreclutamento "
                f"({unit_name}) - motivo: {reason_label}"
            )
            self.battle_log.append(log_entry)
            message = log_entry
        else:
            message = "Autoreclutamento non attivo."

        return {
            "ok": True,
            "message": message,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def _run_player_auto_recruit(self) -> List[str]:
        """Esegue una iterazione del piano di autoreclutamento player al termine del round."""
        logs: List[str] = []
        if self.state != SessionState.ACTIVE:
            return logs

        if not self.player_auto_recruit.get("enabled"):
            return logs

        unit_id = self.player_auto_recruit.get("unit_id")
        unit_name = self.player_auto_recruit.get("unit_name") or (unit_id or "unità")
        turns_remaining = int(self.player_auto_recruit.get("turns_remaining") or 0)

        if not unit_id or unit_id not in self.unit_costs:
            self.player_auto_recruit["enabled"] = False
            self.player_auto_recruit["last_result"] = "invalid_unit"
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Autoreclutamento interrotto: unità non valida"
            )
            return logs

        if turns_remaining <= 0:
            self.player_auto_recruit["enabled"] = False
            self.player_auto_recruit["last_result"] = "completed"
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Autoreclutamento completato ({unit_name})"
            )
            return logs

        self.player_auto_recruit["attempted_turns"] = int(self.player_auto_recruit.get("attempted_turns") or 0) + 1
        self.player_auto_recruit["turns_remaining"] = turns_remaining - 1

        recruit_log = self._recruit_unit(PLAYER, unit_id, auto=True)
        if recruit_log:
            self.player_auto_recruit["successful_recruits"] = int(self.player_auto_recruit.get("successful_recruits") or 0) + 1
            self.player_auto_recruit["last_result"] = "success"
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Autoreclutamento riuscito: {unit_name}"
            )
        else:
            self.player_auto_recruit["last_result"] = "skipped"
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Autoreclutamento non riuscito: cooldown o grux insufficienti per {unit_name}"
            )

        if int(self.player_auto_recruit.get("turns_remaining") or 0) <= 0:
            self.player_auto_recruit["enabled"] = False
            self.player_auto_recruit["last_result"] = "completed"
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Piano autoreclutamento terminato ({unit_name})"
            )

        return logs

    def _recruit_unit(self, entity: Occupation, unit_id: str, auto: bool) -> Optional[str]:
        """Recluta una unità, scala il costo e ricalcola il vettore esercito."""
        if self.state != SessionState.ACTIVE:
            if auto:
                return None
            raise ValueError("La partita è terminata.")

        if unit_id not in self.unit_costs:
            raise ValueError(f"Unità sconosciuta: {unit_id}")

        if not self._can_recruit_now(entity):
            last_turn = self.last_recruit_turn.get(entity)
            turns_passed = 0 if last_turn is None else (self.game_map.turn - last_turn)
            remaining = max(0, self.recruit_cooldown_turns - turns_passed)
            if auto:
                return None
            raise ValueError(
                f"Reclutamento in cooldown: attendi ancora {remaining} turno/i prima di reclutare di nuovo."
            )

        cost = self.unit_costs[unit_id]
        if self.grux_balance[entity] < cost:
            if auto:
                return None
            raise ValueError(f"Grux insufficienti: servono {cost}, disponibili {self.grux_balance[entity]}")

        home_terrain = self.player_home_terrain if entity == PLAYER else self.ai_home_terrain
        before_breakdown = self._strength_breakdown(entity, home_terrain)

        self.grux_balance[entity] -= cost

        if entity == PLAYER:
            self.player_units.append(unit_id)
            self.player_army = aggregate_army(self.player_units, self.data["units"])
            self.player_modified, _ = apply_modifiers(
                army_vector=self.player_army,
                terrain_name=self.player_home_terrain,
                weather_name=self.weather,
                troop_status_name=self.player_troop_status,
                modifiers_data=self.data,
            )
            self.player_army_cost += cost
        else:
            self.ai_units.append(unit_id)
            self.ai_army = aggregate_army(self.ai_units, self.data["units"])
            self.ai_modified, _ = apply_modifiers(
                army_vector=self.ai_army,
                terrain_name=self.ai_home_terrain,
                weather_name=self.weather,
                troop_status_name=self.ai_troop_status,
                modifiers_data=self.data,
            )
            self.ai_army_cost += cost

        side = entity.value.upper()
        unit_name = self.units_map.get(unit_id, {}).get("name", unit_id)
        log_entry = f"[Turno {self.game_map.turn}] 💰 {side} recluta {unit_name} per {cost} grux"
        self.battle_log.append(log_entry)
        self.last_recruit_turn[entity] = self.game_map.turn

        after_breakdown = self._strength_breakdown(entity, home_terrain)
        log_strength_debug(
            "recruit_strength_delta",
            {
                "debug_notice": "DEBUG TEMPORANEO - rimuovere cartella debug in produzione",
                "turn": self.game_map.turn,
                "entity": entity.value,
                "unit_id": unit_id,
                "unit_cost": cost,
                "grux_balance_after": self.grux_balance[entity],
                "before": before_breakdown,
                "after": after_breakdown,
                "delta_effective_strength": round(
                    after_breakdown["effective_strength"] - before_breakdown["effective_strength"],
                    4,
                ),
            },
        )
        return log_entry

    # ──────────────────────────────────────────────────────────
    # RISOLUZIONE BATTAGLIA (privato)
    # ──────────────────────────────────────────────────────────

    def _resolve_encounter(self, move_result: Dict[str, Any], attacker: Occupation) -> Dict[str, Any]:
        """Risolve armata, guarnigione o assalto al castello."""
        encounter_type = move_result["encounter_type"]
        if encounter_type == "field_army":
            return self._resolve_field_battle(move_result, attacker)
        return self._resolve_static_defense(move_result, attacker)

    def _effective_army_strength(self, entity: Occupation, terrain: str) -> float:
        """Forza effettiva dell'armata sul terreno corrente, penalizzata se ha staccato troppi presidi."""
        return self._strength_breakdown(entity, terrain)["effective_strength"]

    def _strength_breakdown(self, entity: Occupation, terrain: str) -> Dict[str, Any]:
        """Breakdown DEBUG della forza usata in combattimento."""
        army_vector = self.player_army if entity == PLAYER else self.ai_army
        troop_status = self.player_troop_status if entity == PLAYER else self.ai_troop_status
        modified, warnings = apply_modifiers(
            army_vector=army_vector,
            terrain_name=terrain,
            weather_name=self.weather,
            troop_status_name=troop_status,
            modifiers_data=self.data,
        )

        composition = self._army_composition(entity)
        unit_power_rows: List[Dict[str, Any]] = []
        base_total = 0.0
        stack_bonus_total = 0.0
        total_legions = 0
        for unit_id, count in composition.items():
            value = self._unit_battle_value(unit_id)
            base_part = value * count
            # Bonus stack controllato: utile ma meno esplosivo in late game.
            stack_bonus = value * 0.22 * ((count - 1) ** 1.08) if count > 1 else 0.0
            stack_bonus = min(stack_bonus, base_part * 0.55)
            unit_power_rows.append(
                {
                    "unit_id": unit_id,
                    "unit_name": self.units_map.get(unit_id, {}).get("name", unit_id),
                    "count": count,
                    "unit_value": round(value, 3),
                    "base_part": round(base_part, 3),
                    "stack_bonus": round(stack_bonus, 3),
                }
            )
            base_total += base_part
            stack_bonus_total += stack_bonus
            total_legions += count

        strategy_compatibility = self._strategy_compatibility(entity, modified)
        strategy_factor = self._strategy_factor(entity, terrain, modified)
        detached = self.game_map.count_garrisons(entity)
        detach_penalty = max(0.7, 1.0 - (max(0, detached) * 0.06))

        # Fattore contesto ricavato dai modificatori su attributi: centro su 1.0
        context_factor = max(0.75, min(1.25, (sum(modified.values()) / 4.6)))

        base_strength = base_total + stack_bonus_total
        effective_strength = base_strength * strategy_factor * context_factor * detach_penalty
        return {
            "entity": entity.value,
            "terrain": terrain,
            "weather": self.weather,
            "troop_status": troop_status,
            "composition": composition,
            "composition_text": self._format_composition(entity),
            "legions_total": total_legions,
            "unit_power_rows": unit_power_rows,
            "detached_garrisons_over_base": max(0, detached),
            "detach_penalty": round(detach_penalty, 4),
            "strategy_factor": round(strategy_factor, 4),
            "strategy_compatibility": round(strategy_compatibility, 4),
            "context_factor": round(context_factor, 4),
            "base_strength": round(base_strength, 4),
            "effective_strength": int(round(effective_strength)),
            "modified_vector": {k: round(v, 4) for k, v in modified.items()},
            "modifier_warnings": warnings,
        }

    def _retreat_to_castle(self, entity: Occupation) -> None:
        """Ritira un'armata sulla linea davanti al castello, se ancora controllato."""
        castle_pos = self.game_map.get_castle_position(entity)
        if castle_pos is None:
            self.state = SessionState.GAME_OVER
            self.winner = entity.opposite().value
            return

        castle_cell = self.game_map.get_cell(*castle_pos)
        if castle_cell is None or castle_cell.occupation != entity:
            self.state = SessionState.GAME_OVER
            self.winner = entity.opposite().value
            return

        rally_cells: List[Tuple[int, int]] = []
        for neighbor in self.game_map.get_neighbors(*castle_pos):
            if neighbor.is_castle:
                continue
            if neighbor.occupation == entity:
                rally_cells.append((neighbor.row, neighbor.col))

        if not rally_cells:
            for neighbor in self.game_map.get_neighbors(*castle_pos):
                if neighbor.is_castle:
                    continue
                if neighbor.occupation == Occupation.NEUTRAL:
                    rally_cells.append((neighbor.row, neighbor.col))

        if not rally_cells:
            for neighbor in self.game_map.get_neighbors(*castle_pos):
                if not neighbor.is_castle:
                    rally_cells.append((neighbor.row, neighbor.col))

        if not rally_cells:
            self.state = SessionState.GAME_OVER
            self.winner = entity.opposite().value
            return

        if entity == PLAYER:
            rally_cells.sort(key=lambda pos: (-pos[0], abs(pos[1] - castle_pos[1])))
        else:
            rally_cells.sort(key=lambda pos: (pos[0], abs(pos[1] - castle_pos[1])))

        rally_pos = rally_cells[0]
        rally_cell = self.game_map.get_cell(*rally_pos)
        if rally_cell is None:
            self.state = SessionState.GAME_OVER
            self.winner = entity.opposite().value
            return

        rally_cell.occupation = entity
        self.game_map.positions[entity] = rally_pos

    def _resolve_field_battle(self, move_result: Dict[str, Any], attacker: Occupation) -> Dict[str, Any]:
        """Scontro tra le due armate principali. Il perdente si ritira al castello."""
        defender = attacker.opposite()
        terrain = move_result["terrain"]
        to_pos = tuple(move_result["to_pos"])
        attacker_units_before = len(self._entity_units(attacker))
        defender_units_before = len(self._entity_units(defender))

        enemy_castle = self.game_map.get_castle_position(defender)
        battle_label = self._format_battle_location(terrain)
        if enemy_castle == to_pos:
            battle_label = "🏰 Assalto al castello centrale"

        # Caso bordo: una delle due armate e vuota. Evita "battaglie" fittizie con forza 0.
        if attacker_units_before <= 0 or defender_units_before <= 0:
            if attacker_units_before > defender_units_before:
                winner = attacker
                loser = defender
            elif defender_units_before > attacker_units_before:
                winner = defender
                loser = attacker
            else:
                winner = defender
                loser = attacker

            contested_cell = self.game_map.get_cell(*to_pos)
            if contested_cell is not None:
                contested_cell.garrison_strength = 0
                contested_cell.garrison_unit_ids = []
                contested_cell.fortification_level = 0
                contested_cell.occupation = winner

            self.game_map.positions[winner] = to_pos
            self._retreat_to_castle(loser)

            if enemy_castle == to_pos and winner == attacker:
                self.state = SessionState.GAME_OVER
                self.winner = attacker.value

            attacker_comp = self._format_composition(attacker)
            defender_comp = self._format_composition(defender)
            attacker_strength = (
                self._strength_breakdown(attacker, terrain)["effective_strength"]
                if attacker_units_before > 0
                else 0
            )
            defender_strength = (
                self._strength_breakdown(defender, terrain)["effective_strength"]
                if defender_units_before > 0
                else 0
            )

            if attacker_units_before <= 0 and defender_units_before <= 0:
                outcome_text = f"Nessuno scontro: armate assenti, prevale {winner.value.upper()}"
            elif attacker_units_before <= 0:
                outcome_text = f"Nessuno scontro: armata {attacker.value.upper()} assente, prevale {winner.value.upper()}"
            else:
                outcome_text = f"Nessuno scontro: armata {defender.value.upper()} assente, prevale {winner.value.upper()}"

            log_entry = (
                f"[Turno {self.game_map.turn}] {battle_label}: "
                f"{attacker.value.upper()} [{attacker_comp}] forza {attacker_strength} "
                f"vs {defender.value.upper()} [{defender_comp}] forza {defender_strength} "
                f"→ {outcome_text}"
            )
            self.battle_log.append(log_entry)

            return {
                "type": "field_army",
                "terrain": terrain,
                "winner": winner.value,
                "loser": loser.value,
                "attacker_strength": round(attacker_strength, 3),
                "defender_strength": round(defender_strength, 3),
                "log": log_entry,
            }

        attacker_breakdown = self._strength_breakdown(attacker, terrain)
        defender_breakdown = self._strength_breakdown(defender, terrain)
        attacker_strength = attacker_breakdown["effective_strength"]
        defender_strength = defender_breakdown["effective_strength"]
        defender_movement_modifier = self.movement_system.get_defense_modifier(defender)

        if defender_movement_modifier.get("active"):
            defender_strength_before_penalty = defender_strength
            defender_strength = int(round(defender_strength * float(defender_movement_modifier["factor"])))
            defender_breakdown["effective_strength_before_movement_penalty"] = defender_strength_before_penalty
            defender_breakdown["movement_defense_penalty"] = {
                "active": True,
                "reduction_ratio": round(float(defender_movement_modifier["reduction_ratio"]), 4),
                "factor": round(float(defender_movement_modifier["factor"]), 4),
                "blocked_turns": int(defender_movement_modifier["blocked_turns"]),
                "last_terrain": defender_movement_modifier.get("last_terrain"),
                "last_cost": defender_movement_modifier.get("last_cost"),
            }
            defender_breakdown["effective_strength"] = defender_strength

        if attacker_strength > defender_strength:
            winner = attacker
            loser = defender
        elif defender_strength > attacker_strength:
            winner = defender
            loser = attacker
        else:
            winner = defender
            loser = attacker

        contested_cell = self.game_map.get_cell(*to_pos)
        if contested_cell is not None:
            contested_cell.garrison_strength = 0
            contested_cell.garrison_unit_ids = []
            contested_cell.fortification_level = 0
            contested_cell.occupation = winner

        self.game_map.positions[winner] = to_pos
        self._retreat_to_castle(loser)

        if enemy_castle == to_pos and winner == attacker:
            self.state = SessionState.GAME_OVER
            self.winner = attacker.value

        attacker_comp = attacker_breakdown["composition_text"]
        defender_comp = defender_breakdown["composition_text"]

        attacker_losses = self._calculate_losses_for_battle(
            attacker_units_before,
            attacker_strength,
            defender_strength,
        )
        defender_losses = self._calculate_losses_for_battle(
            defender_units_before,
            defender_strength,
            attacker_strength,
        )
        attacker_loss_result = self._apply_attacker_losses(attacker, attacker_losses)
        defender_loss_result = self._apply_attacker_losses(defender, defender_losses)

        log_entry = (
            f"[Turno {self.game_map.turn}] {battle_label}: "
            f"{attacker.value.upper()} [{attacker_comp}] forza {attacker_strength} "
            f"vs {defender.value.upper()} [{defender_comp}] forza {defender_strength} "
            f"→ Ritirata di {loser.value.upper()}"
        )
        if defender_movement_modifier.get("active"):
            penalty_pct = int(round(float(defender_movement_modifier["reduction_ratio"]) * 100))
            log_entry += (
                f" | Difesa {defender.value.upper()} ridotta del {penalty_pct}% "
                f"(movimento incompleto)"
            )
        if attacker_loss_result["losses"] > 0 or defender_loss_result["losses"] > 0:
            log_entry += (
                f" | Perdite {attacker.value.upper()}: {attacker_loss_result['losses']}"
                f" | Perdite {defender.value.upper()}: {defender_loss_result['losses']}"
            )
        self.battle_log.append(log_entry)
        if attacker_loss_result["losses"] > 0 and attacker_loss_result["removed_text"]:
            self.battle_log.append(
                f"[Turno {self.game_map.turn}] ☠ {attacker.value.upper()} perde {attacker_loss_result['removed_text']}"
            )
        if defender_loss_result["losses"] > 0 and defender_loss_result["removed_text"]:
            self.battle_log.append(
                f"[Turno {self.game_map.turn}] ☠ {defender.value.upper()} perde {defender_loss_result['removed_text']}"
            )
        log_strength_debug(
            "field_battle_strength",
            {
                "debug_notice": "DEBUG TEMPORANEO - rimuovere cartella debug in produzione",
                "turn": self.game_map.turn,
                "terrain": terrain,
                "attacker": attacker.value,
                "defender": defender.value,
                "attacker_breakdown": attacker_breakdown,
                "defender_breakdown": defender_breakdown,
                "attacker_units_before": attacker_units_before,
                "defender_units_before": defender_units_before,
                "attacker_losses": attacker_loss_result["losses"],
                "defender_losses": defender_loss_result["losses"],
                "winner": winner.value,
                "loser": loser.value,
                "encounter_pos": list(to_pos),
            },
        )

        return {
            "type": "field_army",
            "terrain": terrain,
            "winner": winner.value,
            "loser": loser.value,
            "attacker_strength": round(attacker_strength, 3),
            "defender_strength": round(defender_strength, 3),
            "log": log_entry,
        }

    def _resolve_static_defense(self, move_result: Dict[str, Any], attacker: Occupation) -> Dict[str, Any]:
        """Risoluzione di guarnigioni e castelli."""
        defender = attacker.opposite()
        terrain = move_result["terrain"]
        from_pos = tuple(move_result.get("from_pos", self.game_map.positions.get(attacker, (0, 0))))
        to_pos = tuple(move_result["to_pos"])
        dest_cell = self.game_map.get_cell(*to_pos)
        encounter_type = move_result["encounter_type"]
        attacker_units_before = len(self._entity_units(attacker))

        attacker_breakdown = self._strength_breakdown(attacker, terrain)
        attacker_strength = attacker_breakdown["effective_strength"]
        garrison_strength = dest_cell.garrison_strength if dest_cell else 0
        garrison_units = list(dest_cell.garrison_unit_ids) if dest_cell else []
        fortification_level = dest_cell.fortification_level if dest_cell else 0
        fortification_bonus = 0.0
        garrison_component = 0.0
        garrison_unit_quality_bonus = 0.0
        synergy_bonus = 0.0

        if garrison_strength > 0:
            # Presidio più incisivo, con componente che scala sull'intensità dell'assalto.
            garrison_component = (
                (garrison_strength * 18.0)
                + (attacker_strength * min(0.22, garrison_strength * 0.025))
            )

        if garrison_units:
            # Le unità realmente distaccate modificano la resa difensiva del presidio.
            garrison_unit_quality_bonus = (
                sum(self._garrison_unit_defense_value(unit_id, terrain) for unit_id in garrison_units) * 11.5
            )

        if fortification_level > 0:
            # Fortificazioni con impatto crescente anche in late game:
            # base fissa + componente scalata sulla forza dell'assalto.
            scaling_component = attacker_strength * min(0.32, 0.12 + (fortification_level * 0.05))
            stack_component = max(0, fortification_level - 1) * 16.0
            fortification_bonus = (fortification_level * 18.0) + scaling_component + stack_component

        if garrison_strength > 0 and fortification_level > 0:
            # Sinergia: presidio dentro fortificazione rende la difesa molto più efficiente.
            synergy_bonus = (
                (fortification_level * garrison_strength * 7.0)
                + (attacker_strength * min(0.12, 0.015 * fortification_level * garrison_strength))
            )

        if dest_cell and dest_cell.is_castle:
            # Difesa castello rinforzata per evitare cadute immediate
            defender_units = len(self.player_units if defender == PLAYER else self.ai_units)
            terrain_bonus = 8.0 if terrain in {"Foresta", "Montagna", "Palude"} else 5.0
            castle_bonus = 38.0 + (defender_units * 3.2)
        else:
            terrain_bonus = 5.0 if terrain in {"Foresta", "Montagna", "Palude"} else 2.0
            castle_bonus = 0.0

        defender_score = (
            garrison_component
            + garrison_unit_quality_bonus
            + terrain_bonus
            + castle_bonus
            + fortification_bonus
            + synergy_bonus
        )
        attacker_losses = self._calculate_losses_for_battle(
            attacker_units_before,
            attacker_strength,
            defender_score,
            fortification_level=fortification_level,
            garrison_strength=garrison_strength,
        )
        castle_damage = 0
        castle_hp_before = None
        castle_hp_after = None

        if attacker_strength > defender_score:
            winner = attacker
            loser = defender
            if dest_cell is not None and dest_cell.is_castle:
                castle_hp_before = self.castle_hp.get(defender, self.castle_hp_max.get(defender, CASTLE_BASE_HP))
                castle_damage = self._compute_castle_damage(attacker_strength, defender_score)
                castle_hp_after = max(0, castle_hp_before - castle_damage)
                self.castle_hp[defender] = castle_hp_after

                if castle_hp_after <= 0:
                    dest_cell.garrison_strength = 0
                    dest_cell.garrison_unit_ids = []
                    dest_cell.fortification_level = 0
                    dest_cell.occupation = attacker
                    self.state = SessionState.GAME_OVER
                    self.winner = attacker.value
                else:
                    # Il castello regge l'assalto: l'attaccante viene respinto alla linea di partenza.
                    self._retreat_to_castle(attacker)
                    dest_cell.occupation = defender
                    winner = defender
                    loser = attacker
            else:
                if dest_cell is not None:
                    dest_cell.garrison_strength = 0
                    dest_cell.garrison_unit_ids = []
                    dest_cell.fortification_level = 0
                    dest_cell.occupation = attacker
                self.game_map.positions[attacker] = to_pos
        else:
            winner = defender
            loser = attacker
            if encounter_type == "castle":
                # Assalto respinto: niente spam in adiacenza, rientro alla linea di partenza.
                self._retreat_to_castle(attacker)
            else:
                self._retreat_to_castle(attacker)
            if dest_cell is not None:
                dest_cell.occupation = defender

        loss_result = self._apply_attacker_losses(attacker, attacker_losses)

        if encounter_type == "castle":
            label = "🏰 Assalto al castello centrale"
        elif dest_cell is not None and dest_cell.is_mine:
            label = "⛏ Battaglia per la conquista della miniera"
        elif encounter_type == "garrison" and fortification_level > 0:
            label = "🧱🛡 Assalto a presidio fortificato"
        elif encounter_type == "fortified":
            label = "🧱 Assalto a territorio fortificato"
        elif encounter_type == "garrison":
            label = "🛡 Scontro contro presidio territoriale"
        else:
            label = "⚔ Scontro territoriale"

        attacker_comp = attacker_breakdown["composition_text"]

        log_entry = (
            f"[Turno {self.game_map.turn}] {label} su {terrain}: "
            f"{attacker.value.upper()} [{attacker_comp}] forza {attacker_strength} "
            f"vs difesa statica {int(round(defender_score))} "
            f"→ Vince {winner.value.upper()}"
        )
        if loss_result["losses"] > 0:
            log_entry += f" | Perdite {attacker.value.upper()}: {loss_result['losses']}"
        if castle_hp_before is not None and castle_hp_after is not None:
            log_entry += (
                f" | Danno castello: {castle_damage} "
                f"(HP {castle_hp_before}->{castle_hp_after})"
            )
        self.battle_log.append(log_entry)
        if loss_result["losses"] > 0 and loss_result["removed_text"]:
            self.battle_log.append(
                f"[Turno {self.game_map.turn}] ☠ {attacker.value.upper()} perde {loss_result['removed_text']}"
            )
        log_strength_debug(
            "static_defense_battle_strength",
            {
                "debug_notice": "DEBUG TEMPORANEO - rimuovere cartella debug in produzione",
                "turn": self.game_map.turn,
                "terrain": terrain,
                "encounter_type": encounter_type,
                "attacker": attacker.value,
                "defender": defender.value,
                "attacker_breakdown": attacker_breakdown,
                "defense_breakdown": {
                    "garrison_strength": garrison_strength,
                    "fortification_level": fortification_level,
                    "fortification_bonus": round(fortification_bonus, 4),
                    "synergy_bonus": round(synergy_bonus, 4),
                    "garrison_component": round(garrison_component, 4),
                    "garrison_unit_quality_bonus": round(garrison_unit_quality_bonus, 4),
                    "garrison_unit_ids": garrison_units,
                    "terrain_bonus": terrain_bonus,
                    "castle_bonus": castle_bonus,
                    "castle_hp_before": castle_hp_before,
                    "castle_hp_after": castle_hp_after,
                    "castle_damage": castle_damage,
                    "defender_score": round(defender_score, 4),
                    "attacker_units_before": attacker_units_before,
                    "attacker_losses": loss_result["losses"],
                },
                "winner": winner.value,
                "loser": loser.value,
                "encounter_pos": list(to_pos),
            },
        )

        return {
            "type": encounter_type,
            "terrain": terrain,
            "winner": winner.value,
            "loser": loser.value,
            "attacker_strength": round(attacker_strength, 3),
            "defender_strength": round(defender_score, 3),
            "log": log_entry,
        }

    # ──────────────────────────────────────────────────────────
    # SERIALIZZAZIONE
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Stato completo della sessione (per l'API)."""
        return {
            "state":   self.state.value,
            "winner":  self.winner,
            "weather": self.weather,
            "player": {
                "units":         self.player_units,
                "strategy_id":   self.player_strategy_id,
                "strategy_name": self.strategies_map.get(self.player_strategy_id, {}).get("name", self.player_strategy_id),
                "army":          self.player_army,
                "modified":      self.player_modified,
                "troop_status":  self.player_troop_status,
                "legions":       self.player_legions,
                "castle": {
                    "hp": self.castle_hp.get(PLAYER, self.castle_hp_max.get(PLAYER, CASTLE_BASE_HP)),
                    "max_hp": self.castle_hp_max.get(PLAYER, CASTLE_BASE_HP),
                },
                "auto_recruit": {
                    "enabled": bool(self.player_auto_recruit.get("enabled")),
                    "unit_id": self.player_auto_recruit.get("unit_id"),
                    "unit_name": self.player_auto_recruit.get("unit_name"),
                    "turns_total": int(self.player_auto_recruit.get("turns_total") or 0),
                    "turns_remaining": int(self.player_auto_recruit.get("turns_remaining") or 0),
                    "attempted_turns": int(self.player_auto_recruit.get("attempted_turns") or 0),
                    "successful_recruits": int(self.player_auto_recruit.get("successful_recruits") or 0),
                    "last_result": self.player_auto_recruit.get("last_result") or "inactive",
                },
                "available_garrisons": self._available_garrisons(PLAYER),
                "grux_balance":  self.grux_balance[PLAYER],
                "army_cost":     self.player_army_cost,
                "available_mine_slots": self._available_mine_slots(PLAYER),
                "fortification_base_cost": self.base_fortification_cost,
                "movement": self.movement_system.export_entity_state(PLAYER),
                "abilities": {
                    ability_id: state.to_dict(self.game_map.turn)
                    for ability_id, state in self.ability_states[PLAYER].items()
                },
                "unit_costs":    {unit_id: self.unit_costs[unit_id] for unit_id in self.player_units},
            },
            "ai": {
                "units":         self.ai_units,
                "strategy_id":   self.ai_strategy_id,
                "strategy_name": self.ai_strategy_name,
                "difficulty":    self.ai_difficulty,
                "difficulty_labels": get_ai_difficulty_labels(),
                "legions":       self.ai_legions,
                "castle": {
                    "hp": self.castle_hp.get(AI, self.castle_hp_max.get(AI, CASTLE_BASE_HP)),
                    "max_hp": self.castle_hp_max.get(AI, CASTLE_BASE_HP),
                },
                "army":          self.ai_army,
                "modified":      self.ai_modified,
                "troop_status":  self.ai_troop_status,
                "available_garrisons": self._available_garrisons(AI),
                "grux_balance":  self.grux_balance[AI],
                "army_cost":     self.ai_army_cost,
                "available_mine_slots": self._available_mine_slots(AI),
                "movement": self.movement_system.export_entity_state(AI),
                "abilities": {
                    ability_id: state.to_dict(self.game_map.turn)
                    for ability_id, state in self.ability_states[AI].items()
                },
                "unit_costs":    {unit_id: self.unit_costs[unit_id] for unit_id in self.ai_units},
            },
            "movement": self.movement_system.export_config(),
            "map":        self.game_map.to_dict(),
            "battle_log": self.battle_log,
            "debug": {
                "ai_kill_switch_active": self.debug_ai_kill_switch,
                "kill_switch_notice": "DEBUG TEMPORANEO - rimuovere endpoint, flag e pulsante kill switch IA in produzione",
            },
        }
