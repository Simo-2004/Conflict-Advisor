"""
War Advisor - Canale eventi (SGANCIABILE)

Dice al frontend *cosa* è successo e *dove*, in forma di dati.

Perché esiste
─────────────
Fino a qui l'unico racconto di un turno era `battle_log`, cioè un elenco di
frasi. Per scriverci sopra un effetto — un lampo sulla cella dove si è
combattuto, una scossa sul castello colpito — bisognava rileggere quelle frasi
con delle espressioni regolari. È una strada che questo progetto ha già
percorso, e male: nel modulo del registro otto regex su otto sembravano
funzionare, e una contava zero senza dirlo. Su un effetto grafico l'errore è
peggiore, perché il fallimento è invisibile: l'animazione semplicemente non
compare e non si capisce perché.

Qui gli eventi nascono già strutturati, nel punto esatto in cui il gioco sa
cosa sta facendo.

Come si consumano
─────────────────
Gli eventi NON vengono azzerati a ogni turno: si accumulano con un `id`
crescente e la lista viene tagliata alle ultime `MAX_EVENTI`. Il frontend
tiene da parte l'ultimo `id` che ha già mostrato e riproduce solo quelli più
recenti.

Il motivo è che non tutto succede dentro `execute_turn`: piazzare una miniera
o un presidio sono chiamate separate, e con l'azzeramento a inizio turno quegli
eventi sarebbero spariti prima di essere visti. Con l'id progressivo funzionano
tutti e due i casi, e più chiamate nello stesso turno non si pestano.

Rimozione
─────────
Cancella questo file e i punti marcati [EVENT-CHANNEL] in
`gamecore/session/session.py`. Sono tutti chiamate a un solo metodo e non
hanno valore di ritorno: toglierli non cambia una virgola della partita.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# ══════════════════════════════════════════════════════════════════
# Tipi di evento
# ══════════════════════════════════════════════════════════════════
#
# I nomi sono la parte pubblica: il frontend ci attacca sopra effetti e suoni.
# Aggiungerne uno nuovo non richiede di toccare niente qui, basta emetterlo.

BATTAGLIA = "battaglia"                  # scontro fra due legioni su una cella
PERDITE = "perdite"                      # truppe cadute (segue quasi sempre una battaglia)
ASSALTO_CASTELLO = "assalto_castello"    # castello colpito ma non caduto
CASTELLO_CADUTO = "castello_caduto"      # fine partita
CELLA_CONQUISTATA = "cella_conquistata"
MINIERA = "miniera"
FORTIFICAZIONE = "fortificazione"
PRESIDIO = "presidio"
LEGIONE_CREATA = "legione_creata"
ARMATA_SCHIERATA = "armata_schierata"  # una legione ha superato la soglia

#: Chiave che gli eventi di combattimento portano nel `dettaglio`: dice se fra
#: le truppe coinvolte c'era artiglieria. La calcola il motore, che sa cosa c'è
#: dentro le legioni; chi ascolta non deve andarsela a cercare.
CHIAVE_ARTIGLIERIA = "artiglieria"

#: Id dell'unità artiglieria in `data/units.json`.
UNITA_ARTIGLIERIA = "artillery"

#: Da quante unità una legione smette di essere un reparto e diventa
#: un'armata.
#:
#: Esiste perché `LEGIONE_CREATA` non basta a riconoscere le forze grosse.
#: Le legioni dell'IA nascono quasi vuote e si riempiono turno dopo turno
#: con le reclute: misurate su 12 partite complete, alla nascita hanno da
#: 1 a 6 unità e arrivano a 13-147. Chi ascolta vuole il momento in cui la
#: legione diventa grossa, non quello in cui viene formata, ed è per
#: quello che c'è `ARMATA_SCHIERATA`.
SOGLIA_ARMATA = 10

#: Quanti eventi tenere. Una partita lunga ne produce qualche centinaio: qui
#: serve solo la coda recente, il resto lo racconta già il registro.
MAX_EVENTI = 240


class EventLog:
    """Coda di eventi con id progressivo.

    Non solleva mai: un errore nel canale eventi non deve far cadere un turno.
    """

    def __init__(self) -> None:
        self._eventi: List[Dict[str, Any]] = []
        self._prossimo_id: int = 1

    def emetti(
        self,
        tipo: str,
        *,
        turno: int,
        entita: Optional[str] = None,
        pos: Optional[Sequence[int]] = None,
        quantita: Optional[float] = None,
        dettaglio: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Registra un evento.

        `entita` è chi lo ha causato ('player'/'ai'), `pos` la cella in
        coordinate [riga, colonna], `quantita` l'intensità — danni, perdite,
        livello — che serve a graduare l'effetto invece di mostrarlo sempre
        uguale.
        """
        try:
            evento: Dict[str, Any] = {
                "id": self._prossimo_id,
                "turno": int(turno),
                "tipo": str(tipo),
                "entita": entita,
                "pos": [int(pos[0]), int(pos[1])] if pos is not None and len(pos) >= 2 else None,
                "quantita": None if quantita is None else round(float(quantita), 2),
            }
            if dettaglio:
                evento["dettaglio"] = dettaglio

            self._prossimo_id += 1
            self._eventi.append(evento)

            if len(self._eventi) > MAX_EVENTI:
                del self._eventi[: len(self._eventi) - MAX_EVENTI]
        except Exception:
            return

    def to_list(self) -> List[Dict[str, Any]]:
        return list(self._eventi)

    @property
    def ultimo_id(self) -> int:
        return self._prossimo_id - 1

    def __len__(self) -> int:
        return len(self._eventi)
