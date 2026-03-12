"""
War Advisor - Game Flow Glue

Collante minimale tra il ranking strategico e l'avvio della partita.
Riceve i dati del giocatore gia' calcolati dal backend, genera l'esercito
dell'IA e crea una GameSession pronta per il frontend.
"""

from typing import Any, Dict, Optional

from gamecore.economy import STARTING_GRUX, calculate_army_cost, get_unit_costs
from gamecore.maps import TERRAIN_TYPES
from gamecore.session import GameSession, build_ai_army


def start_game_session(
    *,
    data: Dict[str, Any],
    player_units: list[str],
    terrain: str,
    weather: Optional[str],
    troop_status: Optional[str],
    strategy_id: str,
    army_profile: Dict[str, float],
    modified_profile: Dict[str, float],
    map_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Crea una sessione di gioco completa partendo dal risultato di /calculate."""
    if terrain not in TERRAIN_TYPES:
        raise ValueError(f"Terreno non valido: '{terrain}'. Valori ammessi: {TERRAIN_TYPES}")

    unit_costs = get_unit_costs(data["units"])
    player_army_cost = calculate_army_cost(player_units, unit_costs)
    if player_army_cost > STARTING_GRUX:
        raise ValueError("L'esercito selezionato supera il budget iniziale disponibile.")

    ai_data = build_ai_army(
        data=data,
        ai_terrain="Montagna",
        weather=weather,
        n_units=3,
        budget=STARTING_GRUX,
        seed=map_seed,
    )

    session = GameSession(
        player_units=player_units,
        player_strategy_id=strategy_id,
        player_army=army_profile,
        player_modified=modified_profile,
        player_troop_status=troop_status,
        player_budget=STARTING_GRUX - player_army_cost,
        player_army_cost=player_army_cost,
        ai_data=ai_data,
        weather=weather,
        data=data,
        player_home_terrain=terrain,
        map_seed=map_seed,
    )

    return {
        "session": session,
        "ai_data": ai_data,
        "message": (
            f"Partita avviata! L'IA ha scelto: {ai_data['strategy']['name']} "
            f"con {', '.join(ai_data['units'])}."
        ),
    }