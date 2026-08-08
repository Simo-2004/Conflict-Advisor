"""
War Advisor - Condizione delle truppe

Gestisce lo stato delle truppe (Fresche / Stanche / Demoralizzate / Veterane)
per singola legione. Gli stati e i loro effetti numerici restano quelli di
`data/modifiers.json`, applicati da `engine.apply_modifiers`: qui si decide
solo QUANDO una legione passa da uno stato all'altro, non quanto valga lo
stato. Il metro di valutazione è quello della schermata iniziale.

Il modello ha due assi indipendenti più un grado:

    fatica   0..100   sale marciando, scalando terreni duri e combattendo
    morale   0..100   scende perdendo scontri, risale riposando
    veterana bool     grado permanente guadagnato vincendo

Lo stato mostrato è la sintesi dei tre, con priorità:

    Demoralizzate  →  morale sotto soglia
    Stanche        →  fatica sopra soglia
    Veterane       →  grado guadagnato e condizione a posto
    Fresche        →  tutto a posto

Le soglie hanno isteresi (si entra a un valore, si esce a un altro) perché
senza lo stato lampeggerebbe a ogni turno intorno al punto critico.

Tutto il blocco costanti qui sotto è la manopola di bilanciamento: è pensato
per essere ritoccato senza toccare la logica.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

# ── Nomi di stato (devono coincidere con data/modifiers.json) ───────
STATUS_FRESH = "Fresche"
STATUS_TIRED = "Stanche"
STATUS_DEMORALIZED = "Demoralizzate"
STATUS_VETERAN = "Veterane"

ALL_STATUSES = (STATUS_FRESH, STATUS_TIRED, STATUS_DEMORALIZED, STATUS_VETERAN)

# ── Fatica da marcia ───────────────────────────────────────────────
# Proporzionale al costo movimento del terreno, così la stanchezza segue le
# stesse regole che il giocatore già conosce dal sistema di movimento.
TERRAIN_FATIGUE = {
    "Pianura": 4.0,
    "Foresta": 6.0,
    "Fiume": 7.0,
    "Palude": 9.0,
    "Montagna": 11.0,
}
DEFAULT_TERRAIN_FATIGUE = 5.0
# Quota di fatica pagata nei turni in cui la legione è ancora dentro il terreno
# senza averlo finito di attraversare. Senza, montagne e paludi risulterebbero
# MENO faticose della pianura: bloccano per più turni e quei turni sarebbero
# contati come riposo.
TRAVERSAL_FATIGUE_RATIO = 0.6

# ── Fatica e morale dagli scontri ──────────────────────────────────
BATTLE_FATIGUE_WIN = 10.0
BATTLE_FATIGUE_LOSS = 14.0
BATTLE_MORALE_WIN = 12.0
BATTLE_MORALE_LOSS = 32.0

SIEGE_FATIGUE = 12.0          # assalto al castello: costa comunque
SIEGE_MORALE_REPELLED = 18.0  # assalto respinto a vuoto: morale giù
SIEGE_MORALE_BREACH = 20.0    # castello abbattuto: morale su
# Un assalto che intacca il castello è un progresso, non una disfatta: la
# penalità al morale si riduce in proporzione al danno inflitto. Senza questo
# una legione che sta vincendo l'assedio si demoralizzava proprio mentre
# avanzava, perché abbattere un castello richiede molti assalti respinti.
SIEGE_PROGRESS_RELIEF = 4.0   # quanto pesa la frazione di HP tolti

# Il morale non è a senso unico: risale piano da solo finché non si perde uno
# scontro. Senza questa deriva ogni legione in campagna finiva demoralizzata
# per sempre, perché il recupero pieno richiede di stare ferma.
MORALE_DRIFT_PER_TURN = 1.6

# ── Riposo ─────────────────────────────────────────────────────────
# Si recupera stando fermi, ovunque, ma serve tempo: due turni per iniziare
# e il recupero cala con la distanza dal proprio castello. Lontano da casa
# ci si riprende poco, che è il modo di dire "più sei fuori più ti logori"
# senza legarlo al possesso delle celle (che una legione conquista appena
# ci passa sopra, quindi non direbbe nulla).
REST_WARMUP_TURNS = 2
REST_FATIGUE_RECOVERY = 9.0
REST_MORALE_RECOVERY = 7.0
REST_DISTANCE_PENALTY = 0.55   # per cella di distanza dal proprio castello

# ── Grado veterano ─────────────────────────────────────────────────
VETERAN_VICTORIES = 3               # vittorie necessarie per la promozione
VETERAN_FATIGUE_MULTIPLIER = 0.5    # i veterani si stancano la metà
VETERAN_MORALE_LOSS_MULTIPLIER = 0.6

# ── Soglie con isteresi ────────────────────────────────────────────
TIRED_ENTER = 45.0      # fatica oltre cui si diventa Stanche
TIRED_EXIT = 28.0       # fatica sotto cui si torna a posto
DEMORALIZED_ENTER = 38.0  # morale sotto cui si crolla
DEMORALIZED_EXIT = 58.0   # morale sopra cui ci si riprende

FATIGUE_MAX = 100.0
MORALE_MAX = 100.0

# ── Condizione di partenza per ogni stato della schermata iniziale ──
# Serve a onorare la scelta fatta prima della battaglia: chi parte con truppe
# stanche parte davvero stanco, non azzerato.
STATUS_SEEDS: Dict[str, Dict[str, Any]] = {
    STATUS_FRESH:        {"fatigue": 0.0,  "morale": 100.0, "veteran": False},
    STATUS_TIRED:        {"fatigue": 55.0, "morale": 100.0, "veteran": False},
    STATUS_DEMORALIZED:  {"fatigue": 30.0, "morale": 25.0,  "veteran": False},
    STATUS_VETERAN:      {"fatigue": 0.0,  "morale": 100.0, "veteran": True},
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def new_condition(
    status: Optional[str] = None,
    *,
    fatigue: Optional[float] = None,
    morale: Optional[float] = None,
    veteran: Optional[bool] = None,
    victories: int = 0,
) -> Dict[str, Any]:
    """Crea una condizione, opzionalmente seminata da uno stato iniziale."""
    seed = STATUS_SEEDS.get(status or STATUS_FRESH, STATUS_SEEDS[STATUS_FRESH])
    condition = {
        "fatigue": float(seed["fatigue"] if fatigue is None else fatigue),
        "morale": float(seed["morale"] if morale is None else morale),
        "veteran": bool(seed["veteran"] if veteran is None else veteran),
        "victories": int(victories),
        "rest_turns": 0,
        "status": STATUS_FRESH,
    }
    resolve_status(condition)
    return condition


def ensure_condition(legion: Dict[str, Any], fallback_status: Optional[str] = None) -> Dict[str, Any]:
    """Restituisce la condizione della legione, creandola se manca.

    Le legioni nate prima di questo sistema non hanno il campo: partono dalla
    condizione di default invece di far esplodere il turno.
    """
    condition = legion.get("condition")
    if not isinstance(condition, dict):
        condition = new_condition(fallback_status)
        legion["condition"] = condition
    return condition


def _fatigue_multiplier(condition: Dict[str, Any]) -> float:
    return VETERAN_FATIGUE_MULTIPLIER if condition.get("veteran") else 1.0


def _morale_loss_multiplier(condition: Dict[str, Any]) -> float:
    return VETERAN_MORALE_LOSS_MULTIPLIER if condition.get("veteran") else 1.0


def add_fatigue(condition: Dict[str, Any], amount: float) -> None:
    """Aggiunge fatica, già ridotta se la legione è veterana."""
    condition["fatigue"] = _clamp(
        condition["fatigue"] + (amount * _fatigue_multiplier(condition)), 0.0, FATIGUE_MAX
    )


def lose_morale(condition: Dict[str, Any], amount: float) -> None:
    condition["morale"] = _clamp(
        condition["morale"] - (amount * _morale_loss_multiplier(condition)), 0.0, MORALE_MAX
    )


def gain_morale(condition: Dict[str, Any], amount: float) -> None:
    condition["morale"] = _clamp(condition["morale"] + amount, 0.0, MORALE_MAX)


def apply_march(condition: Dict[str, Any], terrain: str) -> None:
    """La legione si è mossa: paga la fatica del terreno e perde il riposo."""
    add_fatigue(condition, TERRAIN_FATIGUE.get(terrain, DEFAULT_TERRAIN_FATIGUE))
    condition["rest_turns"] = 0


def apply_traversal(condition: Dict[str, Any], terrain: str) -> None:
    """Turno speso dentro un terreno difficile senza averlo ancora superato."""
    add_fatigue(
        condition,
        TERRAIN_FATIGUE.get(terrain, DEFAULT_TERRAIN_FATIGUE) * TRAVERSAL_FATIGUE_RATIO,
    )
    condition["rest_turns"] = 0


def apply_battle(condition: Dict[str, Any], *, won: bool) -> None:
    """Esito di uno scontro fra legioni."""
    condition["rest_turns"] = 0
    if won:
        add_fatigue(condition, BATTLE_FATIGUE_WIN)
        gain_morale(condition, BATTLE_MORALE_WIN)
        condition["victories"] = int(condition.get("victories", 0)) + 1
        if condition["victories"] >= VETERAN_VICTORIES:
            condition["veteran"] = True
    else:
        add_fatigue(condition, BATTLE_FATIGUE_LOSS)
        lose_morale(condition, BATTLE_MORALE_LOSS)


def apply_siege(condition: Dict[str, Any], *, breached: bool, damage_ratio: float = 0.0) -> None:
    """Esito di un assalto al castello nemico.

    `damage_ratio` è la frazione di HP tolti in questo assalto: più il colpo
    è stato pesante, meno pesa il fatto di non aver sfondato.
    """
    condition["rest_turns"] = 0
    add_fatigue(condition, SIEGE_FATIGUE)
    if breached:
        gain_morale(condition, SIEGE_MORALE_BREACH)
        return

    relief = _clamp(max(0.0, damage_ratio) * SIEGE_PROGRESS_RELIEF, 0.0, 1.0)
    lose_morale(condition, SIEGE_MORALE_REPELLED * (1.0 - relief))


def apply_morale_drift(condition: Dict[str, Any]) -> None:
    """Risalita lenta del morale nei turni senza sconfitte."""
    gain_morale(condition, MORALE_DRIFT_PER_TURN)


def apply_rest(condition: Dict[str, Any], distance_from_home: int) -> None:
    """La legione è rimasta ferma: recupera, ma tanto meno quanto è lontana.

    Il recupero parte solo dopo `REST_WARMUP_TURNS` turni fermi, così fermarsi
    un attimo davanti al castello nemico non rigenera nulla.
    """
    condition["rest_turns"] = int(condition.get("rest_turns", 0)) + 1
    if condition["rest_turns"] <= REST_WARMUP_TURNS:
        return

    penalty = max(0, int(distance_from_home)) * REST_DISTANCE_PENALTY
    fatigue_recovery = max(0.0, REST_FATIGUE_RECOVERY - penalty)
    morale_recovery = max(0.0, REST_MORALE_RECOVERY - penalty)

    condition["fatigue"] = _clamp(condition["fatigue"] - fatigue_recovery, 0.0, FATIGUE_MAX)
    condition["morale"] = _clamp(condition["morale"] + morale_recovery, 0.0, MORALE_MAX)


def resolve_status(condition: Dict[str, Any]) -> str:
    """Ricalcola lo stato mostrato e lo scrive nella condizione."""
    previous = condition.get("status", STATUS_FRESH)
    fatigue = float(condition.get("fatigue", 0.0))
    morale = float(condition.get("morale", MORALE_MAX))

    was_demoralized = previous == STATUS_DEMORALIZED
    was_tired = previous == STATUS_TIRED

    # Isteresi: la soglia di uscita è più severa di quella d'ingresso.
    demoralized = morale <= DEMORALIZED_ENTER or (was_demoralized and morale < DEMORALIZED_EXIT)
    tired = fatigue >= TIRED_ENTER or (was_tired and fatigue > TIRED_EXIT)

    if demoralized:
        status = STATUS_DEMORALIZED
    elif tired:
        status = STATUS_TIRED
    elif condition.get("veteran"):
        status = STATUS_VETERAN
    else:
        status = STATUS_FRESH

    condition["status"] = status
    return status


def status_of(legion: Dict[str, Any], fallback_status: Optional[str] = None) -> str:
    """Stato corrente di una legione, creando la condizione se manca."""
    return ensure_condition(legion, fallback_status).get("status", STATUS_FRESH)


def merge_into_pool(
    pool: Dict[str, Any],
    pool_size: int,
    condition: Dict[str, Any],
    incoming: int,
) -> Dict[str, Any]:
    """Fonde una condizione dentro quella di un gruppo, pesando per numero di unità.

    Serve al richiamo delle legioni: le truppe tornano in riserva e si mescolano
    con quelle già lì, quindi la riserva eredita una media e non si può usare il
    richiamo come reset gratuito della stanchezza.
    """
    incoming = max(0, int(incoming))
    if incoming == 0:
        return pool

    pool_size = max(0, int(pool_size))
    total = pool_size + incoming
    if total == 0:
        return pool

    for key in ("fatigue", "morale"):
        pool[key] = ((pool.get(key, 0.0) * pool_size) + (condition.get(key, 0.0) * incoming)) / total

    # Il grado non si media: se rientrano veterani, la riserva sa addestrare.
    pool["veteran"] = bool(pool.get("veteran")) or bool(condition.get("veteran"))
    pool["victories"] = max(int(pool.get("victories", 0)), int(condition.get("victories", 0)))
    resolve_status(pool)
    return pool


def dilute_pool(pool: Dict[str, Any], pool_size: int, fresh_units: int = 1) -> Dict[str, Any]:
    """Reclute fresche entrano in riserva e ne abbassano la stanchezza media."""
    return merge_into_pool(
        pool,
        pool_size,
        {"fatigue": 0.0, "morale": MORALE_MAX, "veteran": False, "victories": 0},
        fresh_units,
    )


def describe(condition: Dict[str, Any]) -> Dict[str, Any]:
    """Payload leggibile per il frontend."""
    return {
        "status": condition.get("status", STATUS_FRESH),
        "fatigue": round(float(condition.get("fatigue", 0.0)), 1),
        "morale": round(float(condition.get("morale", MORALE_MAX)), 1),
        "veteran": bool(condition.get("veteran")),
        "victories": int(condition.get("victories", 0)),
        "rest_turns": int(condition.get("rest_turns", 0)),
        "veteran_progress": f"{min(int(condition.get('victories', 0)), VETERAN_VICTORIES)}/{VETERAN_VICTORIES}",
    }


def snapshot_statuses(legions: Iterable[Dict[str, Any]], fallback_status: Optional[str] = None) -> Dict[str, int]:
    """Conteggio per stato, utile ai riepiloghi."""
    counts = {name: 0 for name in ALL_STATUSES}
    for legion in legions:
        counts[status_of(legion, fallback_status)] = counts.get(status_of(legion, fallback_status), 0) + 1
    return counts
