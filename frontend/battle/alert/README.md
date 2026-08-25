# Modulo Log pericoli

Card nella barra laterale, sotto "Economia e Presidi", con quello che l'IA sta
facendo e che al giocatore conviene sapere. Puramente presentazionale.

## Cosa mostra

**Riga di stato** in cima — quello che è in viaggio *adesso*: quante carovane,
quante truppe, quando arriva la prima. Sparisce quando non c'è niente in marcia,
invece di restare lì a dire zero. Legge `ai.convoys` dallo stato, non gli
eventi, così è giusto anche ricaricando la pagina a metà partita.

**Cronologia** sotto, dal più recente:

| | quando | evento |
|---|---|---|
| ⚠ rosso | l'IA schiera un'armata | `armata_schierata` |
| 🚚 ambra chiara | parte una carovana di rifornimenti | `carovana_partita` |
| 📥 ambra piena | i rinforzi raggiungono il fronte | `carovana_arrivata` |

Le voci delle carovane ancora per strada portano a destra un conto alla
rovescia che cala a ogni turno; all'arrivo la voce si smorza. Il conto sta in
colonna a destra e non in fondo al testo perché a barra stretta il testo si
accorcia con i puntini, e quella mezza riga è la parte su cui si decide
qualcosa.

L'arrivo è più marcato della partenza: è il momento in cui il fronte nemico è
davvero cresciuto, e vale più dell'annuncio di dieci turni prima.

## Perché una card e non i riquadri fissi

Prima gli avvisi comparivano in alto a destra, sopra la mappa, e sparivano dopo
6,5 secondi: si sovrapponevano al campo di battaglia e bastava guardare altrove
per perderli. In una card la cronologia resta, e si può tornare indietro a
vedere cosa è successo mentre si era distratti.

## Cosa contiene

- `alert.js` — costruisce la card e la riempie; si aggancia da solo avvolgendo
  `renderBattleState`, come i moduli atmosfera, schermata finale e audio
- `alert.css` — stili usati solo da qui

Nessun file del gioco lo chiama, e la card se la costruisce il modulo: se non
viene caricato, nella barra laterale non resta niente di vuoto.

## La soglia dell'armata

10 unità, decisa dal backend (`SOGLIA_ARMATA` in
`gamecore/session/turn_events.py`). Non si può usare `legione_creata` al suo
posto: le legioni dell'IA nascono quasi vuote e si riempiono turno dopo turno
con le reclute — misurate su 12 partite, alla nascita hanno **da 1 a 6 unità** e
arrivano a **13-147**. Una soglia sulla nascita non sarebbe scattata mai.

Le carovane invece si mostrano tutte: sono ~37 a partita, cioè una voce ogni
cinque o sei turni. Da riquadro che interrompeva servivano soglie; in un log no,
il log è fatto per contenerle.

## Perché solo le forze nemiche

Che la tua armata sia pronta lo sai già, l'hai formata tu. Quella dell'IA no, e
sapere che dieci uomini si sono ammassati da qualche parte — o che ne stanno
arrivando altri tre fra sei turni — ha valore tattico.

Il suono (BRAAAM) invece parte per entrambi gli schieramenti. Se serve la voce
anche per le proprie legioni basta togliere il controllo `evento.entita === 'ai'`
in `smista()` — ma allora vanno cambiati anche testi e colori, perché "armata
nemica" in rosso sulla propria direbbe il falso.

## Limiti

- La lista tiene 40 voci e si ferma a 260px di altezza, poi scorre da sola. La
  cronologia completa sta comunque nel registro di battaglia.
- Con la barra laterale compressa (pulsante ▶) il log sparisce insieme
  all'economia, restando solo il titolo.

## Rimozione

Cancella questa cartella e le due righe marcate `[ALERT-MODULE]` in
`frontend/battle.html` (il `<link>` nel `<head>` e lo `<script>` in fondo).
Niente altro lo referenzia.
