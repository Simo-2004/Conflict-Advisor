/*
 * War Advisor - Avvisi sulle forze nemiche (SGANCIABILE)
 *
 * Due cose, nello stesso angolo in alto a destra:
 *
 *   1. AVVISI DI PASSAGGIO — riquadri che compaiono e spariscono
 *      · rosso   quando l'IA schiera un'armata (`armata_schierata`)
 *      · ambra   quando parte una carovana grossa (`carovana_partita`)
 *
 *   2. PANNELLO PERMANENTE — resta a schermo finché l'IA ha rinforzi in
 *      marcia, con quante carovane, quante truppe e quando arrivano.
 *
 * Perché tutti e due. Gli avvisi prendono l'occhio nel momento giusto ma si
 * possono perdere: se stai guardando l'altra metà dello schermo, sei turni
 * dopo non sai più niente. Il pannello invece non si perde — ed è la parte che
 * conta, perché quelle sono truppe che stanno arrivando all'avversario.
 * L'avviso serve a farti alzare gli occhi, il pannello a rispondere.
 *
 * A stabilire quando una legione è un'armata e quanto ci mette una carovana è
 * il backend (`SOGLIA_ARMATA` in turn_events.py, `caravans.py`): qui non si
 * contano truppe né turni, si mostra quello che il gioco ha già deciso.
 *
 * Rimozione: cancella questa cartella e le due righe marcate [ALERT-MODULE] in
 * battle.html. Nessun file del gioco lo chiama.
 */
(function () {
    'use strict';

    const ZONA_ID = 'warAlertZona';
    const PANNELLO_ID = 'warAlertCarovane';

    /* Quanto resta a schermo un avviso. Abbastanza da leggerlo con calma
       mentre si sta facendo altro, non tanto da restare lì al turno dopo. */
    const DURATA_MS = 6500;
    const USCITA_MS = 340;

    /* Quanti riquadri insieme. */
    const MAX_A_SCHERMO = 3;

    /* Da quante truppe in su una carovana merita di interrompere il giocatore.
       Le carovane sono 37 a partita: avvisarle tutte sarebbe rumore, e il
       rumore si smette di leggerlo. Misurata la distribuzione, la soglia a 4
       lascia passare ~2,5 avvisi a partita — le ondate vere, quelle comprate
       al Mercato Nero. Tutte le altre restano nel pannello permanente. */
    const SOGLIA_CAROVANA = 4;

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

    function riga(classe, testo) {
        const el = document.createElement('span');
        el.className = classe;
        el.textContent = testo;      // mai innerHTML: i nomi arrivano dai dati
        return el;
    }

    /* ── Avvisi di passaggio ─────────────────────────────────────── */

    function mostra(opzioni) {
        const z = zona();
        const avvisi = z.querySelectorAll('.war-alert');
        for (let i = 0; i <= avvisi.length - MAX_A_SCHERMO; i++) {
            avvisi[i].remove();
        }

        const avviso = document.createElement('div');
        avviso.className = 'war-alert' + (opzioni.variante ? ' ' + opzioni.variante : '');
        avviso.setAttribute('role', 'status');
        avviso.appendChild(riga('war-alert-icona', opzioni.icona));

        const testo = document.createElement('div');
        testo.className = 'war-alert-testo';
        testo.appendChild(riga('war-alert-titolo', opzioni.titolo));
        testo.appendChild(riga('war-alert-corpo', opzioni.corpo));
        if (opzioni.dettaglio) {
            const sotto = riga('war-alert-dettaglio', opzioni.dettaglio);
            sotto.title = opzioni.dettaglio;   // il testo tagliato resta leggibile
            testo.appendChild(sotto);
        }
        avviso.appendChild(testo);

        /* In cima alla colonna: il pannello delle carovane sta in fondo e non
           deve essere spinto giù dagli avvisi che arrivano. */
        z.insertBefore(avviso, z.firstChild);
        setTimeout(function () { chiudi(avviso); }, DURATA_MS);
    }

    function chiudi(avviso) {
        if (!avviso || !avviso.parentNode) return;
        avviso.classList.add('is-uscita');
        setTimeout(function () {
            if (avviso.parentNode) avviso.parentNode.removeChild(avviso);
        }, USCITA_MS);
    }

    /* "unità" non cambia al plurale: la funzione esiste solo per non
       ripetere la stessa concatenazione in cinque punti. */
    function unita(n) {
        return n + ' unità';
    }

    function avvisaArmata(evento) {
        const parti = [];
        const nome = evento.dettaglio && evento.dettaglio.nome;
        if (nome) parti.push(nome);
        if (evento.quantita) parti.push(unita(Math.round(evento.quantita)));
        if (evento.pos && evento.pos.length === 2) {
            /* Stesso formato del resto dell'interfaccia ("cella 8,7"). */
            parti.push('cella ' + evento.pos[0] + ',' + evento.pos[1]);
        }
        mostra({
            icona: '⚠',
            titolo: 'Attenzione',
            corpo: 'Grossa legione nemica rilevata',
            dettaglio: parti.join(' · ')
        });
    }

    function avvisaCarovana(evento) {
        const d = evento.dettaglio || {};
        const parti = [];
        if (d.unita) parti.push(d.unita);
        if (d.arrivo_turno) parti.push('arrivo al turno ' + d.arrivo_turno);
        if (d.legione) parti.push('verso ' + d.legione);
        mostra({
            variante: 'is-rifornimento',
            icona: '🚚',
            titolo: 'Rifornimenti nemici',
            corpo: unita(Math.round(evento.quantita || 0)) + ' in marcia verso il fronte',
            dettaglio: parti.join(' · ')
        });
    }

    /* ── Pannello permanente delle carovane ──────────────────────── */
    /* Si ridisegna a ogni render invece di aggiornare i pezzi: sono quattro
       righe di testo, e ricostruirle costa meno che tenerle sincronizzate. */

    function aggiornaCarovane(stato) {
        const dati = stato && stato.ai && stato.ai.convoys;
        const vecchio = document.getElementById(PANNELLO_ID);

        const inMarcia = dati ? (dati.unita_in_marcia || 0) : 0;
        if (!dati || inMarcia <= 0 || stato.state === 'game_over') {
            if (vecchio) vecchio.remove();
            return;
        }

        const pannello = document.createElement('div');
        pannello.id = PANNELLO_ID;
        pannello.className = 'war-convoy';
        pannello.setAttribute('role', 'status');

        const testa = document.createElement('div');
        testa.className = 'war-convoy-testa';
        testa.appendChild(riga('war-convoy-icona', '🚚'));
        testa.appendChild(riga('war-convoy-titolo', 'Rinforzi nemici in marcia'));
        pannello.appendChild(testa);

        const carovane = dati.carovane || [];
        const sommario = [];
        if (carovane.length) {
            sommario.push(carovane.length + (carovane.length === 1 ? ' carovana' : ' carovane'));
        }
        sommario.push(unita(inMarcia));
        if (dati.in_raduno) sommario.push(dati.in_raduno + ' al raduno');
        pannello.appendChild(riga('war-convoy-sommario', sommario.join(' · ')));

        /* Con poche carovane si elencano una per una: sapere QUANDO arriva
           ciascuna è la sola cosa su cui il giocatore può agire. Con tante,
           l'elenco diventerebbe più alto della mappa. */
        if (carovane.length && carovane.length <= 4) {
            const lista = document.createElement('div');
            lista.className = 'war-convoy-lista';
            carovane.forEach(function (c) {
                const mancano = c.turni_mancanti;
                const quando = mancano <= 0
                    ? 'in arrivo'
                    : 'turno ' + c.arrivo_turno + ' · fra ' + mancano;
                lista.appendChild(riga('war-convoy-voce', unita(c.quantita) + ' → ' + quando));
            });
            pannello.appendChild(lista);
        } else if (dati.prossimo_arrivo) {
            pannello.appendChild(riga(
                'war-convoy-voce',
                'prossimo arrivo: turno ' + dati.prossimo_arrivo
            ));
        }

        if (vecchio) {
            vecchio.replaceWith(pannello);
        } else {
            zona().appendChild(pannello);
        }
    }

    /* ── Lettura degli eventi ────────────────────────────────────── */

    let ultimoIdVisto = null;

    function applica(stato) {
        if (!stato) return;

        /* Il pannello guarda lo stato corrente, non gli eventi: deve essere
           giusto anche ricaricando la pagina a metà partita. */
        aggiornaCarovane(stato);

        if (!Array.isArray(stato.events)) return;
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
            if (evento.entita !== 'ai') continue;
            if (evento.tipo === 'armata_schierata') {
                avvisaArmata(evento);
            } else if (evento.tipo === 'carovana_partita'
                       && (evento.quantita || 0) >= SOGLIA_CAROVANA) {
                avvisaCarovana(evento);
            }
        }
    }

    /* ── Interfaccia pubblica ────────────────────────────────────── */

    window.WarAlert = {
        /* Per vederli senza aspettare che l'IA si muova:
           WarAlert.prova() dalla console. */
        prova: function () {
            avvisaArmata({ dettaglio: { nome: 'Falange Nera' }, quantita: 12, pos: [8, 7] });
            avvisaCarovana({
                quantita: 5,
                dettaglio: { unita: '5× Fanteria Pesante', arrivo_turno: 41, legione: 'Falange Nera' }
            });
            aggiornaCarovane({
                map: { turn: 29 },
                ai: {
                    convoys: {
                        carovane: [
                            { quantita: 3, arrivo_turno: 34, turni_mancanti: 5 },
                            { quantita: 5, arrivo_turno: 41, turni_mancanti: 12 }
                        ],
                        in_raduno: 2, unita_in_marcia: 10, prossimo_arrivo: 34
                    }
                }
            });
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
