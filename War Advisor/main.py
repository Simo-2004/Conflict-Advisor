"""
War Advisor - FastAPI Backend
API per il sistema di raccomandazione strategica per wargame
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
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
app.mount("/static", StaticFiles(directory=".", html=True), name="static")

# Carica i dati all'avvio
try:
    DATA = load_data()
except Exception as e:
    raise RuntimeError(f"Errore nel caricamento dei dati: {e}")


# ==================== MODELLI PYDANTIC ====================

class ConfigResponse(BaseModel):
    """Risposta per l'endpoint GET /config"""
    units: List[Dict[str, Any]] = Field(..., description="Lista di unità disponibili")
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
        units = get_available_units(DATA)
        terrains = get_available_terrains(DATA)
        weather = get_available_weather(DATA)
        troop_status = get_available_troop_status(DATA)
        return ConfigResponse(
            units=units,
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
            critical_warnings=critical_warnings,
            ranking=ranking,
            top_strategy=top_strategy
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Radice: serve il file index.html"""
    with open("index.html", "r", encoding="utf-8") as f:
        return {"message": "War Advisor API - Apri index.html nel browser"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
