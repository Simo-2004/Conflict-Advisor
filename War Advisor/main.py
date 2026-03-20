"""
War Advisor - FastAPI Backend
API per il sistema di raccomandazione strategica per wargame
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field
import os
import sys
from typing import List, Dict, Any, Optional

from engine import (
    load_data,
    aggregate_army,
    apply_modifiers,
    compute_ranking,
    get_available_units,
    get_available_terrains,
    get_available_weather,
    get_available_troop_status
)

from gamecore.session import GameSession, SessionState
from gamecore.gameflow import start_game_session
from gamecore.economy import STARTING_GRUX, calculate_army_cost, get_unit_costs

if getattr(sys, 'frozen', False):
    APP_BASE_DIR = sys._MEIPASS
else:
    APP_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FRONTEND_DIR = os.path.join(APP_BASE_DIR, "frontend")

# Inizializza FastAPI
app = FastAPI(
    title="War Advisor API",
    description="Sistema di raccomandazione strategica per wargame",
    version="1.0.0"
)

# CORS - Consenti richieste dal frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Monta la cartella statica per il frontend
app.mount("/static", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")

# Carica i dati all'avvio
try:
    DATA = load_data()
except Exception as e:
    raise RuntimeError(f"Errore nel caricamento dei dati: {e}")

UNIT_COSTS = get_unit_costs(DATA["units"])

# Sessione di gioco attiva (una sola partita alla volta)
_active_session: Optional[GameSession] = None


# ==================== MODELLI PYDANTIC ====================

class ConfigResponse(BaseModel):
    """Risposta per l'endpoint GET /config"""
    units: List[Dict[str, Any]] = Field(..., description="Lista di unità disponibili")
    strategies: List[Dict[str, Any]] = Field(..., description="Lista di strategie disponibili")
    terrains: List[Dict[str, Any]] = Field(..., description="Lista di terreni disponibili")
    weather: List[Dict[str, Any]] = Field(..., description="Lista di condizioni meteo disponibili")
    troop_status: List[Dict[str, Any]] = Field(..., description="Lista di stati truppe disponibili")


class CalculateRequest(BaseModel):
    """Richiesta per l'endpoint POST /calculate"""
    units: List[str] = Field(..., description="Lista di ID unità selezionate", min_items=1)
    terrain: str = Field(..., description="Nome del terreno")
    weather: Optional[str] = Field(None, description="Nome della condizione meteo")
    troop_status: Optional[str] = Field(None, description="Stato delle truppe")


class StrategyResult(BaseModel):
    """Risultato di una strategia nel ranking"""
    id: str
    name: str
    description: str
    distance: float
    compatibility: float
    ideal_attributes: Dict[str, float]


class CalculateResponse(BaseModel):
    """Risposta per l'endpoint POST /calculate"""
    army_profile: Dict[str, float] = Field(..., description="Vettore dell'esercito originale")
    modified_profile: Dict[str, float] = Field(..., description="Vettore dell'esercito modificato dai modificatori")
    terrain_id: str
    terrain_name: str
    weather_name: Optional[str] = Field(None, description="Condizione meteo applicata")
    troop_status_name: Optional[str] = Field(None, description="Stato truppe applicato")
    budget_grux: int = Field(..., description="Budget iniziale disponibile")
    selected_units_cost: int = Field(..., description="Costo totale delle unità selezionate")
    remaining_grux: int = Field(..., description="Bilancio residuo in grux")
    critical_warnings: List[str] = Field(default_factory=list, description="Warning per attributi CRITICAL non soddisfatti")
    ranking: List[StrategyResult] = Field(..., description="Ranking delle strategie (da migliore a peggiore)")
    top_strategy: StrategyResult = Field(..., description="Strategia consigliata (migliore)")


# ==================== ENDPOINT ====================

@app.get("/config", response_model=ConfigResponse)
async def get_config():
    """
    Endpoint GET /config
    Ritorna le liste di unità, terreni, meteo e stati truppe disponibili per popolare i dropdown del frontend.
    """
    try:
        units_by_id = {unit["id"]: unit for unit in DATA["units"]}
        units = [
            {
                **unit,
                "attributes": units_by_id.get(unit["id"], {}).get("attributes", unit.get("attributes", {})),
                "cost_grux": UNIT_COSTS[unit["id"]],
            }
            for unit in get_available_units(DATA)
        ]
        terrains = get_available_terrains(DATA)
        strategies = [
            {
                "id": strategy["id"],
                "name": strategy["name"],
                "description": strategy["description"],
            }
            for strategy in DATA["strategies"]
        ]
        weather = get_available_weather(DATA)
        troop_status = get_available_troop_status(DATA)
        return ConfigResponse(
            units=units,
            strategies=strategies,
            terrains=terrains,
            weather=weather,
            troop_status=troop_status
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/calculate", response_model=CalculateResponse)
async def calculate(request: CalculateRequest):
    """
    Endpoint POST /calculate
    Calcola il profilo dell'esercito e ritorna il ranking delle strategie.
    
    Input:
    - units: Lista di ID unità selezionate
    - terrain: Nome del terreno
    - weather: (Opzionale) Nome della condizione meteo
    - troop_status: (Opzionale) Stato delle truppe
    
    Output:
    - Profilo esercito originale
    - Profilo esercito modificato dai modificatori
    - Ranking completo delle strategie
    - Strategia consigliata (top 1)
    """
    try:
        # Valida l'input
        if not request.units:
            raise ValueError("Deve essere selezionata almeno un'unità")

        selected_units_cost = calculate_army_cost(request.units, UNIT_COSTS)
        if selected_units_cost > STARTING_GRUX:
            raise ValueError(
                f"Esercito troppo costoso: {selected_units_cost} grux su {STARTING_GRUX} disponibili"
            )
        
        # Calcola il vettore dell'esercito originale
        army_profile = aggregate_army(request.units, DATA["units"])
        
        # Applica i modificatori (terreno, meteo, stato truppe)
        modified_profile, critical_warnings = apply_modifiers(
            army_vector=army_profile,
            terrain_name=request.terrain,
            weather_name=request.weather,
            troop_status_name=request.troop_status,
            modifiers_data=DATA
        )
        
        # Calcola il ranking delle strategie (con affinità bidirezionali)
        ranking_data = compute_ranking(
            army_vector=modified_profile,
            strategies_list=DATA["strategies"],
            unit_ids=request.units,
            terrain_name=request.terrain,
            weather_name=request.weather,
            affinities_data=DATA.get("unit_affinities", {})
        )
        
        # Prepara il ranking come lista di StrategyResult
        ranking = [
            StrategyResult(
                id=s["id"],
                name=s["name"],
                description=s["description"],
                distance=s["distance"],
                compatibility=s["compatibility"],
                ideal_attributes=s["ideal_attributes"]
            )
            for s in ranking_data
        ]
        
        # Top strategy (migliore)
        top_strategy = ranking[0] if ranking else None
        
        return CalculateResponse(
            army_profile=army_profile,
            modified_profile=modified_profile,
            terrain_id=request.terrain.lower().replace(" ", "_"),
            terrain_name=request.terrain,
            weather_name=request.weather,
            troop_status_name=request.troop_status,
            budget_grux=STARTING_GRUX,
            selected_units_cost=selected_units_cost,
            remaining_grux=STARTING_GRUX - selected_units_cost,
            critical_warnings=critical_warnings,
            ranking=ranking,
            top_strategy=top_strategy
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== MODELLI PYDANTIC — GIOCO ====================

class ConfirmRequest(BaseModel):
    """Richiesta POST /game/confirm — il giocatore ha scelto la sua strategia."""
    units: List[str]             = Field(..., description="ID unità del giocatore", min_items=1)
    terrain: str                 = Field(..., description="Terreno scelto")
    weather: Optional[str]       = Field(None, description="Condizione meteo")
    troop_status: Optional[str]  = Field(None, description="Stato truppe del giocatore")
    strategy_id: str             = Field(..., description="ID strategia confermata dal giocatore")
    army_profile: Dict[str, float]      = Field(..., description="Vettore esercito grezzo (da /calculate)")
    modified_profile: Dict[str, float]  = Field(..., description="Vettore esercito modificato (da /calculate)")
    map_seed: Optional[int]      = Field(None, description="Seed opzionale per la mappa (None = casuale)")


class MoveRequest(BaseModel):
    """Richiesta POST /game/move — il giocatore si sposta di una casella."""
    to_row: int = Field(..., description="Riga di destinazione")
    to_col: int = Field(..., description="Colonna di destinazione")
    leave_garrison: bool = Field(False, description="Se True lascia un distaccamento sulla casella di partenza")
    garrison_unit_id: Optional[str] = Field(None, description="ID unità da distaccare nel presidio")


class GarrisonRequest(BaseModel):
    """Richiesta per piazzare presidio con scelta unità."""
    unit_id: Optional[str] = Field(None, description="ID unità da distaccare")


class MineRequest(BaseModel):
    """Richiesta per piazzare una miniera."""
    row: int = Field(..., description="Riga della cella")
    col: int = Field(..., description="Colonna della cella")


class RecruitRequest(BaseModel):
    """Richiesta per reclutare una unità."""
    unit_id: str = Field(..., description="ID unità da comprare")


class StrategyChangeRequest(BaseModel):
    """Richiesta per cambiare strategia del player durante la battaglia."""
    strategy_id: str = Field(..., description="ID strategia da impostare")


class AIDifficultyRequest(BaseModel):
    """Richiesta per cambiare la difficoltà runtime dell'IA."""
    difficulty: str = Field(..., description="ID difficoltà IA (es: easy, normal)")


class AbilityResearchRequest(BaseModel):
    """Richiesta per avviare ricerca di una abilità specifica."""
    ability_id: str = Field(..., description="ID abilità da ricercare")


# ==================== ENDPOINT GIOCO ====================

@app.post("/game/confirm")
async def game_confirm(request: ConfirmRequest):
    """
    POST /game/confirm

    Chiamato quando il giocatore ha confermato la sua strategia nel frontend.

    Azioni:
      1. Valida il terreno.
      2. Costruisce l'esercito dell'IA (ai_builder) in base alle condizioni di partenza.
      3. Crea la GameSession con mappa procedurale.
      4. Ritorna lo stato iniziale della partita (mappa + info eserciti).
    """
    global _active_session

    try:
        started = start_game_session(
            data=DATA,
            player_units=request.units,
            terrain=request.terrain,
            weather=request.weather,
            troop_status=request.troop_status,
            strategy_id=request.strategy_id,
            army_profile=request.army_profile,
            modified_profile=request.modified_profile,
            map_seed=request.map_seed,
        )

        _active_session = started["session"]
        session_dict = _active_session.to_dict()
        session_dict["message"] = started["message"]
        return session_dict

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/game/move")
async def game_move(request: MoveRequest):
    """
    POST /game/move

    Il giocatore si sposta nella cella adiacente (to_row, to_col).

    Dopo la mossa del giocatore:
      - Se c'è scontro, viene risolto immediatamente.
      - L'IA esegue automaticamente la sua mossa.
      - Ritorna il nuovo stato completo della partita.
    """
    if _active_session is None:
        raise HTTPException(status_code=400, detail="Nessuna partita attiva. Prima chiama POST /game/confirm.")

    try:
        result = _active_session.player_move(
            request.to_row,
            request.to_col,
            leave_garrison=request.leave_garrison,
            garrison_unit_id=request.garrison_unit_id,
        )
        if not result.get("ok", True):
            raise HTTPException(status_code=400, detail=result.get("message", "Mossa non valida."))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/game/state")
async def game_state():
    """
    GET /game/state

    Ritorna lo stato completo della sessione di gioco corrente
    (mappa, eserciti, log battaglie, turno, ecc.).
    """
    if _active_session is None:
        raise HTTPException(status_code=404, detail="Nessuna partita attiva.")
    return _active_session.to_dict()


@app.post("/game/place-mine")
async def game_place_mine(request: MineRequest):
    """Piazza una miniera di grux su una cella controllata dal giocatore."""
    if _active_session is None:
        raise HTTPException(status_code=400, detail="Nessuna partita attiva.")

    try:
        return _active_session.place_mine(request.row, request.col)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/game/place-garrison-here")
async def game_place_garrison_here(request: Optional[GarrisonRequest] = None):
    """Piazza subito un presidio sulla casella corrente del player."""
    if _active_session is None:
        raise HTTPException(status_code=400, detail="Nessuna partita attiva.")

    try:
        unit_id = request.unit_id if request is not None else None
        return _active_session.place_garrison_here(unit_id=unit_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/game/place-fortification")
async def game_place_fortification(request: MineRequest):
    """Piazza una fortificazione su una cella controllata dal giocatore."""
    if _active_session is None:
        raise HTTPException(status_code=400, detail="Nessuna partita attiva.")

    try:
        return _active_session.place_fortification(request.row, request.col)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/game/recruit")
async def game_recruit(request: RecruitRequest):
    """Compra una nuova unità spendendo grux dalla tesoreria globale."""
    if _active_session is None:
        raise HTTPException(status_code=400, detail="Nessuna partita attiva.")

    try:
        return _active_session.recruit_player_unit(request.unit_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/game/research-ability")
async def game_research_ability(request: AbilityResearchRequest):
    """Avvia la ricerca abilità del player."""
    if _active_session is None:
        raise HTTPException(status_code=400, detail="Nessuna partita attiva.")

    try:
        return _active_session.research_player_ability(request.ability_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/game/set-strategy")
async def game_set_strategy(request: StrategyChangeRequest):
    """Aggiorna la strategia attiva del player durante la partita."""
    if _active_session is None:
        raise HTTPException(status_code=400, detail="Nessuna partita attiva.")

    try:
        return _active_session.set_player_strategy(request.strategy_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/game/set-ai-difficulty")
async def game_set_ai_difficulty(request: AIDifficultyRequest):
    """Aggiorna la difficoltà runtime dell'IA per la sessione attiva."""
    if _active_session is None:
        raise HTTPException(status_code=400, detail="Nessuna partita attiva.")

    try:
        return _active_session.set_ai_difficulty(request.difficulty)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/game/debug/ai-kill-switch")
async def game_debug_ai_kill_switch():
    """DEBUG TEMPORANEO (DA RIMUOVERE): toggle pausa completa IA."""
    if _active_session is None:
        raise HTTPException(status_code=400, detail="Nessuna partita attiva.")

    try:
        return _active_session.toggle_debug_ai_kill_switch()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/game/reset")
async def game_reset():
    """
    DELETE /game/reset

    Termina la sessione corrente e la azzera,
    permettendo di iniziare una nuova partita.
    """
    global _active_session
    _active_session = None
    return {"message": "Sessione azzerata. Puoi iniziare una nuova partita."}


@app.get("/", response_class=HTMLResponse)
async def root():
    """Radice: serve il file index.html direttamente"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@app.get("/battle", response_class=HTMLResponse)
async def battle_page():
    """Serve la pagina dedicata alla battaglia."""
    battle_path = os.path.join(FRONTEND_DIR, "battle.html")

    with open(battle_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
