/*
 * War Advisor - Avviso armate nemiche (SGANCIABILE)
 *
 * Quando l'IA ammassa abbastanza truppe da fare un'armata, compare per qualche
 * secondo un riquadro rosso in alto a destra. È lo stesso momento che fa
 * partire il BRAAAM: tutti e due leggono l'evento `armata_schierata` del canale
 * eventi, nessuno dei due chiama l'altro.
 *
 * A stabilire quando una legione diventa un'armata è il backend
 * (`SOGLIA_ARMATA` in gamecore/session/turn_events.py): qui non si contano le
 * truppe, si mostra quello che il gioco ha già deciso.
 *
 * Perché solo le legioni nemiche: che la tua armata sia pronta lo sai già, sei
 * stato tu a formarla. Quella dell'IA no, e ha valore tattico saperlo.
 *
 * Rimozione: cancella questa cartella e le due righe marcate [ALERT-MODULE] in
 * battle.html. Nessun file del gioco lo chiama.
 */
(function () {
    'use strict';

    const ZONA_ID = 'warAlertZona';

    /* Quanto resta a schermo. Abbastanza da leggerlo con calma mentre si sta
       facendo altro, non tanto da restare lì mentre si gioca il turno dopo. */
    const DURATA_MS = 6500;
    const USCITA_MS = 340;

    /* Quanti riquadri insieme. Gli annunci sono rari (misurati: 1,8 a partita),
       ma due legioni possono superare la soglia nello stesso turno e la colonna
       non deve crescere all'infinito. */
    const MAX_A_SCHERMO = 3;

    /* ── Il contenitore ──────────────────────────────────────────── */
    /* Sta su `body` e non sulla mappa: `renderMapBoard` ricostruisce tutte le
       caselle a ogni render e si porterebbe via qualsiasi cosa attaccata lì. */

    function zona() {
        let z = document.getElementById(ZONA_ID);
        if (!z) {
            z = document.createElement('div');
            z.id = ZONA_ID;
            z.className = 'war-alert-zona';
            document.body.appendChild(z);
        }
        return z;
    }

    /* ── Il riquadro ─────────────────────────────────────────────── */

    function riga(classe, testo) {
        const el = document.createElement('span');
        el.className = classe;
        el.textContent = testo;      // mai innerHTML: il nome arriva dai dati
        return el;
    }

    function dettaglioDi(evento) {
        const parti = [];
        const nome = evento.dettaglio && evento.dettaglio.nome;
        if (nome) parti.push(nome);
        if (evento.quantita) parti.push(Math.round(evento.quantita) + ' unità');
        if (evento.pos && evento.pos.length === 2) {
            /* Stesso formato del resto dell'interfaccia ("cella 8,7"). */
            parti.push('cella ' + evento.pos[0] + ',' + evento.pos[1]);
        }
        return parti.join(' · ');
    }

    function mostra(evento) {
        const z = zona();
        while (z.children.length >= MAX_A_SCHERMO) {
            z.removeChild(z.firstChild);
        }

        const avviso = document.createElement('div');
        avviso.className = 'war-alert';
        avviso.setAttribute('role', 'status');

        avviso.appendChild(riga('war-alert-icona', '⚠'));

        const testo = document.createElement('div');
        testo.className = 'war-alert-testo';
        testo.appendChild(riga('war-alert-titolo', 'Attenzione'));
        testo.appendChild(riga('war-alert-corpo', 'Grossa legione nemica rilevata'));

        const dettaglio = dettaglioDi(evento);
        if (dettaglio) {
            const sotto = riga('war-alert-dettaglio', dettaglio);
            sotto.title = dettaglio;      // il testo tagliato resta leggibile
            testo.appendChild(sotto);
        }

        avviso.appendChild(testo);
        z.appendChild(avviso);

        setTimeout(function () { chiudi(avviso); }, DURATA_MS);
    }

    function chiudi(avviso) {
        if (!avviso || !avviso.parentNode) return;
        avviso.classList.add('is-uscita');
        setTimeout(function () {
            if (avviso.parentNode) avviso.parentNode.removeChild(avviso);
        }, USCITA_MS);
    }

    /* ── Lettura degli eventi ────────────────────────────────────── */

    let ultimoIdVisto = null;

    function applica(stato) {
        if (!stato || !Array.isArray(stato.events)) return;
        const eventi = stato.events;

        /* Primo giro: si prende nota di dove siamo e basta. Entrando in una
           partita già avviata comparirebbero tutti insieme gli avvisi delle
           ultime decine di turni. */
        if (ultimoIdVisto === null) {
            ultimoIdVisto = eventi.length ? eventi[eventi.length - 1].id : 0;
            return;
        }

        /* Partita nuova: gli id ripartono da capo. */
        const ultimo = eventi.length ? eventi[eventi.length - 1].id : 0;
        if (ultimo < ultimoIdVisto) {
            ultimoIdVisto = ultimo;
            return;
        }

        const nuovi = eventi.filter(function (e) { return e.id > ultimoIdVisto; });
        if (!nuovi.length) return;
        ultimoIdVisto = nuovi[nuovi.length - 1].id;

        /* A partita finita non si avvisa più di niente: davanti c'è la
           schermata di vittoria o sconfitta, e un allarme tattico lì sotto
           sarebbe solo rumore. */
        if (stato.state === 'game_over') return;

        for (const evento of nuovi) {
            if (evento.tipo === 'armata_schierata' && evento.entita === 'ai') {
                mostra(evento);
            }
        }
    }

    /* ── Interfaccia pubblica ────────────────────────────────────── */

    window.WarAlert = {
        /* Per vederlo senza aspettare che l'IA ammassi truppe:
           WarAlert.prova() dalla console. */
        prova: function () {
            mostra({ dettaglio: { nome: 'Falange Nera' }, quantita: 12, pos: [8, 7] });
        }
    };

    /* ── Aggancio ────────────────────────────────────────────────── */
    /* Si avvolge attorno a renderBattleState invece di farsi chiamare da
       dentro: stesso schema dei moduli atmosfera, schermata finale e audio. */

    function hook() {
        const originale = window.renderBattleState;
        if (typeof originale !== 'function') return false;

        window.renderBattleState = function () {
            const risultato = originale.apply(this, arguments);
            try {
                applica(arguments[0]);
            } catch (_) {
                /* un avviso non deve mai far cadere il render della partita */
            }
            return risultato;
        };
        return true;
    }

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', hook);
    } else {
        hook();
    }
})();
