"""
War Advisor - Conflict Strategy Recommender Engine
Motore di raccomandazione strategica basato su Distanza Semantica Euclidea
Con supporto per modificatori di terreno, meteo e stato delle truppe
"""

import json
import math
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Path per i dati
DATA_DIR = Path(__file__).parent / "data"


def load_data() -> Dict[str, Any]:
    """
    Carica i dati dai file JSON (units, strategies, modifiers, affinità).
    
    Returns:
        Dict con chiavi 'units', 'strategies', 'terrain', 'weather', 'troop_status', 'unit_affinities'
    """
    with open(DATA_DIR / "units.json", "r", encoding="utf-8") as f:
        units_data = json.load(f)
    
    with open(DATA_DIR / "strategies.json", "r", encoding="utf-8") as f:
        strategies_data = json.load(f)
    
    with open(DATA_DIR / "modifiers.json", "r", encoding="utf-8") as f:
        modifiers_data = json.load(f)
    
    # Carica affinità unità-ambiente (sistema bidirezionale)
    affinities_path = DATA_DIR / "unit_affinities.json"
    if affinities_path.exists():
        with open(affinities_path, "r", encoding="utf-8") as f:
            affinities_data = json.load(f)
    else:
        affinities_data = {}
    
    return {
        "units": units_data["units"],
        "strategies": strategies_data["strategies"],
        "terrain": modifiers_data.get("terrain", {}),
        "weather": modifiers_data.get("weather", {}),
        "troop_status": modifiers_data.get("troop_status", {}),
        "unit_affinities": affinities_data
    }


def aggregate_army(selected_unit_ids: List[str], units_list: List[Dict]) -> Dict[str, float]:
    """
    Aggrega i vettori degli attributi di un'armata calcolando la media.
    
    Args:
        selected_unit_ids: Lista di ID di unità selezionate
        units_list: Lista di tutte le unità disponibili
    
    Returns:
        Vettore dell'esercito con valori medi degli attributi (8 dimensioni)
    """
    if not selected_unit_ids:
        raise ValueError("Nessuna unità selezionata")
    
    # Crea una mappa unit_id -> unit_data
    units_map = {unit["id"]: unit for unit in units_list}
    
    # Attributi di cui calcolare la media
    attribute_keys = [
        "U1_attack", "U2_defense", "U3_mobility", "U4_stealth",
        "U5_discipline", "U6_terrain_adapt", "U7_range_power", "U8_support"
    ]
    
    # Inizializza i cumuli degli attributi
    attribute_sums = {key: 0.0 for key in attribute_keys}
    
    # Somma gli attributi di tutte le unità selezionate
    for unit_id in selected_unit_ids:
        if unit_id not in units_map:
            raise ValueError(f"Unità non trovata: {unit_id}")
        
        unit = units_map[unit_id]
        for key in attribute_keys:
            attribute_sums[key] += unit["attributes"][key]
    
    # Calcola la media
    army_vector = {
        key: value / len(selected_unit_ids)
        for key, value in attribute_sums.items()
    }
    
    return army_vector


def apply_modifiers(
    army_vector: Dict[str, float],
    terrain_name: str = None,
    weather_name: str = None,
    troop_status_name: str = None,
    modifiers_data: Dict[str, Any] = None
) -> Tuple[Dict[str, float], List[str]]:
    """
    Applica i modificatori (terreno, meteo, stato truppe) al vettore dell'esercito.
    
    Gestione CRITICAL:
    - Se un attributo è segnato come "CRITICAL" e il valore dell'esercito in quell'attributo è < 0.5,
      applica una penalità massiccia (moltiplicatore 0.5).
    - Se il valore è >= 0.5, nessun malus.
    
    Args:
        army_vector: Vettore dell'esercito originale
        terrain_name: Nome del terreno
        weather_name: Nome del meteo
        troop_status_name: Stato delle truppe
        modifiers_data: Dati dei modificatori caricati da JSON
    
    Returns:
        Tuple (vettore modificato, lista di warning per CRITICAL non soddisfatti)
    """
    if modifiers_data is None:
        modifiers_data = load_data()
    
    modified_vector = army_vector.copy()
    warnings = []
    
    attribute_keys = [
        "U1_attack", "U2_defense", "U3_mobility", "U4_stealth",
        "U5_discipline", "U6_terrain_adapt", "U7_range_power", "U8_support"
    ]
    
    # Applica modificatori terreno
    if terrain_name and terrain_name in modifiers_data.get("terrain", {}):
        terrain_mods = modifiers_data["terrain"][terrain_name]
        for attr_key, modifier in terrain_mods.items():
            if attr_key in modified_vector:
                if modifier == "CRITICAL":
                    # Gestione CRITICAL per terreno
                    if modified_vector[attr_key] < 0.5:
                        modified_vector[attr_key] *= 0.5
                        warnings.append(f"CRITICAL: {attr_key} in {terrain_name} (valore < 0.5) - penalità applicata")
                else:
                    # Moltiplicatore normale
                    modified_vector[attr_key] *= modifier
    
    # Applica modificatori meteo
    if weather_name and weather_name in modifiers_data.get("weather", {}):
        weather_mods = modifiers_data["weather"][weather_name]
        for attr_key, modifier in weather_mods.items():
            if attr_key in modified_vector:
                if modifier == "CRITICAL":
                    # Gestione CRITICAL per meteo
                    if modified_vector[attr_key] < 0.5:
                        modified_vector[attr_key] *= 0.5
                        warnings.append(f"CRITICAL: {attr_key} in {weather_name} (valore < 0.5) - penalità applicata")
                else:
                    # Moltiplicatore normale
                    modified_vector[attr_key] *= modifier
    
    # Applica modificatori stato truppe
    if troop_status_name and troop_status_name in modifiers_data.get("troop_status", {}):
        status_mods = modifiers_data["troop_status"][troop_status_name]
        for attr_key, modifier in status_mods.items():
            if attr_key == "ALL":
                # Modificatore a tutti gli attributi
                for key in attribute_keys:
                    modified_vector[key] *= modifier
            elif attr_key in modified_vector:
                if modifier == "CRITICAL":
                    # Gestione CRITICAL per stato
                    if modified_vector[attr_key] < 0.5:
                        modified_vector[attr_key] *= 0.5
                        warnings.append(f"CRITICAL: {attr_key} in {troop_status_name} (valore < 0.5) - penalità applicata")
                else:
                    # Moltiplicatore normale
                    modified_vector[attr_key] *= modifier
    
    # Clamping: assicurati che i valori rimangano nel range [0.0, 1.0]
    for key in modified_vector:
        modified_vector[key] = max(0.0, min(1.0, modified_vector[key]))
    
    return modified_vector, warnings


def compute_environment_adjustment(
    unit_ids: List[str],
    strategy_id: str,
    terrain_name: str = None,
    weather_name: str = None,
    affinities_data: Dict[str, Any] = None
) -> float:
    """
    Calcola l'aggiustamento della distanza basato sull'affinità unità-ambiente.
    
    Sistema BIDIREZIONALE:
    - Affinità > 0.5 → BONUS (riduce distanza = migliora compatibilità)
    - Affinità < 0.5 → MALUS (aumenta distanza = peggiora compatibilità)
    - Affinità = 0.5 → Neutro (nessun effetto)
    
    Esempio Assassini:
    - Foresta + Notte (1.0, 1.0) → bonus massimo verso Imboscata
    - Pianura + Sereno (0.1, 0.15) → malus forte verso Imboscata
    
    Args:
        unit_ids: Lista di ID delle unità selezionate
        strategy_id: ID della strategia da valutare
        terrain_name: Nome del terreno
        weather_name: Nome del meteo
        affinities_data: Dati delle affinità
    
    Returns:
        Valore da SOMMARE alla distanza (negativo = bonus, positivo = malus)
    """
    if not affinities_data or not unit_ids:
        return 0.0
    
    unit_strategy_affinity = affinities_data.get("unit_strategy_affinity", {})
    environment_affinity = affinities_data.get("environment_affinity", {})
    default_aff = affinities_data.get("default_affinity", 0.5)
    
    total_adjustment = 0.0
    units_with_affinity = 0
    
    for unit_id in unit_ids:
        # Verifica se questa unità ha configurazione affinità
        unit_strat_aff = unit_strategy_affinity.get(unit_id, {})
        natural_strategies = unit_strat_aff.get("natural_strategies", [])
        max_adjustment = unit_strat_aff.get("max_adjustment", 0.1)
        
        # Se la strategia NON è naturale per questa unità, salta
        if strategy_id not in natural_strategies:
            continue
        
        units_with_affinity += 1
        
        # Calcola affinità ambiente per questa unità
        env_aff = environment_affinity.get(unit_id, {})
        
        # Ottieni i pesi terreno/meteo per questa unità
        env_weights = affinities_data.get("environment_weights", {})
        default_weights = affinities_data.get("default_weights", {"terrain": 0.5, "weather": 0.5})
        unit_weights = env_weights.get(unit_id, default_weights)
        terrain_weight = unit_weights.get("terrain", 0.5)
        weather_weight = unit_weights.get("weather", 0.5)
        
        # Affinità terreno (default 0.5 = neutro)
        terrain_aff = default_aff
        if terrain_name and "terrain" in env_aff:
            terrain_aff = env_aff["terrain"].get(terrain_name, default_aff)
        
        # Affinità meteo (default 0.5 = neutro)
        weather_aff = default_aff
        if weather_name and "weather" in env_aff:
            weather_aff = env_aff["weather"].get(weather_name, default_aff)
        
        # Media PESATA delle affinità ambiente (pesi personalizzati per unità)
        avg_affinity = (terrain_aff * terrain_weight) + (weather_aff * weather_weight)
        
        # Converti affinità in adjustment:
        # - avg_affinity = 1.0 → adjustment = -max_adjustment (bonus massimo)
        # - avg_affinity = 0.5 → adjustment = 0 (neutro)
        # - avg_affinity = 0.0 → adjustment = +max_adjustment (malus massimo)
        adjustment = (0.5 - avg_affinity) * 2 * max_adjustment
        
        total_adjustment += adjustment
    
    # Se nessuna unità ha affinità per questa strategia, nessun effetto
    if units_with_affinity == 0:
        return 0.0
    
    # Media degli adjustment di tutte le unità con affinità
    return total_adjustment / len(unit_ids)


def euclidean_distance(vector1: Dict[str, float], vector2: Dict[str, float]) -> float:
    """
    Calcola la distanza Euclidea tra due vettori 8-dimensionali.
    
    La "Distanza Semantica" rappresenta quanto l'esercito è adatto a una strategia:
    - Distanza bassa = strategia adatta
    - Distanza alta = strategia non adatta
    
    Formula: Distance = sqrt(sum((Army_i - Strategy_i)^2))
    
    Args:
        vector1: Primo vettore (es. armata)
        vector2: Secondo vettore (es. strategia ideale)
    
    Returns:
        Distanza Euclidea
    """
    sum_of_squares = 0.0
    for key in vector1.keys():
        diff = vector1[key] - vector2[key]
        sum_of_squares += diff ** 2
    
    return math.sqrt(sum_of_squares)


def compute_ranking(
    army_vector: Dict[str, float],
    strategies_list: List[Dict],
    unit_ids: List[str] = None,
    terrain_name: str = None,
    weather_name: str = None,
    affinities_data: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Calcola il ranking delle strategie basato sulla Distanza Semantica dall'armata.
    
    SISTEMA AFFINITÀ BIDIREZIONALE:
    - Per ogni unità, se la strategia è "naturale" e l'ambiente è favorevole → bonus
    - Se la strategia è "naturale" ma l'ambiente è sfavorevole → malus
    
    Args:
        army_vector: Vettore dell'esercito (eventualmente già modificato dal contesto)
        strategies_list: Lista di strategie disponibili
        unit_ids: Lista ID unità per calcolo affinità
        terrain_name: Terreno per calcolo affinità
        weather_name: Meteo per calcolo affinità
        affinities_data: Dati affinità unità-ambiente
    
    Returns:
        Lista di strategie ordinate dalla distanza minore alla maggiore,
        con aggiunta i campi 'distance' e 'compatibility' (affinità percentuale)
    """
    ranked_strategies = []
    
    max_possible_distance = math.sqrt(8)  # Massima distanza euclidea in 8 dimensioni
    
    for strategy in strategies_list:
        distance = euclidean_distance(army_vector, strategy["ideal_attributes"])
        
        # Applica adjustment affinità (può essere negativo=bonus o positivo=malus)
        if unit_ids and affinities_data:
            adjustment = compute_environment_adjustment(
                unit_ids=unit_ids,
                strategy_id=strategy["id"],
                terrain_name=terrain_name,
                weather_name=weather_name,
                affinities_data=affinities_data
            )
            distance = max(0.0, distance + adjustment)
        
        # Calcola affinità percentuale: 100 - (distance / max_distance * 100)
        compatibility = max(0, 100 - (distance / max_possible_distance * 100))
        
        ranked_strategies.append({
            **strategy,
            "distance": round(distance, 4),
            "compatibility": round(compatibility, 1)
        })
    
    # Ordina per distanza (crescente = migliori prime)
    ranked_strategies.sort(key=lambda s: s["distance"])
    
    return ranked_strategies


def get_available_units(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ritorna lista di unità disponibili per il frontend."""
    return [
        {"id": u["id"], "name": u["name"], "description": u["description"]}
        for u in data["units"]
    ]


def get_available_terrains(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ritorna lista di terreni disponibili per il frontend."""
    terrains = []
    for terrain_name in data.get("terrain", {}).keys():
        terrains.append({"id": terrain_name.lower().replace(" ", "_"), "name": terrain_name})
    return terrains


def get_available_weather(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ritorna lista di condizioni meteo disponibili per il frontend."""
    weather = []
    for weather_name in data.get("weather", {}).keys():
        weather.append({"id": weather_name.lower().replace(" ", "_"), "name": weather_name})
    return weather


def get_available_troop_status(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ritorna lista di stati truppe disponibili per il frontend."""
    statuses = []
    for status_name in data.get("troop_status", {}).keys():
        statuses.append({"id": status_name.lower().replace(" ", "_"), "name": status_name})
    return statuses
