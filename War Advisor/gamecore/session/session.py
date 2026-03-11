"""
War Advisor - GameSession

Gestisce l'intera sessione di gioco a turni:
  - Dati eserciti giocatore e IA
  - Mappa di gioco (GameMap)
  - Avanzamento dei turni
  - Risoluzione delle battaglie tramite confronto di forza vettoriale

Flusso di una partita:
  1. Il giocatore conferma strategia + unità → crea GameSession
  2. Il giocatore chiama player_move(row, col) a ogni turno
  3. Dopo ogni mossa del giocatore, l'IA si muove automaticamente
  4. Se due eserciti si incontrano, scatta _resolve_battle()
  5. Il perdente viene eliminato dalla mappa → is_game_over() → GAME_OVER
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from engine import apply_modifiers
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
        # AI (output di ai_builder.build_ai_army)
        ai_data: Dict[str, Any],
        # Ambiente
        weather: Optional[str],
        # Dati engine
        data: Dict[str, Any],
        # Mappa
        map_seed: Optional[int] = None,
    ) -> None:
        self.data = data

        # --- Giocatore ---
        self.player_units         = player_units
        self.player_strategy_id   = player_strategy_id
        self.player_army          = player_army
        self.player_modified      = player_modified
        self.player_troop_status  = player_troop_status

        # --- IA ---
        self.ai_units         = ai_data["units"]
        self.ai_strategy_id   = ai_data["strategy"]["id"]
        self.ai_strategy_name = ai_data["strategy"]["name"]
        self.ai_army          = ai_data["army_vector"]
        self.ai_modified      = ai_data["modified_vector"]
        self.ai_troop_status  = ai_data["troop_status"]

        # --- Ambiente ---
        self.weather = weather

        # --- Mappa ---
        self.game_map: GameMap = GameMap(seed=map_seed)

        # --- Stato ---
        self.state:      SessionState  = SessionState.ACTIVE
        self.winner:     Optional[str] = None
        self.battle_log: List[str]     = []

    # ──────────────────────────────────────────────────────────
    # MOSSA GIOCATORE (entry-point principale)
    # ──────────────────────────────────────────────────────────

    def player_move(self, to_row: int, to_col: int) -> Dict[str, Any]:
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

        move_result = self.game_map.move(PLAYER, (to_row, to_col))
        if not move_result["ok"]:
            return {
                "ok": False,
                "message": move_result["message"],
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        battle_result: Optional[Dict] = None
        if move_result["battle"]:
            battle_result = self._resolve_battle(
                terrain=move_result["terrain"],
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

            ai_move = self.game_map.move(AI, next_move)
            result["ok"]      = ai_move.get("ok", False)
            result["message"] = ai_move.get("message", "")

            if ai_move.get("battle"):
                result["battle_result"] = self._resolve_battle(
                    terrain=ai_move["terrain"],
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
          - Priorità alle celle strategiche (ordinate per punteggio del suo esercito).
          - Se il giocatore è entro 2 passi e più vicino del target strategico,
            attacca direttamente.
          - Se non ci sono target strategici, avanza verso il giocatore.
        """
        player_pos = self.game_map.positions.get(PLAYER)

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

        # Nessun target strategico: carica il giocatore
        return player_pos

    # ──────────────────────────────────────────────────────────
    # RISOLUZIONE BATTAGLIA (privato)
    # ──────────────────────────────────────────────────────────

    def _resolve_battle(
        self,
        terrain: str,
        attacker: Occupation,
    ) -> Dict[str, Any]:
        """
        Risolve uno scontro.

        Meccanismo:
          1. Applica i modificatori del terreno di battaglia (+ meteo) ai vettori
             grezzi di entrambi gli eserciti.
          2. Forza = somma degli 8 attributi modificati.
          3. Vince il più forte; in caso di parità vince il difensore.
          4. Il perdente viene eliminato dalla mappa.
          5. Aggiorna self.state / self.winner se la partita è finita.

        Returns:
            dict con: attacker, defender, player_strength, ai_strength,
                      winner, loser, terrain, log
        """
        defender = attacker.opposite()

        player_mod, _ = apply_modifiers(
            army_vector=self.player_army,
            terrain_name=terrain,
            weather_name=self.weather,
            troop_status_name=self.player_troop_status,
            modifiers_data=self.data,
        )
        ai_mod, _ = apply_modifiers(
            army_vector=self.ai_army,
            terrain_name=terrain,
            weather_name=self.weather,
            troop_status_name=self.ai_troop_status,
            modifiers_data=self.data,
        )

        player_strength = sum(player_mod.values())
        ai_strength     = sum(ai_mod.values())

        if player_strength > ai_strength:
            winner = PLAYER
            loser  = AI
        elif ai_strength > player_strength:
            winner = AI
            loser  = PLAYER
        else:
            # Parità → vince il difensore
            winner = defender
            loser  = attacker

        log_entry = (
            f"[Turno {self.game_map.turn}] ⚔ Battaglia su {terrain}: "
            f"PLAYER {player_strength:.3f} vs AI {ai_strength:.3f} "
            f"→ Vince {winner.value.upper()}"
        )
        self.battle_log.append(log_entry)

        # Elimina il perdente
        self.game_map.eliminate(loser)

        # Controlla game over
        game_over_winner = self.game_map.is_game_over()
        if game_over_winner:
            self.state  = SessionState.GAME_OVER
            self.winner = game_over_winner.value

        return {
            "attacker":        attacker.value,
            "defender":        defender.value,
            "player_strength": round(player_strength, 3),
            "ai_strength":     round(ai_strength, 3),
            "terrain":         terrain,
            "winner":          winner.value,
            "loser":           loser.value,
            "log":             log_entry,
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
            },
            "ai": {
                "units":         self.ai_units,
                "strategy_id":   self.ai_strategy_id,
                "strategy_name": self.ai_strategy_name,
                "army":          self.ai_army,
                "modified":      self.ai_modified,
                "troop_status":  self.ai_troop_status,
            },
            "map":        self.game_map.to_dict(),
            "battle_log": self.battle_log,
        }
