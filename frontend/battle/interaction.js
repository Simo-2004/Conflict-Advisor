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
                closeBlackMarket();
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

            if (event.key.toLowerCase() === 'm') {
                event.preventDefault();
                openBlackMarket();
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

        /** Le abilità di costruzione sbloccate, come le manda il backend. */
        function getBuildRules(sessionData) {
            const rules = sessionData?.player?.build_rules || {};
            return { anywhere: Boolean(rules.anywhere), anyLegion: Boolean(rules.any_legion) };
        }

        /** Le legioni che possono eseguire l'azione corrente.
         *
         *  Con Costruzione Caotica il vincolo di ruolo cade: qualsiasi legione
         *  scava e fortifica. Il presidio resta fuori — è un distaccamento di
         *  truppe, non un cantiere, e il tipo di legione non c'entra comunque.
         */
        function getBuildWorkers(sessionData) {
            const config = getBuildModeConfig();
            if (!config) return [];
            const { anyLegion } = getBuildRules(sessionData);

            return Object.values(sessionData?.player?.legions || {}).filter((legion) => {
                if ((legion.pos || []).length !== 2) return false;
                if (buildMode === 'garrison') return (legion.units || []).length >= 2;
                if (config.legionType && !anyLegion && legion.legion_type !== config.legionType) return false;
                return true;
            });
        }

        /** Celle su cui si può costruire adesso, indicizzate per "riga,colonna".
         *
         *  Senza abilità sono solo quelle sotto le legioni idonee. Con
         *  Costruzione Territoriale diventa tutto il dominio controllato, e il
         *  cantiere lo apre la legione più vicina alla cella scelta.
         */
        function getEligibleBuildCells(sessionData) {
            const config = getBuildModeConfig();
            const eligible = new Map();
            if (!config) return eligible;

            const workers = getBuildWorkers(sessionData);
            const { anywhere } = getBuildRules(sessionData);

            // Il presidio si lascia dove sono i piedi: nessuna proiezione a distanza.
            if (!anywhere || buildMode === 'garrison') {
                for (const legion of workers) {
                    const key = `${legion.pos[0]},${legion.pos[1]}`;
                    if (!eligible.has(key)) eligible.set(key, legion);
                }
                return eligible;
            }

            if (!workers.length) return eligible;

            const grid = sessionData?.map?.grid || [];
            grid.forEach((row, rowIndex) => {
                row.forEach((cell, colIndex) => {
                    if (cell.occupation !== 'player') return;
                    if (buildMode === 'mine' && (cell.is_castle || cell.is_mine || cell.terrain === 'Fiume')) return;

                    // Il cantiere lo apre chi ha meno strada da fare.
                    let nearest = workers[0];
                    let bestDistance = Infinity;
                    for (const legion of workers) {
                        const distance = Math.abs(legion.pos[0] - rowIndex) + Math.abs(legion.pos[1] - colIndex);
                        if (distance < bestDistance) {
                            bestDistance = distance;
                            nearest = legion;
                        }
                    }
                    eligible.set(`${rowIndex},${colIndex}`, nearest);
                });
            });
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
                const { anywhere, anyLegion } = getBuildRules(currentBattleState);
                // Il suggerimento segue le abilità: con il dominio aperto la
                // frase "clicca dove si trova la legione" sarebbe una bugia.
                const suggerimento = (anywhere && buildMode !== 'garrison')
                    ? `Clicca una qualsiasi delle ${eligible.size} celle accese`
                        + `${anyLegion ? ' (costruisce la legione più vicina, di qualunque tipo)' : ' (costruisce la legione idonea più vicina)'}.`
                    : config.hint;
                hintEl.textContent = eligible.size === 0
                    ? `${config.icon} ${config.label}: nessuna legione idonea in campo. ${config.hint}`
                    : `${config.icon} ${config.label}: ${suggerimento} (Esc per annullare)`;
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
                const { anywhere, anyLegion } = getBuildRules(currentBattleState);
                const cella = currentBattleState?.map?.grid?.[row]?.[col];
                const onCell = Object.values(currentBattleState?.player?.legions || {})
                    .filter((lg) => (lg.pos || []).length === 2 && lg.pos[0] === row && lg.pos[1] === col);

                if (anywhere && buildMode !== 'garrison' && cella && cella.occupation !== 'player') {
                    hintEl.textContent =
                        `${config.icon} (${row},${col}) non è una tua cella: conquistala prima di costruirci.`;
                } else if (anywhere && buildMode === 'mine' && cella && (cella.is_mine || cella.is_castle || cella.terrain === 'Fiume')) {
                    const motivo = cella.is_mine ? 'ha già una miniera'
                        : (cella.is_castle ? 'è il castello' : 'è sul fiume');
                    hintEl.textContent = `${config.icon} (${row},${col}) ${motivo}: scegli un'altra cella.`;
                } else if (anywhere && buildMode !== 'garrison' && !getBuildWorkers(currentBattleState).length) {
                    hintEl.textContent =
                        `${config.icon} Nessuna legione in campo può aprire il cantiere. ${config.hint}`;
                } else if (onCell.length === 0) {
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
                        `${TACTICAL_LEGION_TYPE_LABELS[config.legionType]}` +
                        `${anyLegion ? '' : ", o l'abilità Costruzione Caotica"}.`;
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
            // La cella cliccata può non essere quella della legione: con
            // Costruzione Territoriale il cantiere si apre a distanza, e il
            // backend deve sapere dove.
            const payload = buildMode === 'garrison'
                ? { legion_id: legion.id, unit_id: getSelectedGarrisonUnitId() }
                : { legion_id: legion.id, target: [row, col] };

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

