"""
War Advisor - Debug API (SGANCIABILE)

Router FastAPI con le utility di testing rapido. Tutte le rotte vivono
sotto /game/debug/ e agiscono sulla sessione dall'esterno: il motore non
espone nulla apposta per loro, così togliere il modulo non lascia metodi
orfani in giro.

Rimozione: vedi README.md in questa cartella.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from gamecore.maps import Occupation
from gamecore.session import weather_cycle as wc

PLAYER = Occupation.PLAYER
AI = Occupation.AI


# ── Modelli richiesta ──────────────────────────────────────────────

class EntityScoped(BaseModel):
    entity: str = Field("player", description="'player' oppure 'ai'")


class GruxRequest(EntityScoped):
    amount: int = Field(..., description="Grux da aggiungere (negativo per togliere)")


class UnitsRequest(EntityScoped):
    unit_id: str = Field(..., description="ID unità da aggiungere alla riserva")
    count: int = Field(1, ge=1, le=200, description="Quante unità")


class CastleHpRequest(EntityScoped):
    hp: int = Field(..., ge=0, description="HP castello da impostare")


class SkipTurnsRequest(BaseModel):
    count: int = Field(1, ge=1, le=200, description="Turni da eseguire di fila")


class TerritoryRequest(EntityScoped):
    cells: int = Field(8, ge=1, le=224, description="Quante celle assegnare")


class OutcomeRequest(BaseModel):
    winner: str = Field(..., description="'player' oppure 'ai'")


class WeatherRequest(BaseModel):
    cycle: Optional[str] = Field(None, description="'Giorno' o 'Notte' (assente = lascia com'è)")
    weather: Optional[str] = Field(None, description="'Sereno', 'Pioggia' o 'Nebbia' (assente = lascia com'è)")
    freeze: Optional[bool] = Field(None, description="True blocca l'orologio, False lo fa ripartire")


# ── Helper ─────────────────────────────────────────────────────────

def _entity_from(value: str) -> Occupation:
    normalized = (value or "").strip().lower()
    if normalized in ("player", "giocatore"):
        return PLAYER
    if normalized in ("ai", "ia"):
        return AI
    raise HTTPException(status_code=400, detail=f"Entità non valida: {value!r} (usa 'player' o 'ai').")


def _reserve_of(session: Any, entity: Occupation) -> List[str]:
    return session.player_units if entity == PLAYER else session.ai_units


# ── Meteo: blocco dell'orologio e forzatura delle condizioni ───────
# Il blocco è una sostituzione a caldo di `_advance_weather` sull'ISTANZA:
# la sessione non espone nessun interruttore e non deve farlo. Lo sblocco
# cancella l'attributo dall'istanza, così torna a valere il metodo della
# classe e non resta traccia del passaggio del modulo.
FROZEN_FLAG = "_debug_weather_frozen"
FROZEN_METHOD = "_advance_weather"


def _weather_frozen(session: Any) -> bool:
    return bool(getattr(session, FROZEN_FLAG, False))


def _set_weather_frozen(session: Any, frozen: bool) -> None:
    if frozen:
        session.__dict__[FROZEN_METHOD] = lambda logs: None
        session.__dict__[FROZEN_FLAG] = True
    else:
        session.__dict__.pop(FROZEN_METHOD, None)
        session.__dict__.pop(FROZEN_FLAG, None)


def _weather_payload(session: Any) -> Dict[str, Any]:
    """Stato meteo completo per i controlli del pannello."""
    state = session.weather_state()
    return {
        "cycle": session.day_cycle,
        "weather": session.weather_base,
        "key": session.weather,
        "label": state.get("label"),
        "emoji": state.get("emoji"),
        "changes_in": state.get("changes_in", 0),
        "frozen": _weather_frozen(session),
        "cycles": list(wc.CYCLES),
        "weathers": list(wc.WEATHERS),
        "unit_effects": state.get("unit_effects", []),
    }


def build_debug_router(get_session: Callable[[], Any]) -> APIRouter:
    """Costruisce il router.

    `get_session` è una callable che restituisce la sessione attiva: il
    modulo non importa nulla da main.py, così la dipendenza resta a senso
    unico e si può cancellare senza rompere il server.
    """
    router = APIRouter(prefix="/game/debug", tags=["debug"])

    def session_or_404() -> Any:
        session = get_session()
        if session is None:
            raise HTTPException(status_code=400, detail="Nessuna partita attiva.")
        return session

    def ok(session: Any, message: str, **extra: Any) -> Dict[str, Any]:
        session.battle_log.append(f"[Turno {session.game_map.turn}] 🧪 DEBUG: {message}")
        payload = {
            "ok": True,
            "message": message,
            "state": session.state.value,
            "session": session.to_dict(),
        }
        payload.update(extra)
        return payload

    # ── Kill switch IA ─────────────────────────────────────────────
    @router.post("/ai-kill-switch")
    async def ai_kill_switch() -> Dict[str, Any]:
        """Congela o riattiva l'IA. Con lo switch attivo non muove, non
        costruisce e non recluta."""
        session = session_or_404()
        try:
            return session.toggle_debug_ai_kill_switch()
        except Exception as exc:                                  # pragma: no cover
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Economia ───────────────────────────────────────────────────
    @router.post("/grant-grux")
    async def grant_grux(request: GruxRequest) -> Dict[str, Any]:
        session = session_or_404()
        entity = _entity_from(request.entity)
        session.grux_balance[entity] = max(0, session.grux_balance.get(entity, 0) + request.amount)
        return ok(
            session,
            f"{entity.value.upper()} → {request.amount:+} grux "
            f"(saldo {session.grux_balance[entity]})",
            balance=session.grux_balance[entity],
        )

    # ── Truppe ─────────────────────────────────────────────────────
    @router.post("/grant-units")
    async def grant_units(request: UnitsRequest) -> Dict[str, Any]:
        session = session_or_404()
        entity = _entity_from(request.entity)
        if request.unit_id not in session.units_map:
            raise HTTPException(status_code=400, detail=f"Unità sconosciuta: {request.unit_id}")

        _reserve_of(session, entity).extend([request.unit_id] * request.count)
        session._recompute_entity_army_state(entity)
        if entity == AI:
            # L'IA tiene le legioni allineate alla riserva: senza questo le
            # truppe regalate resterebbero ferme in riserva. Prima del primo
            # turno le legioni non esistono ancora, quindi vanno create qui,
            # altrimenti il rinforzo non arriva mai in campo.
            session._ensure_ai_legions_initialized()
            session._sync_ai_legion_units()

        name = session.units_map.get(request.unit_id, {}).get("name", request.unit_id)
        return ok(
            session,
            f"{entity.value.upper()} → +{request.count} {name} "
            f"(riserva {len(_reserve_of(session, entity))})",
            reserve_size=len(_reserve_of(session, entity)),
        )

    @router.post("/clear-units")
    async def clear_units(request: EntityScoped) -> Dict[str, Any]:
        session = session_or_404()
        entity = _entity_from(request.entity)
        removed = len(_reserve_of(session, entity))
        _reserve_of(session, entity).clear()
        session._recompute_entity_army_state(entity)
        if entity == AI:
            session._sync_ai_legion_units()
        return ok(session, f"{entity.value.upper()} → riserva svuotata ({removed} unità rimosse)")

    # ── Castelli ───────────────────────────────────────────────────
    @router.post("/set-castle-hp")
    async def set_castle_hp(request: CastleHpRequest) -> Dict[str, Any]:
        session = session_or_404()
        entity = _entity_from(request.entity)
        maximum = session.castle_hp_max.get(entity, request.hp)
        session.castle_hp[entity] = min(request.hp, maximum)
        return ok(
            session,
            f"castello {entity.value.upper()} → {session.castle_hp[entity]}/{maximum} HP",
            castle_hp=session.castle_hp[entity],
        )

    # ── Territorio ─────────────────────────────────────────────────
    @router.post("/grant-territory")
    async def grant_territory(request: TerritoryRequest) -> Dict[str, Any]:
        """Assegna le celle neutre più vicine al castello: sblocca in fretta
        slot miniera e costruzioni senza dover marciare."""
        session = session_or_404()
        entity = _entity_from(request.entity)
        castle = session.game_map.castle_positions.get(entity)
        if castle is None:
            raise HTTPException(status_code=400, detail="Castello non trovato.")

        candidates = [
            cell
            for row in session.game_map.grid
            for cell in row
            if cell.occupation == Occupation.NEUTRAL and not cell.is_castle
        ]
        candidates.sort(key=lambda c: abs(c.row - castle[0]) + abs(c.col - castle[1]))

        assigned = 0
        for cell in candidates[: request.cells]:
            cell.occupation = entity
            assigned += 1
        return ok(session, f"{entity.value.upper()} → +{assigned} celle controllate", cells=assigned)

    # ── Abilità ────────────────────────────────────────────────────
    @router.post("/unlock-abilities")
    async def unlock_abilities(request: EntityScoped) -> Dict[str, Any]:
        """Completa istantaneamente le ricerche: le abilità risultano
        sbloccate retrodatando il turno di inizio."""
        session = session_or_404()
        entity = _entity_from(request.entity)
        states = session.ability_states.get(entity, {})
        for state in states.values():
            state.started_turn = session.game_map.turn - state.turns_required
        return ok(session, f"{entity.value.upper()} → tutte le abilità sbloccate", unlocked=len(states))

    # ── Movimento ──────────────────────────────────────────────────
    @router.post("/clear-movement-blocks")
    async def clear_movement_blocks() -> Dict[str, Any]:
        """Azzera i turni di marcia residui: le legioni ripartono subito."""
        session = session_or_404()
        cleared = 0
        for entity, legions in ((PLAYER, session.player_legions), (AI, session.ai_legions)):
            for legion_id in list(legions):
                key = session._legion_movement_key(entity, legion_id)
                state = session.movement_system._legion_state(key)
                if state.blocked_turns or state.display_blocked_turns:
                    state.blocked_turns = 0
                    state.display_blocked_turns = 0
                    cleared += 1
        return ok(session, f"marce sbloccate su {cleared} legioni", cleared=cleared)

    # ── Turni ──────────────────────────────────────────────────────
    @router.post("/skip-turns")
    async def skip_turns(request: SkipTurnsRequest) -> Dict[str, Any]:
        session = session_or_404()
        executed = 0
        for _ in range(request.count):
            if session.state.value != "active":
                break
            session.execute_turn()
            executed += 1
        return ok(session, f"eseguiti {executed} turni di fila", executed=executed)

    # ── Meteo ──────────────────────────────────────────────────────
    @router.post("/weather")
    async def set_weather(request: WeatherRequest) -> Dict[str, Any]:
        """Impone le condizioni e/o blocca l'orologio del meteo.

        Con l'orologio bloccato le condizioni non cambiano più da sole, nemmeno
        saltando decine di turni: serve a provare a mano lo stesso scenario.
        """
        session = session_or_404()

        cycle = request.cycle or session.day_cycle
        weather = request.weather or session.weather_base
        if cycle not in wc.CYCLES:
            raise HTTPException(status_code=400, detail=f"Ciclo non valido: {cycle!r} (usa {list(wc.CYCLES)}).")
        if weather not in wc.WEATHERS:
            raise HTTPException(status_code=400, detail=f"Meteo non valido: {weather!r} (usa {list(wc.WEATHERS)}).")

        changed = (cycle != session.day_cycle) or (weather != session.weather_base)
        session.day_cycle = cycle
        session.weather_base = weather
        session._refresh_weather_key()

        if request.freeze is not None:
            _set_weather_frozen(session, request.freeze)

        if changed and not _weather_frozen(session):
            # Contatore rimesso a un intervallo pieno: senza, la condizione
            # appena imposta poteva cambiare al turno successivo.
            session.turns_to_weather_change = wc.next_change_delay(session.weather_rng)

        parts = [f"condizioni → {session.weather}"]
        if request.freeze is not None:
            parts.append("orologio bloccato" if request.freeze else "orologio riavviato")
        return ok(session, " · ".join(parts), weather=_weather_payload(session))

    @router.get("/weather")
    async def get_weather() -> Dict[str, Any]:
        """Condizioni correnti, stato del blocco e opzioni disponibili."""
        return _weather_payload(session_or_404())

    # ── Fine partita ───────────────────────────────────────────────
    @router.post("/force-outcome")
    async def force_outcome(request: OutcomeRequest) -> Dict[str, Any]:
        """Chiude la partita azzerando il castello del perdente."""
        session = session_or_404()
        winner = _entity_from(request.winner)
        loser = winner.opposite()
        session.castle_hp[loser] = 0
        castle_pos = session.game_map.castle_positions.get(loser)
        if castle_pos is not None:
            cell = session.game_map.get_cell(*castle_pos)
            if cell is not None:
                cell.occupation = winner
        session.state = type(session.state).GAME_OVER
        session.winner = winner.value
        return ok(session, f"partita forzata: vince {winner.value.upper()}")

    # ── Ispezione ──────────────────────────────────────────────────
    @router.get("/snapshot")
    async def snapshot() -> Dict[str, Any]:
        """Riassunto compatto per capire al volo com'è messa la partita."""
        session = session_or_404()

        def side(entity: Occupation, legions: Dict[str, Any], reserve: List[str]) -> Dict[str, Any]:
            controlled = sum(
                1
                for row in session.game_map.grid
                for cell in row
                if cell.occupation == entity
            )
            return {
                "grux": session.grux_balance.get(entity, 0),
                "reserve": len(reserve),
                "legions": [
                    {
                        "name": legion.get("name"),
                        "units": len(legion.get("units", [])),
                        "pos": list(legion.get("pos", ())),
                        "type": legion.get("legion_type"),
                    }
                    for legion in legions.values()
                ],
                "castle_hp": session.castle_hp.get(entity, 0),
                "castle_hp_max": session.castle_hp_max.get(entity, 0),
                "cells": controlled,
            }

        return {
            "turn": session.game_map.turn,
            "state": session.state.value,
            "winner": session.winner,
            "ai_kill_switch": bool(getattr(session, "debug_ai_kill_switch", False)),
            "ai_difficulty": getattr(session, "ai_difficulty", None),
            "weather": _weather_payload(session),
            "player": side(PLAYER, session.player_legions, session.player_units),
            "ai": side(AI, session.ai_legions, session.ai_units),
        }

    return router
