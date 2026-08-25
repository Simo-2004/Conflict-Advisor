/*
 * War Advisor - Log pericoli (SGANCIABILE)
 *
 * Una card nella barra laterale, sotto "Economia e Presidi", con quello che
 * l'IA sta facendo e che al giocatore conviene sapere:
 *
 *   🔴 ⚠   ha schierato un'armata          (`armata_schierata`)
 *   🟠 🚚  ha mandato rinforzi al fronte   (`carovana_partita`)
 *   🟠 📥  i rinforzi sono arrivati        (`carovana_arrivata`)
 *
 * In cima alla card c'è una riga di stato con quello che è in viaggio adesso:
 * quante carovane, quante truppe, quando arriva la prima. Sotto, la cronologia
 * dal più recente. Le voci delle carovane ancora in marcia portano un conto
 * alla rovescia che si aggiorna a ogni turno.
 *
 * Prima tutto questo compariva come riquadri fissi in alto a destra, sopra la
 * mappa: si sovrapponevano al campo di battaglia e sparivano dopo sei secondi,
 * quindi bastava guardare altrove per perderli. In una card, la cronologia
 * resta.
 *
 * A stabilire quando una legione è un'armata e quanto ci mette una carovana è
 * il backend (`SOGLIA_ARMATA` in turn_events.py, `caravans.py`): qui non si
 * contano truppe né turni, si mostra quello che il gioco ha già deciso.
 *
 * Rimozione: cancella questa cartella e le due righe marcate [ALERT-MODULE] in
 * battle.html. La card se la costruisce da sé, quindi non resta niente di
 * vuoto nella barra laterale. Nessun file del gioco lo chiama.
 */
(function () {
    'use strict';

    const CARD_ID = 'dangerLog';
    const LISTA_ID = 'dangerLogList';
    const STATO_ID = 'dangerLogStatus';

    /* Quante voci tenere. Una partita lunga ne produce una sessantina: oltre
       questa soglia le più vecchie escono, tanto la cronologia completa sta
       già nel registro di battaglia. */
    const MAX_VOCI = 40;

    /* ── La card ─────────────────────────────────────────────────── */
    /* Se la costruisce il modulo invece di stare in battle.html: così
       cancellare la cartella non lascia una card vuota nella barra. Stesso
       schema del pannello di debug. */

    function card() {
        let el = document.getElementById(CARD_ID);
        if (el) return el;

        const barra = document.getElementById('battleSidebarColumn');
        if (!barra) return null;

        el = document.createElement('div');
        el.id = CARD_ID;
        el.className = 'battle-card danger-log';
        el.innerHTML =
            '<div class="battle-card-header">'
            + '<h3>Log pericoli</h3>'
            + '</div>'
            + '<div class="danger-log-body">'
            + '<div class="danger-log-status" id="' + STATO_ID + '"></div>'
            + '<ul class="danger-log-list" id="' + LISTA_ID + '"></ul>'
            + '<p class="danger-log-empty">Nessun movimento nemico rilevato.</p>'
            + '</div>';
        barra.appendChild(el);
        return el;
    }

    /* ── Pezzi di markup ─────────────────────────────────────────── */

    function riga(classe, testo) {
        const el = document.createElement('span');
        el.className = classe;
        el.textContent = testo;      // mai innerHTML: i nomi arrivano dai dati
        return el;
    }

    /* "unità" non cambia al plurale: la funzione esiste solo per non ripetere
       la stessa concatenazione in cinque punti. */
    function unita(n) {
        return n + ' unità';
    }

    /* ── Le voci ─────────────────────────────────────────────────── */

    function aggiungi(opzioni) {
        const lista = document.getElementById(LISTA_ID);
        if (!lista) return;

        const voce = document.createElement('li');
        voce.className = 'danger-entry ' + opzioni.tipo;
        if (opzioni.arrivo) voce.dataset.arrivo = opzioni.arrivo;

        voce.appendChild(riga('danger-entry-icona', opzioni.icona));

        const testo = document.createElement('div');
        testo.className = 'danger-entry-testo';
        testo.appendChild(riga('danger-entry-corpo', opzioni.corpo));

        const sotto = riga('danger-entry-dettaglio', opzioni.dettaglio || '');
        sotto.title = opzioni.dettaglio || '';
        testo.appendChild(sotto);
        voce.appendChild(testo);

        /* Turno e conto alla rovescia in colonna a destra, fuori dal testo che
           si accorcia: a barra stretta il "fra 11" finiva tagliato dai puntini
           di sospensione, ed è la mezza riga su cui si decide qualcosa. */
        const tempo = document.createElement('div');
        tempo.className = 'danger-entry-tempo';
        tempo.appendChild(riga('danger-entry-turno', 'T' + opzioni.turno));
        if (opzioni.arrivo) {
            /* Si aggiorna a ogni turno: sta in un suo nodo così non si
               riscrive tutta la voce. */
            tempo.appendChild(riga('danger-entry-eta', ''));
        }
        voce.appendChild(tempo);

        /* Il più recente in cima: la card è alta poche righe e quello che
           conta è appena successo. */
        lista.insertBefore(voce, lista.firstChild);
        while (lista.children.length > MAX_VOCI) {
            lista.removeChild(lista.lastChild);
        }
    }

    function vociArmata(evento) {
        const parti = [];
        const nome = evento.dettaglio && evento.dettaglio.nome;
        if (nome) parti.push(nome);
        if (evento.pos && evento.pos.length === 2) {
            /* Stesso formato del resto dell'interfaccia ("cella 8,7"). */
            parti.push('cella ' + evento.pos[0] + ',' + evento.pos[1]);
        }
        aggiungi({
            tipo: 'is-armata',
            icona: '⚠',
            corpo: 'Armata nemica: ' + unita(Math.round(evento.quantita || 0)),
            dettaglio: parti.join(' · '),
            turno: evento.turno
        });
    }

    function vocePartenza(evento) {
        const d = evento.dettaglio || {};
        const parti = [];
        if (d.unita) parti.push(d.unita);
        if (d.arrivo_turno) parti.push('arrivo T' + d.arrivo_turno);
        aggiungi({
            tipo: 'is-partenza',
            icona: '🚚',
            corpo: 'Rinforzi in marcia: ' + unita(Math.round(evento.quantita || 0)),
            dettaglio: parti.join(' · '),
            turno: evento.turno,
            arrivo: d.arrivo_turno || null
        });
    }

    function voceArrivo(evento) {
        const d = evento.dettaglio || {};
        const parti = [];
        if (d.unita) parti.push(d.unita);
        if (d.legione) parti.push('a ' + d.legione);
        aggiungi({
            tipo: 'is-arrivo',
            icona: '📥',
            corpo: d.forza_legione
                ? 'Rinforzi arrivati: +' + Math.round(evento.quantita || 0)
                    + ' → ' + unita(d.forza_legione)
                : 'Rinforzi arrivati: +' + Math.round(evento.quantita || 0),
            dettaglio: parti.join(' · '),
            turno: evento.turno
        });
    }

    /* ── Riga di stato: cosa è in viaggio adesso ─────────────────── */

    function aggiornaStato(stato) {
        const box = document.getElementById(STATO_ID);
        if (!box) return;

        const dati = stato.ai && stato.ai.convoys;
        const inMarcia = dati ? (dati.unita_in_marcia || 0) : 0;
        if (!dati || inMarcia <= 0 || stato.state === 'game_over') {
            box.replaceChildren();
            box.classList.remove('is-attivo');
            return;
        }

        const carovane = dati.carovane || [];
        const parti = [];
        if (carovane.length) {
            parti.push(carovane.length + (carovane.length === 1 ? ' carovana' : ' carovane'));
        }
        parti.push(unita(inMarcia));
        if (dati.in_raduno) parti.push(dati.in_raduno + ' al raduno');

        box.replaceChildren(
            riga('danger-log-status-icona', '🚚'),
            riga('danger-log-status-testo', parti.join(' · ')),
            riga('danger-log-status-eta',
                dati.prossimo_arrivo ? 'prossimo T' + dati.prossimo_arrivo : '')
        );
        box.classList.add('is-attivo');
    }

    /* Conto alla rovescia delle carovane ancora in marcia. Si tocca solo il
       nodo del tempo, non tutta la voce: riscriverla farebbe saltare la
       selezione del testo e lo scorrimento della lista. */
    function aggiornaAttese(turno) {
        const lista = document.getElementById(LISTA_ID);
        if (!lista) return;
        for (const voce of lista.children) {
            const arrivo = Number(voce.dataset.arrivo);
            if (!arrivo) continue;
            const eta = voce.querySelector('.danger-entry-eta');
            if (!eta) continue;
            const mancano = arrivo - turno;
            if (mancano > 0) {
                eta.textContent = 'fra ' + mancano;
                voce.classList.remove('is-conclusa');
            } else {
                eta.textContent = '';
                voce.classList.add('is-conclusa');
                delete voce.dataset.arrivo;
            }
        }
    }

    function aggiornaVuoto() {
        const el = document.getElementById(CARD_ID);
        const lista = document.getElementById(LISTA_ID);
        if (!el || !lista) return;
        el.classList.toggle('is-vuoto', lista.children.length === 0);
    }

    /* ── Lettura degli eventi ────────────────────────────────────── */

    let ultimoIdVisto = null;

    function smista(eventi) {
        for (const evento of eventi) {
            if (evento.entita !== 'ai') continue;
            if (evento.tipo === 'armata_schierata') {
                vociArmata(evento);
            } else if (evento.tipo === 'carovana_partita') {
                vocePartenza(evento);
            } else if (evento.tipo === 'carovana_arrivata') {
                voceArrivo(evento);
            }
        }
    }

    function applica(stato) {
        if (!stato || !Array.isArray(stato.events)) return;
        if (!card()) return;

        const eventi = stato.events;
        const turno = (stato.map && stato.map.turn) || 0;

        if (ultimoIdVisto === null) {
            /* Primo giro: si riempie con quello che è già successo. Da toast
               si saltava, se no partivano venti riquadri insieme; in un log
               invece la cronologia è esattamente quello che si vuole trovare
               ricaricando la pagina a metà partita. */
            const arretrati = eventi.slice(-MAX_VOCI * 3);
            smista(arretrati);
            ultimoIdVisto = eventi.length ? eventi[eventi.length - 1].id : 0;
        } else {
            /* Partita nuova: gli id ripartono da capo e il log si svuota. */
            const ultimo = eventi.length ? eventi[eventi.length - 1].id : 0;
            if (ultimo < ultimoIdVisto) {
                const lista = document.getElementById(LISTA_ID);
                if (lista) lista.replaceChildren();
                ultimoIdVisto = ultimo;
            } else {
                const nuovi = eventi.filter(function (e) { return e.id > ultimoIdVisto; });
                if (nuovi.length) {
                    ultimoIdVisto = nuovi[nuovi.length - 1].id;
                    smista(nuovi);
                }
            }
        }

        aggiornaStato(stato);
        aggiornaAttese(turno);
        aggiornaVuoto();
    }

    /* ── Interfaccia pubblica ────────────────────────────────────── */

    window.WarAlert = {
        /* Per vedere com'è fatto senza aspettare che l'IA si muova:
           WarAlert.prova() dalla console. */
        prova: function () {
            if (!card()) return;
            vocePartenza({ quantita: 3, turno: 39,
                dettaglio: { unita: '3× Arcieri', arrivo_turno: 51, legione: "Fauci d'Acciaio" } });
            vociArmata({ quantita: 14, turno: 42, pos: [8, 7],
                dettaglio: { nome: "Fauci d'Acciaio" } });
            voceArrivo({ quantita: 3, turno: 51,
                dettaglio: { unita: '3× Arcieri', legione: "Fauci d'Acciaio", forza_legione: 17 } });
            aggiornaStato({ state: 'active', map: { turn: 45 }, ai: { convoys: {
                carovane: [{ quantita: 3, arrivo_turno: 51, turni_mancanti: 6 }],
                in_raduno: 2, unita_in_marcia: 5, prossimo_arrivo: 51 } } });
            aggiornaAttese(45);
            aggiornaVuoto();
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
                /* il log non deve mai far cadere il render della partita */
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
