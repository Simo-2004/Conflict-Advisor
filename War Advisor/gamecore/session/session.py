"""
War Advisor - GameSession

Gestisce una partita dove l'obiettivo è conquistare il castello avversario.
Le armate sul campo possono lasciare guarnigioni per rallentare l'assalto e,
quando perdono uno scontro, si ritirano al proprio castello invece di sparire.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from engine import aggregate_army, apply_modifiers
from gamecore.economy import MINE_YIELD_PER_ROUND, STARTING_GRUX, available_mine_slots, get_unit_costs
from gamecore.maps import GameMap, Occupation

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
    ) -> None:
        self.data = data
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
        self.battle_log: List[str]     = []
        self.available_garrisons: Dict[Occupation, int] = {
            PLAYER: max(2, len(self.player_units)),
            AI: max(2, len(self.ai_units)),
        }
        self.grux_balance: Dict[Occupation, int] = {
            PLAYER: player_budget,
            AI: ai_data.get("remaining_grux", STARTING_GRUX - self.ai_army_cost),
        }

    # ──────────────────────────────────────────────────────────
    # MOSSA GIOCATORE (entry-point principale)
    # ──────────────────────────────────────────────────────────

    def player_move(self, to_row: int, to_col: int, leave_garrison: bool = False) -> Dict[str, Any]:
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

        if leave_garrison and self.available_garrisons[PLAYER] <= 0:
            return {
                "ok": False,
                "message": "Non hai più distaccamenti disponibili da lasciare sul campo.",
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
            self.available_garrisons[PLAYER] -= 1

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
            if leave_garrison and self.available_garrisons[AI] <= 0:
                leave_garrison = False

            ai_move = self.game_map.move(AI, next_move, leave_garrison=leave_garrison)
            if leave_garrison and ai_move.get("leave_garrison"):
                self.available_garrisons[AI] -= 1

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

        # Priorita difensiva: se il player e vicino al castello IA, intercetta.
        if player_pos and own_castle:
            player_to_own_castle = abs(player_pos[0] - own_castle[0]) + abs(player_pos[1] - own_castle[1])
            if player_to_own_castle <= 3:
                return player_pos

        if enemy_castle:
            dist_castle = abs(ai_pos[0] - enemy_castle[0]) + abs(ai_pos[1] - enemy_castle[1])
            if dist_castle <= 4:
                return enemy_castle

        targets = self.game_map.get_strategic_targets(
            entity=AI,
            army_vector=self.ai_army,
            terrain_modifiers=self.data["terrain"],
        )

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
        if self.available_garrisons[AI] <= 1:
            return False

        if cell.is_castle:
            return cell.garrison_strength < 3

        if cell.is_strategic:
            return cell.garrison_strength < 1

        return False

    def _advance_round_economy(self) -> List[str]:
        """Accredita i grux delle miniere e fa gestire all'IA la propria economia."""
        logs: List[str] = []
        for entity in (PLAYER, AI):
            mine_count = self.game_map.count_mines(entity)
            if mine_count > 0:
                income = mine_count * MINE_YIELD_PER_ROUND
                self.grux_balance[entity] += income
                logs.append(
                    f"[Turno {self.game_map.turn}] ⛏ {entity.value.upper()} incassa {income} grux da {mine_count} miniere"
                )

        logs.extend(self._auto_manage_ai_economy())
        return logs

    def _auto_manage_ai_economy(self) -> List[str]:
        """L'IA piazza miniere disponibili e recluta automaticamente se può permetterselo."""
        logs: List[str] = []
        ai_slots = self._available_mine_slots(AI)
        while ai_slots > 0:
            placed = self._place_best_ai_mine()
            if not placed:
                break
            logs.append(placed)
            ai_slots -= 1

        affordable_units = [unit for unit in self.data["units"] if self.unit_costs[unit["id"]] <= self.grux_balance[AI]]
        if affordable_units:
            best_unit = max(
                affordable_units,
                key=lambda unit: self._effective_unit_value_for_ai(unit),
            )
            recruit_log = self._recruit_unit(AI, best_unit["id"], auto=True)
            if recruit_log:
                logs.append(recruit_log)

        return logs

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

    def _available_mine_slots(self, entity: Occupation) -> int:
        """Slot miniera disponibili in base alle celle controllate."""
        return available_mine_slots(
            controlled_cells=self.game_map.count_occupied(entity),
            existing_mines=self.game_map.count_mines(entity),
        )

    def place_mine(self, row: int, col: int) -> Dict[str, Any]:
        """Piazza una miniera del giocatore su una casella controllata."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")
        if self._available_mine_slots(PLAYER) <= 0:
            raise ValueError("Non hai slot miniera disponibili. Serve più territorio controllato.")

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

    def place_garrison_here(self) -> Dict[str, Any]:
        """Piazza immediatamente un presidio sulla casella corrente dell'armata player."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")
        if self.available_garrisons[PLAYER] <= 0:
            raise ValueError("Non hai più guarnigioni disponibili.")

        player_pos = self.game_map.positions.get(PLAYER)
        if player_pos is None:
            raise ValueError("Posizione PLAYER non disponibile.")

        cell = self.game_map.get_cell(*player_pos)
        if cell is None or cell.occupation != PLAYER:
            raise ValueError("La cella corrente non è controllata dal PLAYER.")

        cell.garrison_strength += 1
        self.available_garrisons[PLAYER] -= 1

        row, col = player_pos
        log_entry = f"[Turno {self.game_map.turn}] 🛡 PLAYER piazza un presidio su ({row},{col})"
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "cell": cell.to_dict(),
            "state": self.state.value,
            "map": self.game_map.to_dict(),
        }

    def _place_best_ai_mine(self) -> Optional[str]:
        """L'IA piazza una miniera sulla miglior cella controllata disponibile."""
        best_cell = None
        best_score = float("-inf")
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != AI or cell.is_castle or cell.is_mine or cell.terrain == "Fiume":
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
        if unit_id not in self.unit_costs:
            raise ValueError(f"Unità sconosciuta: {unit_id}")

        cost = self.unit_costs[unit_id]
        if self.grux_balance[entity] < cost:
            if auto:
                return None
            raise ValueError(f"Grux insufficienti: servono {cost}, disponibili {self.grux_balance[entity]}")

        self.grux_balance[entity] -= cost

        if entity == PLAYER:
            self.player_units.append(unit_id)
            self.available_garrisons[PLAYER] += 1
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
            self.available_garrisons[AI] += 1
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
        log_entry = f"[Turno {self.game_map.turn}] 💰 {side} recluta {unit_id} per {cost} grux"
        self.battle_log.append(log_entry)
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
        army_vector = self.player_army if entity == PLAYER else self.ai_army
        troop_status = self.player_troop_status if entity == PLAYER else self.ai_troop_status
        modified, _ = apply_modifiers(
            army_vector=army_vector,
            terrain_name=terrain,
            weather_name=self.weather,
            troop_status_name=troop_status,
            modifiers_data=self.data,
        )
        detached = self.game_map.count_garrisons(entity) - 2
        detach_penalty = max(0.7, 1.0 - (max(0, detached) * 0.06))
        return sum(modified.values()) * detach_penalty

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

        attacker_strength = self._effective_army_strength(attacker, terrain)
        defender_strength = self._effective_army_strength(defender, terrain)

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
            contested_cell.occupation = winner

        self.game_map.positions[winner] = to_pos
        self._retreat_to_castle(loser)

        enemy_castle = self.game_map.get_castle_position(defender)
        if enemy_castle == to_pos and winner == attacker:
            self.state = SessionState.GAME_OVER
            self.winner = attacker.value

        battle_label = "⚔ Battaglia campale"
        if enemy_castle == to_pos:
            battle_label = "🏰 Assalto al castello centrale"

        log_entry = (
            f"[Turno {self.game_map.turn}] {battle_label} su {terrain}: "
            f"{attacker.value.upper()} {attacker_strength:.3f} vs {defender.value.upper()} {defender_strength:.3f} "
            f"→ Ritirata di {loser.value.upper()}"
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

    def _resolve_static_defense(self, move_result: Dict[str, Any], attacker: Occupation) -> Dict[str, Any]:
        """Risoluzione di guarnigioni e castelli."""
        defender = attacker.opposite()
        terrain = move_result["terrain"]
        to_pos = tuple(move_result["to_pos"])
        dest_cell = self.game_map.get_cell(*to_pos)
        encounter_type = move_result["encounter_type"]

        attacker_strength = self._effective_army_strength(attacker, terrain)
        garrison_strength = dest_cell.garrison_strength if dest_cell else 0
        terrain_bonus = 0.25 if terrain in {"Foresta", "Montagna", "Palude"} else 0.0
        castle_bonus = 1.35 if dest_cell and dest_cell.is_castle else 0.0
        defender_score = (garrison_strength * 1.15) + terrain_bonus + castle_bonus

        if attacker_strength > defender_score:
            winner = attacker
            loser = defender
            if dest_cell is not None:
                dest_cell.garrison_strength = 0
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

        if encounter_type == "castle":
            label = "🏰 Assalto al castello centrale"
        elif dest_cell is not None and dest_cell.is_mine:
            label = "⛏ Battaglia per la conquista della miniera"
        elif encounter_type == "garrison":
            label = "🛡 Scontro contro presidio territoriale"
        else:
            label = "⚔ Scontro territoriale"

        log_entry = (
            f"[Turno {self.game_map.turn}] {label} su {terrain}: "
            f"{attacker.value.upper()} {attacker_strength:.3f} vs difesa {defender_score:.3f} "
            f"→ Vince {winner.value.upper()}"
        )
        self.battle_log.append(log_entry)

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
                "army":          self.player_army,
                "modified":      self.player_modified,
                "troop_status":  self.player_troop_status,
                "available_garrisons": self.available_garrisons[PLAYER],
                "grux_balance":  self.grux_balance[PLAYER],
                "army_cost":     self.player_army_cost,
                "available_mine_slots": self._available_mine_slots(PLAYER),
                "unit_costs":    {unit_id: self.unit_costs[unit_id] for unit_id in self.player_units},
            },
            "ai": {
                "units":         self.ai_units,
                "strategy_id":   self.ai_strategy_id,
                "strategy_name": self.ai_strategy_name,
                "army":          self.ai_army,
                "modified":      self.ai_modified,
                "troop_status":  self.ai_troop_status,
                "available_garrisons": self.available_garrisons[AI],
                "grux_balance":  self.grux_balance[AI],
                "army_cost":     self.ai_army_cost,
                "available_mine_slots": self._available_mine_slots(AI),
                "unit_costs":    {unit_id: self.unit_costs[unit_id] for unit_id in self.ai_units},
            },
            "map":        self.game_map.to_dict(),
            "battle_log": self.battle_log,
        }
