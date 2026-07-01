        const ORDER_MODE_LABELS = {
            manual: 'Manuale',
            orders: 'Ordini',
        };

        const MOVEMENT_ORDER_LABELS = {
            advance_castle: 'Assalto castello',
            engage_ai: 'Ingaggia IA',
            expand_front: 'Espansione fronte',
            defend_castle: 'Difesa castello',
            hold: 'Mantieni posizione',
        };

        const BUILD_ORDER_LABELS = {
            balanced: 'Bilanciato',
            economy: 'Economia',
            fortify: 'Fortificazioni',
            garrison: 'Presidi',
            none: 'Nessun supporto',
        };

        function renderOrderSelectOptions(select, values, labelsByValue) {
            if (!select || !Array.isArray(values) || values.length === 0) {
                return;
            }
            const currentValue = select.value;
            select.innerHTML = values
                .map(value => `<option value="${value}">${labelsByValue[value] || value}</option>`)
                .join('');
            if (values.includes(currentValue)) {
                select.value = currentValue;
            }
        }

        function renderOrderControls(sessionData, gameOver) {
            const player = sessionData.player || {};
            const orders = player.orders || {};
            const options = orders.options || {};
            const controlMode = player.control_mode || 'manual';

            const controlModeSelect = document.getElementById('orderControlModeSelect');
            const movementSelect = document.getElementById('orderMovementSelect');
            const buildSelect = document.getElementById('orderBuildSelect');
            const applyBtn = document.getElementById('ordersApplyBtn');
            const executeBtn = document.getElementById('ordersExecuteBtn');

            if (controlModeSelect) {
                renderOrderSelectOptions(
                    controlModeSelect,
                    options.control_modes || ['orders', 'manual'],
                    ORDER_MODE_LABELS,
                );
                controlModeSelect.value = controlMode;
                controlModeSelect.disabled = gameOver;
            }

            if (movementSelect) {
                renderOrderSelectOptions(
                    movementSelect,
                    options.movement_orders || Object.keys(MOVEMENT_ORDER_LABELS),
                    MOVEMENT_ORDER_LABELS,
                );
                movementSelect.value = orders.movement_order || 'advance_castle';
                movementSelect.disabled = gameOver;
            }

            if (buildSelect) {
                renderOrderSelectOptions(
                    buildSelect,
                    options.build_orders || Object.keys(BUILD_ORDER_LABELS),
                    BUILD_ORDER_LABELS,
                );
                buildSelect.value = orders.build_order || 'balanced';
                buildSelect.disabled = gameOver;
            }

            if (applyBtn) {
                applyBtn.disabled = gameOver;
            }

            if (executeBtn) {
                const orderModeActive = controlMode === 'orders';
                executeBtn.disabled = gameOver;
                executeBtn.title = orderModeActive
                    ? 'Esegui un turno completo secondo gli ordini attivi'
                    : 'Esegue il turno e passa automaticamente alla modalità Ordini';
            }
        }

        function renderBattleState(sessionData) {
            currentBattleState = sessionData;

            const controlMode = sessionData.player?.control_mode || 'manual';
            const manualControl = controlMode === 'manual';
            const movementOrder = sessionData.player?.orders?.movement_order || 'advance_castle';
            const buildOrder = sessionData.player?.orders?.build_order || 'balanced';

            document.getElementById('battleStatusMode').textContent = manualControl
                ? `Azione: ${actionLabel(currentAction)}`
                : `Controllo: ${ORDER_MODE_LABELS[controlMode] || controlMode}`;
            if (sessionData.state === 'game_over') {
                document.getElementById('battleStatusRound').textContent = `Fine partita: ${sessionData.winner}`;
                document.getElementById('battleStatusHint').textContent = 'Il registro mostra il riepilogo completo della battaglia.';
            } else {
                document.getElementById('battleStatusRound').textContent = `Turno ${sessionData.map.turn}`;
                if (!manualControl) {
                    const moveLabel = MOVEMENT_ORDER_LABELS[movementOrder] || movementOrder;
                    const buildLabel = BUILD_ORDER_LABELS[buildOrder] || buildOrder;
                    document.getElementById('battleStatusHint').textContent =
                        `Modalità Ordini: ${moveLabel} + ${buildLabel}. Premi "Esegui turno ordini" o tasto E.`;
                } else if (currentAction === 'move_garrison' && sessionData.player.available_garrisons <= 0) {
                    document.getElementById('battleStatusHint').textContent = 'Nessun presidio disponibile: recluta unità o cambia azione.';
                } else if (currentAction === 'place_mine' && sessionData.player.available_mine_slots <= 0) {
                    document.getElementById('battleStatusHint').textContent = 'Nessuno slot miniera: conquista più territorio per costruirne altre.';
                } else if (currentAction === 'place_fortification') {
                    document.getElementById('battleStatusHint').textContent = 'Seleziona una cella PLAYER per fortificarla (costo crescente sulla stessa casella).';
                } else {
                    document.getElementById('battleStatusHint').textContent = 'Usa i pulsanti azione o premi H per i comandi rapidi.';
                }
            }

            const playerLegion = buildLegionInfo(sessionData.player.units || []);
            const aiLegion = buildLegionInfo(sessionData.ai.units || []);
            renderGarrisonUnitSelector(sessionData.player.units || []);
            updateGarrisonDefensePreview();

            document.getElementById('playerGruxValue').textContent = formatGrux(sessionData.player.grux_balance);
            document.getElementById('playerGruxSub').textContent = `Costo legione: ${formatGrux(sessionData.player.army_cost)}`;
            document.getElementById('playerMinesInfo').textContent = `Miniere attive: ${sessionData.map.stats.player_mines} · Slot liberi: ${sessionData.player.available_mine_slots}`;
            document.getElementById('playerFortInfo').textContent = `Fortificazioni: ${sessionData.map.stats.player_fortification_levels} livelli su ${sessionData.map.stats.player_fortified_cells} celle`;
            document.getElementById('playerReserveInfo').textContent = `Guarnigioni disponibili: ${sessionData.player.available_garrisons}`;
            document.getElementById('playerLegionSummary').textContent = `Unità sul campo: ${playerLegion.totalUnits} (${playerLegion.totalTypes} tipi)`;
            document.getElementById('playerLegionMeta').textContent = `Strategia: ${sessionData.player.strategy_name || sessionData.player.strategy_id} · Stato: ${sessionData.player.troop_status || 'N/D'}`;
            document.getElementById('playerLegionComposition').textContent = `Composizione: ${playerLegion.compositionText}`;

            document.getElementById('aiGruxValue').textContent = formatGrux(sessionData.ai.grux_balance);
            document.getElementById('aiGruxSub').textContent = `Costo legione: ${formatGrux(sessionData.ai.army_cost)}`;
            document.getElementById('aiMinesInfo').textContent = `Miniere attive: ${sessionData.map.stats.ai_mines} · Slot liberi: ${sessionData.ai.available_mine_slots}`;
            document.getElementById('aiFortInfo').textContent = `Fortificazioni: ${sessionData.map.stats.ai_fortification_levels} livelli su ${sessionData.map.stats.ai_fortified_cells} celle`;
            document.getElementById('aiReserveInfo').textContent = `Guarnigioni disponibili: ${sessionData.ai.available_garrisons}`;
            document.getElementById('aiLegionSummary').textContent = `Unità sul campo: ${aiLegion.totalUnits} (${aiLegion.totalTypes} tipi)`;
            document.getElementById('aiLegionMeta').textContent = `Strategia: ${sessionData.ai.strategy_name || sessionData.ai.strategy_id} · Stato: ${sessionData.ai.troop_status || 'N/D'}`;
            document.getElementById('aiLegionComposition').textContent = `Composizione: ${aiLegion.compositionText}`;

            const abilityState = sessionData.player?.abilities?.domain_engineering;
            const abilityLabel = document.getElementById('abilityLabel');
            if (abilityState) {
                if (abilityState.unlocked) {
                    abilityLabel.textContent = 'Abilità: Sbloccata';
                } else if (abilityState.researching) {
                    abilityLabel.textContent = `Abilità: ${abilityState.turns_remaining} turni`;
                } else {
                    abilityLabel.textContent = 'Abilità: Pronta ricerca';
                }
            } else {
                abilityLabel.textContent = 'Abilità';
            }

            const killSwitchBtn = document.getElementById('aiKillSwitchBtn');
            const killSwitchActive = Boolean(sessionData.debug?.ai_kill_switch_active);
            if (killSwitchBtn) {
                killSwitchBtn.classList.toggle('active', killSwitchActive);
                killSwitchBtn.textContent = killSwitchActive ? '🧪 IA OFF (PAUSA)' : '🧪 IA ON';
            }

            const gameOver = sessionData.state === 'game_over';
            renderOrderControls(sessionData, gameOver);

            const actionButtons = [
                document.getElementById('actionMoveBtn'),
                document.getElementById('actionGarrisonBtn'),
                document.getElementById('actionMineBtn'),
                document.getElementById('actionFortifyBtn'),
            ];
            actionButtons.forEach((btn) => {
                if (btn) btn.disabled = gameOver || !manualControl;
            });

            const garrisonUnitSelect = document.getElementById('garrisonUnitSelect');
            if (garrisonUnitSelect && (gameOver || !manualControl)) {
                garrisonUnitSelect.disabled = true;
            }

            const difficultySelect = document.getElementById('aiDifficultySelect');
            const applyDifficultyBtn = document.getElementById('applyAiDifficultyBtn');
            const difficultyLabels = sessionData.ai?.difficulty_labels || { easy: 'Facile', normal: 'Normale' };
            const currentDifficulty = sessionData.ai?.difficulty || 'easy';
            if (difficultySelect) {
                const options = Object.entries(difficultyLabels)
                    .map(([id, label]) => `<option value="${id}">${label}</option>`)
                    .join('');
                difficultySelect.innerHTML = options;
                difficultySelect.value = currentDifficulty;
                difficultySelect.disabled = gameOver;
            }
            if (applyDifficultyBtn) {
                applyDifficultyBtn.disabled = gameOver;
            }

            const strategySelect = document.getElementById('strategySelect');
            const strategyInfoBtn = document.getElementById('strategyInfoBtn');
            if (strategySelect && sessionData.player?.strategy_id) {
                strategySelect.value = sessionData.player.strategy_id;
            }
            if (strategyInfoBtn) {
                strategyInfoBtn.disabled = gameOver;
            }

            const recruitSelect = document.getElementById('recruitSelect');
            const recruitBtn = document.getElementById('recruitBtn');
            const autoRecruitBtn = document.getElementById('autoRecruitBtn');
            if (recruitSelect) {
                recruitSelect.disabled = gameOver;
            }
            if (recruitBtn) {
                recruitBtn.disabled = gameOver;
            }

            const autoRecruitState = sessionData.player?.auto_recruit || null;
            if (autoRecruitBtn) {
                const enabled = Boolean(autoRecruitState?.enabled);
                autoRecruitBtn.disabled = gameOver;
                autoRecruitBtn.classList.toggle('active', enabled);
                autoRecruitBtn.textContent = enabled ? 'Ferma autoreclutamento' : 'Autoreclutamento';
                if (enabled && autoRecruitState?.unit_name) {
                    autoRecruitBtn.title = `${autoRecruitState.unit_name} (${autoRecruitState.turns_remaining} turni rimanenti)`;
                } else {
                    autoRecruitBtn.title = 'Configura piano automatico di reclutamento';
                }
            }

            renderMapBoard(sessionData.map);

            const logLines = [...(sessionData.battle_log || []), ...transientLogLines];
            renderLog(logLines);
            applyHintTone();
        }

        function applyHintTone() {
            const hint = document.getElementById('battleStatusHint');
            if (!hint) return;
            const text = (hint.textContent || '').toLowerCase();
            const isError = /\berrore\b/.test(text);
            hint.classList.toggle('status-hint-error', isError);
            hint.classList.toggle('status-hint-info', !isError);
        }

        function formatGrux(value) {
            const amount = Number.isFinite(value) ? value : 0;
            return `${amount.toLocaleString('it-IT')} grux`;
        }

        function buildLegionInfo(unitIds) {
            if (!Array.isArray(unitIds) || unitIds.length === 0) {
                return {
                    totalUnits: 0,
                    totalTypes: 0,
                    compositionText: 'nessuna unità disponibile',
                };
            }

            const namesById = new Map(recruitableUnits.map(unit => [unit.id, unit.name || unit.id]));
            const counts = new Map();
            for (const unitId of unitIds) {
                const unitName = namesById.get(unitId) || unitId;
                counts.set(unitName, (counts.get(unitName) || 0) + 1);
            }

            const sorted = [...counts.entries()].sort((a, b) => {
                if (b[1] !== a[1]) return b[1] - a[1];
                return a[0].localeCompare(b[0], 'it');
            });

            const parts = sorted.map(([name, count]) => `${name} x${count}`);
            return {
                totalUnits: unitIds.length,
                totalTypes: sorted.length,
                compositionText: parts.join(', '),
            };
        }

        function getSelectedGarrisonUnitId() {
            const selector = document.getElementById('garrisonUnitSelect');
            if (!selector || selector.disabled) {
                return null;
            }
            return selector.value || null;
        }

        function evaluateUnitBattleValue(unitId, terrainName) {
            const unit = recruitableUnits.find(item => item.id === unitId);
            if (!unit || !unit.attributes) return 0;
            const attrs = unit.attributes;
            const baseValue = (
                (attrs.U1_attack || 0) * 24
                + (attrs.U2_defense || 0) * 20
                + (attrs.U3_mobility || 0) * 12
                + (attrs.U4_stealth || 0) * 10
                + (attrs.U5_discipline || 0) * 14
                + (attrs.U6_terrain_adapt || 0) * 10
                + (attrs.U7_range_power || 0) * 8
                + (attrs.U8_support || 0) * 6
            );

            const terrain = String(terrainName || '').toLowerCase();
            let terrainFactor = 1.0 + ((attrs.U6_terrain_adapt || 0) * 0.18);

            if (terrain === 'foresta') {
                terrainFactor += ((attrs.U4_stealth || 0) * 0.08) + ((attrs.U3_mobility || 0) * 0.04);
            } else if (terrain === 'palude') {
                terrainFactor += ((attrs.U6_terrain_adapt || 0) * 0.08) + ((attrs.U3_mobility || 0) * 0.05);
            } else if (terrain === 'montagna') {
                terrainFactor += ((attrs.U2_defense || 0) * 0.08) + ((attrs.U5_discipline || 0) * 0.04);
            } else if (terrain === 'pianura') {
                terrainFactor += ((attrs.U1_attack || 0) * 0.05) + ((attrs.U7_range_power || 0) * 0.03);
            } else if (terrain === 'fiume') {
                terrainFactor += ((attrs.U3_mobility || 0) * 0.08) + ((attrs.U6_terrain_adapt || 0) * 0.08);
            }

            return baseValue * terrainFactor;
        }

        function updateGarrisonDefensePreview() {
            const preview = document.getElementById('garrisonDefensePreview');
            if (!preview) return;

            if (!currentBattleState || !currentBattleState.map || !currentBattleState.map.positions?.player) {
                preview.textContent = 'Difesa presidio stimata: stato mappa non disponibile.';
                return;
            }

            const selectedUnitId = getSelectedGarrisonUnitId();
            if (!selectedUnitId) {
                preview.textContent = 'Difesa presidio stimata: nessuna unità distaccabile.';
                return;
            }

            const [row, col] = currentBattleState.map.positions.player;
            const cell = currentBattleState.map.grid?.[row]?.[col];
            if (!cell) {
                preview.textContent = 'Difesa presidio stimata: cella non disponibile.';
                return;
            }

            const existingGarrison = Number(cell.garrison_strength || 0);
            const fortificationLevel = Number(cell.fortification_level || 0);
            const nextGarrison = existingGarrison + 1;

            const unitBattleValue = evaluateUnitBattleValue(selectedUnitId, cell.terrain);
            const unitBonus = unitBattleValue * 11.5;
            const garrisonBase = nextGarrison * 18;
            const terrainBonus = ['Foresta', 'Montagna', 'Palude'].includes(cell.terrain) ? 5 : 2;
            const fortificationBase = (fortificationLevel * 18) + (Math.max(0, fortificationLevel - 1) * 16);
            const synergyBase = fortificationLevel > 0 ? (fortificationLevel * nextGarrison * 7) : 0;

            const estimatedDefense = Math.round(
                garrisonBase + unitBonus + terrainBonus + fortificationBase + synergyBase
            );

            const unitName = recruitableUnits.find(unit => unit.id === selectedUnitId)?.name || selectedUnitId;
            preview.textContent =
                `Difesa presidio stimata: ${estimatedDefense} ` +
                `(unità ${unitName} +${Math.round(unitBonus)}, presidio +${Math.round(garrisonBase)}, ` +
                `terreno +${terrainBonus}, fortificazioni +${Math.round(fortificationBase + synergyBase)}).`;
        }

        function renderGarrisonUnitSelector(unitIds) {
            const selector = document.getElementById('garrisonUnitSelect');
            if (!selector) return;

            const previousValue = selector.value;
            const namesById = new Map(recruitableUnits.map(unit => [unit.id, unit.name || unit.id]));
            const counts = new Map();
            for (const unitId of unitIds) {
                counts.set(unitId, (counts.get(unitId) || 0) + 1);
            }

            const options = [];
            for (const [unitId, count] of counts.entries()) {
                if (count <= 0) continue;
                options.push({
                    id: unitId,
                    name: namesById.get(unitId) || unitId,
                    count,
                });
            }

            options.sort((a, b) => a.name.localeCompare(b.name, 'it'));
            selector.innerHTML = options
                .map(item => `<option value="${item.id}">${item.name} (${item.count})</option>`)
                .join('');

            const hasDetachableUnit = unitIds.length > 1 && options.length > 0;
            selector.disabled = !hasDetachableUnit;
            if (!hasDetachableUnit) {
                selector.innerHTML = '<option value="">Nessuna unità distaccabile</option>';
                updateGarrisonDefensePreview();
                return;
            }

            if (previousValue && options.some(item => item.id === previousValue)) {
                selector.value = previousValue;
            }

            updateGarrisonDefensePreview();
        }

        function initHintToneObserver() {
            const hint = document.getElementById('battleStatusHint');
            if (!hint) return;
            const observer = new MutationObserver(() => applyHintTone());
            observer.observe(hint, { childList: true, characterData: true, subtree: true });
            applyHintTone();
        }

        function escapeHtml(text) {
            return text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function renderLog(lines) {
            const playerContainer = document.getElementById('battleLogPlayer');
            const aiContainer = document.getElementById('battleLogAi');
            if (!lines || lines.length === 0) {
                playerContainer.innerHTML = '<div class="log-entry">Nessuna azione.</div>';
                aiContainer.innerHTML = '<div class="log-entry">Nessuna azione.</div>';
                return;
            }

            const playerLines = [];
            const aiLines = [];

            for (const line of lines) {
                const isAutoRecruitEvent = /autoreclutamento/i.test(line);
                if (isAutoRecruitEvent) {
                    playerLines.push(line);
                    continue;
                }

                const hasPlayer = /\bPLAYER\b|\bplayer\b/.test(line);
                const hasAi = /\bIA\b|\bAI\b|\bai\b/.test(line);

                if (hasPlayer) playerLines.push(line);
                if (hasAi) aiLines.push(line);

                if (!hasPlayer && !hasAi) {
                    playerLines.push(line);
                    aiLines.push(line);
                }
            }

            const formatLine = (line) => {
                let safe = escapeHtml(line);
                safe = safe.replace(/(\[Turno\s+\d+\])/g, '<span class="log-turn">$1</span>');
                safe = safe.replace(/\bPLAYER\b|\bplayer\b/g, '<span class="log-player">PLAYER</span>');
                safe = safe.replace(/\bIA\b|\bAI\b|\bai\b/g, '<span class="log-ai">IA</span>');
                safe = safe.replace(/\b(Turno|Assalto|Battaglia|Presidio|Scontro|Ritirata|conquista)\b/g, '<span class="log-system">$1</span>');

                const raw = String(line).toLowerCase();
                let priorityClass = 'log-priority-low';
                if (raw.includes('errore') || raw.includes('assalto') || raw.includes('☠') || raw.includes('perdite') || raw.includes('vince')) {
                    priorityClass = 'log-priority-high';
                } else if (raw.includes('battaglia') || raw.includes('ritirata') || raw.includes('recluta') || raw.includes('fortifica') || raw.includes('presidio')) {
                    priorityClass = 'log-priority-medium';
                }

                return `<div class="log-entry ${priorityClass}">${safe}</div>`;
            };

            playerContainer.innerHTML = playerLines.length > 0
                ? playerLines.map(formatLine).join('')
                : '<div class="log-entry">Nessuna azione PLAYER.</div>';

            aiContainer.innerHTML = aiLines.length > 0
                ? aiLines.map(formatLine).join('')
                : '<div class="log-entry">Nessuna azione IA.</div>';

            playerContainer.scrollTop = playerContainer.scrollHeight;
            aiContainer.scrollTop = aiContainer.scrollHeight;
        }

        function renderMapBoard(mapData) {
            const board = document.getElementById('mapBoard');
            board.innerHTML = '';
            board.style.gridTemplateColumns = `repeat(${mapData.cols}, minmax(42px, 1fr))`;

            const manualControl = (currentBattleState?.player?.control_mode || 'manual') === 'manual';
            const playerPos = mapData.positions.player || null;
            const adjacentMoves = getAdjacentMoves(playerPos, mapData.rows, mapData.cols);
            const playerTransit = getEntityTransitState('player', mapData);
            const aiTransit = getEntityTransitState('ai', mapData);
            const cellRefs = new Map();

            mapData.grid.forEach((row, rowIndex) => {
                row.forEach((cell, colIndex) => {
                    const button = document.createElement('button');
                    button.className = `map-cell ${terrainClass(cell.terrain)}`;
                    button.type = 'button';
                    button.dataset.row = String(rowIndex);
                    button.dataset.col = String(colIndex);
                    button.title = `${cell.terrain} (${rowIndex}, ${colIndex})`;

                    if (cell.is_strategic) button.classList.add('cell-strategic');
                    if (cell.occupation === 'player') button.classList.add('cell-player');
                    if (cell.occupation === 'ai') button.classList.add('cell-ai');

                    if (mapData.positions.player && mapData.positions.player[0] === rowIndex && mapData.positions.player[1] === colIndex) {
                        button.classList.add('cell-player-army');
                        if (playerTransit) {
                            button.classList.add('cell-army-in-transit');
                            button.title += buildTransitTitleSuffix(playerTransit);
                        }
                    }
                    if (mapData.positions.ai && mapData.positions.ai[0] === rowIndex && mapData.positions.ai[1] === colIndex) {
                        button.classList.add('cell-ai-army');
                        if (aiTransit) {
                            button.classList.add('cell-army-in-transit');
                            button.title += buildTransitTitleSuffix(aiTransit);
                        }
                    }

                    const isAdjacent = adjacentMoves.some(move => move[0] === rowIndex && move[1] === colIndex);
                    const canMine = canPlaceMineOnCell(cell, rowIndex, colIndex, mapData.positions.player);
                    const canFortify = canPlaceFortificationOnCell(cell, rowIndex, colIndex, mapData.positions.player);
                    const mineMode = currentAction === 'place_mine';
                    const fortifyMode = currentAction === 'place_fortification';

                    if (currentBattleState && currentBattleState.state !== 'game_over' && manualControl) {
                        if (isAdjacent || (mineMode && canMine) || (fortifyMode && canFortify)) {
                            button.classList.add('cell-adjacent');
                        }
                        button.onclick = (event) => handleCellAction(event, rowIndex, colIndex, isAdjacent, canMine, canFortify);
                    } else {
                        if (currentBattleState && currentBattleState.state !== 'game_over' && !manualControl) {
                            button.classList.add('cell-orders-locked');
                            button.title += ' · Movimento manuale disattivato (modalità ordini)';
                        }
                        button.disabled = true;
                    }

                    button.innerHTML = buildCellLabel(cell, rowIndex, colIndex, mapData, playerTransit, aiTransit);

                    board.appendChild(button);
                    cellRefs.set(`${rowIndex},${colIndex}`, button);
                });
            });

            renderTransitMarker(board, mapData, 'player', playerTransit, cellRefs);
            renderTransitMarker(board, mapData, 'ai', aiTransit, cellRefs);
        }

        function getEntityTransitState(entityKey, mapData) {
            const movement = currentBattleState?.[entityKey]?.movement;
            if (!movement) return null;

            const blockedTurns = Number(movement.blocked_turns || 0);
            const missingRatio = Math.max(0, Math.min(1, Number(movement.missing_ratio || 0)));
            const progressRatio = Math.max(0, Math.min(1, Number(movement.progress_ratio || 1)));

            if (missingRatio <= 0 || blockedTurns <= 0) {
                return null;
            }

            const fromPos = Array.isArray(movement.last_from_pos) ? movement.last_from_pos : null;
            const toPos = Array.isArray(movement.last_to_pos) ? movement.last_to_pos : null;
            if (!fromPos || !toPos || fromPos.length !== 2 || toPos.length !== 2) {
                return null;
            }

            const currentPos = mapData?.positions?.[entityKey];
            if (!Array.isArray(currentPos) || currentPos[0] !== toPos[0] || currentPos[1] !== toPos[1]) {
                return null;
            }

            const deltaRow = toPos[0] - fromPos[0];
            const deltaCol = toPos[1] - fromPos[1];

            if ((Math.abs(deltaRow) + Math.abs(deltaCol)) !== 1) {
                return null;
            }

            return {
                fromPos,
                toPos,
                progressRatio,
                progressPercent: Math.round(progressRatio * 100),
                missingPercent: Math.round(missingRatio * 100),
                blockedTurns,
                terrain: movement.last_terrain || 'Terreno',
                cost: Number(movement.last_cost || 0),
            };
        }

        function renderTransitMarker(board, mapData, entityKey, transitState, cellRefs) {
            if (!transitState) return;

            const fromPos = transitState.fromPos;
            const toPos = transitState.toPos;
            if (!Array.isArray(fromPos) || !Array.isArray(toPos)) return;

            const fromButton = cellRefs.get(`${fromPos[0]},${fromPos[1]}`);
            const toButton = cellRefs.get(`${toPos[0]},${toPos[1]}`);
            if (!fromButton || !toButton) return;

            const boardRect = board.getBoundingClientRect();
            const fromRect = fromButton.getBoundingClientRect();
            const toRect = toButton.getBoundingClientRect();

            const fromX = (fromRect.left - boardRect.left) + board.scrollLeft + (fromRect.width / 2);
            const fromY = (fromRect.top - boardRect.top) + board.scrollTop + (fromRect.height / 2);
            const toX = (toRect.left - boardRect.left) + board.scrollLeft + (toRect.width / 2);
            const toY = (toRect.top - boardRect.top) + board.scrollTop + (toRect.height / 2);

            const progress = Math.max(0, Math.min(1, Number(transitState.progressRatio || 0)));
            const x = fromX + ((toX - fromX) * progress);
            const y = fromY + ((toY - fromY) * progress);

            const marker = document.createElement('div');
            marker.className = `transit-marker ${entityKey}`;
            marker.textContent = entityKey === 'player' ? 'YOU' : 'IA';
            marker.title =
                `${entityKey === 'player' ? 'PLAYER' : 'IA'} in movimento: ` +
                `${transitState.progressPercent}% completato, ` +
                `${transitState.missingPercent}% mancante`; 
            marker.style.left = `${x}px`;
            marker.style.top = `${y}px`;

            board.appendChild(marker);
        }

        function buildTransitTitleSuffix(transitState) {
            return (
                ` · Movimento in corso: ${transitState.progressPercent}% completato` +
                ` (${transitState.missingPercent}% mancante, costo ${transitState.cost}, terreno ${transitState.terrain})`
            );
        }

        function buildCellLabel(cell, rowIndex, colIndex, mapData, playerTransit = null, aiTransit = null) {
            const isPlayerArmy = mapData.positions.player && mapData.positions.player[0] === rowIndex && mapData.positions.player[1] === colIndex;
            const isAiArmy = mapData.positions.ai && mapData.positions.ai[0] === rowIndex && mapData.positions.ai[1] === colIndex;

            if (isPlayerArmy) {
                if (playerTransit) return '';
                let playerLabel = cell.is_mine ? 'YOU⛏' : 'YOU';
                if (cell.fortification_level > 0) {
                    playerLabel += `<span class="fort-badge">🧱${cell.fortification_level}</span>`;
                }
                return playerLabel;
            }
            if (isAiArmy) {
                if (aiTransit) return '';
                let aiLabel = cell.is_mine ? 'IA⛏' : 'IA';
                if (cell.fortification_level > 0) {
                    aiLabel += `<span class="fort-badge">🧱${cell.fortification_level}</span>`;
                }
                return aiLabel;
            }

            let label = cell.is_castle ? '🏰' : terrainAbbrev(cell.terrain);
            if (cell.is_mine) {
                label = '⛏' + label;
            }
            if (cell.fortification_level > 0) {
                label += `<span class="fort-badge">🧱${cell.fortification_level}</span>`;
            }
            if (cell.garrison_strength > 0) {
                label += `<span class="garrison-badge">${cell.garrison_strength}</span>`;
            }
            return label;
        }


