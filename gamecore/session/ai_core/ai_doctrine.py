"""
War Advisor - Dottrine operative dell'IA (un file per tutte le difficoltà)

I file di difficoltà dicono *cosa vuole* l'IA: quanto è aggressiva, quando
assalta, quante legioni schiera. Questo dice **come ci arriva**, cioè la
manovra:

    corsie          ogni legione tiene la sua (sinistra, centro, destra),
                    se no scendono tutte dalla colonna centrale
    aggiramento     il castello si raggiunge da un punto d'attacco laterale,
                    non in linea retta
    vagabondaggio   ai livelli bassi l'IA gironzola invece di andare al sodo
    attesa          e ogni tanto si ferma

Un file solo perché la logica è identica per tutti e cambia solo la tabella di
numeri: aggiungere una difficoltà = aggiungere una riga a `DOCTRINES`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Sequence, Tuple

Pos = Tuple[int, int]

# ── Corsie ─────────────────────────────────────────────────────────
# Espresse come frazione della larghezza mappa, così valgono su qualsiasi
# dimensione. Sinistra e destra stanno larghe davvero: a un quinto e a
# quattro quinti, non a ridosso del centro, altrimenti l'aggiramento non si
# vede nemmeno.
LANE_LEFT = "sinistra"
LANE_CENTER = "centro"
LANE_RIGHT = "destra"

LANE_FRACTIONS: Dict[str, float] = {
    LANE_LEFT: 0.18,
    LANE_CENTER: 0.50,
    LANE_RIGHT: 0.82,
}

#: A quante caselle dal castello nemico si smette di girare largo e si punta
#: dritto: da lì in poi le corsie si richiudono a tenaglia.
DEFAULT_CONVERGE_DISTANCE = 4

#: Quanto prima del castello si piazza il punto d'attacco laterale.
APPROACH_GAP = 3

#: Distanza dal castello oltre la quale un aggiramento già speso torna
#: disponibile: vuol dire che la legione è stata respinta e ricomincia.
RESET_FLANK_DISTANCE = 9


@dataclass(frozen=True)
class Doctrine:
    """Come manovra l'IA a una data difficoltà."""

    name: str
    #: Corsie assegnate alle legioni, a rotazione. Con due voci opposte due
    #: legioni arrivano da lati diversi: è l'accerchiamento.
    lanes: Sequence[str]
    #: Quanto spesso, invece dell'obiettivo ovvio, sceglie una meta laterale.
    wander_chance: float
    #: Raggio del giro a vuoto, in caselle.
    wander_radius: int
    #: Quanto spesso si ferma un turno o due (attesa strategica).
    hold_chance: float
    hold_turns: Tuple[int, int]
    #: Quanto spesso l'assalto al castello passa da un fianco invece che dritto.
    flank_chance: float
    #: Prima di questo turno il castello nemico non è un obiettivo: serve a
    #: togliere la corsa cieca dei livelli bassi, che partivano al turno 4.
    castle_from_turn: int
    #: Distanza a cui le corsie si richiudono sul castello.
    converge_distance: int = DEFAULT_CONVERGE_DISTANCE
    #: Legioni che la dottrina vuole in campo per manovrare (non per difendersi:
    #: quella resta una decisione del profilo di difficoltà). Serve a chi deve
    #: accerchiare: con una legione sola non si accerchia nessuno.
    offensive_legions: int = 1
    #: Da quale turno pretende quelle legioni.
    offensive_from_turn: int = 0
    descrizione: str = ""


# ══════════════════════════════════════════════════════════════════
# I QUATTRO PROFILI
# ══════════════════════════════════════════════════════════════════

DOCTRINES: Dict[str, Doctrine] = {
    "easy": Doctrine(
        name="easy",
        lanes=(LANE_CENTER,),
        wander_chance=0.45,
        wander_radius=4,
        hold_chance=0.22,
        hold_turns=(1, 2),
        flank_chance=0.0,
        castle_from_turn=14,
        offensive_legions=1,
        descrizione="Gironzola, si ferma spesso, arriva al castello tardi e per la via più ovvia.",
    ),
    "normal": Doctrine(
        name="normal",
        lanes=(LANE_LEFT, LANE_RIGHT),
        wander_chance=0.20,
        wander_radius=3,
        hold_chance=0.11,
        hold_turns=(1, 2),
        flank_chance=0.35,
        castle_from_turn=10,
        offensive_legions=1,
        descrizione="Gira ancora, ma comincia a tenersi su una corsia e ogni tanto aggira.",
    ),
    "hard": Doctrine(
        name="hard",
        lanes=(LANE_LEFT, LANE_RIGHT),
        wander_chance=0.06,
        wander_radius=2,
        hold_chance=0.04,
        hold_turns=(1, 1),
        flank_chance=0.80,
        castle_from_turn=0,
        converge_distance=4,
        offensive_legions=2,
        offensive_from_turn=18,
        descrizione="Va a segno: due legioni su corsie opposte, assalto quasi sempre dal fianco.",
    ),
    "nightmare": Doctrine(
        name="nightmare",
        lanes=(LANE_LEFT, LANE_RIGHT, LANE_RIGHT, LANE_LEFT),
        wander_chance=0.02,
        wander_radius=2,
        hold_chance=0.01,
        hold_turns=(1, 1),
        flank_chance=0.92,
        castle_from_turn=0,
        converge_distance=3,
        offensive_legions=3,
        offensive_from_turn=12,
        descrizione="Tenaglia: legioni multiple per lato, corsie larghe fino a ridosso delle mura.",
    ),
}

DEFAULT_DOCTRINE = "normal"


@dataclass
class MovePlan:
    """Cosa fa questa legione, questo turno."""

    target: Optional[Pos]
    lane_col: Optional[int] = None
    hold: bool = False
    reason: str = ""


class DoctrineRuntime:
    """Applica una dottrina alle legioni, tenendo memoria fra un turno e l'altro.

    Lo stato (corsia, punto d'attacco, attesa in corso) vive dentro il
    dizionario della legione: così sopravvive ai salvataggi e sparisce insieme
    alla legione, senza registri paralleli da tenere puliti.
    """

    def __init__(self, doctrine: Doctrine, seed: Optional[int] = None) -> None:
        self.doctrine = doctrine
        self.rng = random.Random(seed)

    # ── Corsie ─────────────────────────────────────────────────────
    def lane_of(self, legion: Dict, legion_index: int) -> str:
        """Corsia della legione, assegnata una volta sola e poi ricordata.

        Ricordarla conta: riassegnarla ogni turno con l'indice della lista
        farebbe cambiare lato alle legioni ogni volta che una muore.
        """
        lane = legion.get("doctrine_lane")
        if lane in LANE_FRACTIONS:
            return lane
        lanes = self.doctrine.lanes or (LANE_CENTER,)
        lane = lanes[legion_index % len(lanes)]
        legion["doctrine_lane"] = lane
        return lane

    def lane_column(self, lane: str, cols: int) -> int:
        fraction = LANE_FRACTIONS.get(lane, 0.5)
        return max(0, min(cols - 1, int(round((cols - 1) * fraction))))

    # ── Piano di movimento ─────────────────────────────────────────
    def plan(
        self,
        *,
        legion: Dict,
        legion_index: int,
        ai_pos: Pos,
        base_target: Optional[Pos],
        enemy_castle: Optional[Pos],
        rows: int,
        cols: int,
        turn: int,
        under_threat: bool,
        is_walkable: Callable[[Pos], bool],
    ) -> MovePlan:
        """Decide meta e corsia di questa legione per questo turno.

        `under_threat` (nemico in casa) spegne tutto: attesa, vagabondaggio e
        aggiramenti sono lussi da fase di manovra, non da emergenza.
        """
        lane = self.lane_of(legion, legion_index)
        lane_col = self.lane_column(lane, cols)

        if under_threat:
            legion.pop("doctrine_hold_until", None)
            legion.pop("doctrine_waypoint", None)
            return MovePlan(target=base_target, lane_col=lane_col, reason="minaccia in casa")

        # 1. Attesa strategica già in corso.
        hold_until = int(legion.get("doctrine_hold_until", 0) or 0)
        if turn <= hold_until:
            return MovePlan(target=base_target, lane_col=lane_col, hold=True,
                            reason="attesa strategica")

        # 2. Nuova attesa.
        if self.doctrine.hold_chance > 0 and self.rng.random() < self.doctrine.hold_chance:
            durata = self.rng.randint(*self.doctrine.hold_turns)
            legion["doctrine_hold_until"] = turn + durata
            return MovePlan(target=base_target, lane_col=lane_col, hold=True,
                            reason=f"attesa strategica ({durata} turni)")

        # 3. Castello troppo presto: ai livelli bassi la corsa cieca al
        #    castello dal turno 4 era la cosa più prevedibile del gioco.
        if (
            enemy_castle is not None
            and base_target is not None
            and tuple(base_target) == tuple(enemy_castle)
            and turn < self.doctrine.castle_from_turn
        ):
            deviata = self._wander_target(ai_pos, rows, cols, is_walkable, enemy_castle)
            if deviata is not None:
                legion.pop("doctrine_waypoint", None)
                return MovePlan(target=deviata, lane_col=lane_col,
                                reason="troppo presto per il castello")

        # 4. Aggiramento: il castello si raggiunge passando da un punto
        #    d'attacco sulla propria corsia, non in linea retta.
        if enemy_castle is not None and base_target is not None and tuple(base_target) == tuple(enemy_castle):
            waypoint = self._approach_point(legion, ai_pos, enemy_castle, rows, cols, lane_col, is_walkable)
            if waypoint is not None:
                return MovePlan(target=waypoint, lane_col=lane_col,
                                reason=f"aggiramento da {lane}")

        # 5. Vagabondaggio: meta laterale invece di quella ovvia.
        if self.doctrine.wander_chance > 0 and self.rng.random() < self.doctrine.wander_chance:
            deviata = self._wander_target(ai_pos, rows, cols, is_walkable, enemy_castle)
            if deviata is not None:
                return MovePlan(target=deviata, lane_col=lane_col, reason="giro largo")

        return MovePlan(target=base_target, lane_col=lane_col)

    # ── Aggiramento ────────────────────────────────────────────────
    def _approach_point(
        self,
        legion: Dict,
        ai_pos: Pos,
        enemy_castle: Pos,
        rows: int,
        cols: int,
        lane_col: int,
        is_walkable: Callable[[Pos], bool],
    ) -> Optional[Pos]:
        """Punto d'attacco laterale, deciso una volta e tenuto fino a lì.

        Sceglierlo ogni turno lo farebbe ballare insieme al lancio del dado, e
        la legione oscillerebbe invece di aggirare.
        """
        distanza = abs(ai_pos[0] - enemy_castle[0]) + abs(ai_pos[1] - enemy_castle[1])

        # A ridosso delle mura la manovra è finita: si converge.
        if distanza <= self.doctrine.converge_distance:
            legion.pop("doctrine_waypoint", None)
            return None

        memorizzato = legion.get("doctrine_waypoint")
        if isinstance(memorizzato, (list, tuple)) and len(memorizzato) == 2:
            waypoint = (int(memorizzato[0]), int(memorizzato[1]))
            arrivata = abs(ai_pos[0] - waypoint[0]) + abs(ai_pos[1] - waypoint[1]) <= 1
            if not arrivata:
                return waypoint
            legion.pop("doctrine_waypoint", None)
            legion["doctrine_flanked"] = True
            return None

        # Si aggira UNA volta per avvicinamento. Senza questo freno la legione
        # arrivava sul fianco, puntava il castello, al turno dopo si rilanciava
        # il dado e tornava sul fianco: oscillava a due passi dalle mura invece
        # di assaltarle. Il conto riparte solo se viene ricacciata indietro.
        if legion.get("doctrine_flanked"):
            if distanza >= RESET_FLANK_DISTANCE:
                legion.pop("doctrine_flanked", None)
            return None

        if self.rng.random() >= self.doctrine.flank_chance:
            return None

        # Il punto sta qualche casella prima del castello, sulla propria corsia:
        # ci si arriva di lato e si scende sulle mura da lì.
        verso = -1 if ai_pos[0] < enemy_castle[0] else 1
        riga = enemy_castle[0] + (verso * APPROACH_GAP)
        riga = max(0, min(rows - 1, riga))

        for scarto in (0, 1, -1, 2, -2):
            candidato = (riga, max(0, min(cols - 1, lane_col + scarto)))
            if candidato == tuple(enemy_castle) or not is_walkable(candidato):
                continue
            # Se ci è già praticamente sopra non è un aggiramento, è un giro a
            # vuoto: si considera fatto e si punta il castello.
            if abs(ai_pos[0] - candidato[0]) + abs(ai_pos[1] - candidato[1]) <= 2:
                legion["doctrine_flanked"] = True
                return None
            legion["doctrine_waypoint"] = candidato
            return candidato
        return None

    # ── Vagabondaggio ──────────────────────────────────────────────
    def _wander_target(
        self,
        ai_pos: Pos,
        rows: int,
        cols: int,
        is_walkable: Callable[[Pos], bool],
        enemy_castle: Optional[Pos],
    ) -> Optional[Pos]:
        """Meta a caso nei dintorni, mai il castello nemico."""
        raggio = max(1, self.doctrine.wander_radius)
        for _ in range(12):
            riga = ai_pos[0] + self.rng.randint(-raggio, raggio)
            colonna = ai_pos[1] + self.rng.randint(-raggio, raggio)
            candidato = (max(0, min(rows - 1, riga)), max(0, min(cols - 1, colonna)))
            if candidato == tuple(ai_pos):
                continue
            if enemy_castle is not None and candidato == tuple(enemy_castle):
                continue
            if is_walkable(candidato):
                return candidato
        return None

    # ── Legioni volute dalla manovra ───────────────────────────────
    def offensive_legions(self, turn: int) -> int:
        """Quante legioni servono per manovrare come dice la dottrina.

        Con una legione sola non esiste accerchiamento: incubo ne vuole tre,
        difficile due, gli altri restano com'erano.
        """
        if turn < self.doctrine.offensive_from_turn:
            return 1
        return max(1, int(self.doctrine.offensive_legions))


def for_difficulty(difficulty: Optional[str], seed: Optional[int] = None) -> DoctrineRuntime:
    """Dottrina della difficoltà indicata, con ripiego sul profilo normale."""
    key = (difficulty or "").strip().lower()
    doctrine = DOCTRINES.get(key, DOCTRINES[DEFAULT_DOCTRINE])
    return DoctrineRuntime(doctrine, seed=seed)
