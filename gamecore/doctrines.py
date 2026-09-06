"""
War Advisor - Layer dottrine (SGANCIABILE)

Oltre al moltiplicatore di forza che il motore ricava dalla compatibilità,
ogni strategia ha un effetto unico che cambia *come si gioca*. Una legione ha
una strategia sola, quindi gli effetti non si cumulano mai.

`engine.py` e i file in `data/` non sanno che questo layer esiste: fuori da qui
ci sono solo agganci marcati [DOCTRINE-LAYER], tutti inerti se il file sparisce.
Per rimuoverlo: `grep -rn "DOCTRINE-LAYER" --include=*.py .`, cancella questo
file e togli i blocchi marcati.

Due regole valgono per tutte:
  · LA PORTA — l'effetto si accende solo con la composizione giusta, quindi si
    paga in truppe comprate invece di essere un interruttore gratuito;
  · L'ATTRITO — l'effetto vale dal turno dopo il cambio e fra un cambio e
    l'altro passano tre turni, se no una legione sola le userebbe tutte a
    rotazione tenendo ogni effetto sempre acceso.

Implementate:
  Blitz                  chi perde contro di lei si demoralizza il doppio
  Accerchiamento         il difensore perde più truppe (solo in attacco)
  Manovra sui Fianchi    +40 punti movimento
  Schermo e Fuoco        fortifica senza genieri e gratis fino al livello 2
  Difesa in Profondità   ripiega di una cella, non fino al castello

Le altre cinque non hanno ancora effetto e si comportano come prima.
"""

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ── Identificativi (coincidono con data/strategies.json) ───────────
FRONTAL_ASSAULT = "frontal_assault"
AMBUSH = "ambush"
DEFENSE_DEPTH = "defense_depth"
FLANK_MANEUVER = "flank_maneuver"
GUERRILLA = "guerrilla"
BREAKTHROUGH = "breakthrough"
ENCIRCLEMENT = "encirclement"
SCREEN_AND_FIRE = "screen_and_fire"
TACTICAL_RETREAT = "tactical_retreat"
BLITZ = "blitz"

# ── Unità citate dalle porte ───────────────────────────────────────
HEAVY_INFANTRY = "heavy_infantry"
LIGHT_CAVALRY = "light_cavalry"
ARCHERS = "archers"
PIKEMEN = "pikemen"
ARTILLERY = "artillery"
ASSASSINS = "assassins"

# ══════════════════════════════════════════════════════════════════
# ATTRITO
# ══════════════════════════════════════════════════════════════════

#: Turni minimi fra un cambio di dottrina e il successivo, per legione.
CHANGE_COOLDOWN_TURNS = 3

#: Ritardo prima che l'effetto entri in vigore: si decide prima di vedere come
#: va lo scontro, non dopo.
ACTIVATION_DELAY_TURNS = 1

# ══════════════════════════════════════════════════════════════════
# PORTE DI COMPOSIZIONE
# ══════════════════════════════════════════════════════════════════

FLANK_MIN_CAVALRY = 3
DEFENSE_DEPTH_MIN_PIKEMEN = 3

#: Accerchiamento: la morsa vuole tutti i pezzi, quindi si accende solo da metà
#: partita, quando le legioni sono grandi. Se risulta troppo tardiva, è questa
#: la lista da accorciare.
ENCIRCLEMENT_REQUIRED_TYPES: Tuple[str, ...] = (
    ARCHERS, ASSASSINS, LIGHT_CAVALRY, HEAVY_INFANTRY,
)
ENCIRCLEMENT_MIN_TYPES_PRESENT = len(ENCIRCLEMENT_REQUIRED_TYPES)

#: Schermo e Fuoco: i pezzi che sparano e lo schermo che li copre.
SCREEN_MIN_ARTILLERY = 1
SCREEN_MIN_SHIELD = 1

#: Blitz: la carica pura. Un'unità di un altro tipo e non è più un blitz.
BLITZ_ONLY_TYPE = LIGHT_CAVALRY

# ══════════════════════════════════════════════════════════════════
# GRANDEZZA DEGLI EFFETTI
# ══════════════════════════════════════════════════════════════════

#: Accerchiamento. Sopra il +25% il tetto del motore (52% di perdite per il
#: lato più forte) se lo mangerebbe proprio dove l'effetto dovrebbe vedersi.
ENCIRCLEMENT_LOSS_MULTIPLIER = 1.25

#: Blitz. Una sconfitta sola basta a mandare sotto la soglia di Demoralizzate;
#: non è definitivo, il morale risale da solo.
BLITZ_MORALE_MULTIPLIER = 2.0

#: Manovra sui Fianchi. Turni di blocco dopo la mossa, per terreno:
#:
#:                    100 pt (norma)   140 pt   180 pt
#:     Foresta  140          1            0        0
#:     Palude   180          1            1        0
#:     Montagna 220          2            1        1
#:
#: Con +40 la foresta smette di bloccare e la montagna passa da due turni a
#: uno; per sbloccare anche la palude servirebbero +80. Tenuto basso: il
#: terreno è metà del disegno della mappa.
FLANK_EXTRA_MOVEMENT_POINTS = 40

#: Schermo e Fuoco. Fin qui la fortificazione è gratis e non servono genieri;
#: dal livello successivo si paga come sempre. Il tetto basso evita che
#: parcheggiare una legione produca una fortezza (due livelli ≈ 166 grux).
SCREEN_FREE_FORTIFICATION_LEVEL = 2

#: Il proprio castello resta fuori dallo sconto: ha un tetto suo e riduce i
#: danni d'assedio, regalarne i primi livelli è un'altra partita.
SCREEN_FREE_ON_CASTLE = False

# ══════════════════════════════════════════════════════════════════
# PORTA
# ══════════════════════════════════════════════════════════════════


def _counts(units: Optional[Iterable[str]]) -> Counter:
    return Counter(units or ())


def gate_passed(strategy_id: str, units: Optional[Iterable[str]]) -> bool:
    """La legione ha la composizione che quella dottrina richiede?

    Una dottrina senza effetto non ha porta: restituisce sempre False, così
    nessun ramo del motore la tratta come attiva.
    """
    conteggi = _counts(units)
    totale = sum(conteggi.values())
    if totale <= 0:
        return False

    if strategy_id == FLANK_MANEUVER:
        return conteggi[LIGHT_CAVALRY] >= FLANK_MIN_CAVALRY

    if strategy_id == DEFENSE_DEPTH:
        return conteggi[PIKEMEN] >= DEFENSE_DEPTH_MIN_PIKEMEN

    if strategy_id == ENCIRCLEMENT:
        presenti = sum(1 for tipo in ENCIRCLEMENT_REQUIRED_TYPES if conteggi[tipo] > 0)
        return presenti >= ENCIRCLEMENT_MIN_TYPES_PRESENT

    if strategy_id == SCREEN_AND_FIRE:
        # Lo schermo è chi sta davanti ai pezzi: fanteria pesante o picchieri.
        schermo = conteggi[HEAVY_INFANTRY] + conteggi[PIKEMEN]
        return conteggi[ARTILLERY] >= SCREEN_MIN_ARTILLERY and schermo >= SCREEN_MIN_SHIELD

    if strategy_id == BLITZ:
        return conteggi[BLITZ_ONLY_TYPE] == totale

    return False


def gate_text(strategy_id: str) -> str:
    """Cosa serve, in una riga, per l'interfaccia e per i log."""
    return {
        FLANK_MANEUVER: f"almeno {FLANK_MIN_CAVALRY} Cavallerie Leggere",
        DEFENSE_DEPTH: f"almeno {DEFENSE_DEPTH_MIN_PIKEMEN} Picchieri",
        ENCIRCLEMENT: "Arcieri, Assassini, Cavalleria e Fanteria Pesante tutti presenti",
        SCREEN_AND_FIRE: "almeno un'Artiglieria e una truppa che le faccia da schermo",
        BLITZ: "solo Cavalleria Leggera",
    }.get(strategy_id, "")


def effect_text(strategy_id: str) -> str:
    """Cosa fa, in una riga."""
    return {
        FLANK_MANEUVER: (
            f"+{FLANK_EXTRA_MOVEMENT_POINTS} punti movimento: la foresta non blocca "
            f"più e la montagna costa un turno invece di due"
        ),
        DEFENSE_DEPTH: "se perde arretra di una cella invece di tornare al castello",
        ENCIRCLEMENT: (
            f"in attacco il difensore perde il "
            f"{int((ENCIRCLEMENT_LOSS_MULTIPLIER - 1) * 100)}% di truppe in più"
        ),
        SCREEN_AND_FIRE: (
            f"fortifica senza genieri e gratis fino al livello "
            f"{SCREEN_FREE_FORTIFICATION_LEVEL}"
        ),
        BLITZ: "chi perde contro di lei lascia il doppio del morale",
    }.get(strategy_id, "")


def has_effect(strategy_id: str) -> bool:
    """Questa dottrina ha già un effetto scritto?"""
    return bool(effect_text(strategy_id))


def status_text(strategy_id: str, units: Optional[Iterable[str]]) -> str:
    """A che punto è la dottrina, in una riga.

    La porta è invisibile: senza questa riga adottarla con la composizione
    sbagliata non dà nessun segnale e sembra che il gioco sia rotto.
    """
    if not has_effect(strategy_id):
        return "nessun effetto speciale"
    if gate_passed(strategy_id, units):
        return effect_text(strategy_id)
    return "effetto spento: servono %s" % gate_text(strategy_id)


# ══════════════════════════════════════════════════════════════════
# ATTIVAZIONE (porta + attrito)
# ══════════════════════════════════════════════════════════════════


def is_active(
    strategy_id: str,
    units: Optional[Iterable[str]],
    *,
    turn: int,
    since_turn: Optional[int],
) -> bool:
    """L'effetto è acceso adesso su questa legione?

    `since_turn` è il turno di adozione. Con None — legioni nate prima che il
    layer esistesse — vale come adottata da sempre.
    """
    if not gate_passed(strategy_id, units):
        return False
    if since_turn is None:
        return True
    return int(turn) >= int(since_turn) + ACTIVATION_DELAY_TURNS


def can_change(turn: int, last_change_turn: Optional[int]) -> bool:
    """È passato abbastanza tempo dall'ultimo cambio di dottrina?"""
    if last_change_turn is None:
        return True
    return int(turn) - int(last_change_turn) >= CHANGE_COOLDOWN_TURNS


def turns_before_change(turn: int, last_change_turn: Optional[int]) -> int:
    """Quanti turni mancano al prossimo cambio consentito."""
    if last_change_turn is None:
        return 0
    return max(0, CHANGE_COOLDOWN_TURNS - (int(turn) - int(last_change_turn)))


# ══════════════════════════════════════════════════════════════════
# GLI EFFETTI
# ══════════════════════════════════════════════════════════════════


def enemy_loss_multiplier(
    strategy_id: str,
    units: Optional[Iterable[str]],
    *,
    turn: int,
    since_turn: Optional[int],
    attacking: bool,
) -> float:
    """Accerchiamento: la morsa fa più morti, ma solo quando è lei ad attaccare.

    In difesa non fa niente, ed è il costo che la rende una scelta.
    """
    if not attacking or strategy_id != ENCIRCLEMENT:
        return 1.0
    if not is_active(strategy_id, units, turn=turn, since_turn=since_turn):
        return 1.0
    return ENCIRCLEMENT_LOSS_MULTIPLIER


def scaled_losses(base_losses: int, multiplier: float) -> int:
    """Perdite ritoccate dalla morsa, arrotondate per eccesso a metà.

    Con l'arrotondamento pari di Python un +25% su 2 perdite restava 2, cioè
    niente proprio negli scontri piccoli, che sono la maggioranza.
    """
    if base_losses <= 0 or multiplier <= 1.0:
        return base_losses
    return max(base_losses, int(base_losses * multiplier + 0.5))


def morale_loss_multiplier(
    winner_strategy_id: str,
    winner_units: Optional[Iterable[str]],
    *,
    turn: int,
    since_turn: Optional[int],
) -> float:
    """Blitz: lo sfondamento lascia il segno oltre lo scontro.

    Si legge sulla dottrina di CHI VINCE e si applica al morale di chi perde.
    """
    if winner_strategy_id != BLITZ:
        return 1.0
    if not is_active(winner_strategy_id, winner_units, turn=turn, since_turn=since_turn):
        return 1.0
    return BLITZ_MORALE_MULTIPLIER


def movement_points(
    strategy_id: str,
    units: Optional[Iterable[str]],
    *,
    turn: int,
    since_turn: Optional[int],
    base_points: int,
) -> int:
    """Manovra sui Fianchi: la colonna a cavallo passa dove le altre si fermano."""
    if strategy_id != FLANK_MANEUVER:
        return base_points
    if not is_active(strategy_id, units, turn=turn, since_turn=since_turn):
        return base_points
    return base_points + FLANK_EXTRA_MOVEMENT_POINTS


def retreats_one_cell(
    strategy_id: str,
    units: Optional[Iterable[str]],
    *,
    turn: int,
    since_turn: Optional[int],
) -> bool:
    """Difesa in Profondità: cede terreno, non l'esercito.

    Invece di riattraversare mezza mappa fino al castello arretra di una cella:
    il costo è che resta a contatto e il turno dopo la ribeccano.
    """
    if strategy_id != DEFENSE_DEPTH:
        return False
    return is_active(strategy_id, units, turn=turn, since_turn=since_turn)


def fortification_relief(
    strategy_id: str,
    units: Optional[Iterable[str]],
    *,
    turn: int,
    since_turn: Optional[int],
    current_level: int,
    is_castle: bool = False,
) -> Optional[Dict[str, bool]]:
    """Schermo e Fuoco: posizioni preparate.

    La legione alza il muro da sé e non paga i primi livelli, ma solo su ordine
    del giocatore: non è un automatismo, se no la mappa si riempirebbe di forti.
    None quando la dottrina non c'entra, così il chiamante non cambia niente.
    """
    if strategy_id != SCREEN_AND_FIRE:
        return None
    if not is_active(strategy_id, units, turn=turn, since_turn=since_turn):
        return None
    gratis = int(current_level) < SCREEN_FREE_FORTIFICATION_LEVEL
    if is_castle and not SCREEN_FREE_ON_CASTLE:
        gratis = False
    # I genieri non servono nemmeno per i livelli alti: la dottrina è quella
    # del cantiere, il tetto riguarda solo chi paga.
    return {"skip_engineers": True, "free": gratis}


# ══════════════════════════════════════════════════════════════════
# SCELTA DELLA DOTTRINA PER L'IA
# ══════════════════════════════════════════════════════════════════

#: Punteggio di una dottrina che passa la porta ma non c'entra con la
#: situazione: serve a non azzerare le candidate.
AI_BASE_SCORE = 1.0

#: Quanto pesa il fatto che la dottrina sia quella giusta per il momento.
AI_SITUATION_BONUS = 2.0

#: Una dottrina senza effetto non è sbagliata, è solo inutile: vale meno ma
#: resta scegliibile, se no l'IA facile sceglierebbe sempre fra le cinque
#: implementate e non sembrerebbe casuale.
AI_NO_EFFECT_SCORE = 0.55

#: Dottrine che vogliono andare addosso a qualcuno e dottrine che vogliono
#: tenere terreno. Serve ai profili che leggono come gioca il player e ne
#: ricavano una postura (per ora solo l'incubo, `strategy_bias`).
OFFENSIVE_DOCTRINES = (FRONTAL_ASSAULT, BLITZ, BREAKTHROUGH, ENCIRCLEMENT,
                       FLANK_MANEUVER)
DEFENSIVE_DOCTRINES = (DEFENSE_DEPTH, SCREEN_AND_FIRE, TACTICAL_RETREAT,
                       AMBUSH, GUERRILLA)

#: Quanto la postura sposta il punteggio. Senza, l'IA che "cambia strategia
#: perché ti legge come aggressivo" lo scriveva solo nel log: a combattere
#: andava comunque la dottrina scelta legione per legione.
AI_POSTURE_WEIGHT = 0.6

#: Quota minima del miglior fattore di forza perché una dottrina resti in
#: lista. La strategia moltiplica la forza fra 0.30 e 2.35: senza filtro l'IA
#: sorteggiava anche quelle incompatibili e si dimezzava da sola. La soglia
#: scala con la difficoltà: chi sceglie stringe, chi sorteggia scarta solo i
#: disastri, se no il filtro rafforzerebbe anche facile e normale.
AI_MIN_FACTOR_RATIO = 0.75
AI_MIN_FACTOR_RATIO_RANDOM = 0.55

#: Durezza oltre la quale il filtro è già al massimo.
AI_FACTOR_FULL_SHARPNESS = 4.0


def ai_factor_floor(sharpness: float) -> float:
    """Quanto stringe il filtro, data la durezza del profilo di difficoltà."""
    quota = min(1.0, max(0.0, float(sharpness) / AI_FACTOR_FULL_SHARPNESS))
    return AI_MIN_FACTOR_RATIO_RANDOM + (
        AI_MIN_FACTOR_RATIO - AI_MIN_FACTOR_RATIO_RANDOM
    ) * quota


def ai_candidates(units: Optional[Iterable[str]]) -> List[str]:
    """Le dottrine che questa legione può davvero adottare, più le neutre."""
    tutte = (
        FRONTAL_ASSAULT, AMBUSH, DEFENSE_DEPTH, FLANK_MANEUVER, GUERRILLA,
        BREAKTHROUGH, ENCIRCLEMENT, SCREEN_AND_FIRE, TACTICAL_RETREAT, BLITZ,
    )
    return [sid for sid in tutte if gate_passed(sid, units) or not has_effect(sid)]


def ai_viable(
    candidates: Sequence[str],
    strength_factors: Sequence[float],
    floor_ratio: Optional[float] = None,
) -> List[int]:
    """Indici delle candidate che non indeboliscono la legione oltre soglia.

    Il chiamante passa il fattore di forza di ogni candidata; qui si scartano
    quelle troppo sotto la migliore. Ne resta sempre almeno una.
    """
    if not candidates or not strength_factors:
        return list(range(len(candidates)))
    migliore = max(strength_factors)
    if migliore <= 0.0:
        return list(range(len(candidates)))
    quota = AI_MIN_FACTOR_RATIO if floor_ratio is None else float(floor_ratio)
    tenuti = [i for i, f in enumerate(strength_factors) if f >= migliore * quota]
    return tenuti or [strength_factors.index(migliore)]


def ai_scores(
    units: Optional[Iterable[str]],
    candidates: Sequence[str],
    situation: Dict[str, Any],
    strength_factors: Optional[Sequence[float]] = None,
) -> List[float]:
    """Quanto vale ogni dottrina per l'IA, in questa situazione.

    `situation` sono le letture grossolane fatte dal motore:
        assalto      sta andando addosso al castello nemico
        contatto     ha un nemico adiacente adesso
        in_ritirata  è sotto pressione / morale basso
        terreno_duro il percorso davanti passa per bosco, palude o montagna
        postura      quanto il profilo vuole attaccare o difendere, se lo sa

    `strength_factors` pesa il punteggio sulla forza che quella strategia dà
    davvero a questa legione. Quanto dare retta al risultato lo decide la
    difficoltà con `doctrine_sharpness()`: a facile la lista è sorteggiata.
    """
    assalto = bool(situation.get("assalto"))
    contatto = bool(situation.get("contatto"))
    ritirata = bool(situation.get("in_ritirata"))
    duro = bool(situation.get("terreno_duro"))
    postura = situation.get("postura") or {}

    migliore = max(strength_factors) if strength_factors else 0.0

    punteggi: List[float] = []
    for posto, sid in enumerate(candidates):
        if not has_effect(sid):
            punteggio = AI_NO_EFFECT_SCORE
        else:
            punteggio = AI_BASE_SCORE
            if sid in (ENCIRCLEMENT, BLITZ) and contatto:
                punteggio += AI_SITUATION_BONUS
            elif sid == FLANK_MANEUVER and duro:
                punteggio += AI_SITUATION_BONUS
            elif sid == SCREEN_AND_FIRE and not assalto and not contatto:
                # Fortificare ha senso quando si tiene una posizione, non
                # mentre si marcia addosso a qualcuno.
                punteggio += AI_SITUATION_BONUS
            elif sid == DEFENSE_DEPTH and (ritirata or (contatto and not assalto)):
                punteggio += AI_SITUATION_BONUS

        punteggio *= _peso_postura(sid, postura)

        if migliore > 0.0 and posto < len(strength_factors):
            punteggio *= strength_factors[posto] / migliore

        punteggi.append(punteggio)
    return punteggi


def _peso_postura(strategy_id: str, postura: Dict[str, float]) -> float:
    """Quanto la postura del profilo tira verso questa dottrina.

    `postura` è il dizionario {offense, defense} che i profili evoluti
    ricavano leggendo come gioca il player; senza, tutte le dottrine pesano
    uguale e non cambia niente.
    """
    if not postura:
        return 1.0
    if strategy_id in OFFENSIVE_DOCTRINES:
        spinta = float(postura.get("offense", 0.5))
    elif strategy_id in DEFENSIVE_DOCTRINES:
        spinta = float(postura.get("defense", 0.5))
    else:
        return 1.0
    return max(0.1, 1.0 + AI_POSTURE_WEIGHT * (spinta - 0.5))
