"""
War Advisor - Session Abilities

Catalogo delle abilità, stato delle ricerche e risoluzione degli effetti.

Tutto quello che un'abilità *è* sta qui dentro: nome, percorso, turni, prezzo
in grux, prerequisiti, esclusività e — soprattutto — i suoi effetti, espressi
come dati e non come codice. Fuori da questo file ci sono solo agganci corti
marcati [ABILITY-EFFECTS], che chiedono un moltiplicatore o un flag e non
sanno quali abilità esistano.

Aggiungere un'abilità nuova = aggiungere una riga a `CATALOG`. Se usa uno degli
effetti già previsti non serve toccare nient'altro, frontend compreso: la UI
dell'albero si disegna da questo catalogo.

Regole di sistema, valide per player e IA allo stesso modo:

  * una ricerca alla volta. Senza questo vincolo i grux sarebbero l'unico
    limite e al primo turno si avviava tutto l'albero in parallelo;
  * la ricerca si paga all'avvio, e i turni scorrono da lì;
  * `min_turn` tiene le abilità più forti fuori dall'apertura di partita —
    è la garanzia che gli stili di gioco non tocchino lo start-mid game;
  * `exclusive_group`: dentro un gruppo se ne sceglie UNA. Serve agli stili di
    gioco, che altrimenti si sommerebbero tutti a fine partita.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ══════════════════════════════════════════════════════════════════
# Vocabolario degli effetti
# ══════════════════════════════════════════════════════════════════

PATH_ENGINEERING = "Ingegneria"
PATH_ECONOMY = "Economia"
PATH_STYLE = "Stili di Gioco"

PATH_ORDER = (PATH_ENGINEERING, PATH_ECONOMY, PATH_STYLE)

#: Flag = effetti che non sono numeri ma permessi.
FLAG_BUILD_ANYWHERE = "build_anywhere"
FLAG_BUILD_ANY_LEGION = "build_any_legion"
FLAG_BLACK_MARKET = "black_market"
FLAG_SPY_NETWORK = "spy_network"

#: Contesti in cui si chiede il bonus di una unità.
CTX_ATTACK = "attack"
CTX_DEFENSE = "defense"
CTX_SIEGE = "siege"

#: Nei dizionari di bonus vale "qualsiasi unità".
ANY_UNIT = "*"

#: Gruppo di esclusività degli stili di gioco.
STYLE_GROUP = "stile"

#: Chiavi economiche. Sono tutti moltiplicatori (1.0 = nessun effetto)
#: tranne `recruit_cooldown`, che è un numero di turni da sommare.
ECO_MINE_INCOME = "mine_income"
ECO_RECRUIT_COST = "recruit_cost"
ECO_FORTIFICATION_COST = "fortification_cost"
ECO_CASTLE_DAMAGE_TAKEN = "castle_damage_taken"
ECO_RECRUIT_COOLDOWN = "recruit_cooldown"


@dataclass(frozen=True)
class AbilityDef:
    """Definizione statica di un'abilità."""

    ability_id: str
    name: str
    path: str
    description: str
    effect_text: str
    turns_required: int
    grux_cost: int
    min_turn: int = 0
    requires: Tuple[str, ...] = ()
    exclusive_group: Optional[str] = None
    flags: Tuple[str, ...] = ()
    attack_bonus: Mapping[str, float] = field(default_factory=dict)
    defense_bonus: Mapping[str, float] = field(default_factory=dict)
    siege_bonus: Mapping[str, float] = field(default_factory=dict)
    economy: Mapping[str, float] = field(default_factory=dict)

    def bonus_for(self, unit_id: str, context: str) -> float:
        """Bonus frazionario di questa abilità per l'unità nel contesto dato."""
        table = {
            CTX_ATTACK: self.attack_bonus,
            CTX_DEFENSE: self.defense_bonus,
            CTX_SIEGE: self.siege_bonus,
        }.get(context)
        if not table:
            return 0.0
        return float(table.get(ANY_UNIT, 0.0)) + float(table.get(unit_id, 0.0))


# ══════════════════════════════════════════════════════════════════
# Catalogo
# ══════════════════════════════════════════════════════════════════
#
# I numeri sono tarati sulla durata reale delle partite misurate con
# `scripts/balancetest.py` e con le simulazioni delle dottrine IA:
# 117-133 turni a incubo, 212-253 a facile. Da lì i `min_turn`:
#
#   turno 0-15   apertura     nessuna abilità è ancora attiva
#   turno 15-45  metà partita economia e ingegneria di base
#   turno 45+    fine partita stili di gioco, fortezza, costruzione caotica
#
# I bonus di combattimento stanno fra il 3% e il 6% apposta: devono farsi
# sentire su una legione da venti unità, non ribaltare uno scontro.

CATALOG: Tuple[AbilityDef, ...] = (
    # ── Ingegneria ────────────────────────────────────────────────
    AbilityDef(
        ability_id="domain_engineering",
        name="Costruzione Territoriale",
        path=PATH_ENGINEERING,
        description=(
            "Il genio militare smette di lavorare solo sotto i piedi dell'esercito: "
            "miniere e fortificazioni si progettano su tutto il dominio controllato."
        ),
        effect_text="Costruisci su qualsiasi cella controllata, non solo dove ti trovi",
        turns_required=32,
        grux_cost=220,
        min_turn=0,
        flags=(FLAG_BUILD_ANYWHERE,),
    ),
    AbilityDef(
        ability_id="rapid_entrenchment",
        name="Trinceramento Rapido",
        path=PATH_ENGINEERING,
        description=(
            "Palizzate prefabbricate e squadre addestrate a montarle in una notte. "
            "Fortificare smette di essere un lusso da fine partita."
        ),
        effect_text="Fortificazioni -28% di costo",
        turns_required=16,
        grux_cost=150,
        min_turn=6,
        economy={ECO_FORTIFICATION_COST: 0.72},
    ),
    AbilityDef(
        ability_id="fortress_doctrine",
        name="Dottrina Fortezza",
        path=PATH_ENGINEERING,
        description=(
            "Ogni cella tenuta viene trattata come una piccola fortezza: presidi "
            "disposti sui camminamenti, mura del castello rinforzate ai punti deboli."
        ),
        effect_text="Presidi e difensori +10% · castello -10% danni da assedio",
        turns_required=24,
        grux_cost=300,
        min_turn=16,
        requires=("rapid_entrenchment",),
        defense_bonus={ANY_UNIT: 0.10},
        economy={ECO_CASTLE_DAMAGE_TAKEN: 0.90},
    ),
    AbilityDef(
        ability_id="chaotic_engineering",
        name="Costruzione Caotica",
        path=PATH_ENGINEERING,
        description=(
            "Finita la disciplina dei ruoli: picconi in mano a tutti. Qualsiasi "
            "legione costruisce qualsiasi cosa, minerarie e costruzione comprese."
        ),
        effect_text="Ogni legione può costruire miniere e fortificazioni",
        turns_required=30,
        grux_cost=460,
        min_turn=34,
        requires=("domain_engineering",),
        flags=(FLAG_BUILD_ANY_LEGION,),
    ),
    # ── Economia ──────────────────────────────────────────────────
    AbilityDef(
        ability_id="supply_lines",
        name="Linee di Rifornimento",
        path=PATH_ECONOMY,
        description=(
            "Carovane scortate e depositi intermedi: dalle miniere al castello "
            "si perde molto meno per strada."
        ),
        effect_text="Miniere +10% di resa per turno",
        turns_required=18,
        grux_cost=170,
        min_turn=4,
        economy={ECO_MINE_INCOME: 1.10},
    ),
    AbilityDef(
        ability_id="war_industry",
        name="Industria Bellica",
        path=PATH_ECONOMY,
        description=(
            "Fabbriche d'armi a ciclo continuo. Le reclute costano meno e arrivano "
            "più in fretta, perché l'equipaggiamento non si fa più aspettare."
        ),
        effect_text="Reclutamento -12% di costo · cooldown -1 turno",
        turns_required=24,
        grux_cost=330,
        min_turn=18,
        requires=("supply_lines",),
        economy={ECO_RECRUIT_COST: 0.88, ECO_RECRUIT_COOLDOWN: -1},
    ),
    AbilityDef(
        ability_id="black_market",
        name="Mercato Nero",
        path=PATH_ECONOMY,
        description=(
            "Un contatto in un retrobottega che non chiede e non risponde. Blocchi "
            "di truppe già equipaggiate, a prezzi che nessun quartiermastro giustifica."
        ),
        effect_text="Sblocca il Mercato Nero: blocchi scontati, e niente cooldown",
        turns_required=20,
        grux_cost=250,
        min_turn=12,
        flags=(FLAG_BLACK_MARKET,),
    ),
    AbilityDef(
        ability_id="spy_industry",
        name="Industria dello Spionaggio",
        path=PATH_ECONOMY,
        description=(
            "Gli stessi contatti che ti procurano le truppe procurano anche le "
            "carte. Cartografi comprati, corrieri intercettati, un ufficiale "
            "nemico con debiti di gioco: la nebbia sul campo si dirada."
        ),
        effect_text=(
            "Info Strategie e autoreclutamento diventano esatti · "
            "sblocca il dossier sul nemico"
        ),
        turns_required=26,
        grux_cost=340,
        min_turn=20,
        requires=("black_market",),
        flags=(FLAG_SPY_NETWORK,),
    ),
    # ── Stili di gioco (se ne sceglie UNO) ────────────────────────
    AbilityDef(
        ability_id="style_siege",
        name="Scuola d'Assedio",
        path=PATH_STYLE,
        description=(
            "Bombardieri che sanno dove colpisce una palla e dove si apre una "
            "breccia. La tua guerra si decide davanti alle mura."
        ),
        effect_text="Artiglieria +3% in campo, +9% contro mura e fortificazioni",
        turns_required=22,
        grux_cost=280,
        min_turn=24,
        exclusive_group=STYLE_GROUP,
        attack_bonus={"artillery": 0.03},
        defense_bonus={"artillery": 0.03},
        siege_bonus={"artillery": 0.09},
    ),
    AbilityDef(
        ability_id="style_shock",
        name="Scuola d'Urto",
        path=PATH_STYLE,
        description=(
            "Si sfonda al centro e non si guarda indietro: cavalleria in testa, "
            "fanteria pesante subito dietro ad allargare la breccia."
        ),
        effect_text="Cavalleria Leggera +6% e Fanteria Pesante +4% in attacco",
        turns_required=22,
        grux_cost=280,
        min_turn=24,
        exclusive_group=STYLE_GROUP,
        attack_bonus={"light_cavalry": 0.06, "heavy_infantry": 0.04},
    ),
    AbilityDef(
        ability_id="style_shadow",
        name="Scuola dell'Ombra",
        path=PATH_STYLE,
        description=(
            "Nessuna battaglia campale se si può evitarla. Si muove di notte, si "
            "colpisce dove non c'è nessuno a guardare."
        ),
        effect_text="Esploratori e Assassini +6% in attacco, +3% in difesa",
        turns_required=22,
        grux_cost=280,
        min_turn=24,
        exclusive_group=STYLE_GROUP,
        attack_bonus={"scouts": 0.06, "assassins": 0.06},
        defense_bonus={"scouts": 0.03, "assassins": 0.03},
    ),
    AbilityDef(
        ability_id="style_bulwark",
        name="Scuola del Baluardo",
        path=PATH_STYLE,
        description=(
            "Non si conquista: si tiene. Ogni cella presa diventa un problema per "
            "chi prova a riprendersela, e i picchieri chiudono la porta."
        ),
        effect_text="Tutte le truppe +4% in difesa · Picchieri +5%",
        turns_required=22,
        grux_cost=280,
        min_turn=24,
        exclusive_group=STYLE_GROUP,
        defense_bonus={ANY_UNIT: 0.04, "pikemen": 0.05},
    ),
)

ABILITIES: Dict[str, AbilityDef] = {ability.ability_id: ability for ability in CATALOG}

# Compatibilità: il resto del motore chiama questa abilità per nome.
DOMAIN_ENGINEERING_ID = "domain_engineering"
#: Serve a chi deve spiegare all'utente *quale* ricerca gli manca.
SPY_INDUSTRY_ID = "spy_industry"
DOMAIN_ENGINEERING_NAME = ABILITIES[DOMAIN_ENGINEERING_ID].name
DOMAIN_ENGINEERING_TURNS = ABILITIES[DOMAIN_ENGINEERING_ID].turns_required

BLACK_MARKET_ID = "black_market"


# ══════════════════════════════════════════════════════════════════
# Stato di ricerca
# ══════════════════════════════════════════════════════════════════


@dataclass
class AbilityResearchState:
    """Stato ricerca di una singola abilità per un'entità."""

    ability_id: str
    name: str
    turns_required: int
    started_turn: Optional[int] = None
    grux_cost: int = 0

    @property
    def definition(self) -> Optional[AbilityDef]:
        return ABILITIES.get(self.ability_id)

    def is_researching(self) -> bool:
        return self.started_turn is not None

    def turns_elapsed(self, current_turn: int) -> int:
        if self.started_turn is None:
            return 0
        return max(0, current_turn - self.started_turn)

    def turns_remaining(self, current_turn: int) -> int:
        if self.started_turn is None:
            return self.turns_required
        return max(0, self.turns_required - self.turns_elapsed(current_turn))

    def is_unlocked(self, current_turn: int) -> bool:
        return self.started_turn is not None and self.turns_elapsed(current_turn) >= self.turns_required

    def start(self, current_turn: int) -> bool:
        if self.started_turn is not None:
            return False
        self.started_turn = current_turn
        return True

    def to_dict(self, current_turn: int) -> Dict[str, object]:
        definition = self.definition
        return {
            "id": self.ability_id,
            "name": self.name,
            "path": definition.path if definition else "",
            "description": definition.description if definition else "",
            "effect_text": definition.effect_text if definition else "",
            "turns_required": self.turns_required,
            "grux_cost": self.grux_cost,
            "min_turn": definition.min_turn if definition else 0,
            "requires": list(definition.requires) if definition else [],
            "exclusive_group": definition.exclusive_group if definition else None,
            "started_turn": self.started_turn,
            "researching": self.is_researching() and not self.is_unlocked(current_turn),
            "unlocked": self.is_unlocked(current_turn),
            "turns_remaining": self.turns_remaining(current_turn),
        }


StateMap = Dict[str, AbilityResearchState]


def build_default_ability_states(turn_scale: float = 1.0) -> StateMap:
    """Set abilità disponibile per la sessione: tutto il catalogo, da ricercare.

    `turn_scale` accorcia i tempi di ricerca: serve alle difficoltà alte
    dell'IA, che con una ricerca alla volta e partite da 120 turni non
    arriverebbero mai in fondo a un percorso.
    """
    return {
        ability.ability_id: AbilityResearchState(
            ability_id=ability.ability_id,
            name=ability.name,
            turns_required=max(4, int(round(ability.turns_required * turn_scale))),
            grux_cost=ability.grux_cost,
        )
        for ability in CATALOG
    }


# ══════════════════════════════════════════════════════════════════
# Disponibilità di una ricerca
# ══════════════════════════════════════════════════════════════════


def unlocked_ids(states: StateMap, current_turn: int) -> Tuple[str, ...]:
    """Abilità già sbloccate, in ordine di catalogo."""
    return tuple(
        ability_id
        for ability_id in ABILITIES
        if ability_id in states and states[ability_id].is_unlocked(current_turn)
    )


def researching_id(states: StateMap, current_turn: int) -> Optional[str]:
    """Ricerca in corso, se c'è (una sola alla volta)."""
    for ability_id, state in states.items():
        if state.is_researching() and not state.is_unlocked(current_turn):
            return ability_id
    return None


def availability(ability_id: str, states: StateMap, current_turn: int) -> Tuple[bool, str]:
    """Si può avviare questa ricerca? Ritorna (sì/no, motivo se no).

    Il motivo è testo da mostrare: lo usano sia l'errore dell'API sia la
    pastiglia di stato nell'albero delle abilità.
    """
    definition = ABILITIES.get(ability_id)
    state = states.get(ability_id)
    if definition is None or state is None:
        return False, "Abilità sconosciuta."

    if state.is_unlocked(current_turn):
        return False, "Già sbloccata."
    if state.is_researching():
        return False, "Ricerca già in corso."

    busy = researching_id(states, current_turn)
    if busy is not None:
        return False, f"Ricerca occupata: {ABILITIES[busy].name}"

    if current_turn < definition.min_turn:
        return False, f"Disponibile dal turno {definition.min_turn}"

    for required in definition.requires:
        required_state = states.get(required)
        if required_state is None or not required_state.is_unlocked(current_turn):
            required_name = ABILITIES[required].name if required in ABILITIES else required
            return False, f"Richiede: {required_name}"

    if definition.exclusive_group:
        for other in CATALOG:
            if other.ability_id == ability_id:
                continue
            if other.exclusive_group != definition.exclusive_group:
                continue
            other_state = states.get(other.ability_id)
            if other_state is not None and other_state.is_researching():
                return False, f"Stile già scelto: {other.name}"

    return True, ""


def states_payload(
    states: StateMap,
    current_turn: int,
    grux_balance: Optional[int] = None,
) -> Dict[str, Dict[str, object]]:
    """Payload dell'albero abilità per il frontend.

    Porta anche il verdetto di disponibilità già calcolato: la UI non deve
    reimplementare prerequisiti ed esclusività, che vivono solo qui.
    """
    payload: Dict[str, Dict[str, object]] = {}
    for ability_id, state in states.items():
        entry = state.to_dict(current_turn)
        can_start, reason = availability(ability_id, states, current_turn)
        affordable = grux_balance is None or grux_balance >= state.grux_cost
        if can_start and not affordable:
            can_start, reason = False, f"Servono {state.grux_cost} grux"
        entry["can_start"] = can_start
        entry["blocked_reason"] = reason
        payload[ability_id] = entry
    return payload


def path_order() -> List[str]:
    """Percorsi nell'ordine in cui vanno mostrati."""
    seen = [p for p in PATH_ORDER if any(a.path == p for a in CATALOG)]
    for ability in CATALOG:
        if ability.path not in seen:
            seen.append(ability.path)
    return seen


# ══════════════════════════════════════════════════════════════════
# Risoluzione degli effetti
# ══════════════════════════════════════════════════════════════════


def effective_ids(ids: Iterable[str]) -> Tuple[str, ...]:
    """Filtra le abilità che contano davvero.

    Dentro un gruppo esclusivo vale solo la prima sbloccata in ordine di
    catalogo: così anche se qualcosa le sblocca tutte insieme (il pannello di
    debug lo fa apposta) gli stili di gioco non si sommano fra loro.
    """
    taken_groups: set = set()
    result: List[str] = []
    for ability_id in ids:
        definition = ABILITIES.get(ability_id)
        if definition is None:
            continue
        group = definition.exclusive_group
        if group:
            if group in taken_groups:
                continue
            taken_groups.add(group)
        result.append(ability_id)
    return tuple(result)


def has_flag(ids: Iterable[str], flag: str) -> bool:
    """Una delle abilità sbloccate concede questo permesso?"""
    return any(flag in ABILITIES[a].flags for a in effective_ids(ids))


def unit_factor(ids: Iterable[str], unit_id: str, context: str) -> float:
    """Moltiplicatore di una unità nel contesto dato (1.0 = nessun effetto).

    I bonus si sommano prima di essere applicati: due abilità da +5% fanno
    +10%, non +10.25%. Con numeri così piccoli la differenza è nulla, ma la
    somma è quella che si legge nelle descrizioni, e deve tornare.
    """
    total = 0.0
    for ability_id in effective_ids(ids):
        total += ABILITIES[ability_id].bonus_for(unit_id, context)
    return 1.0 + total


def has_unit_effects(ids: Iterable[str], context: str) -> bool:
    """C'è almeno un bonus da applicare in questo contesto?

    Serve a saltare del tutto il giro sulle unità quando non c'è niente da
    moltiplicare: `_unit_battle_value` viene chiamata migliaia di volte a turno.
    """
    for ability_id in effective_ids(ids):
        definition = ABILITIES[ability_id]
        table = {
            CTX_ATTACK: definition.attack_bonus,
            CTX_DEFENSE: definition.defense_bonus,
            CTX_SIEGE: definition.siege_bonus,
        }.get(context)
        if table:
            return True
    return False


def economy_factor(ids: Iterable[str], key: str, default: float = 1.0) -> float:
    """Moltiplicatore economico complessivo per la chiave data."""
    factor = default
    for ability_id in effective_ids(ids):
        value = ABILITIES[ability_id].economy.get(key)
        if value is not None:
            factor *= float(value)
    return factor


def recruit_cooldown_bonus(ids: Iterable[str]) -> int:
    """Turni di cooldown reclutamento in più (negativo = più veloce)."""
    total = 0
    for ability_id in effective_ids(ids):
        total += int(ABILITIES[ability_id].economy.get(ECO_RECRUIT_COOLDOWN, 0))
    return total


# ══════════════════════════════════════════════════════════════════
# Priorità di ricerca dell'IA
# ══════════════════════════════════════════════════════════════════
#
# L'IA ricerca con le stesse regole del giocatore — una alla volta, pagando,
# rispettando prerequisiti e turno minimo. Cambia solo *cosa* sceglie, e
# quanto in là arriva: a facile si ferma all'economia di base, a incubo
# arriva in fondo a tutti e tre i percorsi.

AI_RESEARCH_PLANS: Dict[str, Tuple[str, ...]] = {
    "easy": (
        "supply_lines",
        "domain_engineering",
    ),
    "normal": (
        "supply_lines",
        "rapid_entrenchment",
        "domain_engineering",
        "war_industry",
        "style_shock",
    ),
    "hard": (
        "supply_lines",
        "rapid_entrenchment",
        "war_industry",
        "domain_engineering",
        "fortress_doctrine",
        "style_siege",
        "black_market",
    ),
    "nightmare": (
        "supply_lines",
        "rapid_entrenchment",
        "war_industry",
        "black_market",
        "domain_engineering",
        "fortress_doctrine",
        "style_siege",
        "chaotic_engineering",
    ),
}

#: Quanti grux l'IA tiene comunque da parte: se spendesse fino all'ultimo per
#: ricercare, smetterebbe di reclutare e la ricerca diventerebbe un autogol.
AI_RESEARCH_RESERVE = 120

#: Quanto sono più corte le ricerche dell'IA, per difficoltà.
#:
#: Serve perché le partite durano tanto meno quanto più l'IA è forte — misurate
#: 212-253 turni a facile contro 117-133 a incubo. A tempi pieni chi gioca a
#: incubo vedrebbe l'IA sbloccare MENO abilità di chi gioca a normale, che è
#: esattamente il contrario di quello che deve succedere.
AI_RESEARCH_SCALE: Dict[str, float] = {
    "easy": 1.0,
    "normal": 0.9,
    "hard": 0.7,
    "nightmare": 0.55,
}


def ai_research_scale(difficulty: str) -> float:
    return AI_RESEARCH_SCALE.get(str(difficulty).lower(), 1.0)


def ai_next_research(
    difficulty: str,
    states: StateMap,
    current_turn: int,
    grux_balance: int,
) -> Optional[str]:
    """Prossima abilità che l'IA di questa difficoltà avvierebbe, se può."""
    plan = AI_RESEARCH_PLANS.get(str(difficulty).lower())
    if not plan:
        plan = AI_RESEARCH_PLANS["normal"]

    for ability_id in plan:
        state = states.get(ability_id)
        if state is None:
            continue
        can_start, _ = availability(ability_id, states, current_turn)
        if not can_start:
            continue
        if grux_balance - state.grux_cost < AI_RESEARCH_RESERVE:
            continue
        return ability_id
    return None
