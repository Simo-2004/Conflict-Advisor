
        function renderBattleState(sessionData) {
            currentBattleState = sessionData;

            if (sessionData.state === 'game_over') {
                document.getElementById('battleStatusRound').textContent = `Fine partita: ${sessionData.winner}`;
                document.getElementById('battleStatusHint').textContent = 'Il registro mostra il riepilogo completo della battaglia.';
            } else {
                document.getElementById('battleStatusRound').textContent = `Turno ${sessionData.map.turn}`;
                document.getElementById('battleStatusHint').textContent = 'Seleziona una legione e usa Presidio/Miniera/Fortifica, o premi H per i comandi rapidi.';
            }

            renderTacticalLegionSelect(sessionData);
            updateBattleStatusModePill(sessionData);
            updateTacticalActionButtons(sessionData);

            const playerLegion = buildLegionInfo(sessionData.player.units || []);
            const aiLegion = buildLegionInfo(sessionData.ai.units || []);
            renderGarrisonUnitSelector(sessionData);
            updateGarrisonDefensePreview(sessionData);

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
            const abilityCard = document.getElementById('abilityResearchBtn');
            const abilityLabel = document.getElementById('abilityLabel');
            if (abilityLabel && abilityCard) {
                let statusText = 'Apri per vedere le ricerche';
                let unlocked = false;
                let researching = false;
                if (abilityState) {
                    if (abilityState.unlocked) {
                        statusText = 'Sbloccata';
                        unlocked = true;
                    } else if (abilityState.researching) {
                        statusText = `Ricerca in corso · ${abilityState.turns_remaining} turni`;
                        researching = true;
                    } else {
                        statusText = 'Pronta per la ricerca';
                    }
                }
                abilityLabel.textContent = statusText;
                abilityCard.classList.toggle('is-unlocked', unlocked);
                abilityCard.classList.toggle('is-researching', researching);
            }

            const killSwitchBtn = document.getElementById('aiKillSwitchBtn');
            const killSwitchActive = Boolean(sessionData.debug?.ai_kill_switch_active);
            if (killSwitchBtn) {
                killSwitchBtn.classList.toggle('active', killSwitchActive);
                killSwitchBtn.textContent = killSwitchActive ? '🧪 IA OFF (PAUSA)' : '🧪 IA ON';
            }

            const gameOver = sessionData.state === 'game_over';

            const garrisonUnitSelect = document.getElementById('garrisonUnitSelect');
            if (garrisonUnitSelect && gameOver) {
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
            renderLegionMarkersOnMap(sessionData.map, sessionData);

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

        const TACTICAL_LEGION_TYPE_LABELS = {
            army: 'Esercito',
            mining: 'Mineraria',
            construction: 'Costruzione',
        };

        function getSelectedGarrisonUnitId() {
            const selector = document.getElementById('garrisonUnitSelect');
            if (!selector || selector.disabled) {
                return null;
            }
            return selector.value || null;
        }

        function getSelectedTacticalLegionId() {
            const selector = document.getElementById('tacticalLegionSelect');
            return selector && selector.value ? selector.value : null;
        }

        function getSelectedTacticalLegion(sessionData) {
            const legionId = getSelectedTacticalLegionId();
            if (!legionId) return null;
            return (sessionData?.player?.legions || {})[legionId] || null;
        }

        function renderTacticalLegionSelect(sessionData) {
            const selector = document.getElementById('tacticalLegionSelect');
            if (!selector) return;

            const legions = Object.values(sessionData?.player?.legions || {});
            const previousValue = selector.value;

            if (legions.length === 0) {
                selector.innerHTML = '<option value="">Nessuna legione attiva</option>';
                selector.disabled = true;
                return;
            }

            selector.disabled = sessionData.state === 'game_over';
            selector.innerHTML = legions.map((legion) => {
                const typeLabel = TACTICAL_LEGION_TYPE_LABELS[legion.legion_type] || 'Esercito';
                return `<option value="${legion.id}">${legion.name} (${typeLabel})</option>`;
            }).join('');

            if (previousValue && legions.some((legion) => legion.id === previousValue)) {
                selector.value = previousValue;
            }
        }

        function updateBattleStatusModePill(sessionData) {
            const pill = document.getElementById('battleStatusMode');
            if (!pill) return;

            const legion = getSelectedTacticalLegion(sessionData);
            if (!legion) {
                pill.textContent = 'Legione: nessuna';
                return;
            }
            const typeLabel = TACTICAL_LEGION_TYPE_LABELS[legion.legion_type] || 'Esercito';
            pill.textContent = `Legione: ${legion.name} (${typeLabel})`;
        }

        function updateTacticalActionButtons(sessionData) {
            const gameOver = sessionData.state === 'game_over';
            const legion = getSelectedTacticalLegion(sessionData);
            const unitsCount = legion ? (legion.units || []).length : 0;

            const garrisonBtn = document.getElementById('actionGarrisonBtn');
            const mineBtn = document.getElementById('actionMineBtn');
            const fortifyBtn = document.getElementById('actionFortifyBtn');

            if (garrisonBtn) garrisonBtn.disabled = gameOver || !legion || unitsCount < 2;
            if (mineBtn) mineBtn.disabled = gameOver || !legion || legion.legion_type !== 'mining';
            if (fortifyBtn) fortifyBtn.disabled = gameOver || !legion || legion.legion_type !== 'construction';
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

        function updateGarrisonDefensePreview(sessionData) {
            const preview = document.getElementById('garrisonDefensePreview');
            if (!preview) return;

            const state = sessionData || currentBattleState;
            const legion = getSelectedTacticalLegion(state);
            if (!legion) {
                preview.textContent = 'Difesa presidio stimata: seleziona una legione.';
                return;
            }
            if ((legion.units || []).length < 2) {
                preview.textContent = 'Difesa presidio stimata: la legione deve avere almeno 2 truppe.';
                return;
            }

            const selectedUnitId = getSelectedGarrisonUnitId();
            if (!selectedUnitId) {
                preview.textContent = 'Difesa presidio stimata: nessuna unità distaccabile.';
                return;
            }

            const [row, col] = legion.pos;
            const cell = state?.map?.grid?.[row]?.[col];
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

        function renderGarrisonUnitSelector(sessionData) {
            const selector = document.getElementById('garrisonUnitSelect');
            if (!selector) return;

            const legion = getSelectedTacticalLegion(sessionData);
            const unitIds = legion ? (legion.units || []) : [];

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

            const hasDetachableUnit = unitIds.length >= 2 && options.length > 0;
            if (!hasDetachableUnit) {
                selector.innerHTML = '<option value="">Nessuna unità distaccabile</option>';
                selector.disabled = true;
                updateGarrisonDefensePreview(sessionData);
                return;
            }

            selector.disabled = sessionData.state === 'game_over';
            selector.innerHTML = options
                .map(item => `<option value="${item.id}">${item.name} (${item.count})</option>`)
                .join('');

            if (previousValue && options.some(item => item.id === previousValue)) {
                selector.value = previousValue;
            }

            updateGarrisonDefensePreview(sessionData);
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
                    button.disabled = true;

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
            const isPlayerArmy = false;
            const isAiArmy = false;

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

        /* ══════════════════════════════════════════════════════════
         *  LEGION MAP SYSTEM
         *  Le legioni si muovono autonomamente sulla mappa passo-passo.
         *  Ogni volta che renderBattleState() viene chiamato (= ogni turno
         *  o ogni refresh) la legione avanza di 1 step lungo il path BFS
         *  verso la destinazione, a meno che non ci sia già arrivata.
         * ══════════════════════════════════════════════════════════ */

        /* BFS per trovare il percorso più breve tra due celle.
         * Tratta i fiumi come non attraversabili (opzione conservativa).
         * Restituisce un array di [row, col] dal nodo START (escluso) a END (incluso),
         * o null se non raggiungibile. */
        function bfsPath(grid, rows, cols, startRow, startCol, endRow, endCol) {
            if (startRow === endRow && startCol === endCol) return [];

            const visited = Array.from({ length: rows }, () => new Array(cols).fill(false));
            const parent = Array.from({ length: rows }, () => new Array(cols).fill(null));
            visited[startRow][startCol] = true;
            const queue = [[startRow, startCol]];

            const dirs = [[-1,0],[1,0],[0,-1],[0,1]];

            while (queue.length > 0) {
                const [r, c] = queue.shift();
                for (const [dr, dc] of dirs) {
                    const nr = r + dr;
                    const nc = c + dc;
                    if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue;
                    if (visited[nr][nc]) continue;
                    // Le legioni evitano i fiumi (come il player)
                    if (grid[nr][nc].terrain === 'Fiume') continue;
                    visited[nr][nc] = true;
                    parent[nr][nc] = [r, c];
                    if (nr === endRow && nc === endCol) {
                        // Ricostruisci il percorso
                        const path = [];
                        let cur = [nr, nc];
                        while (cur[0] !== startRow || cur[1] !== startCol) {
                            path.unshift(cur);
                            cur = parent[cur[0]][cur[1]];
                        }
                        return path;
                    }
                    queue.push([nr, nc]);
                }
            }
            return null; // Irraggiungibile
        }

        /* Colore distintivo per la pedina di una legione PLAYER, in base al suo indice. */
        const LEGION_MARKER_COLORS = ['#2563eb', '#059669', '#d97706', '#7c3aed', '#0891b2', '#db2777'];
        function getLegionColor(idx) {
            return LEGION_MARKER_COLORS[idx % LEGION_MARKER_COLORS.length];
        }

        /* Estrae le tre iniziali (le prime 3 lettere) del nome legione,
         * usate come etichetta compatta sulla pedina in mappa. */
        function getLegionInitials(name) {
            const clean = (name || '').trim();
            if (!clean) return '???';
            return clean.slice(0, 3).toUpperCase();
        }

        /* Avanza le legioni attive di 1 passo verso la destinazione.
         * Chiamato prima del render per aggiornare currentPos. */
        function renderLegionMarkersOnMap(mapData, sessionData) {
            const board = document.getElementById('mapBoard');
            if (!board) return;

            // Rimuovi tutti i marker legione precedenti
            board.querySelectorAll('.legion-map-marker').forEach(m => m.remove());

            if (!sessionData) return;
            const playerLegions = sessionData.player?.legions ? Object.values(sessionData.player.legions) : [];
            const aiLegions = sessionData.ai?.legions ? Object.values(sessionData.ai.legions) : [];
            const allLegions = [...playerLegions.map(l => ({...l, isAi: false})), ...aiLegions.map(l => ({...l, isAi: true}))];

            if (allLegions.length === 0) return;

            allLegions.forEach((leg, idx) => {
                if (!leg.pos) return;
                const [r, c] = leg.pos;
                const cellBtn = board.querySelector(`[data-row="${r}"][data-col="${c}"]`);
                if (!cellBtn) return;

                const color = leg.isAi ? '#c0392b' : getLegionColor(idx);
                const atDest = leg.target && leg.pos[0] === leg.target[0] && leg.pos[1] === leg.target[1];

                const marker = document.createElement('div');
                marker.className = 'legion-map-marker';
                marker.dataset.legionId = String(leg.id);

                const boardRect = board.getBoundingClientRect();
                const cellRect = cellBtn.getBoundingClientRect();
                const x = (cellRect.left - boardRect.left) + board.scrollLeft + (cellRect.width / 2);
                const y = (cellRect.top  - boardRect.top)  + board.scrollTop  + (cellRect.height / 2) + (leg.isAi ? -10 : 10);

                marker.style.cssText = [
                    `position:absolute`,
                    `left:${x}px`,
                    `top:${y}px`,
                    `transform:translate(-50%,-50%)`,
                    `background:${color}`,
                    `color:#fff`,
                    `font-size:0.6em`,
                    `font-weight:800`,
                    `padding:2px 5px`,
                    `border-radius:6px`,
                    `z-index:40`,
                    `pointer-events:none`,
                    `white-space:nowrap`,
                    `box-shadow:0 2px 6px rgba(0,0,0,0.35)`,
                    `letter-spacing:0.01em`,
                    atDest ? 'outline:2px solid #fff' : '',
                ].filter(Boolean).join(';');

                const initials = getLegionInitials(leg.name);
                marker.textContent = leg.isAi ? `🤖${initials}` : initials;
                marker.title = `${leg.name}${atDest ? ' · ARRIVATA' : ' · in marcia'}`;

                board.appendChild(marker);
            });
        }
        function updateLegionStatusHint(sessionData) {
            const hint = document.getElementById('battleStatusHint');
            if (!hint) return;

            const legions = (window.LegionsPanel && window.LegionsPanel.getActiveLegions)
                ? window.LegionsPanel.getActiveLegions()
                : [];

            if (!legions || legions.length === 0) return;

            const inMarcia = legions.filter(l => {
                if (!l.currentPos || !l.target) return false;
                return l.currentPos[0] !== l.target[0] || l.currentPos[1] !== l.target[1];
            });
            const arrivate = legions.filter(l => {
                if (!l.currentPos || !l.target) return false;
                return l.currentPos[0] === l.target[0] && l.currentPos[1] === l.target[1];
            });

            const parts = [];
            if (inMarcia.length > 0) {
                const nomi = inMarcia.map(l => {
                    const passiRim = l.path ? l.path.length - (l.pathStep || 0) : '?';
                    return `${l.name} (${passiRim} passi)`;
                }).join(', ');
                parts.push(`&#9658; In marcia: ${nomi}`);
            }
            if (arrivate.length > 0) {
                const nomi = arrivate.map(l => l.name).join(', ');
                parts.push(`&#10003; Arrivate: ${nomi}`);
            }

            if (parts.length > 0) {
                hint.innerHTML = parts.join(' · ');
            }
        }

