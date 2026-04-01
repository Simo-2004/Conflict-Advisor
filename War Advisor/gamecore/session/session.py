"""
War Advisor - GameSession

Gestisce una partita dove l'obiettivo è conquistare il castello avversario.
Le armate sul campo possono lasciare guarnigioni per rallentare l'assalto e,
quando perdono uno scontro, si ritirano al proprio castello invece di sparire.
"""

from enum import Enum
from collections import Counter
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
            "message": (
                f"[Turno {self.game_map.turn}] PLAYER si riposiziona -> ({to_row},{to_col}) "
                f"[{terrain}] senza truppe: nessuna conquista o attacco"
            ),
        }

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

        strategic_targets = self.game_map.get_strategic_targets(
            entity=AI,
            army_vector=self.ai_army,
            terrain_modifiers=self.data["terrain"],
        )

        easy_target = self.ai_policy.choose_target(
            ai_pos=ai_pos,
            player_pos=player_pos,
            own_castle=own_castle,
            enemy_castle=enemy_castle,
            strategic_targets=strategic_targets,
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
            if dist_castle <= 4:
                return enemy_castle

        targets = strategic_targets

        if targets:
            _, best_cell     = targets[0]
            strat_pos        = (best_cell.row, best_cell.col)
            dist_strat       = abs(ai_pos[0] - strat_pos[0]) + abs(ai_pos[1] - strat_pos[1])

            if player_pos:
                dist_player = abs(ai_pos[0] - player_pos[0]) + abs(ai_pos[1] - player_pos[1])
                if dist_player <= 2 and dist_player <= dist_strat:
                    return player_pos

            return strat_pos

        # Nessun target strategico: carica il castello o il giocatore
        return enemy_castle or player_pos

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
                income = mine_count * MINE_YIELD_PER_ROUND
                self.grux_balance[entity] += income
                logs.append(
                    f"[Turno {self.game_map.turn}] ⛏ {entity.value.upper()} incassa {income} grux da {mine_count} miniere"
                )

        if not self.debug_ai_kill_switch:
            logs.extend(self._auto_manage_ai_economy())
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
        """Regola perdite condivisa: KO totale se in netto svantaggio, altrimenti perdite proporzionali."""
        if units_before <= 0:
            return 0

        if own_strength <= enemy_strength:
            return units_before

        pressure_ratio = min(1.0, enemy_strength / max(1.0, own_strength))
        loss_ratio = 0.08 + (0.42 * pressure_ratio) + (0.04 * fortification_level) + (0.03 * garrison_strength)
        loss_ratio = min(0.72, max(0.06, loss_ratio))

        losses = int(round(units_before * loss_ratio))
        if units_before > 1 and enemy_strength > 0:
            losses = max(1, losses)
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
        strategy_id = self.player_strategy_id if entity == PLAYER else self.ai_strategy_id
        strategy = next((s for s in self.data["strategies"] if s["id"] == strategy_id), None)
        if strategy is None:
            return 1.0

        distance = euclidean_distance(modified_vector, strategy["ideal_attributes"])
        compatibility = max(0.0, 1.0 - (distance / (8 ** 0.5)))

        # Armata ben organizzata può ribaltare differenze moderate,
        # ma non differenze schiaccianti di massa.
        return 0.82 + (compatibility * 0.46)

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
        ai_army_pos = self.game_map.positions.get(AI)

        best_cell = None
        best_score = float("-inf")
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != AI or cell.is_castle or cell.is_mine or cell.terrain == "Fiume":
                    continue
                if not ai_can_build_anywhere and ai_army_pos != (cell.row, cell.col):
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
            # Bonus forte se accumuli lo stesso tipo (effetto massa/specializzazione)
            stack_bonus = value * 0.34 * ((count - 1) ** 1.22) if count > 1 else 0.0
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
            "context_factor": round(context_factor, 4),
            "base_strength": round(base_strength, 4),
            "effective_strength": int(round(effective_strength)),
            "modified_vector": {k: round(v, 4) for k, v in modified.items()},
            "modifier_warnings": warnings,
        }

    def _retreat_to_castle(self, entity: Occupation) -> None:
        """Ritira un'armata al proprio castello, se ancora controllato."""
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

        self.game_map.positions[entity] = castle_pos
        castle_cell.occupation = entity

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

        if attacker_strength > defender_score:
            winner = attacker
            loser = defender
            if dest_cell is not None:
                dest_cell.garrison_strength = 0
                dest_cell.garrison_unit_ids = []
                dest_cell.fortification_level = 0
                dest_cell.occupation = attacker
            self.game_map.positions[attacker] = to_pos
            if dest_cell and dest_cell.is_castle:
                self.state = SessionState.GAME_OVER
                self.winner = attacker.value
        else:
            winner = defender
            loser = attacker
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
                "available_garrisons": self._available_garrisons(PLAYER),
                "grux_balance":  self.grux_balance[PLAYER],
                "army_cost":     self.player_army_cost,
                "available_mine_slots": self._available_mine_slots(PLAYER),
                "fortification_base_cost": self.base_fortification_cost,
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
                "army":          self.ai_army,
                "modified":      self.ai_modified,
                "troop_status":  self.ai_troop_status,
                "available_garrisons": self._available_garrisons(AI),
                "grux_balance":  self.grux_balance[AI],
                "army_cost":     self.ai_army_cost,
                "available_mine_slots": self._available_mine_slots(AI),
                "abilities": {
                    ability_id: state.to_dict(self.game_map.turn)
                    for ability_id, state in self.ability_states[AI].items()
                },
                "unit_costs":    {unit_id: self.unit_costs[unit_id] for unit_id in self.ai_units},
            },
            "map":        self.game_map.to_dict(),
            "battle_log": self.battle_log,
            "debug": {
                "ai_kill_switch_active": self.debug_ai_kill_switch,
                "kill_switch_notice": "DEBUG TEMPORANEO - rimuovere endpoint, flag e pulsante kill switch IA in produzione",
            },
        }
