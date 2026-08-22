/*
 * War Advisor - Audio di battaglia (SGANCIABILE)
 *
 * Tema di sottofondo ed effetti sonori, pilotati dal canale eventi del
 * backend. Si aggancia da sé avvolgendo `renderBattleState`: nessun altro file
 * sa che questo modulo esiste.
 *
 * Espone `window.WarAudio`, che altri moduli possono chiamare senza sapere se
 * l'audio c'è (`window.WarAudio && window.WarAudio.play(...)`). La schermata
 * di fine partita lo fa già.
 *
 * Rimozione: cancella questa cartella, la riga marcata [AUDIO-MODULE] in
 * battle.html e il mount /assets in main.py.
 *
 * ──────────────────────────────────────────────────────────────────────
 * LE REGOLE DEI SUONI
 *
 *   scontro fra legioni senza artiglieria  →  Sword Fight
 *   scontro con artiglieria da una parte   →  Astronomical Explosion
 *   assalto al castello con artiglieria    →  Astronomical Explosion
 *   assalto al castello senza artiglieria  →  Sword Fight
 *   nuova legione formata                  →  Cinematic Sound BRAAAM
 *
 * Chi ha l'artiglieria lo decide il backend e lo scrive nell'evento: qui non
 * si va a frugare nella composizione delle legioni.
 *
 * ──────────────────────────────────────────────────────────────────────
 * LE PROTEZIONI
 *
 *  1. Ogni evento suona UNA volta sola: si tiene l'id dell'ultimo già visto.
 *  2. Un turno = al massimo un suono di combattimento. Se in un turno ci sono
 *     tre scontri con artiglieria non partono tre esplosioni sovrapposte.
 *  3. Se nello stesso turno c'è sia artiglieria sia acciaio, vince
 *     l'esplosione: è l'evento più forte, e sono comunque uno solo.
 *  4. Niente sovrapposizioni: c'è una coda, e un suono parte solo quando il
 *     precedente ha finito (con un tetto di attesa, se no un file lungo
 *     bloccherebbe tutto).
 *  5. Le celle neutre non producono eventi di scontro, quindi non suonano:
 *     è il canale eventi a garantirlo, non un controllo qui.
 *  6. Al primo caricamento la coda arretrata NON viene suonata: entrando in
 *     una partita già avviata partirebbero tutti insieme gli scontri delle
 *     ultime decine di turni.
 */
(function () {
    'use strict';

    const BASE = '/assets/Sounds/';

    /* Nome logico → file, volume, e se va in loop.
       I nomi logici sono la parte pubblica: cambiare un file qui non tocca
       nessuno degli altri moduli che chiamano `WarAudio.play`. */
    const SUONI = {
        tema:       { file: 'Civil War Field Loop.mp3',   volume: 0.22, loop: true },
        spade:      { file: 'Sword Fight.mp3',            volume: 0.55 },
        esplosione: { file: 'Astronomical Explosion.mp3', volume: 0.55 },
        legione:    { file: 'Cinematic Sound BRAAAM.mp3', volume: 0.45 },
        /* Fine partita. `chiudeTema: true` spegne la musica invece di
           abbassarla: la partita è finita, il tema di sottofondo sotto la
           fanfara di vittoria suonerebbe come un disco rimasto acceso. */
        victory:    { file: 'Victory.mp3',                volume: 0.6, chiudeTema: true },
        defeat:     { file: 'Defeat.mp3',                 volume: 0.6, chiudeTema: true }
    };

    /* Quanto al massimo si aspetta che un effetto finisca prima di far partire
       il successivo in coda. Senza tetto un file lungo terrebbe fermo tutto. */
    const ATTESA_MASSIMA_MS = 2600;

    /* Il tema si abbassa mentre suona un effetto, e risale dopo: senza, la
       musica e l'esplosione si impastano. */
    const VOLUME_TEMA_ABBASSATO = 0.07;

    const CHIAVE_SILENZIO = 'warAdvisorAudioMuto';

    let elementi = {};           // nome → HTMLAudioElement
    let sbloccato = false;       // il browser vieta l'audio prima di un gesto
    let muto = false;
    let coda = [];
    let inRiproduzione = null;
    let timerCoda = null;

    /* ── Caricamento ─────────────────────────────────────────────── */

    function prepara() {
        for (const nome in SUONI) {
            const spec = SUONI[nome];
            const audio = new Audio(BASE + encodeURIComponent(spec.file));
            audio.preload = 'auto';
            audio.volume = spec.volume;
            if (spec.loop) audio.loop = true;
            elementi[nome] = audio;
        }
    }

    /* ── Sblocco ─────────────────────────────────────────────────── */
    /* I browser rifiutano di far partire l'audio finché l'utente non ha
       toccato la pagina. Si prova comunque al caricamento — a volte passa, se
       l'utente ha già usato il sito — e in caso contrario si riprova a ogni
       gesto FINCHÉ non parte davvero.
     *
     * Prima si smetteva di ascoltare al primo gesto, riuscito o no: se quel
     * primo tentativo veniva rifiutato dal browser, la musica non partiva più
     * per tutta la sessione e l'unico modo di riaverla era spegnere e
     * riaccendere l'audio a mano. */

    function ascoltaGesti() {
        document.addEventListener('pointerdown', daGesto, true);
        document.addEventListener('keydown', daGesto, true);
    }

    function staccaAscoltatori() {
        document.removeEventListener('pointerdown', daGesto, true);
        document.removeEventListener('keydown', daGesto, true);
    }

    function daGesto(evento) {
        /* Il pulsante dell'audio ha il suo trattamento: se il gesto generico
           lo sbloccasse, il clic successivo sullo stesso pulsante lo
           spegnerebbe subito dopo — ed è esattamente perché serviva premerlo
           due volte per sentire qualcosa. */
        if (evento && evento.target && evento.target.closest
            && evento.target.closest('#warAudioBtn')) {
            return;
        }
        sblocca();
    }

    function sblocca() {
        sbloccato = true;
        if (muto) return;
        avviaTema();
        serviCoda();
    }

    function avviaTema() {
        const tema = elementi.tema;
        if (!tema || muto) return;
        sbloccato = true;
        tema.volume = SUONI.tema.volume;

        const esito = tema.play();
        if (esito && typeof esito.then === 'function') {
            esito.then(function () {
                /* Partita davvero: solo adesso smettiamo di stare in ascolto. */
                staccaAscoltatori();
            }).catch(function () {
                /* Rifiutata: si resta in ascolto e si ritenta al gesto dopo. */
            });
        } else {
            staccaAscoltatori();
        }
    }

    function fermaTema() {
        const tema = elementi.tema;
        if (!tema) return;
        tema.pause();
        try { tema.currentTime = 0; } catch (_) {}
    }

    /* ── Coda: un effetto per volta ──────────────────────────────── */

    function accoda(nome) {
        if (!SUONI[nome] || SUONI[nome].loop) return;
        /* Finché l'audio è bloccato o muto gli effetti si buttano via invece
           di accodarli. Accodandoli, al primo clic dell'utente sarebbero
           partiti tutti insieme gli scontri dei turni precedenti — e la coda
           restava incastrata, perché il controllo anti-doppione qui sotto
           trovava il nome già dentro e non ripartiva più. */
        if (!sbloccato || muto) return;
        /* Lo stesso effetto non si mette due volte in attesa: è la protezione
           contro più scontri identici nello stesso turno. */
        if (coda.indexOf(nome) !== -1) return;
        coda.push(nome);
        serviCoda();
    }

    function serviCoda() {
        if (muto || !sbloccato || inRiproduzione || coda.length === 0) return;

        const nome = coda.shift();
        const audio = elementi[nome];
        if (!audio) return;

        inRiproduzione = nome;
        if (SUONI[nome].chiudeTema) {
            fermaTema();
        } else {
            abbassaTema(true);
        }

        try { audio.currentTime = 0; } catch (_) {}
        audio.volume = SUONI[nome].volume;

        const esito = audio.play();
        if (esito && typeof esito.catch === 'function') {
            esito.catch(function () { fine(); });
        }

        audio.onended = fine;
        /* Rete di sicurezza: se `onended` non arriva (file corrotto, scheda in
           secondo piano) la coda non deve restare bloccata per sempre. Quando
           la durata è nota si usa quella: le fanfare di fine partita durano
           più del tetto fisso e verrebbero considerate finite troppo presto. */
        clearTimeout(timerCoda);
        const durataNota = isFinite(audio.duration) && audio.duration > 0
            ? (audio.duration * 1000) + 250
            : ATTESA_MASSIMA_MS;
        timerCoda = setTimeout(fine, Math.max(ATTESA_MASSIMA_MS, durataNota));
    }

    function fine() {
        clearTimeout(timerCoda);
        const precedente = inRiproduzione;
        if (inRiproduzione && elementi[inRiproduzione]) {
            elementi[inRiproduzione].onended = null;
        }
        const chiuso = precedente && SUONI[precedente] && SUONI[precedente].chiudeTema;
        inRiproduzione = null;
        if (coda.length === 0 && !chiuso) {
            abbassaTema(false);
        }
        serviCoda();
    }

    function abbassaTema(giu) {
        const tema = elementi.tema;
        if (!tema || muto) return;
        tema.volume = giu ? VOLUME_TEMA_ABBASSATO : SUONI.tema.volume;
    }

    /* ── Silenzio ────────────────────────────────────────────────── */

    function leggiSilenzio() {
        try { return localStorage.getItem(CHIAVE_SILENZIO) === '1'; } catch (_) { return false; }
    }

    function scriviSilenzio(valore) {
        try { localStorage.setItem(CHIAVE_SILENZIO, valore ? '1' : '0'); } catch (_) {}
    }

    function impostaMuto(valore) {
        muto = Boolean(valore);
        scriviSilenzio(muto);
        if (muto) {
            coda = [];
            fermaTema();
            for (const nome in elementi) { elementi[nome].pause(); }
            inRiproduzione = null;
        } else {
            avviaTema();
        }
        aggiornaPulsante();
    }

    /* ── Pulsante ────────────────────────────────────────────────── */

    function creaPulsante() {
        const bottone = document.createElement('button');
        bottone.id = 'warAudioBtn';
        bottone.type = 'button';
        bottone.className = 'war-audio-btn';
        bottone.addEventListener('click', function () {
            /* Se non è ancora partito niente, il primo clic vale "accendi",
               non "spegni": premere il pulsante dell'audio per sentire il
               silenzio non ha senso. */
            const tema = elementi.tema;
            if (!muto && tema && tema.paused) {
                sblocca();
                aggiornaPulsante();
                return;
            }
            impostaMuto(!muto);
        });
        document.body.appendChild(bottone);
        aggiornaPulsante();
    }

    function aggiornaPulsante() {
        const bottone = document.getElementById('warAudioBtn');
        if (!bottone) return;
        bottone.textContent = muto ? '\u{1F507}' : '\u{1F50A}';
        bottone.title = muto ? 'Audio spento — clicca per riaccendere' : 'Audio acceso — clicca per spegnere';
        bottone.setAttribute('aria-label', bottone.title);
        bottone.classList.toggle('is-muted', muto);
    }

    /* ── Lettura degli eventi ────────────────────────────────────── */

    let ultimoIdVisto = null;

    function decidi(eventi) {
        /* Un turno produce al massimo un suono di combattimento: si guarda
           tutto il blocco di eventi nuovi e si sceglie, invece di suonare a
           ogni evento. È questo che impedisce tre esplosioni sovrapposte
           quando in un turno ci sono tre scontri. */
        let combattimento = null;   // 'esplosione' vince su 'spade'
        let nuovaLegione = false;

        for (const evento of eventi) {
            const tipo = evento.tipo;
            const dettaglio = evento.dettaglio || {};

            if (tipo === 'battaglia' || tipo === 'assalto_castello' || tipo === 'castello_caduto') {
                if (dettaglio.artiglieria) {
                    combattimento = 'esplosione';
                } else if (combattimento !== 'esplosione') {
                    combattimento = 'spade';
                }
            } else if (tipo === 'legione_creata') {
                nuovaLegione = true;
            }
        }

        if (combattimento) accoda(combattimento);
        if (nuovaLegione) accoda('legione');
    }

    function applica(stato) {
        if (!stato || !Array.isArray(stato.events)) return;
        const eventi = stato.events;

        /* Primo giro: si prende nota di dove siamo e basta. Entrando in una
           partita già avviata, la coda arretrata farebbe partire insieme gli
           scontri delle ultime decine di turni. */
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

        decidi(nuovi);
    }

    /* ── Interfaccia pubblica ────────────────────────────────────── */

    window.WarAudio = {
        /* Nomi sconosciuti sono un no-op voluto: chi chiama non deve sapere
           quali file esistono. */
        play: function (nome) { accoda(nome); },
        mute: function () { impostaMuto(true); },
        unmute: function () { impostaMuto(false); },
        toggle: function () { impostaMuto(!muto); },
        isMuted: function () { return muto; },
        suoniDisponibili: function () { return Object.keys(SUONI); }
    };

    /* ── Aggancio ────────────────────────────────────────────────── */

    function hook() {
        const originale = window.renderBattleState;
        if (typeof originale !== 'function') return false;

        window.renderBattleState = function () {
            const risultato = originale.apply(this, arguments);
            try {
                applica(arguments[0]);
            } catch (_) {
                /* l'audio non deve mai far cadere il render della partita */
            }
            return risultato;
        };
        return true;
    }

    function avvia() {
        muto = leggiSilenzio();
        prepara();
        creaPulsante();
        hook();

        /* Primo tentativo subito: su un sito già usato il browser spesso lo
           concede, e la musica c'è dal caricamento senza dover cliccare. Se
           lo rifiuta, `avviaTema` lascia gli ascoltatori attaccati. */
        ascoltaGesti();
        if (!muto) avviaTema();
    }

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', avvia);
    } else {
        avvia();
    }
})();
