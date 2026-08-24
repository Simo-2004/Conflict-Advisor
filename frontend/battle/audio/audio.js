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
 *   armata schierata (soglia dal backend)  →  Cinematic Sound BRAAAM
 *   vittoria / sconfitta                   →  Victory / Defeat
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
 *     precedente ha finito davvero.
 *  5. La coda non si allunga: un effetto già in corso non si richiama, ne
 *     aspetta al massimo un altro, e quello che ha atteso troppo si butta
 *     invece di suonare in ritardo su un turno ormai passato.
 *  6. I suoni di fine partita passano davanti a tutto e chiudono il banco:
 *     dopo la fanfara non arriva più nessuno dei colpi che l'hanno decisa.
 *  7. Le celle neutre non producono eventi di scontro, quindi non suonano:
 *     è il canale eventi a garantirlo, non un controllo qui.
 *  8. Al primo caricamento la coda arretrata NON viene suonata: entrando in
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
        /* `pazienza` alta: schierare un'armata capita una volta o due a
           partita, mentre gli scontri sono continui. Con la stessa attesa
           degli altri il BRAAAM scadeva sempre dietro a un'esplosione e non
           si sentiva mai; qualche secondo di ritardo, per un evento così
           raro, vale molto più del silenzio. */
        legione:    { file: 'Cinematic Sound BRAAAM.mp3', volume: 0.45, pazienza: 12000 },
        /* Fine partita. `finale: true` vuol dire due cose: spegne la musica
           invece di abbassarla — il tema di sottofondo sotto la fanfara
           suonerebbe come un disco rimasto acceso — e chiude il banco,
           cioè passa davanti a qualsiasi effetto e non ne lascia entrare
           altri dopo. */
        victory:    { file: 'Victory.mp3',                volume: 0.6, finale: true },
        defeat:     { file: 'Defeat.mp3',                 volume: 0.6, finale: true }
    };

    /* Quanto a lungo un effetto in attesa resta attuale. Un suono di scontro
       racconta il turno in cui è nato: se la coda lo fa partire cinque secondi
       dopo, il giocatore sta già guardando altro e quello che sente è solo
       rumore. Scaduto si butta, invece di suonarlo in ritardo.

       I suoni rari possono dichiarare la loro `pazienza` e aspettare di più. */
    const SCADENZA_MS = 3500;

    /* Quanti effetti possono aspettare il loro turno. Due: l'esplosione dura
       oltre cinque secondi e gli scontri di artiglieria si ripetono turno
       dopo turno, quindi senza un tetto la coda cresceva più in fretta di
       quanto riuscisse a smaltirla e l'audio raccontava battaglie di parecchi
       turni prima. Con un solo posto, però, un evento raro come l'armata
       schierata restava sempre fuori. */
    const CODA_MASSIMA = 2;

    /* Rete di sicurezza per quando la durata del file non è ancora nota:
       serve solo a non lasciare la coda ferma per sempre se `onended` non
       arriva mai (file corrotto, scheda in secondo piano). Deve stare SOPRA
       la durata dell'effetto più lungo: un tetto troppo basso scattava a
       suono ancora in corso, e il successivo partiva sovrapposto proprio
       come se la coda non ci fosse. */
    const DURATA_IGNOTA_MS = 9000;

    /* Il tema si abbassa mentre suona un effetto, e risale dopo: senza, la
       musica e l'esplosione si impastano. */
    const VOLUME_TEMA_ABBASSATO = 0.07;

    const CHIAVE_SILENZIO = 'warAdvisorAudioMuto';

    let elementi = {};           // nome → HTMLAudioElement
    let sbloccato = false;       // il browser vieta l'audio prima di un gesto
    let muto = false;
    let coda = [];               // voci { nome, nato }
    let inRiproduzione = null;
    let timerCoda = null;
    let partitaFinita = false;   // dopo la fanfara non entra più nessun effetto

    function adesso() {
        return (window.performance && window.performance.now)
            ? window.performance.now() : Date.now();
    }

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
                /* Rifiutata: si torna in ascolto e si ritenta al gesto dopo.
                   Rimettersi in ascolto, invece di darlo per scontato, serve
                   quando il tema era già partito una volta ed è stato spento
                   dalla fanfara di fine partita: lì gli ascoltatori erano
                   stati staccati, e senza questa riga la musica non sarebbe
                   più tornata per il resto della sessione. */
                ascoltaGesti();
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
        const spec = SUONI[nome];
        if (!spec || spec.loop) return;
        /* Finché l'audio è bloccato o muto gli effetti si buttano via invece
           di accodarli. Accodandoli, al primo clic dell'utente sarebbero
           partiti tutti insieme gli scontri dei turni precedenti — e la coda
           restava incastrata, perché il controllo anti-doppione qui sotto
           trovava il nome già dentro e non ripartiva più. */
        if (!sbloccato || muto) return;

        /* I suoni di fine partita non fanno la fila: quello che sta suonando
           appartiene a un turno che non conta più.

           Senza questo si sentiva la fanfara PRIMA della battaglia che
           aveva deciso la partita: la schermata finale chiede il suo suono
           durante il render, gli eventi del turno vengono letti subito dopo
           (questo modulo avvolge `renderBattleState` dall'esterno di quello
           della schermata), e in coda finivano nell'ordine sbagliato. */
        if (spec.finale) {
            partitaFinita = true;
            /* Richiesta due volte (un render ripetuto a partita già finita):
               si lascia suonare quella in corso invece di farla ripartire
               da capo. */
            if (inRiproduzione === nome) return;
            coda = [{ nome: nome, nato: adesso() }];
            interrompiCorrente();
            serviCoda();
            return;
        }
        if (partitaFinita) return;

        /* Un effetto non si sovrappone a se stesso né si mette due volte in
           attesa: è la protezione contro gli scontri di artiglieria a
           ripetizione, che chiedono la stessa esplosione turno dopo turno.
           Guardare solo la coda non bastava, perché quello in riproduzione
           dalla coda è già uscito. */
        if (inRiproduzione === nome) return;
        for (let i = 0; i < coda.length; i++) {
            if (coda[i].nome === nome) return;
        }
        if (coda.length >= CODA_MASSIMA) return;

        coda.push({ nome: nome, nato: adesso() });
        serviCoda();
    }

    function serviCoda() {
        if (muto || !sbloccato || inRiproduzione) return;

        /* Si scartano gli effetti che hanno aspettato troppo: raccontano un
           turno che il giocatore ha già dimenticato. I suoni di fine partita
           non scadono mai — quelli si aspettano. */
        let voce = null;
        while (coda.length) {
            const candidata = coda.shift();
            const suo = SUONI[candidata.nome];
            const attesa = suo && suo.pazienza ? suo.pazienza : SCADENZA_MS;
            if (suo && (suo.finale || adesso() - candidata.nato <= attesa)) {
                voce = candidata;
                break;
            }
        }
        if (!voce) return;

        const nome = voce.nome;
        const audio = elementi[nome];
        if (!audio) return;

        inRiproduzione = nome;
        if (SUONI[nome].finale) {
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
        clearTimeout(timerCoda);
        const durata = (isFinite(audio.duration) && audio.duration > 0)
            ? audio.duration * 1000
            : DURATA_IGNOTA_MS;
        timerCoda = setTimeout(fine, durata + 250);
    }

    /* Zittisce l'effetto in corso e libera il posto, senza far ripartire
       niente: cosa viene dopo lo decide chi chiama. */
    function interrompiCorrente() {
        clearTimeout(timerCoda);
        const audio = inRiproduzione ? elementi[inRiproduzione] : null;
        if (audio) {
            audio.onended = null;
            audio.pause();
            try { audio.currentTime = 0; } catch (_) {}
        }
        inRiproduzione = null;
    }

    function fine() {
        const precedente = inRiproduzione;
        const chiuso = precedente && SUONI[precedente] && SUONI[precedente].finale;
        /* Si ferma davvero l'effetto uscente: se a chiamare `fine` è stata
           la rete di sicurezza e non `onended`, il file sta ancora suonando
           e il prossimo gli si accavallerebbe sopra. */
        interrompiCorrente();
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
            } else if (tipo === 'armata_schierata') {
                /* Non `legione_creata`: quello è il momento della nascita, e
                   le legioni dell'IA nascono con una manciata di uomini per
                   poi riempirsi turno dopo turno. Il BRAAAM è l'arrivo di
                   un'armata, e a stabilire quando una legione lo diventa è il
                   backend — come per l'artiglieria, qui non si contano le
                   truppe. */
                nuovaLegione = true;
            }
        }

        if (combattimento) accoda(combattimento);
        if (nuovaLegione) accoda('legione');
    }

    function applica(stato) {
        if (!stato || !Array.isArray(stato.events)) return;

        /* Fuori dal game over il banco riapre. Ci si potrebbe affidare agli id
           che ripartono da capo, ma quello succede solo se la partita nuova ha
           gia' prodotto meno eventi della precedente: qui il segnale è
           diretto e non dipende da quanto è durata la partita di prima. */
        if (stato.state !== 'game_over' && partitaFinita) {
            partitaFinita = false;
            /* E con il banco riparte la musica. "Ricomincia scontro" rifa la
               partita SENZA ricaricare la pagina (`restartFromStoredSetup` in
               features.js), quindi il modulo non si reinizializza: il tema,
               che la fanfara aveva spento, resterebbe fermo fino al tocco
               successivo sul pulsante dell'audio. */
            avviaTema();
        }

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
