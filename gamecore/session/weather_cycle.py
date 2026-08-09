"""
War Advisor - Meteo e ciclo giorno/notte

Il gioco ha già una configurazione meteo bilanciata in `data/modifiers.json`:
Sereno, Pioggia, Nebbia e Notte, con i loro moltiplicatori sugli attributi.
Quei valori NON si toccano — sono la taratura fatta a suo tempo e restano il
metro di valutazione.

Qui si fa una cosa sola: separare i due assi che nel file stanno mescolati.

    ciclo   Giorno | Notte      (Giorno è neutro: non cambia nulla)
    meteo   Sereno | Pioggia | Nebbia

I due assi si sommano, quindi "Notte + Pioggia" è uno stato valido mentre
"Giorno + Notte" non esiste per costruzione: sono valori dello stesso asse.

La somma è realizzata **componendo le voci di configurazione** in una singola
entry sintetica che viene registrata nella mappa meteo della sessione. Così è
`engine.apply_modifiers` ad applicarla, con la sua logica di sempre (CRITICAL
compreso), e `engine.py` non va toccato.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

# ── Assi ───────────────────────────────────────────────────────────
CYCLE_DAY = "Giorno"
CYCLE_NIGHT = "Notte"
CYCLES: Tuple[str, ...] = (CYCLE_DAY, CYCLE_NIGHT)

WEATHER_CLEAR = "Sereno"
WEATHER_RAIN = "Pioggia"
WEATHER_FOG = "Nebbia"
WEATHERS: Tuple[str, ...] = (WEATHER_CLEAR, WEATHER_RAIN, WEATHER_FOG)

#: Chiavi di `modifiers.json` da cui prendere i moltiplicatori di ogni asse.
#: Giorno non ha una voce: è il default che non cambia nulla.
CYCLE_SOURCE_KEY = {CYCLE_DAY: None, CYCLE_NIGHT: "Notte"}

SEPARATOR = " · "

# ── Ritmo dei cambiamenti ──────────────────────────────────────────
# Un solo orologio per entrambi gli assi. Con due orologi indipendenti gli
# intervalli si intrecciavano e le condizioni cambiavano ogni ~10 turni pur
# rispettando il minimo su ciascun asse: qui il minimo vale su ciò che il
# giocatore vede davvero cambiare.
CHANGE_MIN_TURNS = 20
CHANGE_MAX_TURNS = 26
#: A ogni cambio il ciclo si alterna sempre; il meteo si ritira solo a volte,
#: altrimenti non esisterebbero notti serene di seguito a giorni sereni.
WEATHER_REROLL_CHANCE = 0.55

#: Con che peso esce ogni meteo al sorteggio. Il sereno resta il caso comune:
#: le condizioni avverse devono essere un evento, non la norma.
WEATHER_WEIGHTS = {WEATHER_CLEAR: 0.5, WEATHER_RAIN: 0.3, WEATHER_FOG: 0.2}

# ── Presentazione (emoji e colori per l'indicatore in alto) ────────
CYCLE_UI = {
    CYCLE_DAY:   {"emoji": "☀️", "color": "#b45309", "background": "#fffbeb", "border": "#fcd34d"},
    CYCLE_NIGHT: {"emoji": "🌙", "color": "#c7d2fe", "background": "#312e81", "border": "#4338ca"},
}
WEATHER_UI = {
    WEATHER_CLEAR: {"emoji": "🌤", "label": "Sereno"},
    WEATHER_RAIN:  {"emoji": "🌧", "label": "Pioggia"},
    WEATHER_FOG:   {"emoji": "🌫", "label": "Nebbia"},
}

#: Descrizione dell'effetto, per il tooltip. Deriva dai valori reali del file
#: di configurazione, non è testo decorativo.
EFFECT_HINTS = {
    CYCLE_NIGHT: "furtività molto alta, disciplina a rischio",
    WEATHER_RAIN: "tiro e mobilità ridotti",
    WEATHER_FOG: "furtività alta, tiro dimezzato",
}


def combined_key(cycle: str, weather: str) -> str:
    """Nome della voce composta, usato come chiave meteo per l'engine."""
    return f"{cycle}{SEPARATOR}{weather}"


def split_key(key: Optional[str]) -> Tuple[str, str]:
    """Scompone una chiave composta; tollera i nomi semplici di una partita vecchia."""
    if not key:
        return CYCLE_DAY, WEATHER_CLEAR
    if SEPARATOR in key:
        cycle, weather = key.split(SEPARATOR, 1)
        return (
            cycle if cycle in CYCLES else CYCLE_DAY,
            weather if weather in WEATHERS else WEATHER_CLEAR,
        )
    # Chiave a un solo valore: può essere un meteo o "Notte".
    if key == CYCLE_NIGHT:
        return CYCLE_NIGHT, WEATHER_CLEAR
    if key in WEATHERS:
        return CYCLE_DAY, key
    return CYCLE_DAY, WEATHER_CLEAR


def _merge_modifiers(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Somma due set di modificatori.

    I moltiplicatori si moltiplicano fra loro; il marcatore CRITICAL vince su
    tutto, perché è una condizione, non un numero.
    """
    merged: Dict[str, Any] = dict(base)
    for attribute, modifier in extra.items():
        current = merged.get(attribute)
        if modifier == "CRITICAL" or current == "CRITICAL":
            merged[attribute] = "CRITICAL"
        elif current is None:
            merged[attribute] = modifier
        else:
            merged[attribute] = current * modifier
    return merged


def build_combined_weather_map(weather_config: Dict[str, Any]) -> Dict[str, Any]:
    """Genera tutte le combinazioni ciclo × meteo dai valori già bilanciati."""
    combined: Dict[str, Any] = {}
    for cycle in CYCLES:
        source = CYCLE_SOURCE_KEY.get(cycle)
        cycle_mods = dict(weather_config.get(source, {})) if source else {}
        for weather in WEATHERS:
            weather_mods = dict(weather_config.get(weather, {}))
            combined[combined_key(cycle, weather)] = _merge_modifiers(cycle_mods, weather_mods)
    return combined


def data_with_combined_weather(data: Dict[str, Any]) -> Dict[str, Any]:
    """Copia dei dati con le voci composte aggiunte alla mappa meteo.

    Si lavora su una copia: registrarle nel dizionario globale le farebbe
    comparire anche nel selettore meteo della schermata iniziale.
    """
    weather_config = dict(data.get("weather", {}))
    weather_config.update(build_combined_weather_map(weather_config))
    return {**data, "weather": weather_config}


def roll_weather(rng: random.Random, exclude: Optional[str] = None) -> str:
    """Estrae un meteo secondo i pesi, evitando di ripetere quello corrente."""
    candidates = [w for w in WEATHERS if w != exclude] or list(WEATHERS)
    weights = [WEATHER_WEIGHTS.get(w, 1.0) for w in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def next_change_delay(rng: random.Random) -> int:
    return rng.randint(CHANGE_MIN_TURNS, CHANGE_MAX_TURNS)


def advance(cycle: str, weather: str, rng: random.Random) -> Tuple[str, str]:
    """Prossime condizioni: il ciclo si alterna, il meteo a volte cambia."""
    next_cycle = CYCLE_NIGHT if cycle == CYCLE_DAY else CYCLE_DAY
    next_weather = weather
    if rng.random() < WEATHER_REROLL_CHANCE:
        next_weather = roll_weather(rng, exclude=weather)
    return next_cycle, next_weather


def describe(cycle: str, weather: str, *, changes_in: int = 0) -> Dict[str, Any]:
    """Payload per l'indicatore: emoji, colori, etichette ed effetti."""
    cycle_ui = CYCLE_UI.get(cycle, CYCLE_UI[CYCLE_DAY])
    weather_ui = WEATHER_UI.get(weather, WEATHER_UI[WEATHER_CLEAR])

    effects: List[str] = []
    for key in (cycle, weather):
        hint = EFFECT_HINTS.get(key)
        if hint:
            effects.append(f"{key}: {hint}")
    if not effects:
        effects.append("Nessun effetto: condizioni ideali")

    return {
        "cycle": cycle,
        "weather": weather,
        "key": combined_key(cycle, weather),
        "label": f"{cycle}{SEPARATOR}{weather}",
        "emoji": f"{cycle_ui['emoji']}{weather_ui['emoji']}",
        "cycle_emoji": cycle_ui["emoji"],
        "weather_emoji": weather_ui["emoji"],
        "color": cycle_ui["color"],
        "background": cycle_ui["background"],
        "border": cycle_ui["border"],
        "is_night": cycle == CYCLE_NIGHT,
        "effects": effects,
        "changes_in": max(0, int(changes_in)),
    }
