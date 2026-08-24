# Modulo avviso armate nemiche

Riquadro rosso in alto a destra quando l'IA ammassa abbastanza truppe da fare
un'armata. Puramente presentazionale.

## Cosa contiene

- `alert.js` — costruisce e mostra l'avviso; si aggancia da solo avvolgendo
  `renderBattleState`, come i moduli atmosfera, schermata finale e audio
- `alert.css` — stili usati solo da qui

## Come si aggancia

Nessun file del gioco lo chiama. Il modulo legge gli eventi `armata_schierata`
dal payload e disegna. Se il file non viene caricato non cambia niente.

## Da dove viene la soglia

Dal backend, non da qui: `SOGLIA_ARMATA` in
`gamecore/session/turn_events.py` (10 unità). Il motore emette
`armata_schierata` quando una legione la supera, una volta sola per legione.

Non si può usare `legione_creata` al suo posto. Le legioni dell'IA nascono
quasi vuote e si riempiono turno dopo turno con le reclute: misurate su 12
partite complete, alla nascita hanno **da 1 a 6 unità** e arrivano a **13-147**.
Una soglia sulla nascita non sarebbe scattata mai.

## Perché solo le legioni nemiche

Che la tua armata sia pronta lo sai già, l'hai formata tu. Quella dell'IA no, e
sapere che da qualche parte si sono ammassati dieci uomini ha valore tattico.
Il suono (BRAAAM) invece parte per tutti e due gli schieramenti: se serve
l'avviso anche per le proprie legioni basta togliere il controllo
`evento.entita === 'ai'` in `applica()` — ma allora vanno cambiati anche testo
e colore, perché "Grossa legione nemica rilevata" in rosso sulla propria armata
direbbe il falso.

## Perché non si può cliccare

La zona è `pointer-events: none`. Sta sopra il campo di battaglia, e senza
quello un clic su una casella nell'angolo in alto a destra finirebbe
sull'avviso invece che sulla mappa. Sparisce da solo dopo 6,5 secondi.

## Rimozione

Cancella questa cartella e le due righe marcate `[ALERT-MODULE]` in
`frontend/battle.html` (il `<link>` nel `<head>` e lo `<script>` in fondo).
Niente altro lo referenzia.
