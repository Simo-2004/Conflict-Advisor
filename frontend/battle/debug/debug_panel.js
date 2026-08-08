/*
 * War Advisor - Pannello Debug (SGANCIABILE)
 *
 * Modulo autonomo: crea da sé la tab "Debug", il suo pannello e il proprio
 * CSS. Non richiede markup in battle.html oltre al tag <script> che lo carica,
 * e non è referenziato da nessun altro file del frontend.
 *
 * Rimozione: cancella questa cartella e il singolo <script> in battle.html
 * marcato [DEBUG-MODULE]. Istruzioni complete in
 * gamecore/debug_module/README.md
 */
(function () {
    'use strict';

    const API = 'http://127.0.0.1:8000/game/debug';
    const TAB_KEY = 'debug';

    /* ── CSS iniettato dal modulo ────────────────────────────────── */
    const STYLE = `
        .bar-tab[data-tab="debug"] { color: #b45309; }
        .bar-tab[data-tab="debug"].active { color: #92400e; }

        .debug-pane-inner { display: grid; gap: 10px; }

        .debug-warning {
            border: 1px solid #fcd34d;
            border-left: 4px solid #d97706;
            background: #fffbeb;
            color: #92400e;
            border-radius: 8px;
            padding: 8px 10px;
            font-size: 0.78em;
            font-weight: 700;
        }

        .debug-group {
            border: 1px solid var(--border, #ddd);
            border-radius: 10px;
            background: #fff;
            padding: 10px;
            display: grid;
            gap: 8px;
        }

        .debug-group > h4 {
            margin: 0;
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: #64748b;
        }

        .debug-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
        .debug-row > label { font-size: 0.78em; font-weight: 700; color: #475569; }

        .debug-pane-inner input,
        .debug-pane-inner select {
            padding: 6px 8px;
            border-radius: 7px;
            border: 1px solid var(--border, #ddd);
            font-size: 0.84em;
            background: #fff;
            min-width: 0;
        }
        .debug-pane-inner input[type="number"] { width: 84px; }
        .debug-pane-inner select { flex: 1 1 120px; }

        .debug-btn {
            padding: 6px 10px;
            font-size: 0.8em;
            font-weight: 700;
            border: 1px solid transparent;
            border-radius: 7px;
            background: #b45309;
            color: #fff;
            cursor: pointer;
        }
        .debug-btn:hover { background: #92400e; }
        .debug-btn.secondary { background: #475569; }
        .debug-btn.secondary:hover { background: #334155; }
        .debug-btn.danger { background: #b91c1c; }
        .debug-btn.danger:hover { background: #991b1b; }

        .debug-killswitch {
            width: 100%;
            padding: 9px;
            font-size: 0.86em;
            font-weight: 800;
            border-radius: 8px;
            border: 1px solid transparent;
            cursor: pointer;
            background: #16a34a;
            color: #fff;
        }
        .debug-killswitch.frozen { background: #b91c1c; }

        .debug-feedback {
            font-size: 0.76em;
            color: #334155;
            background: #f1f5f9;
            border-radius: 7px;
            padding: 7px 9px;
            min-height: 30px;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .debug-feedback.error { background: #fef2f2; color: #b91c1c; }

        .debug-snapshot {
            font-family: ui-monospace, Consolas, monospace;
            font-size: 0.72em;
            line-height: 1.5;
            background: #0f172a;
            color: #e2e8f0;
            border-radius: 8px;
            padding: 9px;
            max-height: 190px;
            overflow: auto;
            white-space: pre;
        }
    `;

    /* ── Utility ─────────────────────────────────────────────────── */

    function injectStyle() {
        if (document.getElementById('debugPanelStyle')) return;
        const tag = document.createElement('style');
        tag.id = 'debugPanelStyle';
        tag.textContent = STYLE;
        document.head.appendChild(tag);
    }

    function el(id) { return document.getElementById(id); }

    function feedback(text, isError) {
        const box = el('debugFeedback');
        if (!box) return;
        box.textContent = text;
        box.classList.toggle('error', Boolean(isError));
    }

    /** Ridisegna la partita con lo stato appena tornato dal server. */
    function applySession(session) {
        if (session && typeof window.renderBattleState === 'function') {
            window.renderBattleState(session);
        }
    }

    async function call(path, body) {
        try {
            const response = await fetch(`${API}/${path}`, {
                method: body === undefined ? 'GET' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body === undefined ? undefined : JSON.stringify(body),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || `Errore ${response.status}`);
            return payload;
        } catch (error) {
            feedback(`✖ ${error.message}`, true);
            return null;
        }
    }

    async function action(path, body, describe) {
        const result = await call(path, body ?? {});
        if (!result) return;
        applySession(result.session);
        feedback(`✔ ${describe || result.message || 'fatto'}`);
        refreshSnapshot();
    }

    function scope() {
        const select = el('debugEntitySelect');
        return { entity: select ? select.value : 'player' };
    }

    function amount(id, fallback) {
        const input = el(id);
        const value = input ? parseInt(input.value, 10) : NaN;
        return Number.isFinite(value) ? value : fallback;
    }

    /* ── Kill switch ─────────────────────────────────────────────── */

    async function toggleKillSwitch() {
        const result = await call('ai-kill-switch', {});
        if (!result) return;
        applySession(result.session);
        feedback(`✔ ${result.message || 'kill switch aggiornato'}`);
        refreshSnapshot();   // rilegge anche lo stato dello switch
    }

    /** Lo stato dello switch arriva dallo snapshot: il pannello non deve
     *  agganciarsi al render del gioco per restare allineato. */
    function syncKillSwitchButton(frozen) {
        const button = el('debugKillSwitchBtn');
        if (!button) return;
        button.classList.toggle('frozen', Boolean(frozen));
        button.textContent = frozen
            ? '🧪 IA CONGELATA — clicca per riattivare'
            : '🧪 IA attiva — clicca per congelare';
    }

    /* ── Snapshot ────────────────────────────────────────────────── */

    async function refreshSnapshot() {
        const box = el('debugSnapshot');
        if (!box) return;
        const snap = await call('snapshot');
        if (!snap) return;
        syncKillSwitchButton(snap.ai_kill_switch);

        const side = (label, s) => [
            `${label}`,
            `  grux ${s.grux}   riserva ${s.reserve}   celle ${s.cells}`,
            `  castello ${s.castle_hp}/${s.castle_hp_max}`,
            ...(s.legions.length
                ? s.legions.map(l => `  · ${l.name} (${l.type}) ${l.units}u @ ${l.pos.join(',')}`)
                : ['  · nessuna legione']),
        ].join('\n');

        box.textContent = [
            `turno ${snap.turn}   stato ${snap.state}${snap.winner ? `   vince ${snap.winner}` : ''}`,
            `difficoltà ${snap.ai_difficulty}   kill switch ${snap.ai_kill_switch ? 'ON' : 'off'}`,
            '',
            side('PLAYER', snap.player),
            '',
            side('IA', snap.ai),
        ].join('\n');
    }

    /* ── Costruzione pannello ────────────────────────────────────── */

    function paneHtml() {
        return `
            <div class="debug-pane-inner">
                <div class="debug-warning">
                    Strumenti di sviluppo — modulo sganciabile, da rimuovere prima della consegna.
                </div>

                <button class="debug-killswitch" id="debugKillSwitchBtn" type="button">🧪 IA attiva — clicca per congelare</button>

                <div class="debug-group">
                    <h4>Bersaglio delle azioni</h4>
                    <div class="debug-row">
                        <label for="debugEntitySelect">Applica a</label>
                        <select id="debugEntitySelect">
                            <option value="player">Player</option>
                            <option value="ai">IA</option>
                        </select>
                    </div>
                </div>

                <div class="debug-group">
                    <h4>Economia</h4>
                    <div class="debug-row">
                        <input type="number" id="debugGruxAmount" value="1000" step="100">
                        <button class="debug-btn" id="debugGruxBtn" type="button">Aggiungi grux</button>
                        <button class="debug-btn secondary" id="debugGruxBigBtn" type="button">+10.000</button>
                    </div>
                    <div class="debug-row">
                        <input type="number" id="debugTerritoryCells" value="8" min="1" max="224">
                        <button class="debug-btn" id="debugTerritoryBtn" type="button">Assegna celle</button>
                    </div>
                </div>

                <div class="debug-group">
                    <h4>Truppe</h4>
                    <div class="debug-row">
                        <select id="debugUnitSelect"></select>
                        <input type="number" id="debugUnitCount" value="10" min="1" max="200">
                    </div>
                    <div class="debug-row">
                        <button class="debug-btn" id="debugUnitsBtn" type="button">Aggiungi truppe</button>
                        <button class="debug-btn danger" id="debugClearUnitsBtn" type="button">Svuota riserva</button>
                    </div>
                </div>

                <div class="debug-group">
                    <h4>Partita</h4>
                    <div class="debug-row">
                        <input type="number" id="debugSkipTurns" value="10" min="1" max="200">
                        <button class="debug-btn" id="debugSkipBtn" type="button">Salta turni</button>
                    </div>
                    <div class="debug-row">
                        <input type="number" id="debugCastleHp" value="50" min="0">
                        <button class="debug-btn" id="debugCastleHpBtn" type="button">HP castello</button>
                    </div>
                    <div class="debug-row">
                        <button class="debug-btn secondary" id="debugAbilitiesBtn" type="button">Sblocca abilità</button>
                        <button class="debug-btn secondary" id="debugMovementBtn" type="button">Sblocca marce</button>
                    </div>
                    <div class="debug-row">
                        <button class="debug-btn danger" id="debugWinBtn" type="button">Vinci subito</button>
                        <button class="debug-btn danger" id="debugLoseBtn" type="button">Perdi subito</button>
                    </div>
                </div>

                <div class="debug-group">
                    <h4>Stato partita</h4>
                    <div class="debug-row">
                        <button class="debug-btn secondary" id="debugSnapshotBtn" type="button">Aggiorna</button>
                    </div>
                    <div class="debug-snapshot" id="debugSnapshot">—</div>
                </div>

                <div class="debug-feedback" id="debugFeedback">Pronto.</div>
            </div>
        `;
    }

    function wire() {
        const on = (id, handler) => { const node = el(id); if (node) node.addEventListener('click', handler); };

        on('debugKillSwitchBtn', toggleKillSwitch);

        on('debugGruxBtn', () => action('grant-grux', { ...scope(), amount: amount('debugGruxAmount', 1000) }));
        on('debugGruxBigBtn', () => action('grant-grux', { ...scope(), amount: 10000 }));
        on('debugTerritoryBtn', () => action('grant-territory', { ...scope(), cells: amount('debugTerritoryCells', 8) }));

        on('debugUnitsBtn', () => {
            const unit = el('debugUnitSelect');
            if (!unit || !unit.value) { feedback('✖ nessuna unità disponibile nel selettore', true); return; }
            action('grant-units', { ...scope(), unit_id: unit.value, count: amount('debugUnitCount', 10) });
        });
        on('debugClearUnitsBtn', () => action('clear-units', scope()));

        on('debugSkipBtn', () => action('skip-turns', { count: amount('debugSkipTurns', 10) }));
        on('debugCastleHpBtn', () => action('set-castle-hp', { ...scope(), hp: amount('debugCastleHp', 50) }));
        on('debugAbilitiesBtn', () => action('unlock-abilities', scope()));
        on('debugMovementBtn', () => action('clear-movement-blocks', {}));
        on('debugWinBtn', () => action('force-outcome', { winner: 'player' }));
        on('debugLoseBtn', () => action('force-outcome', { winner: 'ai' }));

        on('debugSnapshotBtn', refreshSnapshot);
    }

    /** Riempie il menu unità dalla config del gioco. */
    async function loadUnits() {
        const select = el('debugUnitSelect');
        if (!select) return;
        try {
            const config = await (await fetch('http://127.0.0.1:8000/config')).json();
            select.innerHTML = (config.units || [])
                .map(unit => `<option value="${unit.id}">${unit.name} • ${unit.cost_grux} grux</option>`)
                .join('');
        } catch (_) {
            select.innerHTML = '<option value="">config non disponibile</option>';
        }
    }

    /**
     * Aggiunge tab e pannello alla barra esistente.
     * La barra viene costruita da battle_bar.js dopo il DOMContentLoaded,
     * quindi si attende che compaia invece di dare per scontato l'ordine
     * di caricamento degli script.
     */
    function mount() {
        const bar = el('battle_bar');
        if (!bar || el('debugPaneRoot')) return false;

        const tabs = bar.querySelector('.bar-tabs');
        const content = bar.querySelector('.bar-content');
        if (!tabs || !content) return false;

        injectStyle();

        const tab = document.createElement('button');
        tab.className = 'bar-tab';
        tab.type = 'button';
        tab.dataset.tab = TAB_KEY;
        tab.textContent = '🧪 Debug';
        tabs.appendChild(tab);

        const pane = document.createElement('div');
        pane.className = 'dock-pane';
        pane.dataset.pane = TAB_KEY;
        pane.id = 'debugPaneRoot';
        pane.innerHTML = paneHtml();
        content.appendChild(pane);

        // Lo switch di tab della barra vive dentro una IIFE e non è esposto:
        // il modulo se lo rifà da sé sulle stesse classi. Gli handler delle
        // altre tab usano querySelectorAll su tutto il documento, quindi
        // disattivano correttamente anche questo pannello.
        tab.addEventListener('click', () => {
            if (window.LegionsPanel && typeof window.LegionsPanel.exitPickMode === 'function') {
                window.LegionsPanel.exitPickMode();   // stessa cortesia delle altre tab
            }
            bar.dataset.activeTab = TAB_KEY;
            document.querySelectorAll('.bar-tab').forEach(t => t.classList.toggle('active', t === tab));
            document.querySelectorAll('.dock-pane').forEach(p => p.classList.toggle('active', p === pane));
            refreshSnapshot();
        });

        wire();
        loadUnits();
        refreshSnapshot();
        return true;
    }

    function waitForBar() {
        if (mount()) return;
        let attempts = 0;
        const timer = setInterval(() => {
            attempts += 1;
            if (mount() || attempts > 40) clearInterval(timer);
        }, 150);
    }

    window.addEventListener('DOMContentLoaded', waitForBar);
})();
