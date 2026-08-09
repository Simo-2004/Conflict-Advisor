/* ============================================================
   legions_panel.js
   Logica pannello Legioni: sotto-tab Esercito & Legioni,
   sistema LegionPickMode per agganciare celle mappa.
   Montato da battle_bar.js nel pane data-pane="legions"
   ============================================================ */

(function () {
    'use strict';

    /* ── Stato modulo ──────────────────────────────────────── */
    let activeLegionsSubTab = 'army';  // 'army' | 'legions'
    let activeLegions = [];            // lista legioni create
    let legionDraft = {
        name: '',
        units: {},        // { unitId: qty }
        target: null,     // [row, col] | null
        legionType: 'army'  // 'army' | 'mining' | 'construction'
    };
    let legionPickModeActive = false;
    let legionPickListeners = [];  // cleanup pick listeners

    const LEGION_TYPE_LABELS = {
        army: 'Esercito',
        mining: 'Mineraria',
        construction: 'Costruzione'
    };
    const LEGION_TYPE_ICONS = {
        army: '⚔',
        mining: '⛏',
        construction: '🧱'
    };

    /* ── Helpers ───────────────────────────────────────────── */
    function qs(root, sel) {
        return root ? root.querySelector(sel) : null;
    }

    function buildUnitNamesMap() {
        if (typeof recruitableUnits !== 'undefined' && Array.isArray(recruitableUnits)) {
            return new Map(recruitableUnits.map(u => [u.id, u.name || u.id]));
        }
        return new Map();
    }

    function buildUnitCountsFromState(sessionData) {
        const units = sessionData?.player?.units || [];
        const counts = new Map();
        for (const uid of units) {
            counts.set(uid, (counts.get(uid) || 0) + 1);
        }
        return counts;
    }

    function formatGruxLocal(value) {
        const n = Number.isFinite(value) ? value : 0;
        return `${n.toLocaleString('it-IT')} grux`;
    }

    function countUnits(unitIds) {
        const counts = {};
        for (const uid of unitIds || []) {
            counts[uid] = (counts[uid] || 0) + 1;
        }
        return counts;
    }

    function syncActiveLegionsFromSession(sessionData) {
        const source = Object.values(sessionData?.player?.legions || {});
        activeLegions = source.map((legion) => ({
            id: legion.id,
            name: legion.name || String(legion.id || 'Legione'),
            units: Array.isArray(legion.units) ? countUnits(legion.units) : (legion.units || {}),
            target: Array.isArray(legion.target) ? legion.target : null,
            currentPos: Array.isArray(legion.pos) ? legion.pos : null,
            path: Array.isArray(legion.path) ? legion.path : [],
            pathStep: Number(legion.path_step || 0),
            legionType: legion.legion_type || 'army',
            troopStatus: legion.troop_status || null,
            condition: legion.condition || null,
        }));
    }

    /* ── Condizione truppe ──────────────────────────────────── */

    const CONDITION_CLASS = {
        'Fresche': 'fresh',
        'Stanche': 'tired',
        'Demoralizzate': 'broken',
        'Veterane': 'veteran',
    };
    const CONDITION_ICON = {
        'Fresche': '🌿',
        'Stanche': '😓',
        'Demoralizzate': '💔',
        'Veterane': '🎖',
    };

    /** Badge compatto con lo stato truppe. */
    function conditionBadgeHtml(status, condition) {
        if (!status) return '';
        const cls = CONDITION_CLASS[status] || 'fresh';
        const icon = CONDITION_ICON[status] || '•';
        const grado = condition && condition.veteran ? ' · veterana' : '';
        const titolo = condition
            ? `Fatica ${condition.fatigue}/100 · Morale ${condition.morale}/100 · `
              + `Vittorie ${condition.veteran_progress}`
            : status;
        return `<span class="condition-badge condition-${cls}" title="${titolo}">${icon} ${status}${grado}</span>`;
    }

    /** Barrette di fatica e morale: il dettaglio dietro il badge. */
    function conditionBarsHtml(condition) {
        if (!condition) return '';
        const fatica = Math.max(0, Math.min(100, Number(condition.fatigue) || 0));
        const morale = Math.max(0, Math.min(100, Number(condition.morale) || 0));
        return `
            <div class="condition-bar-row" title="Fatica: sale marciando e combattendo, scende stando fermi">
                <span class="condition-bar-label">Fatica</span>
                <span class="condition-bar"><i class="fill fatigue" style="width:${fatica}%"></i></span>
                <span class="condition-bar-value">${Math.round(fatica)}</span>
            </div>
            <div class="condition-bar-row" title="Morale: scende perdendo scontri, risale vincendo e riposando">
                <span class="condition-bar-label">Morale</span>
                <span class="condition-bar"><i class="fill morale" style="width:${morale}%"></i></span>
                <span class="condition-bar-value">${Math.round(morale)}</span>
            </div>
            <div class="condition-veteran">Vittorie verso il grado: ${condition.veteran_progress}</div>`;
    }

    /* ── Tab switching (sotto-tab) ─────────────────────────── */
    function activateLegionsSubTab(key) {
        activeLegionsSubTab = key;
        const pane = document.getElementById('legionsPane');
        if (!pane) return;

        pane.querySelectorAll('.legions-sub-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.subtab === key);
        });
        pane.querySelectorAll('.legions-sub-pane').forEach(p => {
            p.classList.toggle('active', p.dataset.subpane === key);
        });
    }

    /* ── Render "Esercito" ─────────────────────────────────── */
    function renderArmyTab(sessionData) {
        const pane = qs(document.getElementById('legionsPane'), '[data-subpane="army"]');
        if (!pane) return;

        const state = sessionData;
        const player = state?.player || {};
        const units = player.units || [];
        const namesMap = buildUnitNamesMap();
        const counts = buildUnitCountsFromState(state);

        const totalUnits = units.length;
        const armyCost = player.army_cost || 0;
        const strategyName = player.strategy_name || player.strategy_id || '---';
        // Stato della riserva nel castello: il backend lo valorizza sempre,
        // quindi "N/D" resta solo come rete di sicurezza.
        const troopStatus = player.troop_status || 'N/D';
        const reserveCondition = player.troop_condition || null;

        const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
        const maxCount = sorted.length > 0 ? sorted[0][1] : 1;

        let unitRowsHtml = '';
        if (sorted.length === 0) {
            unitRowsHtml = '<div class="army-empty-msg">Nessuna unità schierata.</div>';
        } else {
            unitRowsHtml = sorted.map(([uid, cnt]) => {
                const name = namesMap.get(uid) || uid;
                const pct = Math.round((cnt / maxCount) * 100);
                return `
                    <div class="army-unit-row" title="${name} — ${cnt} unità">
                        <div class="army-unit-bar" style="width:${pct}%"></div>
                        <span class="army-unit-name">${name}</span>
                        <span class="army-unit-count">×${cnt}</span>
                    </div>`;
            }).join('');
        }

        pane.innerHTML = `
            <div class="army-header">
                <p class="army-title">&#9874; Esercito Attuale</p>
                <span class="army-total-badge">${totalUnits} unità</span>
            </div>

            <div class="army-kpi-row">
                <div class="army-kpi-card">
                    <div class="army-kpi-card-label">Tipi schierati</div>
                    <div class="army-kpi-card-value">${sorted.length}</div>
                </div>
                <div class="army-kpi-card">
                    <div class="army-kpi-card-label">Costo legione</div>
                    <div class="army-kpi-card-value accent">${formatGruxLocal(armyCost)}</div>
                </div>
            </div>

            <div class="army-strategy-badge">
                <span class="army-strategy-dot"></span>
                <span class="army-strategy-text">Strategia: ${strategyName} · Stato: ${troopStatus}</span>
            </div>
            ${reserveCondition ? `
            <div class="condition-detail" title="Condizione delle truppe ferme in castello">
                ${conditionBarsHtml(reserveCondition)}
            </div>` : ''}

            <div class="army-composition-list">
                <p class="army-composition-title">Composizione</p>
                ${unitRowsHtml}
            </div>
        `;
    }

    /* ── Render picker unità nel form Legioni ──────────────── */
    function renderLegionUnitPicker(sessionData) {
        const picker = document.getElementById('legionUnitPicker');
        if (!picker) return;

        const counts = buildUnitCountsFromState(sessionData);
        const namesMap = buildUnitNamesMap();

        if (counts.size === 0) {
            picker.innerHTML = '<div class="army-empty-msg">Nessuna unità disponibile.</div>';
            return;
        }

        picker.innerHTML = [...counts.entries()]
            .sort((a, b) => (namesMap.get(a[0]) || a[0]).localeCompare(namesMap.get(b[0]) || b[0], 'it'))
            .map(([uid, available]) => {
                const name = namesMap.get(uid) || uid;
                const qty = legionDraft.units[uid] || 0;
                const isSelected = qty > 0;
                return `
                    <div class="legion-unit-pick-row ${isSelected ? 'selected' : ''}" data-uid="${uid}">
                        <input class="legion-unit-cb" type="checkbox" id="lcb_${uid}" 
                               ${isSelected ? 'checked' : ''} data-uid="${uid}">
                        <label class="legion-unit-pick-name" for="lcb_${uid}" title="${name}">${name}</label>
                        <span class="legion-unit-pick-available">×${available}</span>
                        <div class="legion-unit-pick-qty">
                            <button class="legion-qty-btn" data-uid="${uid}" data-op="dec" type="button">−</button>
                            <span class="legion-qty-val" id="legionQty_${uid}">${qty}</span>
                            <button class="legion-qty-btn" data-uid="${uid}" data-op="inc" data-max="${available}" type="button">+</button>
                        </div>
                    </div>`;
            }).join('');

        // Checkbox toggle: selezionare una truppa la prende TUTTA.
        // Il caso normale è "mandane venti", non "mandane una": chi ne vuole
        // meno scende col − (che tenendolo premuto va veloce).
        picker.querySelectorAll('.legion-unit-cb').forEach(cb => {
            cb.addEventListener('change', () => {
                const uid = cb.dataset.uid;
                if (cb.checked) {
                    legionDraft.units[uid] = counts.get(uid) || 0;
                } else {
                    delete legionDraft.units[uid];
                }
                renderLegionUnitPicker(sessionData);
                updateSendButton();
            });
        });

        /* Aggiorna la singola riga senza ri-renderizzare tutto il picker:
         * durante una pressione prolungata il bottone non deve sparire da
         * sotto il dito. Ritorna false quando ha toccato il limite. */
        function applyQtyDelta(uid, delta, max) {
            const cur = legionDraft.units[uid] || 0;
            const next = Math.max(0, Math.min(cur + delta, max));
            if (next === cur) return false;

            if (next === 0) delete legionDraft.units[uid];
            else legionDraft.units[uid] = next;

            const valEl = document.getElementById(`legionQty_${uid}`);
            if (valEl) valEl.textContent = next;
            const cb = document.getElementById(`lcb_${uid}`);
            if (cb) cb.checked = next > 0;
            const row = picker.querySelector(`.legion-unit-pick-row[data-uid="${uid}"]`);
            if (row) row.classList.toggle('selected', next > 0);

            updateSendButton();
            return true;
        }

        // Bottoni ± con ripetizione accelerata tenendo premuto.
        const HOLD_START_MS = 350;   // pausa prima che parta la ripetizione
        const HOLD_TICK_MS = 60;     // cadenza della ripetizione
        const HOLD_BOOST_MS = 2000;  // dopo 2s di pressione va a blocchi
        const HOLD_BOOST_STEP = 5;

        picker.querySelectorAll('.legion-qty-btn').forEach(btn => {
            const uid = btn.dataset.uid;
            const max = parseInt(btn.dataset.max || '999', 10);
            const delta = btn.dataset.op === 'inc' ? 1 : -1;
            let startTimer = null;
            let repeatTimer = null;

            const stopHold = () => {
                clearTimeout(startTimer);
                clearInterval(repeatTimer);
                startTimer = repeatTimer = null;
                document.removeEventListener('pointerup', stopHold);
                document.removeEventListener('pointercancel', stopHold);
            };

            btn.addEventListener('pointerdown', (event) => {
                if (event.button !== 0 && event.pointerType === 'mouse') return;
                event.preventDefault();   // niente selezione del testo tenendo premuto

                applyQtyDelta(uid, delta, max);   // il primo scatto è immediato

                const pressedAt = Date.now();
                startTimer = setTimeout(() => {
                    repeatTimer = setInterval(() => {
                        const held = Date.now() - pressedAt;
                        const step = held >= HOLD_BOOST_MS ? HOLD_BOOST_STEP : 1;
                        if (!applyQtyDelta(uid, delta * step, max)) stopHold();
                    }, HOLD_TICK_MS);
                }, HOLD_START_MS);

                // Su document, non sul bottone: il rilascio va intercettato
                // anche se nel frattempo il dito è scivolato fuori.
                document.addEventListener('pointerup', stopHold);
                document.addEventListener('pointercancel', stopHold);
            });
        });
    }

    /* ── LegionPickMode — overlay approach ──────────────────── */
    /*
     * I bottoni .map-cell in modalità Ordini hanno disabled=true.
     * I bottoni disabilitati NON propagano eventi click in nessun browser.
     * Soluzione: overlay trasparente sopra la mappa che intercetta tutti
     * i click, si nasconde 1ms per usare elementFromPoint, trova la cella.
     */
    function enterLegionPickMode(onPick) {
        if (legionPickModeActive) exitLegionPickMode();
        legionPickModeActive = true;
        document.body.classList.add('legion-pick-mode');

        // Toast visivo
        const toast = document.createElement('div');
        toast.className = 'legion-pick-toast';
        toast.id = 'legionPickToast';
        toast.textContent = '>> Clicca una cella sulla mappa';
        document.body.appendChild(toast);

        const board = document.getElementById('mapBoard');
        if (!board) { exitLegionPickMode(); return; }

        // Imposta positioning context sul board (necessario per inset:0)
        const prevPosition = board.style.position;
        board.dataset.legionPrevPosition = prevPosition;
        if (!prevPosition || prevPosition === 'static' || prevPosition === '') {
            board.style.position = 'relative';
        }

        // Overlay trasparente sopra tutta la mappa
        const overlay = document.createElement('div');
        overlay.id = 'legionPickOverlay';
        overlay.style.cssText = [
            'position:absolute',
            'inset:0',
            'z-index:999',
            'cursor:crosshair',
            'background:rgba(233,69,96,0.04)',
            'border-radius:12px',
        ].join(';');
        board.appendChild(overlay);

        const clickHandler = (evt) => {
            // Nascondi overlay 1 frame per trovare l'elemento sottostante
            overlay.style.pointerEvents = 'none';
            const el = document.elementFromPoint(evt.clientX, evt.clientY);
            overlay.style.pointerEvents = '';

            const cell = el ? el.closest('.map-cell') : null;
            const row = cell ? parseInt(cell.dataset.row, 10) : NaN;
            const col = cell ? parseInt(cell.dataset.col, 10) : NaN;

            if (!isNaN(row) && !isNaN(col)) {
                onPick(row, col, cell);
            }
            exitLegionPickMode();
        };

        overlay.addEventListener('click', clickHandler);
        legionPickListeners.push({ el: overlay, handler: clickHandler, event: 'click' });

        // ESC per annullare
        const escHandler = (e) => {
            if (e.key === 'Escape') exitLegionPickMode();
        };
        document.addEventListener('keydown', escHandler);
        legionPickListeners.push({ el: document, handler: escHandler, event: 'keydown' });
    }

    function exitLegionPickMode() {
        legionPickModeActive = false;
        document.body.classList.remove('legion-pick-mode');

        const toast = document.getElementById('legionPickToast');
        if (toast) toast.remove();

        const overlay = document.getElementById('legionPickOverlay');
        if (overlay) overlay.remove();

        // Ripristina position del board
        const board = document.getElementById('mapBoard');
        if (board && board.dataset.legionPrevPosition !== undefined) {
            board.style.position = board.dataset.legionPrevPosition;
            delete board.dataset.legionPrevPosition;
        }

        // Cleanup listeners
        for (const { el, handler, event } of legionPickListeners) {
            el.removeEventListener(event, handler);
        }
        legionPickListeners = [];
    }


    /* ── Update bottone "Invia Legione" ─────────────────────── */
    function updateSendButton() {
        const btn = document.getElementById('legionSendBtn');
        if (!btn) return;
        const hasName = (legionDraft.name || '').trim().length > 0;
        const hasUnits = Object.values(legionDraft.units).some(q => q > 0);
        const hasTarget = legionDraft.target !== null;
        btn.disabled = !(hasName && hasUnits && hasTarget);
    }

    /* ── Render target display ──────────────────────────────── */
    function updateTargetDisplay() {
        const display = document.getElementById('legionTargetDisplay');
        if (!display) return;

        if (legionDraft.target) {
            const [r, c] = legionDraft.target;
            display.textContent = `Riga ${r + 1}, Colonna ${c + 1}`;
            display.classList.add('picked');
        } else {
            display.textContent = 'Nessuna destinazione';
            display.classList.remove('picked');
        }
    }

    /* ── Render lista legioni attive ────────────────────────── */
    function renderLegionsList() {
        const list = document.getElementById('legionsActiveList');
        if (!list) return;

        if (activeLegions.length === 0) {
            list.innerHTML = '<div class="legions-list-empty">Nessuna legione attiva.<br>Crea la prima dal form sopra.</div>';
            return;
        }

        list.innerHTML = activeLegions.map((leg, idx) => {
            const namesMap = buildUnitNamesMap();
            const compParts = Object.entries(leg.units)
                .filter(([, q]) => q > 0)
                .map(([uid, q]) => `${namesMap.get(uid) || uid} ×${q}`)
                .join(', ');
            const dest = leg.target
                ? `Riga ${leg.target[0] + 1}, Col ${leg.target[1] + 1}`
                : 'Destinazione non impostata';

            const typeLabel = LEGION_TYPE_LABELS[leg.legionType] || leg.legionType;
            const typeIcon = LEGION_TYPE_ICONS[leg.legionType] || '⚔';

            return `
                <div class="legion-card" data-idx="${idx}">
                    <div class="legion-card-header">
                        <p class="legion-card-name">&#9816; ${leg.name}</p>
                        <div class="legion-card-actions">
                            <button class="legion-card-retarget" type="button" data-idx="${idx}">Nuova Dest.</button>
                            <button class="legion-card-recall" type="button" data-idx="${idx}">Richiama</button>
                        </div>
                    </div>
                    <div class="legion-card-badges">
                        <span class="legion-card-type-badge legion-type-${leg.legionType}">${typeIcon} ${typeLabel}</span>
                        ${conditionBadgeHtml(leg.troopStatus, leg.condition)}
                    </div>
                    <div class="legion-card-dest">
                        <span class="legion-card-dest-pin">&#9654;</span>
                        ${dest}
                    </div>
                    <div class="legion-card-comp">${compParts || 'Composizione vuota'}</div>
                    ${leg.condition ? `<div class="condition-detail">${conditionBarsHtml(leg.condition)}</div>` : ''}
                </div>`;
        }).join('');

        list.querySelectorAll('.legion-card-recall').forEach(btn => {
            btn.addEventListener('click', async () => {
                const idx = parseInt(btn.dataset.idx, 10);
                const legion = activeLegions[idx];
                if (!legion || !legion.id) return;

                btn.disabled = true;
                try {
                    const response = await fetch('http://127.0.0.1:8000/game/legions/recall', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ legion_id: legion.id })
                    });

                    if (!response.ok) {
                        const err = await response.json();
                        throw new Error(err.detail || 'Errore nel richiamo della legione');
                    }

                    const result = await response.json();
                    if (window.renderBattleState) {
                        window.renderBattleState(result.session);
                    }
                } catch (error) {
                    alert(`Errore: ${error.message}`);
                    btn.disabled = false;
                }
            });
        });

        list.querySelectorAll('.legion-card-retarget').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.idx, 10);
                const legion = activeLegions[idx];
                if (!legion || !legion.id) return;

                if (legionPickModeActive) {
                    exitLegionPickMode();
                    return;
                }

                btn.classList.add('picking');
                btn.textContent = '× Annulla';

                enterLegionPickMode(async (row, col) => {
                    btn.classList.remove('picking');
                    btn.textContent = 'Nuova Dest.';
                    btn.disabled = true;
                    try {
                        const response = await fetch('http://127.0.0.1:8000/game/legions/retarget', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ legion_id: legion.id, target: [row, col] })
                        });

                        if (!response.ok) {
                            const err = await response.json();
                            throw new Error(err.detail || 'Errore nella nuova destinazione');
                        }

                        const result = await response.json();
                        if (window.renderBattleState) {
                            window.renderBattleState(result.session);
                        }
                    } catch (error) {
                        alert(`Errore: ${error.message}`);
                    } finally {
                        btn.disabled = false;
                    }
                });
            });
        });
    }

    /* ── Render tab "Legioni" (form + lista) ────────────────── */
    function renderLegionsTab(sessionData) {
        const pane = qs(document.getElementById('legionsPane'), '[data-subpane="legions"]');
        if (!pane) return;

        pane.innerHTML = `
            <div class="legions-create-section">
                <p class="legions-section-title">&#9876; Crea Legione</p>

                <input class="legions-input" id="legionNameInput" type="text"
                       placeholder="Nome legione (es. Legione Alpha)" maxlength="40">

                <p class="legion-unit-picker-label">Tipo legione</p>
                <div class="legion-type-picker" id="legionTypePicker">
                    <button class="legion-type-btn" type="button" data-type="army">&#9876; Esercito</button>
                    <button class="legion-type-btn" type="button" data-type="mining">&#9935; Mineraria</button>
                    <button class="legion-type-btn" type="button" data-type="construction">&#129521; Costruzione</button>
                </div>

                <p class="legion-unit-picker-label">Composizione</p>
                <div class="legion-unit-picker" id="legionUnitPicker"></div>

                <p class="legion-unit-picker-label">Destinazione</p>
                <div class="legions-target-row">
                    <div class="legions-target-display" id="legionTargetDisplay">Nessuna destinazione</div>
                    <button class="legions-pick-btn" id="legionPickBtn" type="button">&#9654; Seleziona cella</button>
                </div>

                <button class="legions-send-btn" id="legionSendBtn" type="button" disabled>
                    &#9658; Invia Legione
                </button>
            </div>

            <div class="legions-list-section">
                <p class="legions-section-title">&#9816; Legioni Attive</p>
                <div id="legionsActiveList"></div>
            </div>
        `;

        // Ripristina stato draft
        const nameInput = document.getElementById('legionNameInput');
        if (nameInput) {
            nameInput.value = legionDraft.name || '';
            nameInput.addEventListener('input', () => {
                legionDraft.name = nameInput.value;
                updateSendButton();
            });
        }

        // Type picker
        const typePicker = document.getElementById('legionTypePicker');
        if (typePicker) {
            const syncTypeButtons = () => {
                typePicker.querySelectorAll('.legion-type-btn').forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.type === legionDraft.legionType);
                });
            };
            syncTypeButtons();
            typePicker.querySelectorAll('.legion-type-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    legionDraft.legionType = btn.dataset.type;
                    syncTypeButtons();
                });
            });
        }

        // Render unit picker con stato corrente
        renderLegionUnitPicker(sessionData);

        // Target display
        updateTargetDisplay();

        // Pick button
        const pickBtn = document.getElementById('legionPickBtn');
        if (pickBtn) {
            pickBtn.addEventListener('click', () => {
                if (legionPickModeActive) {
                    exitLegionPickMode();
                    pickBtn.classList.remove('picking');
                    pickBtn.textContent = '\u25B6 Seleziona cella';
                    return;
                }

                pickBtn.classList.add('picking');
                pickBtn.textContent = '\u00D7 Annulla';

                enterLegionPickMode((row, col) => {
                    legionDraft.target = [row, col];
                    pickBtn.classList.remove('picking');
                    pickBtn.textContent = '\u25B6 Seleziona cella';
                    updateTargetDisplay();
                    updateSendButton();
                });
            });
        }

        // Send button
        const sendBtn = document.getElementById('legionSendBtn');
        if (sendBtn) {
            sendBtn.addEventListener('click', async () => {
                const name = (legionDraft.name || '').trim();
                if (!name) return;

                try {
                    const response = await fetch('http://127.0.0.1:8000/game/legions/create', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name,
                            units: legionDraft.units,
                            target: legionDraft.target,
                            legion_type: legionDraft.legionType
                        })
                    });

                    if (!response.ok) {
                        const err = await response.json();
                        throw new Error(err.detail || 'Errore creazione legione');
                    }

                    const result = await response.json();
                    if (window.renderBattleState) {
                        window.renderBattleState(result.session);
                    }

                    // Reset draft form
                    legionDraft.name = '';
                    legionDraft.units = {};
                    legionDraft.target = null;
                    legionDraft.legionType = 'army';
                    if (nameInput) nameInput.value = '';

                    // Trigger render manually
                    refreshLegionsPane(result.session);
                } catch (error) {
                    alert(`Errore: ${error.message}`);
                }

                // Flash sul tab legioni
                const legTab = qs(document.getElementById('legionsPane'), '[data-subtab="legions"]');
                if (legTab) {
                    legTab.style.color = '#16a34a';
                    setTimeout(() => { legTab.style.color = ''; }, 800);
                }
            });
        }

        renderLegionsList();
    }

    /* ── Aggiornamento da renderBattleState ─────────────────── */
    function refreshLegionsPane(sessionData) {
        const pane = document.getElementById('legionsPane');
        if (!pane) return;

        syncActiveLegionsFromSession(sessionData);

        if (activeLegionsSubTab === 'army') {
            renderArmyTab(sessionData);
        } else {
            renderLegionsTab(sessionData);
        }
    }

    /* ── Costruzione struttura iniziale del pane ────────────── */
    function buildLegionsPane(container, sessionData) {
        container.id = 'legionsPane';
        container.innerHTML = `
            <div class="legions-sub-tabs">
                <button class="legions-sub-tab active" type="button" data-subtab="army">&#9874; Esercito</button>
                <button class="legions-sub-tab" type="button" data-subtab="legions">&#9876; Legioni</button>
            </div>
            <div class="legions-sub-pane active" data-subpane="army"></div>
            <div class="legions-sub-pane" data-subpane="legions"></div>
        `;

        // Click su sotto-tab
        container.querySelectorAll('.legions-sub-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.dataset.subtab;
                activateLegionsSubTab(key);
                if (key === 'army') {
                    renderArmyTab(
                        typeof currentBattleState !== 'undefined' ? currentBattleState : null
                    );
                } else {
                    renderLegionsTab(
                        typeof currentBattleState !== 'undefined' ? currentBattleState : null
                    );
                }
            });
        });

        // Prima render
        if (sessionData) {
            renderArmyTab(sessionData);
        }
    }

    /* ── API pubblica (usata da battle_bar.js) ──────────────── */
    window.LegionsPanel = {
        /**
         * Monta il pannello nel DOM element passato.
         * @param {HTMLElement} container  - il div[data-pane="legions"]
         * @param {object|null} sessionData - stato sessione iniziale
         */
        mount(container, sessionData) {
            buildLegionsPane(container, sessionData);
        },

        /**
         * Aggiorna il pannello con un nuovo stato sessione.
         * Chiamato da renderBattleState() in render.js
         * @param {object} sessionData
         */
        update(sessionData) {
            refreshLegionsPane(sessionData);
        },

        /**
         * Forza uscita dalla pick mode (es. cambio tab)
         */
        exitPickMode() {
            if (legionPickModeActive) exitLegionPickMode();
        },

        /**
         * Restituisce l'array delle legioni attive (con currentPos, path ecc.)
         * Usato da render.js per renderizzare i marker sulla mappa.
         * @returns {Array}
         */
        getActiveLegions() {
            return activeLegions;
        }
    };

})();
