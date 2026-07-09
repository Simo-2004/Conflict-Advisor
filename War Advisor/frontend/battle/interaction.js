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
                placeGarrisonWithSelectedLegion();
                return;
            }
            if (event.key === '2') {
                event.preventDefault();
                placeMineWithSelectedLegion();
                return;
            }
            if (event.key === '3') {
                event.preventDefault();
                placeFortificationWithSelectedLegion();
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

        async function placeMineWithSelectedLegion() {
            const legionId = getSelectedTacticalLegionId();
            if (!legionId) {
                document.getElementById('battleStatusHint').textContent = 'Seleziona prima una legione Mineraria.';
                return;
            }
            try {
                const response = await fetch('http://127.0.0.1:8000/game/place-mine', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ legion_id: legionId })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nel piazzare la miniera');
                }

                await response.json();
                transientLogLines = [];
                await refreshStateFromServer();
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore PLAYER miniera: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function placeFortificationWithSelectedLegion() {
            const legionId = getSelectedTacticalLegionId();
            if (!legionId) {
                document.getElementById('battleStatusHint').textContent = 'Seleziona prima una legione Costruzione.';
                return;
            }
            try {
                const response = await fetch('http://127.0.0.1:8000/game/place-fortification', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ legion_id: legionId })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nella fortificazione');
                }

                await response.json();
                transientLogLines = [];
                await refreshStateFromServer();
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore PLAYER fortificazione: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function placeGarrisonWithSelectedLegion() {
            const legionId = getSelectedTacticalLegionId();
            if (!legionId) {
                document.getElementById('battleStatusHint').textContent = 'Seleziona prima una legione.';
                return;
            }
            try {
                const selectedGarrisonUnitId = getSelectedGarrisonUnitId();
                const response = await fetch('http://127.0.0.1:8000/game/place-garrison-here', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ legion_id: legionId, unit_id: selectedGarrisonUnitId })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nel piazzare il presidio');
                }

                await response.json();
                transientLogLines = [];
                await refreshStateFromServer();
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore PLAYER presidio: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

