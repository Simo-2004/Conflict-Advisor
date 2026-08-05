"""
War Advisor - In Game Advisor

Genera consigli strategici durante la battaglia usando lo stato corrente,
con una componente di incertezza controllata per simulare intelligence
imperfetta in-game.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Optional

from engine import apply_modifiers, compute_ranking


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _build_rng_seed(
    *,
    turn: int,
    terrain_name: str,
    weather_name: Optional[str],
    troop_status_name: Optional[str],
    player_units: List[str],
    player_strategy_id: str,
) -> int:
    units_key = ",".join(sorted(player_units))
    key = (
        f"{turn}|{terrain_name}|{weather_name or '-'}|{troop_status_name or '-'}|"
        f"{units_key}|{player_strategy_id}"
    )
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _estimate_reliability(turn: int) -> float:
    """
    Affidabilita advisor volutamente limitata all'inizio.

    Sale lentamente con i turni per dare un senso di progressione,
    ma resta comunque lontana dal 100%.
    """
    return _clamp(0.56 + (min(40, max(0, turn - 1)) * 0.007), 0.56, 0.84)


def build_in_game_advisor_payload(
    *,
    data: Dict[str, Any],
    turn: int,
    player_units: List[str],
    player_army: Dict[str, float],
    player_strategy_id: str,
    troop_status_name: Optional[str],
    terrain_name: str,
    weather_name: Optional[str],
) -> Dict[str, Any]:
    """Costruisce il payload advisor per il popup in battaglia."""
    modified_profile, critical_warnings = apply_modifiers(
        army_vector=player_army,
        terrain_name=terrain_name,
        weather_name=weather_name,
        troop_status_name=troop_status_name,
        modifiers_data=data,
    )

    true_ranking = compute_ranking(
        army_vector=modified_profile,
        strategies_list=data["strategies"],
        unit_ids=player_units,
        terrain_name=terrain_name,
        weather_name=weather_name,
        affinities_data=data.get("unit_affinities", {}),
    )

    if not true_ranking:
        raise ValueError("Nessuna strategia disponibile per la valutazione in-game.")

    reliability = _estimate_reliability(turn)
    noise_scale = 1.0 - reliability

    rng = random.Random(
        _build_rng_seed(
            turn=turn,
            terrain_name=terrain_name,
            weather_name=weather_name,
            troop_status_name=troop_status_name,
            player_units=player_units,
            player_strategy_id=player_strategy_id,
        )
    )

    estimated_ranking: List[Dict[str, Any]] = []
    for item in true_ranking:
        base_compat = float(item.get("compatibility", 0.0))
        base_distance = float(item.get("distance", 0.0))

        compat_jitter = rng.uniform(-18.0, 18.0) * noise_scale
        distance_jitter_factor = 1.0 + (rng.uniform(-0.45, 0.45) * noise_scale)

        estimated_compatibility = _clamp(base_compat + compat_jitter, 0.0, 100.0)
        estimated_distance = max(0.0, base_distance * distance_jitter_factor)

        confidence_pct = _clamp(
            (estimated_compatibility * reliability) + (rng.uniform(-6.0, 6.0) * noise_scale),
            0.0,
            100.0,
        )

        score = (
            (estimated_compatibility * 1.2)
            - (estimated_distance * 120.0)
            + (rng.uniform(-10.0, 10.0) * noise_scale)
        )

        estimated_ranking.append(
            {
                "id": item["id"],
                "name": item["name"],
                "description": item.get("description", ""),
                "compatibility": round(estimated_compatibility, 2),
                "distance": round(estimated_distance, 4),
                "confidence": round(confidence_pct, 1),
                "score": round(score, 4),
                "ideal_attributes": item.get("ideal_attributes", {}),
            }
        )

    estimated_ranking.sort(key=lambda row: row["score"], reverse=True)

    if len(estimated_ranking) >= 2:
        swap_chance = 0.52 * noise_scale
        if rng.random() < swap_chance:
            estimated_ranking[0], estimated_ranking[1] = estimated_ranking[1], estimated_ranking[0]

    for index, row in enumerate(estimated_ranking):
        row["rank"] = index + 1
        row.pop("score", None)

    top_strategy = estimated_ranking[0]
    second_strategy = estimated_ranking[1] if len(estimated_ranking) > 1 else estimated_ranking[0]
    worst_strategy = estimated_ranking[-1]

    reliability_pct = int(round(reliability * 100))
    uncertainty_pct = 100 - reliability_pct

    return {
        "turn": turn,
        "terrain_name": terrain_name,
        "weather_name": weather_name,
        "troop_status_name": troop_status_name,
        "army_profile": player_army,
        "modified_profile": modified_profile,
        "critical_warnings": critical_warnings,
        "reliability": {
            "score_pct": reliability_pct,
            "uncertainty_pct": uncertainty_pct,
            "label": "stima preliminare in battaglia",
            "note": (
                "Rapporto parziale: indicazione utile ma non completamente affidabile. "
                "Verifica sempre il terreno e la composizione reale."
            ),
        },
        "top_strategy": top_strategy,
        "second_strategy": second_strategy,
        "worst_strategy": worst_strategy,
        "ranking": estimated_ranking,
    }
