"""
War Advisor - Layer di bilanciamento truppe (SGANCIABILE)

Correzioni decise dopo la campagna di test con `scripts/balancetest.py`
(200 prove casuali + griglia deterministica 8 unità × 6 condizioni × 5 terreni).

Sta tutto qui dentro apposta: nessuna formula del motore è stata riscritta,
nessun attributo di `data/units.json` è stato toccato, `engine.py` non sa che
questo file esiste. Fuori da qui ci sono solo quattro agganci marcati
[BALANCE-LAYER], tutti inerti se il file sparisce.

Rimozione completa:

    grep -rn "BALANCE-LAYER" --include=*.py .

    1. cancella questo file
    2. togli i blocchi marcati in gamecore/economy.py e
       gamecore/session/session.py

Il gioco riparte con i numeri grezzi del motore, senza errori di import.

──────────────────────────────────────────────────────────────────────
1. ARTIGLIERIA — le ridiamo il suo mestiere

   Misurato: valore medio 39.3 contro una media di 65, il peggiore del gioco,
   e — paradosso — il DANNO MINIMO DI SISTEMA contro i castelli: 8 HP con sei
   pezzi, contro i 13 della fanteria pesante. L'unità d'assedio era il peggior
   ariete del gioco.

   La causa sta nei pesi del valore di combattimento: `U7_range_power` vale 8
   su 104 totali, il minimo, e l'artiglieria investe lì quasi tutto (0.98).
   Abbassarle il prezzo l'avrebbe resa conveniente, non sensata: qui invece
   conta molto di più dove dovrebbe contare, cioè contro mura e fortificazioni.
   In campo aperto resta quello che era, e va bene così.

2. GUARITORI — un tampone che si consuma

   Riducono le perdite della propria legione, in attacco e in difesa. Non sono
   invulnerabili: nelle perdite cadono per prime le unità di minor valore, e i
   guaritori sono fra quelle — più la battaglia dura, più il tampone si
   assottiglia. Il prezzo sale a 90 grux perché l'effetto non passa dal valore
   di combattimento e nessun altro conto lo vede.

3. PREZZI — ritocchi, non riscritture

   La formula di `economy.calculate_unit_cost` resta quella: qui si sovrascrive
   solo il risultato finale delle unità elencate.

4. ASSEDIO — la curva del danno al castello

   Misurato sulla curva precedente (tetto 65, mezzo danno a rapporto 15):
   portare più truppe non serviva quasi a niente. Contro un castello con 4
   presidi e 2 livelli di fortificazione:

       20 artiglierie →  19 danni       50 artiglierie →  31 danni
       80 artiglierie →  37 danni      200 artiglierie →  45 danni

   Quadruplicare l'esercito d'assedio dava il 60% di danno in più: un assedio
   non si poteva vincere con la massa, che è esattamente il modo in cui gli
   assedi si vincono. La curva era troppo piatta troppo presto.

   Qui la curva diventa una S: sotto resta severa (un raid di poche unità non
   deve scalfire un castello presidiato), sopra sale sul serio.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Tuple

# ══════════════════════════════════════════════════════════════════
# 1. ARTIGLIERIA
# ══════════════════════════════════════════════════════════════════

#: Quanto conta un'unità nell'assalto a un castello, rispetto al suo valore
#: normale. 2.0 sull'artiglieria porta sei pezzi da 8 a 14 HP di danno: da
#: peggior ariete del gioco a migliore, senza toccarne il valore in campo.
SIEGE_MULTIPLIERS: Dict[str, float] = {
    "artillery": 2.0,
}

#: Stesso principio contro una cella fortificata. Il bonus è pieno da due
#: livelli di fortificazione in su, dimezzato al primo: una palizzata non è
#: una fortezza.
FORTIFICATION_MULTIPLIERS: Dict[str, float] = {
    "artillery": 1.6,
}
FORTIFICATION_FULL_LEVEL = 2.0


def siege_strength(unit_ids: Iterable[str], value_of: Callable[[str], float]) -> float:
    """Forza d'assedio della legione.

    Come la somma dei valori unità, ma pesando chi è fatto per buttare giù
    le mura. `value_of` è la funzione del motore: il layer non ricalcola
    niente per conto suo, quindi meteo e stato truppe restano compresi.
    """
    return sum(value_of(uid) * SIEGE_MULTIPLIERS.get(uid, 1.0) for uid in unit_ids)


def fortification_surplus(
    unit_ids: Iterable[str],
    value_of: Callable[[str], float],
    fortification_level: int,
) -> float:
    """Forza in più contro una cella fortificata (0 se non ce ne sono).

    È un surplus da SOMMARE al valore già calcolato dal motore, non un
    ricalcolo: se il layer sparisce, resta il valore di prima.
    """
    if fortification_level <= 0:
        return 0.0

    scale = min(1.0, fortification_level / FORTIFICATION_FULL_LEVEL)
    surplus = 0.0
    for unit_id in unit_ids:
        multiplier = FORTIFICATION_MULTIPLIERS.get(unit_id)
        if multiplier:
            surplus += value_of(unit_id) * (multiplier - 1.0) * scale
    return surplus


# ══════════════════════════════════════════════════════════════════
# 2. GUARITORI
# ══════════════════════════════════════════════════════════════════

HEALER_UNIT_ID = "healers"

#: Quanta parte delle perdite assorbe ogni guaritore presente nella legione.
HEALER_RELIEF_EACH = 0.12
#: Tetto complessivo: oltre tre guaritori non si guadagna più niente, così
#: una legione di soli guaritori non diventa immortale.
HEALER_RELIEF_MAX = 0.35
#: Sotto questa soglia non si scende mai: una battaglia persa costa comunque.
HEALER_MIN_LOSSES = 1


def reduced_losses(unit_ids: List[str], losses: int) -> Tuple[int, int]:
    """Perdite dopo l'intervento dei guaritori.

    Ritorna (perdite effettive, perdite evitate). Con 3 guaritori una legione
    che perderebbe 10 unità ne perde 7.

    I guaritori contati sono quelli VIVI in questa legione: quando muoiono —
    e muoiono, perché nelle perdite cadono per prime le unità di minor valore —
    il tampone si assottiglia da solo al colpo dopo.
    """
    if losses <= 0:
        return losses, 0

    healers = sum(1 for unit_id in unit_ids if unit_id == HEALER_UNIT_ID)
    if healers <= 0:
        return losses, 0

    relief = min(HEALER_RELIEF_MAX, healers * HEALER_RELIEF_EACH)
    # Arrotondamento per eccesso a metà (0.5 sale): `round()` di Python usa
    # l'arrotondamento bancario e su 6.5 restituisce 6, cioè mezza perdita
    # regalata in più ogni volta che il conto cade esatto a metà.
    effective = int((losses * (1.0 - relief)) + 0.5)
    effective = min(losses, max(HEALER_MIN_LOSSES, effective))
    return effective, losses - effective


def losses_note(saved: int) -> str:
    """Nota per il log di battaglia: l'effetto deve vedersi."""
    if saved <= 0:
        return ""
    return f"guaritori: {saved} perdit{'a' if saved == 1 else 'e'} evitat{'a' if saved == 1 else 'e'}"


# ══════════════════════════════════════════════════════════════════
# 3. PREZZI
# ══════════════════════════════════════════════════════════════════

#: Prezzi imposti dal layer. Guaritori a 90 perché il loro valore in
#: battaglia (55) non misura la riduzione delle perdite: senza il rincaro
#: sarebbero l'acquisto obbligato di ogni legione.
COST_OVERRIDES: Dict[str, int] = {
    "healers": 90,
}


def apply_cost_overrides(costs: Dict[str, int]) -> Dict[str, int]:
    """Applica i ritocchi ai costi calcolati dalla formula, senza toccarla."""
    updated = dict(costs)
    for unit_id, price in COST_OVERRIDES.items():
        if unit_id in updated:
            updated[unit_id] = int(price)
    return updated


# ══════════════════════════════════════════════════════════════════
# 4. DANNO AL CASTELLO
# ══════════════════════════════════════════════════════════════════

#: Danno massimo per assalto. Alzato da 65: con 236 HP di castello, 65 era
#: comunque un minimo di 4 assalti anche per un esercito sterminato.
CASTLE_DAMAGE_MAX = 85.0

#: Rapporto forza/difesa a cui si fa metà del danno massimo. Sceso da 15 a 8:
#: 15 voleva dire quindici volte la difesa del castello per arrivare a metà
#: tabella, cioè un numero di truppe che non si raggiunge in partita.
CASTLE_DAMAGE_HALF_RATIO = 8.0

#: Quanto è "a S" la curva. A 1.0 era una saturazione pura, che schiacciava
#: tutto verso il tetto già con poche truppe. Sopra 1 la parte bassa resta
#: severa — un raid non buca un castello presidiato — e la parte alta premia
#: davvero chi porta un esercito d'assedio.
CASTLE_DAMAGE_STEEPNESS = 1.8


def castle_damage(attacker_strength: float, defender_score: float, floor: int) -> int:
    """Danno di un assalto, in funzione del rapporto forza/difesa.

    Stessa idea di prima (curva satura sul rapporto, non sulla differenza), ma
    con la ginocchiata spostata dove serve. `floor` è il pavimento del motore:
    resta suo, così il castello cade comunque anche con un esercito ridicolo.
    """
    ratio = attacker_strength / max(1.0, defender_score)
    if ratio <= 0.0:
        return floor

    scaled = ratio ** CASTLE_DAMAGE_STEEPNESS
    knee = CASTLE_DAMAGE_HALF_RATIO ** CASTLE_DAMAGE_STEEPNESS
    intensity = scaled / (scaled + knee)

    raw_damage = CASTLE_DAMAGE_MAX * intensity
    return max(floor, min(int(CASTLE_DAMAGE_MAX), int(round(raw_damage))))
