# Modulo avvisi sulle forze nemiche

Angolo in alto a destra del campo di battaglia. Puramente presentazionale.

## Cosa mostra

**Avvisi di passaggio** — compaiono, restano 6,5 secondi, spariscono:

| | quando | evento |
|---|---|---|
| 🔴 rosso | l'IA schiera un'armata | `armata_schierata` |
| 🟠 ambra | parte una carovana di rifornimenti grossa | `carovana_partita` |

**Pannello permanente** — resta finché l'IA ha rinforzi in viaggio, con quante
carovane, quante truppe e fra quanti turni arrivano. Legge `ai.convoys` dallo
stato, non gli eventi, così è giusto anche ricaricando la pagina a metà partita.

## Perché tutti e due

Un avviso prende l'occhio nel momento giusto ma si può perdere: se stai
guardando l'altra metà dello schermo, sei turni dopo non sai più niente. Il
pannello invece non si perde, ed è la parte che conta — quelle sono truppe che
stanno arrivando all'avversario. L'avviso serve a farti alzare gli occhi, il
pannello a rispondere.

## Cosa contiene

- `alert.js` — costruisce e mostra; si aggancia da solo avvolgendo
  `renderBattleState`, come i moduli atmosfera, schermata finale e audio
- `alert.css` — stili usati solo da qui

Nessun file del gioco lo chiama. Se non viene caricato non cambia niente.

## Le soglie

**Armata: 10 unità**, decisa dal backend (`SOGLIA_ARMATA` in
`gamecore/session/turn_events.py`). Non si può usare `legione_creata` al suo
posto: le legioni dell'IA nascono quasi vuote e si riempiono turno dopo turno
con le reclute — misurate su 12 partite, alla nascita hanno **da 1 a 6 unità** e
arrivano a **13-147**. Una soglia sulla nascita non sarebbe scattata mai.

**Carovana: 4 unità**, decisa qui (`SOGLIA_CAROVANA`). Le carovane sono ~37 a
partita: avvisarle tutte sarebbe rumore, e il rumore si smette di leggerlo.
Misurata la distribuzione delle dimensioni, la soglia a 4 lascia passare ~2,5
avvisi a partita — le ondate vere, quasi tutte comprate al Mercato Nero. Le
altre restano nel pannello permanente, che le mostra comunque.

## Perché solo le forze nemiche

Che la tua armata sia pronta lo sai già, l'hai formata tu. Quella dell'IA no, e
sapere che dieci uomini si sono ammassati da qualche parte — o che ne stanno
arrivando altri tre fra sei turni — ha valore tattico.

Il suono (BRAAAM) invece parte per entrambi gli schieramenti. Se serve l'avviso
anche per le proprie legioni basta togliere il controllo `evento.entita === 'ai'`
in `applica()` — ma allora vanno cambiati anche testi e colori, perché "nemica"
in rosso sulla propria armata direbbe il falso.

## Perché non si può cliccare

La zona è `pointer-events: none`. Sta sopra il campo di battaglia, e senza
quello un clic su una casella nell'angolo in alto a destra finirebbe qui invece
che sulla mappa. Gli avvisi spariscono da soli; il pannello sparisce quando non
c'è più niente in viaggio.

## Rimozione

Cancella questa cartella e le due righe marcate `[ALERT-MODULE]` in
`frontend/battle.html` (il `<link>` nel `<head>` e lo `<script>` in fondo).
Niente altro lo referenzia.
