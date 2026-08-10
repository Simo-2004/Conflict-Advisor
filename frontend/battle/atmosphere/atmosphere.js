/*
 * War Advisor - Atmosfera meteo sulla mappa (SGANCIABILE)
 *
 * Riflette sulla sola mappa le condizioni ambientali già calcolate dal backend
 * (`session.weather_state`): luce di giorno, buio di notte, pioggia, nebbia.
 *
 * È puramente decorativo: non legge né scrive lo stato di gioco, non intercetta
 * click (tutti i livelli hanno pointer-events:none) e non tocca nessun altro
 * file del frontend. Se sparisce, la mappa torna esattamente com'era.
 *
 * Rimozione: cancella questa cartella e il singolo <script> in battle.html
 * marcato [ATMOSPHERE-MODULE]. Dettagli in README.md qui accanto.
 */
(function () {
    'use strict';

    const BOARD_ID = 'mapBoard';
    const STAGE_CLASS = 'atmo-stage';
    const ROOT_CLASS = 'atmo-root';

    /* Origine dei tempi del modulo.
     *
     * `renderMapBoard` azzera l'innerHTML della mappa a ogni turno, quindi i
     * livelli vengono ricreati e le loro animazioni CSS ripartirebbero da capo:
     * era questo il "reset brutto" delle gocce a ogni nuovo turno. Ogni livello
     * ricreato riceve un animation-delay negativo calcolato da qui, così
     * riprende esattamente dalla fase in cui sarebbe stato se non fosse mai
     * stato staccato dal DOM. Il turno cambia e la pioggia continua a cadere. */
    const EPOCH = now();

    function now() {
        return (window.performance && performance.now) ? performance.now() : Date.now();
    }

    /* ── CSS iniettato dal modulo ────────────────────────────────── */
    const STYLE = `
        .${ROOT_CLASS} { isolation: isolate; transition: filter 900ms ease; }

        /* Palco: ritaglia i livelli, che sono più grandi del riquadro (servono
           più grandi perché ruotano e derivano). L'overflow qui è hidden, così
           lo sbordo non genera scrollbar sulla mappa. Le misure in px arrivano
           da JS: la mappa scrolla in orizzontale nella vista split, e con
           inset:0 il palco copriva solo la prima schermata. */
        .${STAGE_CLASS} {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            border-radius: 12px;
            pointer-events: none;
            z-index: 2;   /* sopra le celle, sotto pedine (36) e puntamento (999) */
        }

        .atmo-layer {
            position: absolute;
            top: -20%;
            left: -20%;
            width: 140%;
            height: 140%;
            pointer-events: none;
            will-change: transform;
        }

        /* ── Luce ─────────────────────────────────────────────────
           La luminosità di fondo si fa con un filtro sulla mappa, non con un
           velo opaco: il velo sbiadiva i colori invece di ravvivarli. */
        .${ROOT_CLASS}.atmo-day   { filter: brightness(1.07) saturate(1.12); }
        .${ROOT_CLASS}.atmo-night { filter: brightness(0.74) saturate(0.82) contrast(1.03); }

        /* Sotto la pioggia la mappa cala un filo anche di giorno: su un fondo
           chiaro le gocce, che sono chiare, sparivano. */
        .${ROOT_CLASS}.atmo-day.atmo-rain   { filter: brightness(0.91) saturate(0.92); }
        .${ROOT_CLASS}.atmo-night.atmo-rain { filter: brightness(0.70) saturate(0.76) contrast(1.03); }

        /* La nebbia è ciò che "offusca": sfoca appena tutta la mappa. Di notte
           sfoca meno del giorno, altrimenti buio + sfocatura diventano un muro. */
        .${ROOT_CLASS}.atmo-day.atmo-fog   { filter: brightness(1.02) saturate(0.88) blur(0.35px); }
        .${ROOT_CLASS}.atmo-night.atmo-fog { filter: brightness(0.78) saturate(0.76) blur(0.25px); }

        /* ── Velo notturno ────────────────────────────────────────
           Unico livello fermo: dà il tono, non la luminosità. */
        .atmo-veil {
            top: 0; left: 0; width: 100%; height: 100%;
            background:
                radial-gradient(circle at 78% 8%, rgba(199,210,254,0.18) 0%, rgba(199,210,254,0) 42%),
                linear-gradient(180deg, rgba(30,27,75,0.20) 0%, rgba(15,23,42,0.28) 100%);
        }

        /* ── Luce che si muove sulle caselle ──────────────────────
           Pozza di sole calda che attraversa la mappa da sinistra a destra e
           torna indietro. Niente 'soft-light': la mappa parte da un fondo quasi
           bianco (#fafafa) e soft-light su valori vicini a 1 non cambia nulla,
           il sole risultava invisibile. Una tinta calda in sovrapposizione
           normale si vede, e su verdi e ocra sembra davvero luce del sole. */
        .atmo-glow {
            background: radial-gradient(34% 44% at 50% 34%,
                rgba(255,211,112,0.33) 0%,
                rgba(255,224,152,0.17) 40%,
                rgba(255,236,190,0.06) 62%,
                rgba(255,236,190,0) 75%);
            animation: atmo-glow 22s ease-in-out infinite alternate;
        }
        .${ROOT_CLASS}.atmo-night .atmo-glow {
            background: radial-gradient(32% 40% at 50% 26%,
                rgba(186,209,255,0.30) 0%,
                rgba(186,209,255,0.12) 44%,
                rgba(186,209,255,0) 72%);
            animation-duration: 52s;
        }

        /* Ombre di nuvole: passano sopra le caselle e le scuriscono appena.
           'multiply' scurisce senza ingrigire. */
        .atmo-shade {
            background:
                radial-gradient(30% 34% at 22% 30%, rgba(90,104,130,0.20) 0%, rgba(90,104,130,0) 70%),
                radial-gradient(26% 30% at 68% 62%, rgba(90,104,130,0.16) 0%, rgba(90,104,130,0) 70%),
                radial-gradient(20% 24% at 46% 88%, rgba(90,104,130,0.13) 0%, rgba(90,104,130,0) 70%);
            mix-blend-mode: multiply;
            opacity: 0.70;
            animation: atmo-shade 46s ease-in-out infinite alternate;
        }
        .${ROOT_CLASS}.atmo-rain  .atmo-shade { opacity: 0.85; }
        .${ROOT_CLASS}.atmo-night .atmo-shade { opacity: 0.35; }

        /* Andata e ritorno (alternate): un ciclo lineare tornerebbe di scatto
           al punto di partenza, ed è uno dei salti che si vedevano. */
        /* Corsa larga: ±22% di un livello alto e largo 140% della mappa fanno
           circa mezzo tabellone di viaggio per lato, così il passaggio del sole
           si nota davvero. */
        @keyframes atmo-glow {
            from { transform: translate3d(-22%, -3%, 0) scale(1); }
            to   { transform: translate3d(22%, 4%, 0) scale(1.08); }
        }
        @keyframes atmo-shade {
            from { transform: translate3d(-11%, -2%, 0); }
            to   { transform: translate3d(11%, 3%, 0); }
        }

        /* ── Pioggia ──────────────────────────────────────────────
           Gocce vere, non righe: ogni goccia è un'ellisse sfumata dentro una
           piastrella che si ripete. Due livelli a velocità e dimensioni
           diverse danno la profondità. La traslazione vale ESATTAMENTE una
           piastrella, quindi il ciclo si richiude senza giunture. */
        .atmo-rain-near {
            background-image:
                radial-gradient(1.3px 9px   at 14px 26px,  rgba(224,242,255,0.62) 0%, rgba(224,242,255,0) 100%),
                radial-gradient(1.1px 7px   at 58px 100px, rgba(224,242,255,0.48) 0%, rgba(224,242,255,0) 100%),
                radial-gradient(1.2px 8px   at 97px 44px,  rgba(224,242,255,0.55) 0%, rgba(224,242,255,0) 100%),
                radial-gradient(1px   6px   at 36px 152px, rgba(224,242,255,0.38) 0%, rgba(224,242,255,0) 100%),
                radial-gradient(1.15px 7.5px at 118px 128px, rgba(224,242,255,0.45) 0%, rgba(224,242,255,0) 100%);
            background-size: 132px 184px;
            animation: atmo-rain-near 820ms linear infinite;
        }

        .atmo-rain-far {
            background-image:
                radial-gradient(0.9px 5.5px at 26px 40px,   rgba(203,213,225,0.30) 0%, rgba(203,213,225,0) 100%),
                radial-gradient(1px   6px   at 104px 128px, rgba(203,213,225,0.26) 0%, rgba(203,213,225,0) 100%),
                radial-gradient(0.85px 5px  at 150px 60px,  rgba(203,213,225,0.22) 0%, rgba(203,213,225,0) 100%),
                radial-gradient(0.9px 5.5px at 66px 196px,  rgba(203,213,225,0.24) 0%, rgba(203,213,225,0) 100%);
            background-size: 176px 236px;
            animation: atmo-rain-far 1580ms linear infinite;
            opacity: 0.75;
        }

        @keyframes atmo-rain-near {
            from { transform: rotate(11deg) translate3d(0, 0, 0); }
            to   { transform: rotate(11deg) translate3d(0, 184px, 0); }
        }
        @keyframes atmo-rain-far {
            from { transform: rotate(8deg) translate3d(0, 0, 0); }
            to   { transform: rotate(8deg) translate3d(0, 236px, 0); }
        }

        /* ── Nebbia ───────────────────────────────────────────────
           Un banco largo che respira + due strati di nuvolette che attraversano
           davvero la mappa a velocità diverse. Il banco da solo era una coltre
           ferma: il movimento lo danno le nuvolette. */
        .atmo-fog-a {
            background:
                radial-gradient(45% 55% at 20% 45%, rgba(255,255,255,0.72) 0%, rgba(255,255,255,0) 70%),
                radial-gradient(38% 48% at 58% 62%, rgba(248,250,252,0.60) 0%, rgba(248,250,252,0) 70%),
                radial-gradient(42% 50% at 88% 38%, rgba(241,245,249,0.64) 0%, rgba(241,245,249,0) 70%);
            opacity: 0.62;
            animation: atmo-fog-a 21s ease-in-out infinite alternate;
        }
        .${ROOT_CLASS}.atmo-night .atmo-fog-a { opacity: 0.30; }

        @keyframes atmo-fog-a {
            from { transform: translate3d(-6%, 0, 0) scale(1); }
            to   { transform: translate3d(6%, 2%, 0) scale(1.08); }
        }

        /* Nuvolette: piastrelle che scorrono di esattamente una piastrella,
           quindi il giro si chiude senza salto. Due misure a due velocità
           danno la sensazione di banchi che si sfilano davanti. */
        .atmo-wisp-a {
            background-image:
                radial-gradient(22% 30% at 16% 38%, rgba(255,255,255,0.78) 0%, rgba(255,255,255,0) 70%),
                radial-gradient(16% 22% at 44% 66%, rgba(248,250,252,0.62) 0%, rgba(248,250,252,0) 70%),
                radial-gradient(19% 26% at 72% 28%, rgba(255,255,255,0.68) 0%, rgba(255,255,255,0) 70%),
                radial-gradient(13% 18% at 90% 80%, rgba(241,245,249,0.52) 0%, rgba(241,245,249,0) 70%),
                radial-gradient(11% 15% at 28% 88%, rgba(255,255,255,0.46) 0%, rgba(255,255,255,0) 70%);
            background-size: 340px 230px;
            opacity: 1;
            animation: atmo-wisp-a 15s linear infinite;
        }
        .atmo-wisp-b {
            background-image:
                radial-gradient(15% 21% at 20% 30%, rgba(255,255,255,0.52) 0%, rgba(255,255,255,0) 70%),
                radial-gradient(12% 17% at 58% 62%, rgba(248,250,252,0.46) 0%, rgba(248,250,252,0) 70%),
                radial-gradient(10% 14% at 84% 20%, rgba(255,255,255,0.42) 0%, rgba(255,255,255,0) 70%),
                radial-gradient(9% 13% at 36% 84%,  rgba(241,245,249,0.38) 0%, rgba(241,245,249,0) 70%),
                radial-gradient(8% 11% at 70% 44%,  rgba(255,255,255,0.36) 0%, rgba(255,255,255,0) 70%),
                radial-gradient(7% 10% at 12% 68%,  rgba(248,250,252,0.30) 0%, rgba(248,250,252,0) 70%);
            background-size: 240px 170px;
            opacity: 0.90;
            animation: atmo-wisp-b 9.5s linear infinite;
        }
        .${ROOT_CLASS}.atmo-night .atmo-wisp-a { opacity: 0.62; }
        .${ROOT_CLASS}.atmo-night .atmo-wisp-b { opacity: 0.50; }

        @keyframes atmo-wisp-a {
            from { transform: translate3d(0, 0, 0); }
            to   { transform: translate3d(340px, 0, 0); }
        }
        @keyframes atmo-wisp-b {
            from { transform: translate3d(0, 0, 0); }
            to   { transform: translate3d(240px, 0, 0); }
        }

        /* Chi ha chiesto meno animazioni non resta senza meteo: il movimento
           non si spegne, rallenta molto. Fermarlo del tutto faceva sembrare
           l'effetto rotto — pioggia disegnata e immobile. */
        @media (prefers-reduced-motion: reduce) {
            .atmo-rain-near { animation-duration: 3.2s; }
            .atmo-rain-far  { animation-duration: 6.1s; }
            .atmo-fog-a     { animation-duration: 52s; }
            .atmo-wisp-a    { animation-duration: 37s; }
            .atmo-wisp-b    { animation-duration: 24s; }
            .atmo-glow      { animation-duration: 58s; }
            .atmo-shade     { animation-duration: 112s; }
        }
    `;

    function injectStyle() {
        if (document.getElementById('atmosphereStyle')) return;
        const tag = document.createElement('style');
        tag.id = 'atmosphereStyle';
        tag.textContent = STYLE;
        document.head.appendChild(tag);
    }

    /** Livelli richiesti dalla condizione corrente. Ne esistono solo quelli
     *  che servono davvero: ogni livello è una texture grande quanto la mappa,
     *  tenerli tutti in memoria costava senza mostrare niente. */
    function layersFor(isNight, weather) {
        const set = [];
        if (isNight) set.push('atmo-veil');

        if (weather === 'Pioggia') {
            set.push('atmo-shade', 'atmo-rain-far', 'atmo-rain-near');
        } else if (weather === 'Nebbia') {
            set.push('atmo-fog-a', 'atmo-wisp-a', 'atmo-wisp-b');
        } else {
            // il sole va sopra le ombre, non sotto: al contrario lo spegnevano
            set.push('atmo-shade', 'atmo-glow');
        }
        return set;
    }

    function durationMs(value) {
        const raw = String(value || '').split(',')[0].trim();
        if (raw.endsWith('ms')) return parseFloat(raw) || 0;
        if (raw.endsWith('s')) return (parseFloat(raw) || 0) * 1000;
        return 0;
    }

    /** Riallinea le animazioni appena create alla fase che avrebbero avuto se
     *  fossero rimaste attaccate al DOM dall'inizio della partita.
     *  Il modulo è (2 × durata) e non (1 × durata) per via delle animazioni
     *  'alternate': serve sapere anche se il giro corrente è andata o ritorno. */
    function syncPhase(stage) {
        const elapsed = now() - EPOCH;
        for (const layer of stage.children) {
            const dur = durationMs(getComputedStyle(layer).animationDuration);
            if (dur > 0) {
                layer.style.animationDelay = '-' + Math.round(elapsed % (dur * 2)) + 'ms';
            }
        }
    }

    /** Il palco deve coprire tutta l'area scorrevole, non solo la porzione
     *  visibile: nella vista split la mappa scrolla in orizzontale e con
     *  inset:0 il meteo finiva a metà tabellone. Le misure si prendono con il
     *  palco azzerato, così non si misura sé stesso. */
    function sizeStage(board, stage) {
        if (!board.clientWidth) return;   // mappa nascosta (vista Log): niente da misurare

        stage.style.width = '0px';
        stage.style.height = '0px';
        const w = board.scrollWidth;
        const h = board.scrollHeight;
        stage.style.width = w + 'px';
        stage.style.height = h + 'px';
    }

    /** Ricrea palco e livelli solo quando serve davvero: se la mappa non è
     *  stata azzerata e la condizione non è cambiata, il palco resta quello di
     *  prima e le animazioni non subiscono nessuno scatto. */
    function ensureStage(board, key, layers) {
        let stage = board.querySelector('.' + STAGE_CLASS);
        if (stage && stage.dataset.atmoKey === key) return stage;
        if (stage) stage.remove();

        stage = document.createElement('div');
        stage.className = STAGE_CLASS;
        stage.dataset.atmoKey = key;
        stage.setAttribute('aria-hidden', 'true');

        for (const name of layers) {
            const layer = document.createElement('div');
            layer.className = 'atmo-layer ' + name;
            stage.appendChild(layer);
        }

        board.appendChild(stage);
        syncPhase(stage);
        return stage;
    }

    /** Rimisura più tardi: al primo render la mappa è ancora dentro un pannello
     *  display:none (bootstrap.js lo mostra subito DOPO renderBattleState), e
     *  un elemento non renderizzato non si può misurare. */
    function refreshSize(board, delay) {
        setTimeout(() => {
            const stage = board.querySelector('.' + STAGE_CLASS);
            if (stage) sizeStage(board, stage);
        }, delay);
    }

    let watching = false;

    /** La mappa cambia misura con i pulsanti Vista Split/Mappa/Log e con la
     *  finestra: il palco va rimisurato, altrimenti resta della taglia vecchia. */
    function watchBoard(board) {
        if (watching) return;
        watching = true;

        if (typeof ResizeObserver === 'function') {
            new ResizeObserver(() => {
                const stage = board.querySelector('.' + STAGE_CLASS);
                if (stage) sizeStage(board, stage);
            }).observe(board);
        }
        window.addEventListener('resize', () => refreshSize(board, 120));
    }

    function apply(weatherState) {
        const board = document.getElementById(BOARD_ID);
        if (!board) return;

        injectStyle();
        board.classList.add(ROOT_CLASS);

        const isNight = Boolean(weatherState?.is_night);
        const weather = weatherState?.weather || '';

        board.classList.toggle('atmo-night', isNight);
        board.classList.toggle('atmo-day', !isNight);
        board.classList.toggle('atmo-rain', weather === 'Pioggia');
        board.classList.toggle('atmo-fog', weather === 'Nebbia');

        const layers = layersFor(isNight, weather);
        const stage = ensureStage(board, (isNight ? 'notte' : 'giorno') + '|' + weather, layers);
        sizeStage(board, stage);
        refreshSize(board, 0);
        watchBoard(board);

        board.dataset.atmosphere = weatherState?.label || '';
    }

    /* ── Aggancio ────────────────────────────────────────────────── */
    /* Si avvolge attorno a renderBattleState invece di farsi chiamare da
     * dentro: nessun altro file deve sapere che questo modulo esiste. Lo
     * script viene caricato dopo render.js, quindi la funzione c'è già. */
    function hook() {
        const original = window.renderBattleState;
        if (typeof original !== 'function') return false;

        window.renderBattleState = function (sessionData) {
            const result = original.apply(this, arguments);
            try {
                apply(sessionData && sessionData.weather_state);
            } catch (_) {
                /* l'atmosfera non deve mai far cadere il render della partita */
            }
            return result;
        };
        return true;
    }

    if (!hook()) {
        window.addEventListener('DOMContentLoaded', hook);
    }
})();
