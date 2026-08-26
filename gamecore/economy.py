"""
War Advisor - Economy

Gestisce costi delle unità, tesoreria iniziale in grux, miniere e utilità
per controllare il bilancio durante simulazione e battaglia.
"""

from typing import Any, Dict, Iterable, List

# [BALANCE-LAYER] Ritocchi di prezzo dal layer di bilanciamento truppe.
# Se il file viene cancellato i costi tornano quelli della formula qui sotto,
# senza errori: è l'unico aggancio che l'economia ha con quel modulo.
try:
    from gamecore.troop_balance import apply_cost_overrides as _balance_costs
except ImportError:                                           # layer rimosso
    _balance_costs = None


STARTING_GRUX = 400
MINE_YIELD_PER_ROUND = 18
MINE_TILES_PER_SLOT = 4

#: Taglio secco su ogni miniera, di chiunque sia. Le miniere pagavano troppo:
#: chi ne apriva quattro non aveva più un problema di soldi per il resto
#: della partita, e la scelta fra reclutare e costruire spariva.
MINE_YIELD_MALUS = 0.80

#: Quanto rende una miniera a seconda di dove la si scava. La montagna è la
#: roccia buona, la palude è fango: i grux stanno sul terreno scomodo, non
#: dietro casa. Vale per tutti e due i giocatori, IA compresa.
#:
#: La pianura è il riferimento a 1.00, cioè il taglio del 20% e basta; le
#: altre si scostano da lì. Una miniera in palude rende poco più della metà
#: di una in montagna.
MINE_TERRAIN_YIELD = {
    "Montagna": 1.15,
    "Pianura":  1.00,
    "Foresta":  0.85,
    "Palude":   0.70,
}

#: Sul fiume non si scava, quindi non compare in tabella. Un terreno che non
#: conoscessimo vale come la pianura invece di far saltare il conto.
MINE_TERRAIN_YIELD_DEFAULT = 1.00


def mine_yield(terrain: str) -> float:
    """Resa per turno di una singola miniera su quel terreno."""
    return MINE_YIELD_PER_ROUND * MINE_YIELD_MALUS * MINE_TERRAIN_YIELD.get(
        terrain, MINE_TERRAIN_YIELD_DEFAULT
    )


def round_to_five(value: float) -> int:
    """Arrotonda al multiplo di 5 più vicino."""
    return int(5 * round(value / 5))


def calculate_unit_cost(unit: Dict[str, Any]) -> int:
    """Calcola il costo di una unità in grux a partire dai suoi attributi."""
    attrs = unit["attributes"]
    weighted_score = (
        20
        + (sum(attrs.values()) * 7.0)
        + (attrs["U1_attack"] * 10.0)
        + (attrs["U2_defense"] * 8.0)
        + (attrs["U3_mobility"] * 4.0)
        + (attrs["U4_stealth"] * 4.0)
        + (attrs["U5_discipline"] * 4.0)
        + (attrs["U6_terrain_adapt"] * 3.0)
        + (attrs["U7_range_power"] * 6.0)
        + (attrs["U8_support"] * 3.0)
    )
    return max(35, round_to_five(weighted_score))


def get_unit_costs(units: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Restituisce la mappa unit_id -> costo grux.

    Punto unico da cui passano tutti i prezzi del gioco (schermata iniziale,
    reclutamento, esercito IA): il layer di bilanciamento si aggancia qui e
    non deve inseguire i singoli chiamanti.
    """
    costs = {unit["id"]: calculate_unit_cost(unit) for unit in units}
    if _balance_costs is not None:                            # [BALANCE-LAYER]
        costs = _balance_costs(costs)
    return costs


def calculate_army_cost(unit_ids: List[str], unit_costs: Dict[str, int]) -> int:
    """Costo totale dell'esercito selezionato."""
    return sum(unit_costs[unit_id] for unit_id in unit_ids)


def remaining_grux(unit_ids: List[str], unit_costs: Dict[str, int], budget: int = STARTING_GRUX) -> int:
    """Bilancio residuo dopo avere comprato l'esercito iniziale."""
    return budget - calculate_army_cost(unit_ids, unit_costs)


def available_mine_slots(controlled_cells: int, existing_mines: int) -> int:
    """Slot miniera sbloccati: una miniera ogni 4 celle controllate."""
    unlocked = controlled_cells // MINE_TILES_PER_SLOT
    return max(0, unlocked - existing_mines)
