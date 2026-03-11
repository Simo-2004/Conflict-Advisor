"""
War Advisor - AI Army Builder

Costruisce l'esercito dell'IA scegliendo:
  1. Le unità più adatte al terreno di partenza (centro-nord, tipicamente Montagna).
  2. La strategia ottimale dato l'esercito scelto e le condizioni ambientali.

Un piccolo rumore casuale (seed: int) garantisce variabilità tra partite.
"""

import random
from typing import Any, Dict, List, Optional, Tuple

from engine import aggregate_army, apply_modifiers, compute_ranking

# Stato truppe fisso per l'IA all'inizio partita
AI_TROOP_STATUS: str = "Fresche"


def _score_unit_on_terrain(
    unit_attrs: Dict[str, float],
    terrain: str,
    terrain_modifiers: Dict[str, dict],
) -> float:
    """
    Calcola la forza effettiva di un'unità su un dato terreno
    applicando i modificatori (incluso CRITICAL).
    """
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


def build_ai_army(
    data: Dict[str, Any],
    ai_terrain: str,
    weather: Optional[str],
    n_units: int = 3,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Costruisce l'esercito dell'IA.

    Algoritmo:
      1. Scorifica ogni unità disponibile sul terreno di partenza dell'IA,
         aggiungendo un piccolo rumore casuale per variabilità.
      2. Seleziona le `n_units` unità con punteggio più alto.
      3. Calcola il vettore d'esercito (media) e applica i modificatori
         (terreno AI + meteo).
      4. Usa `compute_ranking` per scegliere la strategia ottimale.

    Args:
        data:       dizionario dati caricato da `engine.load_data()`
        ai_terrain: terreno della cella di partenza dell'IA
        weather:    condizione meteo globale (opzionale)
        n_units:    numero di unità da selezionare (default 3)
        seed:       seme per il rumore casuale (None = random)

    Returns:
        dict con:
            units            — lista ID unità selezionate
            troop_status     — stato truppe ("Fresche")
            army_vector      — vettore esercito grezzo
            modified_vector  — vettore dopo applicazione modificatori
            critical_warnings — warning CRITICAL
            strategy         — dict della strategia scelta (id, name, ...)
            ranking          — ranking completo delle strategie
    """
    rng = random.Random(seed)

    all_units: List[Dict] = data["units"]
    terrain_modifiers: Dict[str, dict] = data["terrain"]
    strategies_list: List[Dict] = data["strategies"]
    affinities_data: Dict = data.get("unit_affinities", {})

    # 1. Scorifica ogni unità
    unit_scores: List[Tuple[float, Dict]] = []
    for unit in all_units:
        score = _score_unit_on_terrain(unit["attributes"], ai_terrain, terrain_modifiers)
        score += rng.uniform(-0.15, 0.15)      # variabilità controllata
        unit_scores.append((score, unit))

    unit_scores.sort(key=lambda x: x[0], reverse=True)
    selected_ids: List[str] = [u["id"] for _, u in unit_scores[:n_units]]

    # 2. Aggregazione e modificatori
    army_vector = aggregate_army(selected_ids, all_units)
    modified_vector, warnings = apply_modifiers(
        army_vector=army_vector,
        terrain_name=ai_terrain,
        weather_name=weather,
        troop_status_name=AI_TROOP_STATUS,
        modifiers_data=data,
    )

    # 3. Strategia ottimale
    ranking = compute_ranking(
        army_vector=modified_vector,
        strategies_list=strategies_list,
        unit_ids=selected_ids,
        terrain_name=ai_terrain,
        weather_name=weather,
        affinities_data=affinities_data,
    )

    return {
        "units":             selected_ids,
        "troop_status":      AI_TROOP_STATUS,
        "army_vector":       army_vector,
        "modified_vector":   modified_vector,
        "critical_warnings": warnings,
        "strategy":          ranking[0],
        "ranking":           ranking,
    }
