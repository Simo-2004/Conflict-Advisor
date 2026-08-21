/*
 * War Advisor - Schermata di fine partita (SGANCIABILE)
 *
 * Mostra vittoria o sconfitta con il referto della partita. Si aggancia da sé
 * avvolgendo `renderBattleState`: nessun altro file del frontend sa che questo
 * modulo esiste, esattamente come fa il modulo atmosfera.
 *
 * Non legge né scrive lo stato di gioco: riceve il payload che il gioco già
 * produce e ne ricava dei numeri. Se sparisce, la partita finisce come prima
 * (la pastiglia in alto che scrive "Fine partita").
 *
 * Rimozione: cancella questa cartella e le due righe marcate [ENDGAME-MODULE]
 * in battle.html. Lato backend restano due contatori marcati [ENDGAME-STATS]
 * in gamecore/session/session.py, anch'essi cancellabili.
 *
 * ──────────────────────────────────────────────────────────────────────
 * AUDIO
 *
 * Qui sotto c'è un solo punto di chiamata, `suona()`, che oggi non fa niente.
 * Il giorno che esisterà un `window.WarAudio`, la schermata inizierà a suonare
 * senza che questo file venga toccato. Il sistema audio non l'ho costruito
 * adesso di proposito: non ci sono file sonori nel progetto, lo sblocco
 * dell'autoplay è una decisione che riguarda tutto il gioco e non solo questa
 * schermata, e il bundle dell'exe richiederebbe un --add-data che oggi non
 * servirebbe a niente.
 */
(function () {
    'use strict';

    const OVERLAY_ID = 'endgameOverlay';

    /* ── Aggancio audio, oggi inerte ─────────────────────────────── */
    function suona(nome) {
        try {
            if (window.WarAudio && typeof window.WarAudio.play === 'function') {
                window.WarAudio.play(nome);
            }
        } catch (_) {
            /* il suono non deve mai impedire la schermata */
        }
    }

    /* ── Blocco della pagina sotto ───────────────────────────────── */
    /* Con la schermata finale davanti, la rotellina continuava a far scorrere
       l'interfaccia di gioco dietro. Si blocca l'elemento che scorre davvero
       (`documentElement`) e si compensa la barra che sparisce, se no al momento
       della vittoria tutta la pagina scatta di lato di una quindicina di pixel. */

    function bloccaPagina() {
        const barra = window.innerWidth - document.documentElement.clientWidth;
        if (barra > 0) {
            document.documentElement.style.setProperty('--endgame-barra', barra + 'px');
        }
        document.documentElement.classList.add('endgame-bloccato');
    }

    function sbloccaPagina() {
        document.documentElement.classList.remove('endgame-bloccato');
        document.documentElement.style.removeProperty('--endgame-barra');
    }

    /* ── Calcolo del referto ─────────────────────────────────────── */

    function contaCelle(mappa, lato) {
        let totale = 0;
        const griglia = (mappa && mappa.grid) || [];
        for (const riga of griglia) {
            for (const cella of riga) {
                if (cella && cella.occupation === lato) totale += 1;
            }
        }
        return totale;
    }

    function durata(secondi) {
        const minuti = Math.floor(secondi / 60);
        /* Sotto il minuto "0'" non dice niente: si mostrano i secondi. */
        if (minuti < 1) {
            return { valore: secondi + '"', nota: 'partita lampo' };
        }
        if (minuti < 60) {
            return { valore: minuti + "'", nota: (secondi % 60) + ' secondi' };
        }
        const ore = Math.floor(minuti / 60);
        return { valore: ore + 'h ' + (minuti % 60) + "'", nota: minuti + ' minuti in tutto' };
    }

    function referto(stato) {
        const stats = stato.stats || {};
        const perdite = stats.troops_lost || {};
        const perse = Number(perdite.player || 0);
        const sconfitte = Number(perdite.ai || 0);
        const secondi = Number(stats.elapsed_seconds || 0);
        const celle = contaCelle(stato.map, 'player');

        /* Sotto il minuto il rateo esplode (10 caselle in 30 secondi darebbe
           20 al minuto): si divide sempre per almeno un minuto, così il numero
           resta onesto anche in una partita lampo. */
        const minutiPieni = Math.max(1, secondi / 60);
        const cellePerMinuto = celle / minutiPieni;

        const tempo = durata(secondi);
        let rapporto = '—';
        if (perse > 0) {
            rapporto = (sconfitte / perse).toFixed(1) + '×';
        } else if (sconfitte > 0) {
            rapporto = 'nessuna persa';
        }

        return [
            { valore: tempo.valore, etichetta: 'Durata', nota: tempo.nota },
            { valore: String((stato.map && stato.map.turn) || 0), etichetta: 'Turni' },
            { valore: String(celle), etichetta: 'Caselle tenute' },
            { valore: String(perse), etichetta: 'Truppe perse' },
            { valore: String(sconfitte), etichetta: 'Truppe sconfitte', nota: rapporto },
            {
                valore: cellePerMinuto.toFixed(1),
                etichetta: 'Caselle al minuto',
                nota: secondi < 60 ? 'su meno di un minuto' : ''
            }
        ];
    }

    /* ── Costruzione della schermata ─────────────────────────────── */

    function testo(valore) {
        return String(valore == null ? '' : valore).replace(/[&<>"']/g, function (c) {
            return {
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
            }[c];
        });
    }

    function sottotitolo(vinta, stato) {
        const turno = (stato.map && stato.map.turn) || 0;
        if (vinta) {
            return 'Il castello nemico è caduto al turno ' + turno + '.<br>La campagna è tua.';
        }
        return 'Il tuo castello è caduto al turno ' + turno
            + ".<br>L'avanzata nemica non è stata fermata.";
    }

    function costruisci(vinta, stato) {
        const overlay = document.createElement('div');
        overlay.id = OVERLAY_ID;
        /* `is-open` sta qui e non dopo un requestAnimationFrame: le animazioni
           di questo modulo sono `animation`, che parte da sola quando il nodo
           entra nel DOM, non `transition`, che avrebbe richiesto un fotogramma
           di scarto. Legata al rAF la schermata non compariva affatto quando i
           fotogrammi non venivano prodotti — per esempio a scheda in secondo
           piano, cioè proprio mentre l'IA finisce il turno. */
        overlay.className = 'endgame-overlay is-open '
            + (vinta ? 'is-victory' : 'is-defeat');

        const schede = referto(stato).map(function (voce, indice) {
            return '<div class="endgame-stat" style="animation-delay:' + (260 + indice * 90) + 'ms">'
                + '<span class="endgame-stat-value">' + testo(voce.valore) + '</span>'
                + '<span class="endgame-stat-label">' + testo(voce.etichetta) + '</span>'
                + (voce.nota
                    ? '<span class="endgame-stat-note">' + testo(voce.nota) + '</span>'
                    : '')
                + '</div>';
        }).join('');

        overlay.innerHTML =
            '<div class="endgame-card ' + (vinta ? 'is-victory' : 'is-defeat')
            + '" role="dialog" aria-modal="true" aria-label="'
            + (vinta ? 'Vittoria' : 'Sconfitta') + '">'
            + (vinta ? '<div class="endgame-rays" aria-hidden="true"></div>' : '')
            + '<span class="endgame-crest" aria-hidden="true">' + (vinta ? '\u{1F451}' : '\u{1F3F3}') + '</span>'
            + '<h2 class="endgame-title">' + (vinta ? 'Vittoria' : 'Sconfitta') + '</h2>'
            + '<p class="endgame-subtitle">' + sottotitolo(vinta, stato) + '</p>'
            + '<div class="endgame-stats">' + schede + '</div>'
            + '<div class="endgame-actions">'
            + '<button class="endgame-btn is-primary" type="button" data-azione="rigioca">Rigioca stesso esercito</button>'
            + '<button class="endgame-btn" type="button" data-azione="nuovo">Nuovo esercito</button>'
            + '<button class="endgame-btn" type="button" data-azione="chiudi">Guarda la mappa</button>'
            + '</div>'
            + '</div>';

        overlay.addEventListener('click', function (evento) {
            const azione = evento.target && evento.target.dataset
                ? evento.target.dataset.azione
                : null;

            // Un clic sul fondale NON chiude: è il risultato della partita,
            // non un popup di passaggio, e un clic capitato fuori dalla card
            // (specie ora che il fondale stesso scorre su schermi bassi) non
            // deve buttarlo via come se fosse "Guarda la mappa". Si esce solo
            // da un pulsante esplicito o da Esc.
            if (azione === 'chiudi') {
                chiudi();
                return;
            }
            if (azione === 'nuovo') {
                window.location.href = '/';
                return;
            }
            if (azione === 'rigioca') {
                chiudi();
                if (typeof window.restartFromStoredSetup === 'function') {
                    window.restartFromStoredSetup();
                } else {
                    window.location.href = '/';
                }
            }
        });

        return overlay;
    }

    function chiudi() {
        const overlay = document.getElementById(OVERLAY_ID);
        if (overlay) overlay.remove();
        document.removeEventListener('keydown', chiudiConEsc);
        sbloccaPagina();
    }

    function chiudiConEsc(evento) {
        if (evento.key === 'Escape') chiudi();
    }

    /* ── Stato del modulo ────────────────────────────────────────── */
    /* `renderBattleState` viene richiamata a ogni aggiornamento, anche a
       partita già finita: senza ricordare cosa si è già mostrato la schermata
       si ricostruirebbe di continuo e non si riuscirebbe a chiuderla. */
    let mostrataPer = null;

    function identitaPartita(stato) {
        return String(stato.winner) + '|' + ((stato.map && stato.map.turn) || 0);
    }

    function applica(stato) {
        if (!stato) return;

        if (stato.state !== 'game_over') {
            mostrataPer = null;      // partita nuova: la schermata può tornare
            return;
        }

        const identita = identitaPartita(stato);
        if (mostrataPer === identita) return;
        mostrataPer = identita;

        const vinta = stato.winner === 'player';
        chiudi();
        document.body.appendChild(costruisci(vinta, stato));
        document.addEventListener('keydown', chiudiConEsc);
        bloccaPagina();
        suona(vinta ? 'victory' : 'defeat');
    }

    /* ── Aggancio ────────────────────────────────────────────────── */
    /* Si avvolge attorno a renderBattleState invece di farsi chiamare da
     * dentro: lo script viene caricato dopo render.js, quindi la funzione
     * esiste già. Stesso schema del modulo atmosfera. */
    function hook() {
        const originale = window.renderBattleState;
        if (typeof originale !== 'function') return false;

        window.renderBattleState = function () {
            const risultato = originale.apply(this, arguments);
            try {
                applica(arguments[0]);
            } catch (_) {
                /* la schermata finale non deve mai far cadere il render */
            }
            return risultato;
        };
        return true;
    }

    if (!hook()) {
        window.addEventListener('DOMContentLoaded', hook);
    }
})();
