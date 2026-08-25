"""
War Advisor - Carovane di rinforzo dell'IA

Le reclute dell'IA non compaiono più dentro le legioni al fronte: si radunano
al castello e ci marciano.

Perché esiste
─────────────
L'IA ha un'architettura diversa da quella del player: `ai_units` è l'esercito
autoritativo e le legioni ne sono una *vista* (vedi `_sync_ai_legion_units`).
Effetto collaterale: qualunque truppa entrasse in `ai_units` compariva
all'istante dentro la legione, ovunque fosse.

Misurato su 12 partite complete prima di questo modulo: 989 reclute, di cui
**967 (il 98%) comparse in una legione lontana dal castello**, mediana 8
caselle, massimo 18. Alla velocità reale delle legioni IA — 0,76 caselle per
turno, anch'essa misurata — la recluta mediana saltava una decina di turni di
marcia, e non rischiava mai di essere intercettata perché la strada non la
faceva.

Il player non ha niente del genere: le sue reclute restano in riserva al
castello, e per portarle al fronte deve formare una legione nuova (che nasce a
castello) o richiamare quella in campo, perdendone la posizione.

Come funziona
─────────────
Due tempi.

1. **Raduno.** La recluta esce da `ai_units` e aspetta al castello. Non è più
   parte dell'esercito: non conta in battaglia e non gonfia la forza dell'IA.
2. **Marcia.** Quando il raduno è abbastanza numeroso — o quando il primo
   arrivato ha aspettato troppo — parte una carovana diretta al fronte di quel
   momento. All'arrivo le truppe rientrano in `ai_units` e
   `_sync_ai_legion_units` le distribuisce come sempre.

Il raduno non è burocrazia: senza, ogni singola recluta faceva una carovana per
conto suo e ne uscivano **92-121 a partita**, cioè una riga di registro ogni
due turni. Un rinforzo che il giocatore non riesce a leggere non è visibile,
è rumore. Radunate, diventano una trentina di carovane vere.

Il viaggio è a senso unico e non si aggiorna: la carovana parte per il fronte
di quel momento. Se la legione nel frattempo si sposta, le truppe si uniscono
comunque all'esercito — sono rinforzi che raggiungono il grosso, non un pacco
con l'indirizzo scritto sopra.

Bilanciamento
─────────────
Costo misurato per l'IA rispetto al teletrasporto, su 6 mappe per difficoltà:
easy +1%, normal +9%, hard +7%, nightmare +7% di turni in più per chiudere la
partita. La scala di difficoltà resta ordinata.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Caselle per turno delle legioni IA, misurate su 12 partite complete (1869
#: caselle in 2458 turni). È il passo con cui marciano anche le carovane: non
#: avrebbe senso che i rifornimenti viaggiassero più in fretta dell'esercito.
VELOCITA_CASELLE_PER_TURNO = 0.76

#: Nessuna carovana arriva nello stesso turno in cui parte, nemmeno per una
#: casella: il viaggio deve sempre lasciare al giocatore almeno un turno.
VIAGGIO_MINIMO_TURNI = 1

#: Da quante truppe in poi vale la pena mettersi in marcia.
PARTENZA_MINIMA_UNITA = 3

#: Dopo quanti turni il raduno parte comunque, anche in pochi: un rinforzo che
#: non parte mai non è un rinforzo, e l'IA recluta a ritmi diversi a seconda
#: della difficoltà e di come le va l'economia.
ATTESA_MASSIMA_TURNI = 5


def turni_di_viaggio(distanza: int) -> int:
    """Quanti turni di marcia per coprire `distanza` caselle."""
    if distanza <= 0:
        return 0
    return max(VIAGGIO_MINIMO_TURNI, int(math.ceil(distanza / VELOCITA_CASELLE_PER_TURNO)))


def distanza_caselle(a: Sequence[int], b: Sequence[int]) -> int:
    """Distanza in caselle fra due posizioni (le legioni si muovono in croce)."""
    return abs(int(a[0]) - int(b[0])) + abs(int(a[1]) - int(b[1]))


@dataclass
class Carovana:
    """Un gruppo di truppe in marcia dal castello verso il fronte."""

    id: int
    unita: List[str]
    partenza_turno: int
    arrivo_turno: int
    origine: Tuple[int, int]
    destinazione: Tuple[int, int]
    distanza: int
    legione: Optional[str] = None      # nome della legione a cui puntava

    def turni_mancanti(self, turno: int) -> int:
        return max(0, self.arrivo_turno - turno)

    def to_dict(self, turno: int) -> Dict[str, Any]:
        return {
            "id": self.id,
            "unita": list(self.unita),
            "quantita": len(self.unita),
            "partenza_turno": self.partenza_turno,
            "arrivo_turno": self.arrivo_turno,
            "turni_mancanti": self.turni_mancanti(turno),
            "origine": list(self.origine),
            "destinazione": list(self.destinazione),
            "distanza": self.distanza,
            "legione": self.legione,
        }


@dataclass
class Convogli:
    """Il raduno al castello e le carovane in viaggio."""

    _raduno: List[str] = field(default_factory=list)
    _raduno_dal_turno: Optional[int] = None
    _in_viaggio: List[Carovana] = field(default_factory=list)
    _prossimo_id: int = 1

    # ── Raduno ───────────────────────────────────────────────────

    def raduna(self, unita: Sequence[str], *, turno: int) -> None:
        """Aggiunge truppe al raduno al castello."""
        unita = [str(u) for u in unita]
        if not unita:
            return
        if not self._raduno:
            self._raduno_dal_turno = turno
        self._raduno.extend(unita)

    def raduno(self) -> List[str]:
        return list(self._raduno)

    def raduno_pronto(self, turno: int) -> bool:
        """Il raduno è abbastanza numeroso, o ha aspettato abbastanza?"""
        if not self._raduno:
            return False
        if len(self._raduno) >= PARTENZA_MINIMA_UNITA:
            return True
        if self._raduno_dal_turno is None:
            return False
        return (turno - self._raduno_dal_turno) >= ATTESA_MASSIMA_TURNI

    # ── Partenza ─────────────────────────────────────────────────

    def parti(
        self,
        *,
        turno: int,
        origine: Sequence[int],
        destinazione: Sequence[int],
        legione: Optional[str] = None,
    ) -> Optional[Carovana]:
        """Mette in marcia il raduno. None se non c'è niente da mandare."""
        if not self._raduno:
            return None

        distanza = distanza_caselle(origine, destinazione)
        viaggio = turni_di_viaggio(distanza)
        if viaggio <= 0:
            return None

        carovana = Carovana(
            id=self._prossimo_id,
            unita=list(self._raduno),
            partenza_turno=turno,
            arrivo_turno=turno + viaggio,
            origine=(int(origine[0]), int(origine[1])),
            destinazione=(int(destinazione[0]), int(destinazione[1])),
            distanza=distanza,
            legione=legione,
        )
        self._prossimo_id += 1
        self._in_viaggio.append(carovana)
        self._raduno = []
        self._raduno_dal_turno = None
        return carovana

    def svuota_raduno(self) -> List[str]:
        """Restituisce il raduno e lo azzera, senza farlo partire.

        Serve quando non c'è nessun fronte da raggiungere: le truppe rientrano
        nell'esercito invece di restare in un limbo al castello.
        """
        unita = list(self._raduno)
        self._raduno = []
        self._raduno_dal_turno = None
        return unita

    # ── Arrivo ───────────────────────────────────────────────────

    def arrivate(self, turno: int) -> List[Carovana]:
        """Toglie dalla lista e restituisce le carovane giunte a destinazione."""
        giunte = [c for c in self._in_viaggio if turno >= c.arrivo_turno]
        if giunte:
            self._in_viaggio = [c for c in self._in_viaggio if turno < c.arrivo_turno]
        return giunte

    # ── Lettura ──────────────────────────────────────────────────

    def in_viaggio(self) -> List[Carovana]:
        return list(self._in_viaggio)

    def unita_in_marcia(self) -> int:
        """Truppe fuori dall'esercito: in viaggio più quelle al raduno."""
        return sum(len(c.unita) for c in self._in_viaggio) + len(self._raduno)

    def to_payload(self, turno: int) -> Dict[str, Any]:
        """Quello che il frontend mostra al giocatore."""
        carovane = [c.to_dict(turno) for c in sorted(self._in_viaggio, key=lambda c: c.arrivo_turno)]
        return {
            "carovane": carovane,
            "in_raduno": len(self._raduno),
            "unita_in_marcia": self.unita_in_marcia(),
            "prossimo_arrivo": carovane[0]["arrivo_turno"] if carovane else None,
        }

    def __len__(self) -> int:
        return len(self._in_viaggio)
