/*
 * War Advisor - Avvisi volanti
 *
 * L'unico posto da cui il gioco dice al giocatore che qualcosa non si può
 * fare. Un riquadro rosso in alto a destra, quattro secondi, poi se ne va.
 *
 * Prima gli errori uscivano in due modi, sbagliati tutti e due:
 *   · `alert()` del browser, che blocca la pagina e va chiuso a mano;
 *   · una riga grigia sotto la barra dei turni, che non guarda nessuno.
 * Adesso passano tutti di qui. La riga di stato resta, così il messaggio
 * si può rileggere dopo che il riquadro è sparito.
 *
 * NON è un modulo sganciabile: se sparisce, gli errori non si vedono più.
 * Va caricato per primo, prima di bootstrap.js, così le altre parti lo
 * trovano già pronto.
 *
 * Uso:
 *     segnalaErrore('Non hai grux a sufficienza.');
 */
(function () {
    'use strict';

    const ZONA_ID = 'avvisiVolanti';

    /* Quattro secondi: il tempo di leggere una riga senza restare lì al turno
       dopo. Chi vuole toglierlo prima ci clicca sopra. */
    const DURATA_MS = 4000;
    const USCITA_MS = 320;

    /* Oltre tre riquadri insieme non si legge più niente: i più vecchi escono. */
    const MAX_A_SCHERMO = 3;

    /* ── Il contenitore ──────────────────────────────────────────── */
    /* Attaccato a `body` e non alla mappa: `renderMapBoard` ricostruisce tutte
       le caselle a ogni render e si porterebbe via qualunque cosa attaccata
       lì dentro. */

    function zona() {
        let z = document.getElementById(ZONA_ID);
        if (!z) {
            z = document.createElement('div');
            z.id = ZONA_ID;
            z.className = 'avviso-zona';
            document.body.appendChild(z);
        }
        return z;
    }

    function riga(classe, testo) {
        const el = document.createElement('span');
        el.className = classe;
        el.textContent = testo;      // mai innerHTML: il testo arriva dal server
        return el;
    }

    function chiudi(avviso) {
        if (!avviso || !avviso.parentNode) return;
        avviso.classList.add('is-uscita');
        setTimeout(function () {
            if (avviso.parentNode) avviso.parentNode.removeChild(avviso);
        }, USCITA_MS);
    }

    function riavvia(avviso) {
        clearTimeout(Number(avviso.dataset.timer));
        avviso.dataset.timer = String(setTimeout(function () {
            chiudi(avviso);
        }, DURATA_MS));
    }

    /* ── L'avviso ────────────────────────────────────────────────── */

    function segnalaErrore(messaggio) {
        /* Il testo arriva da un'eccezione o dal `detail` del server, che a
           volte è già prefissato con "Errore:". Toglierlo evita di ripetere
           la stessa parola due volte dentro il riquadro. */
        let testo = String(messaggio == null ? '' : messaggio).trim();
        testo = testo.replace(/^errore[:\s-]+/i, '').trim();
        if (!testo) testo = 'Operazione non riuscita.';

        const z = zona();

        /* Lo stesso errore ripetuto non impila riquadri uguali: ne rinfresca
           uno solo. Succede quando si clicca due volte un comando bloccato. */
        const gemelli = z.querySelectorAll('.avviso');
        for (let i = 0; i < gemelli.length; i++) {
            if (gemelli[i].dataset.testo === testo) {
                gemelli[i].classList.remove('is-uscita');
                riavvia(gemelli[i]);
                return;
            }
        }

        for (let i = 0; i <= gemelli.length - MAX_A_SCHERMO; i++) {
            chiudi(gemelli[i]);
        }

        const avviso = document.createElement('div');
        avviso.className = 'avviso';
        avviso.dataset.testo = testo;
        avviso.setAttribute('role', 'alert');
        avviso.title = 'Clicca per chiudere';

        avviso.appendChild(riga('avviso-icona', '⚠'));

        const corpo = document.createElement('div');
        corpo.className = 'avviso-testo';
        corpo.appendChild(riga('avviso-titolo', 'Non si può fare'));
        corpo.appendChild(riga('avviso-corpo', testo));
        avviso.appendChild(corpo);

        avviso.addEventListener('click', function () { chiudi(avviso); });

        /* In cima alla colonna: l'ultimo arrivato è quello che conta. */
        z.insertBefore(avviso, z.firstChild);
        riavvia(avviso);
    }

    window.segnalaErrore = segnalaErrore;
})();
