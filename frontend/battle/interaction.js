        let turnRequestInFlight = false;


        function toggleShortcuts(forceState = null) {
            const panel = document.getElementById('shortcutsPanel');
            const shouldOpen = forceState === null ? !panel.classList.contains('active') : forceState;
            panel.classList.toggle('active', shouldOpen);
        }

        function toggleSettingsMenu(forceState = null) {
            const menu = document.getElementById('settingsMenu');
            const shouldOpen = forceState === null ? !menu.classList.contains('open') : forceState;
            menu.classList.toggle('open', shouldOpen);
        }

        function initLayoutControls() {
            const divider = document.getElementById('layoutDivider');
            const layoutRoot = document.getElementById('battleLayoutRoot');
            if (!divider || !layoutRoot) return;

            divider.addEventListener('mousedown', (event) => {
                if (window.innerWidth <= 1024 || currentLayoutMode !== 'split') {
                    return;
                }
                event.preventDefault();
                splitterDragging = true;
                divider.classList.add('dragging');
            });

            window.addEventListener('mousemove', (event) => {
                if (!splitterDragging || currentLayoutMode !== 'split') {
                    return;
                }

                const rect = layoutRoot.getBoundingClientRect();
                if (rect.width <= 0) {
                    return;
                }

                const rawRatio = (event.clientX - rect.left) / rect.width;
                layoutSplitRatio = Math.min(0.82, Math.max(0.5, rawRatio));
                applyLayoutMode();
            });

            window.addEventListener('mouseup', () => {
                if (!splitterDragging) {
                    return;
                }
                splitterDragging = false;
                divider.classList.remove('dragging');
            });

            window.addEventListener('resize', () => applyLayoutMode());
        }

        function setLayoutMode(mode) {
            currentLayoutMode = mode;
            applyLayoutMode();
        }

        function applyLayoutMode() {
            const layoutRoot = document.getElementById('battleLayoutRoot');
            if (!layoutRoot) return;

            if (window.innerWidth <= 1024) {
                layoutRoot.classList.remove('view-map', 'view-logs');
            } else {
                layoutRoot.classList.toggle('view-map', currentLayoutMode === 'map');
                layoutRoot.classList.toggle('view-logs', currentLayoutMode === 'logs');
            }

            const mapFr = Math.max(0.5, Math.min(0.82, layoutSplitRatio));
            const sideFr = Math.max(0.18, 1 - mapFr);
            layoutRoot.style.setProperty('--layout-map-fr', `${mapFr}fr`);
            layoutRoot.style.setProperty('--layout-side-fr', `${sideFr}fr`);

            const splitBtn = document.getElementById('layoutSplitBtn');
            const mapBtn = document.getElementById('layoutMapBtn');
            const logsBtn = document.getElementById('layoutLogsBtn');
            if (splitBtn) splitBtn.classList.toggle('active', currentLayoutMode === 'split');
            if (mapBtn) mapBtn.classList.toggle('active', currentLayoutMode === 'map');
            if (logsBtn) logsBtn.classList.toggle('active', currentLayoutMode === 'logs');
        }

        function toggleSidebarCollapse() {
            sidebarCollapsed = !sidebarCollapsed;
            applySidebarCollapseState();
        }

        function applySidebarCollapseState() {
            const layoutRoot = document.getElementById('battleLayoutRoot');
            const sidebar = document.getElementById('battleSidebarColumn');
            const toggleBtn = document.getElementById('sidebarCollapseToggle');
            const icon = document.getElementById('sidebarCollapseIcon');

            if (layoutRoot) layoutRoot.classList.toggle('sidebar-collapsed', sidebarCollapsed);
            if (sidebar) sidebar.classList.toggle('collapsed', sidebarCollapsed);
            if (toggleBtn) {
                toggleBtn.title = sidebarCollapsed ? 'Espandi pannello Economia e Presidi' : 'Comprimi pannello Economia e Presidi';
                toggleBtn.setAttribute('aria-expanded', String(!sidebarCollapsed));
            }
            if (icon) icon.textContent = sidebarCollapsed ? '◀' : '▶';
        }

        function handleOutsideMenuClick(event) {
            const menu = document.getElementById('settingsMenu');
            if (menu && !menu.contains(event.target)) {
                toggleSettingsMenu(false);
            }
        }

        async function handleSettingsAction(action) {
            toggleSettingsMenu(false);
            if (action === 'shortcuts') {
                toggleShortcuts();
                return;
            }
            if (action === 'reset') {
                await resetBattleSession();
                return;
            }
            if (action === 'restart') {
                await restartFromStoredSetup();
            }
        }

        function handleKeyboardShortcuts(event) {
            const activeTag = document.activeElement ? document.activeElement.tagName : '';
            const typing = activeTag === 'INPUT' || activeTag === 'TEXTAREA';
            if (typing) return;

            if (event.key === 'Escape') {
                closeSkillTree();
                closeAutoRecruitMenu();
                closeInGameAdvisorMenu();
                toggleSettingsMenu(false);
            }

            if (event.key === '1') {
                event.preventDefault();
                enterGarrisonMode();
                return;
            }
            if (event.key === '2') {
                event.preventDefault();
                enterMineMode();
                return;
            }
            if (event.key === '3') {
                event.preventDefault();
                enterFortifyMode();
                return;
            }
            if (event.key === 'Escape' && buildMode) {
                event.preventDefault();
                cancelBuildMode();
                return;
            }
            if (event.key.toLowerCase() === 'r') {
                event.preventDefault();
                recruitSelectedUnit();
                return;
            }

            if (event.key.toLowerCase() === 'a') {
                event.preventDefault();
                openSkillTree();
                return;
            }

            if (event.key.toLowerCase() === 'h') {
                event.preventDefault();
                toggleShortcuts();
                return;
            }
            if (event.key.toLowerCase() === 'e') {
                event.preventDefault();
                executeTurn();
                return;
            }

            if (event.key.toLowerCase() === 'v') {
                event.preventDefault();
                const nextMode = currentLayoutMode === 'split'
                    ? 'map'
                    : currentLayoutMode === 'map'
                        ? 'logs'
                        : 'split';
                setLayoutMode(nextMode);
                return;
            }

            const moveByKey = {
                ArrowUp: [-1, 0],
                ArrowDown: [1, 0],
                ArrowLeft: [0, -1],
                ArrowRight: [0, 1],
            };

            if (moveByKey[event.key]) {
                event.preventDefault();
                const [dr, dc] = moveByKey[event.key];
                moveByDelta(dr, dc, event.shiftKey);
            }
        }

        function moveByDelta(dr, dc, leaveGarrison) {
            if (!currentBattleState || !currentBattleState.map || !currentBattleState.map.positions.player) {
                return;
            }
            const [row, col] = currentBattleState.map.positions.player;
            const toRow = row + dr;
            const toCol = col + dc;
            if (toRow < 0 || toRow >= currentBattleState.map.rows || toCol < 0 || toCol >= currentBattleState.map.cols) {
                return;
            }
            movePlayer(toRow, toCol, leaveGarrison);
        }

        function terrainClass(terrain) {
            return `terrain-${terrain.toLowerCase()}`
                .normalize('NFD')
                .replace(/[\u0300-\u036f]/g, '')
                .replace(/\s+/g, '-');
        }

        function terrainAbbrev(terrain) {
            const mapping = {
                'Pianura': 'PIA',
                'Foresta': 'FOR',
                'Montagna': 'MON',
                'Fiume': 'FIU',
                'Palude': 'PAL'
            };
            return mapping[terrain] || terrain.slice(0, 3).toUpperCase();
        }

        async function executeTurn() {
            if (turnRequestInFlight) {
                return;
            }

            turnRequestInFlight = true;
            try {
                const response = await fetch('http://127.0.0.1:8000/game/execute-turn', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore turno');
                }

                const result = await response.json();

                // result.session.battle_log include già i log del turno (persistiti
                // lato server in execute_turn()): non vanno ripetuti qui, altrimenti
                // si duplicano ad ogni turno.
                transientLogLines = [];
                renderBattleState(result.session);
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
            } finally {
                turnRequestInFlight = false;
            }
        }

        async function movePlayer(row, col, leaveGarrison = false) {
            try {
                const response = await fetch('http://127.0.0.1:8000/game/move', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        to_row: row,
                        to_col: col,
                        leave_garrison: leaveGarrison,
                        garrison_unit_id: null
                    })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore durante la mossa');
                }

                await response.json();
                transientLogLines = [];

                const stateResponse = await fetch('http://127.0.0.1:8000/game/state');
                const stateData = await stateResponse.json();
                renderBattleState(stateData);
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore PLAYER mossa: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function refreshStateFromServer() {
            try {
                const stateResponse = await fetch('http://127.0.0.1:8000/game/state');
                if (!stateResponse.ok) {
                    return null;
                }
                const stateData = await stateResponse.json();
                renderBattleState(stateData);
                return stateData;
            } catch (_error) {
                return null;
            }
        }

        // ──────────────────────────────────────────────────────────
        // MODALITÀ PUNTAMENTO (Presidio / Miniera / Fortifica)
        //
        // Le azioni non agiscono più sulla legione del menu a tendina: con più
        // legioni in campo era impossibile capire su quale stessero agendo, e
        // bastava avere un'Esercito selezionata per non poter piazzare miniere.
        // Ora si punta la cella: la legione giusta viene dedotta da lì.
        // ──────────────────────────────────────────────────────────

        const BUILD_MODES = {
            garrison: {
                legionType: null,               // qualsiasi tipo, serve solo 2+ truppe
                label: 'Presidio',
                icon: '🛡',
                hint: 'Clicca la cella della legione che deve lasciare il presidio (serve almeno 2 truppe).',
            },
            mine: {
                legionType: 'mining',
                label: 'Miniera',
                icon: '⛏',
                hint: 'Clicca la cella dove si trova una legione Mineraria.',
            },
            fortify: {
                legionType: 'construction',
                label: 'Fortificazione',
                icon: '🧱',
                hint: 'Clicca la cella dove si trova una legione di Costruzione.',
            },
        };

        function getBuildModeConfig() {
            return buildMode ? BUILD_MODES[buildMode] : null;
        }

        /** Legioni player idonee all'azione corrente, indicizzate per "riga,colonna". */
        function getEligibleBuildCells(sessionData) {
            const config = getBuildModeConfig();
            const eligible = new Map();
            if (!config) return eligible;

            const legions = Object.values(sessionData?.player?.legions || {});
            for (const legion of legions) {
                const pos = legion.pos || [];
                if (pos.length !== 2) continue;
                if (config.legionType && legion.legion_type !== config.legionType) continue;
                if (buildMode === 'garrison' && (legion.units || []).length < 2) continue;

                const key = `${pos[0]},${pos[1]}`;
                if (!eligible.has(key)) eligible.set(key, legion);
            }
            return eligible;
        }

        function setBuildMode(mode) {
            const previous = buildMode;
            buildMode = previous === mode ? null : mode;

            document.body.classList.remove('build-mode-garrison', 'build-mode-mine', 'build-mode-fortify');
            const config = getBuildModeConfig();
            if (config) document.body.classList.add(`build-mode-${buildMode}`);

            // Prima il re-render (che riscrive il messaggio di stato), poi il
            // messaggio della modalità: altrimenti verrebbe subito sovrascritto.
            if (currentBattleState) renderBattleState(currentBattleState);

            const hintEl = document.getElementById('battleStatusHint');
            if (config) {
                const eligible = getEligibleBuildCells(currentBattleState);
                hintEl.textContent = eligible.size === 0
                    ? `${config.icon} ${config.label}: nessuna legione idonea in campo. ${config.hint}`
                    : `${config.icon} ${config.label}: ${config.hint} (Esc per annullare)`;
            } else if (previous) {
                hintEl.textContent = 'Modalità costruzione annullata.';
            }
        }

        function cancelBuildMode() {
            if (buildMode) setBuildMode(buildMode);
        }

        function enterGarrisonMode() { setBuildMode('garrison'); }
        function enterMineMode() { setBuildMode('mine'); }
        function enterFortifyMode() { setBuildMode('fortify'); }

        /** Click su una cella della mappa mentre si è in modalità puntamento. */
        async function handleBuildCellClick(row, col) {
            const config = getBuildModeConfig();
            if (!config) return;

            const eligible = getEligibleBuildCells(currentBattleState);
            const legion = eligible.get(`${row},${col}`);
            const hintEl = document.getElementById('battleStatusHint');

            if (!legion) {
                // Spiega perché quella cella non va bene, invece di fallire in silenzio.
                const onCell = Object.values(currentBattleState?.player?.legions || {})
                    .filter((lg) => (lg.pos || []).length === 2 && lg.pos[0] === row && lg.pos[1] === col);
                if (onCell.length === 0) {
                    hintEl.textContent =
                        `${config.icon} Nessuna tua legione su (${row},${col}). ${config.hint}`;
                } else if (buildMode === 'garrison') {
                    hintEl.textContent =
                        `${config.icon} La legione '${onCell[0].name}' ha una sola truppa: non può lasciare un presidio.`;
                } else {
                    const tipi = onCell
                        .map((lg) => `'${lg.name}' (${TACTICAL_LEGION_TYPE_LABELS[lg.legion_type] || 'Esercito'})`)
                        .join(', ');
                    hintEl.textContent =
                        `${config.icon} Su (${row},${col}) c'è ${tipi}: serve una legione ` +
                        `${TACTICAL_LEGION_TYPE_LABELS[config.legionType]}.`;
                }
                return;
            }

            // La legione puntata diventa anche quella attiva: il pannello resta coerente.
            const selector = document.getElementById('tacticalLegionSelect');
            if (selector) {
                selector.value = legion.id;
                renderGarrisonUnitSelector(currentBattleState);
            }

            const endpoints = {
                garrison: 'place-garrison-here',
                mine: 'place-mine',
                fortify: 'place-fortification',
            };
            const payload = buildMode === 'garrison'
                ? { legion_id: legion.id, unit_id: getSelectedGarrisonUnitId() }
                : { legion_id: legion.id };

            try {
                const response = await fetch(`http://127.0.0.1:8000/game/${endpoints[buildMode]}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || `Errore: ${config.label}`);
                }

                await response.json();
                transientLogLines = [];
                buildMode = null;
                document.body.classList.remove('build-mode-garrison', 'build-mode-mine', 'build-mode-fortify');
                await refreshStateFromServer();
            } catch (error) {
                // Il re-render riscrive il messaggio di stato: va fatto prima,
                // altrimenti il motivo del rifiuto sparisce senza che si veda.
                transientLogLines = [`Errore PLAYER ${config.label.toLowerCase()}: ${error.message}`];
                renderBattleState(currentBattleState);
                hintEl.textContent = `${config.icon} ${error.message}`;
            }
        }

