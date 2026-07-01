        function playerCanBuildAnywhere() {
            const abilityState = currentBattleState?.player?.abilities?.domain_engineering;
            return Boolean(abilityState && abilityState.unlocked);
        }

        function isManualControlMode() {
            const mode = currentBattleState?.player?.control_mode;
            return !mode || mode === 'manual';
        }

        function showOrderModeHint(actionLabel = 'questa azione') {
            const hint = document.getElementById('battleStatusHint');
            if (!hint) return;
            hint.textContent = `Modalità Ordini attiva: passa a Manuale per ${actionLabel}.`;
        }

        function canPlaceMineOnCell(cell, row, col, playerPos) {
            if (!currentBattleState) return false;
            if (!isManualControlMode()) return false;
            if (cell.occupation !== 'player' || cell.is_castle || cell.is_mine || cell.terrain === 'Fiume') return false;
            if (currentBattleState.player.available_mine_slots <= 0) return false;
            if (playerCanBuildAnywhere()) return true;
            return Array.isArray(playerPos) && playerPos[0] === row && playerPos[1] === col;
        }

        function canPlaceFortificationOnCell(cell, row, col, playerPos) {
            if (!currentBattleState) return false;
            if (!isManualControlMode()) return false;
            if (cell.occupation !== 'player' || cell.is_castle) return false;
            if (playerCanBuildAnywhere()) return true;
            return Array.isArray(playerPos) && playerPos[0] === row && playerPos[1] === col;
        }

        function setAction(action) {
            if (!isManualControlMode()) {
                showOrderModeHint('le azioni tattiche manuali');
                return;
            }
            currentAction = action;
            document.getElementById('actionMoveBtn').classList.toggle('active', action === 'move');
            document.getElementById('actionGarrisonBtn').classList.toggle('active', action === 'move_garrison');
            document.getElementById('actionMineBtn').classList.toggle('active', action === 'place_mine');
            document.getElementById('actionFortifyBtn').classList.toggle('active', action === 'place_fortification');

            if (currentBattleState) {
                renderBattleState(currentBattleState);
            }
        }

        function actionLabel(action) {
            if (action === 'move_garrison') return 'Mossa + Presidio';
            if (action === 'place_mine') return 'Piazza Miniera';
            if (action === 'place_fortification') return 'Fortifica';
            return 'Mossa';
        }

        function resetActionToDefault() {
            if (currentAction !== 'move') {
                setAction('move');
            }
        }

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

        function handleCellAction(event, row, col, isAdjacent, canMine, canFortify) {
            const targetCell = currentBattleState?.map?.grid?.[row]?.[col];

            if (!currentBattleState || currentBattleState.state === 'game_over') {
                document.getElementById('battleStatusHint').textContent = 'Partita terminata: nessuna azione disponibile.';
                return;
            }

            if (!isManualControlMode()) {
                showOrderModeHint('il movimento manuale sulla mappa');
                return;
            }

            if (event.altKey && canMine) {
                placeMine(row, col);
                return;
            }

            if (event.shiftKey && isAdjacent) {
                movePlayer(row, col, true);
                return;
            }

            if (currentAction === 'place_mine') {
                if (canMine) {
                    placeMine(row, col);
                } else {
                    if (!currentBattleState || !targetCell) {
                        document.getElementById('battleStatusHint').textContent = 'Stato partita non disponibile: aggiorna la sessione.';
                    } else if (targetCell.occupation !== 'player') {
                        document.getElementById('battleStatusHint').textContent = 'Miniera non valida: puoi costruire solo su celle PLAYER.';
                    } else if (!playerCanBuildAnywhere()) {
                        document.getElementById('battleStatusHint').textContent = 'Senza Abilità puoi costruire solo sulla cella dove si trova la tua armata.';
                    } else {
                        document.getElementById('battleStatusHint').textContent = 'Miniera non valida su questa cella.';
                    }
                }
                return;
            }

            if (currentAction === 'place_fortification') {
                if (canFortify) {
                    placeFortification(row, col);
                } else {
                    if (!playerCanBuildAnywhere()) {
                        document.getElementById('battleStatusHint').textContent = 'Senza Abilità puoi fortificare solo la cella della tua armata.';
                    } else {
                        document.getElementById('battleStatusHint').textContent = 'Fortificazione non valida: seleziona una cella PLAYER non castello.';
                    }
                }
                return;
            }

            if (isAdjacent) {
                movePlayer(row, col, currentAction === 'move_garrison');
            } else if (currentAction === 'move_garrison') {
                if (currentBattleState && currentBattleState.player.available_garrisons <= 0) {
                    document.getElementById('battleStatusHint').textContent = 'Presidio non disponibile: nessuna guarnigione residua.';
                } else {
                    document.getElementById('battleStatusHint').textContent = 'Presidio valido solo su celle adiacenti alla tua armata.';
                }
            } else {
                document.getElementById('battleStatusHint').textContent = 'Mossa valida solo su celle adiacenti alla tua armata.';
            }
        }

        function handleKeyboardShortcuts(event) {
            const activeTag = document.activeElement ? document.activeElement.tagName : '';
            const typing = activeTag === 'INPUT' || activeTag === 'TEXTAREA';
            if (typing) return;

            if (event.key.toLowerCase() === 'e') {
                event.preventDefault();
                executeOrderTurn();
                return;
            }

            const isManualShortcutKey = ['1', '2', '3', '4', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key);
            if (isManualShortcutKey && !isManualControlMode()) {
                event.preventDefault();
                showOrderModeHint('i comandi manuali');
                return;
            }

            if (event.key === '1') {
                event.preventDefault();
                setAction('move');
                return;
            }

            if (event.key === 'Escape') {
                closeSkillTree();
                closeAutoRecruitMenu();
                closeInGameAdvisorMenu();
                toggleSettingsMenu(false);
            }

            if (event.key === '2') {
                event.preventDefault();
                placeGarrisonHere();
                return;
            }
            if (event.key === '3') {
                event.preventDefault();
                autoPlaceMine();
                return;
            }
            if (event.key === '4') {
                event.preventDefault();
                setAction('place_fortification');
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
            if (!isManualControlMode()) {
                return;
            }
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

        function getAdjacentMoves(playerPos, rows, cols) {
            if (!playerPos) return [];
            const [row, col] = playerPos;
            return [
                [row - 1, col],
                [row + 1, col],
                [row, col - 1],
                [row, col + 1]
            ].filter(([r, c]) => r >= 0 && r < rows && c >= 0 && c < cols);
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

        async function movePlayer(row, col, leaveGarrisonOverride = null) {
            try {
                const leaveGarrison = (leaveGarrisonOverride !== null)
                    ? leaveGarrisonOverride
                    : (currentAction === 'move_garrison');
                const selectedGarrisonUnitId = leaveGarrison ? getSelectedGarrisonUnitId() : null;
                const response = await fetch('http://127.0.0.1:8000/game/move', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        to_row: row,
                        to_col: col,
                        leave_garrison: leaveGarrison,
                        garrison_unit_id: selectedGarrisonUnitId
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
                resetActionToDefault();
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore PLAYER mossa: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function placeMine(row, col) {
            if (!isManualControlMode()) {
                showOrderModeHint('piazzare miniere manualmente');
                return;
            }
            try {
                const response = await fetch('http://127.0.0.1:8000/game/place-mine', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ row: row, col: col })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nel piazzare la miniera');
                }

                await response.json();
                transientLogLines = [];
                const stateResponse = await fetch('http://127.0.0.1:8000/game/state');
                const stateData = await stateResponse.json();
                renderBattleState(stateData);
                resetActionToDefault();
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore PLAYER miniera: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function placeGarrisonHere() {
            if (!isManualControlMode()) {
                showOrderModeHint('piazzare presidi manualmente');
                return;
            }
            try {
                const selectedGarrisonUnitId = getSelectedGarrisonUnitId();
                const response = await fetch('http://127.0.0.1:8000/game/place-garrison-here', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ unit_id: selectedGarrisonUnitId })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nel piazzare il presidio');
                }

                await response.json();
                transientLogLines = [];
                const stateResponse = await fetch('http://127.0.0.1:8000/game/state');
                const stateData = await stateResponse.json();
                renderBattleState(stateData);
                setAction('move');
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore PLAYER presidio: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        function findAutoMineTarget() {
            if (!currentBattleState || !currentBattleState.map || !currentBattleState.map.positions.player) {
                return null;
            }

            const mapData = currentBattleState.map;
            const [pr, pc] = mapData.positions.player;
            const candidates = [];

            candidates.push([pr, pc]);
            for (const [r, c] of getAdjacentMoves([pr, pc], mapData.rows, mapData.cols)) {
                candidates.push([r, c]);
            }

            for (let r = 0; r < mapData.rows; r += 1) {
                for (let c = 0; c < mapData.cols; c += 1) {
                    candidates.push([r, c]);
                }
            }

            for (const [r, c] of candidates) {
                const cell = mapData.grid[r][c];
                if (canPlaceMineOnCell(cell, r, c, mapData.positions.player)) {
                    return [r, c];
                }
            }

            return null;
        }

        function autoPlaceMine() {
            if (!isManualControlMode()) {
                showOrderModeHint('piazzare miniere manualmente');
                return;
            }
            if (!currentBattleState) {
                document.getElementById('battleStatusHint').textContent = 'Partita non disponibile.';
                return;
            }

            if ((currentBattleState.player?.available_mine_slots || 0) <= 0) {
                document.getElementById('battleStatusHint').textContent = 'Non puoi piazzare una miniera: non hai slot miniera disponibili (conquista più celle).';
                transientLogLines = ['Errore PLAYER miniera: slot miniera insufficienti, conquista più territorio'];
                renderBattleState(currentBattleState);
                return;
            }

            const target = findAutoMineTarget();
            if (!target) {
                if (!playerCanBuildAnywhere()) {
                    document.getElementById('battleStatusHint').textContent = 'Senza Abilità puoi costruire miniere solo sulla cella della tua armata.';
                    transientLogLines = ['Errore PLAYER miniera: abilità non sbloccata per costruire fuori dalla cella armata'];
                } else {
                    document.getElementById('battleStatusHint').textContent = 'Nessuna cella valida per piazzare una miniera.';
                    transientLogLines = ['Errore PLAYER miniera: nessuna cella valida trovata'];
                }
                renderBattleState(currentBattleState);
                return;
            }

            placeMine(target[0], target[1]);
        }

        function findAutoFortificationTarget() {
            if (!currentBattleState || !currentBattleState.map || !currentBattleState.map.positions.player) {
                return null;
            }

            const mapData = currentBattleState.map;
            const [pr, pc] = mapData.positions.player;
            const candidates = [];

            candidates.push([pr, pc]);
            for (const [r, c] of getAdjacentMoves([pr, pc], mapData.rows, mapData.cols)) {
                candidates.push([r, c]);
            }

            for (let r = 0; r < mapData.rows; r += 1) {
                for (let c = 0; c < mapData.cols; c += 1) {
                    candidates.push([r, c]);
                }
            }

            let best = null;
            for (const [r, c] of candidates) {
                const cell = mapData.grid[r][c];
                if (!canPlaceFortificationOnCell(cell, r, c, mapData.positions.player)) {
                    continue;
                }
                if (!best || cell.fortification_level < best[2]) {
                    best = [r, c, cell.fortification_level];
                }
            }

            return best ? [best[0], best[1]] : null;
        }

        function autoPlaceFortification() {
            if (!isManualControlMode()) {
                showOrderModeHint('fortificare manualmente');
                return;
            }
            if (!currentBattleState) {
                document.getElementById('battleStatusHint').textContent = 'Partita non disponibile.';
                return;
            }

            const target = findAutoFortificationTarget();
            if (!target) {
                document.getElementById('battleStatusHint').textContent = 'Nessuna cella valida per fortificare.';
                transientLogLines = ['Errore PLAYER fortificazione: nessuna cella valida trovata'];
                renderBattleState(currentBattleState);
                return;
            }

            placeFortification(target[0], target[1]);
        }

        async function placeFortification(row, col) {
            if (!isManualControlMode()) {
                showOrderModeHint('fortificare manualmente');
                return;
            }
            try {
                const response = await fetch('http://127.0.0.1:8000/game/place-fortification', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ row: row, col: col })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nella fortificazione');
                }

                await response.json();
                transientLogLines = [];
                const stateResponse = await fetch('http://127.0.0.1:8000/game/state');
                const stateData = await stateResponse.json();
                renderBattleState(stateData);
                resetActionToDefault();
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore PLAYER fortificazione: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

