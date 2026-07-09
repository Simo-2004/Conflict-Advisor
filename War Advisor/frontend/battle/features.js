        async function researchAbility() {
            return researchAbilityById('domain_engineering');
        }

        async function researchAbilityById(abilityId) {
            try {
                const response = await fetch('http://127.0.0.1:8000/game/research-ability', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ability_id: abilityId })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nella ricerca abilità');
                }

                const result = await response.json();
                transientLogLines = [];
                renderBattleState(result.session);
                renderSkillTree(result.session);
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore ricerca abilità: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        function openSkillTree() {
            const overlay = document.getElementById('skillTreeOverlay');
            if (!overlay) return;
            renderSkillTree(currentBattleState);
            overlay.classList.add('open');
        }

        function closeSkillTree() {
            const overlay = document.getElementById('skillTreeOverlay');
            if (!overlay) return;
            overlay.classList.remove('open');
        }

        function closeSkillTreeIfBackdrop(event) {
            if (event.target && event.target.id === 'skillTreeOverlay') {
                closeSkillTree();
            }
        }

        function handleAutoRecruitButton() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                document.getElementById('battleStatusHint').textContent = 'Partita terminata: autoreclutamento non disponibile.';
                return;
            }

            const autoRecruitState = currentBattleState.player?.auto_recruit;
            if (autoRecruitState?.enabled) {
                stopAutoRecruit();
                return;
            }

            openAutoRecruitMenu();
        }

        function openAutoRecruitMenu() {
            const overlay = document.getElementById('autoRecruitOverlay');
            if (!overlay) return;

            const autoSelect = document.getElementById('autoRecruitUnitSelect');
            const recruitSelect = document.getElementById('recruitSelect');
            const turnsInput = document.getElementById('autoRecruitTurnsInput');
            const autoRecruitState = currentBattleState?.player?.auto_recruit;

            if (autoSelect) {
                if (autoRecruitState?.unit_id) {
                    autoSelect.value = autoRecruitState.unit_id;
                } else if (recruitSelect && recruitSelect.value) {
                    autoSelect.value = recruitSelect.value;
                }
            }

            if (turnsInput) {
                const defaultTurns = Number.isFinite(autoRecruitState?.turns_remaining)
                    ? Math.max(1, Math.min(40, Number(autoRecruitState.turns_remaining)))
                    : 6;
                turnsInput.value = String(defaultTurns);
            }

            renderAutoRecruitForecast();
            overlay.classList.add('open');
        }

        function closeAutoRecruitMenu() {
            const overlay = document.getElementById('autoRecruitOverlay');
            if (!overlay) return;
            overlay.classList.remove('open');
        }

        function closeAutoRecruitIfBackdrop(event) {
            if (event.target && event.target.id === 'autoRecruitOverlay') {
                closeAutoRecruitMenu();
            }
        }

        function getAutoRecruitTurnsValue() {
            const input = document.getElementById('autoRecruitTurnsInput');
            const raw = Number.parseInt(input?.value || '0', 10);
            const turns = Number.isFinite(raw) ? raw : 0;
            return Math.max(1, Math.min(40, turns));
        }

        function getPlayerCurrentTerrainName() {
            const mapData = currentBattleState?.map;
            const playerPos = mapData?.positions?.player;
            if (!mapData || !Array.isArray(playerPos)) return 'Pianura';
            const [row, col] = playerPos;
            return mapData.grid?.[row]?.[col]?.terrain || 'Pianura';
        }

        function estimateArmyPotential(unitIds, terrainName) {
            if (!Array.isArray(unitIds) || unitIds.length === 0) return 0;
            const counts = new Map();
            let base = 0;
            for (const unitId of unitIds) {
                base += evaluateUnitBattleValue(unitId, terrainName);
                counts.set(unitId, (counts.get(unitId) || 0) + 1);
            }
            let stackBonus = 0;
            counts.forEach((count, unitId) => {
                if (count <= 1) return;
                const unitValue = evaluateUnitBattleValue(unitId, terrainName);
                stackBonus += unitValue * 0.34 * Math.pow(count - 1, 1.22);
            });
            return Math.max(0, base + stackBonus);
        }

        function renderAutoRecruitForecast() {
            const summary = document.getElementById('autoRecruitSummary');
            const svg = document.getElementById('autoRecruitChart');
            const autoSelect = document.getElementById('autoRecruitUnitSelect');
            if (!summary || !svg || !autoSelect) return;

            const selectedUnitId = autoSelect.value;
            const turns = getAutoRecruitTurnsValue();
            const terrainName = getPlayerCurrentTerrainName();
            const unit = recruitableUnits.find(item => item.id === selectedUnitId);
            const unitName = unit?.name || selectedUnitId || 'Unità';
            const unitPotential = evaluateUnitBattleValue(selectedUnitId, terrainName);
            const currentPotential = estimateArmyPotential(currentBattleState?.player?.units || [], terrainName);

            const values = [];
            for (let i = 0; i < turns; i += 1) {
                const expectedRecruits = Math.floor((i + 2) / 2); // approssima cooldown a 2 turni
                const expected = currentPotential + (expectedRecruits * unitPotential * 0.95);
                const uncertainty = Math.max(0.14, 0.36 - (i * 0.02));
                values.push({
                    turn: i + 1,
                    expected,
                    min: expected * (1 - uncertainty),
                    max: expected * (1 + uncertainty),
                });
            }

            const rawMinY = Math.min(...values.map(v => v.min), currentPotential);
            const rawMaxY = Math.max(...values.map(v => v.max), currentPotential);
            const span = Math.max(1, rawMaxY - rawMinY);
            const minY = Math.max(0, rawMinY - (span * 0.1));
            const maxY = rawMaxY + (span * 0.1);

            const w = 360;
            const h = 170;
            const padX = 24;
            const padY = 16;
            const chartW = w - (padX * 2);
            const chartH = h - (padY * 2);
            const chartInset = Math.min(14, chartW * 0.08);

            const xForIndex = (idx) => {
                if (values.length <= 1) return padX + (chartW / 2);
                const usableWidth = Math.max(20, chartW - (chartInset * 2));
                return padX + chartInset + ((idx / (values.length - 1)) * usableWidth);
            };
            const yForValue = (v) => {
                if (maxY <= minY) return padY + (chartH / 2);
                const y = padY + ((maxY - v) / (maxY - minY)) * chartH;
                return Math.min(padY + chartH - 2, Math.max(padY + 2, y));
            };

            const topPoints = values.map((v, idx) => `${xForIndex(idx)},${yForValue(v.max)}`).join(' ');
            const bottomPoints = [...values].reverse().map((v, idx) => {
                const originalIdx = values.length - 1 - idx;
                return `${xForIndex(originalIdx)},${yForValue(v.min)}`;
            }).join(' ');
            const areaPoints = `${topPoints} ${bottomPoints}`;
            const expectedPoints = values.map((v, idx) => `${xForIndex(idx)},${yForValue(v.expected)}`).join(' ');
            const baselineY = yForValue(currentPotential);
            const startX = xForIndex(0);
            const startY = yForValue(values[0].expected);
            const endX = xForIndex(values.length - 1);
            const endY = yForValue(values[values.length - 1].expected);

            const uncertaintyLayer = values.length > 1
                ? `<polygon points="${areaPoints}" fill="rgba(56, 189, 248, 0.22)"></polygon>`
                : `<line x1="${startX}" y1="${yForValue(values[0].max)}" x2="${startX}" y2="${yForValue(values[0].min)}" stroke="rgba(56, 189, 248, 0.8)" stroke-width="3" stroke-linecap="round"></line>`;
            const trendLayer = values.length > 1
                ? `<polyline points="${expectedPoints}" fill="none" stroke="#0369a1" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"></polyline>`
                : '';
            const endMarker = values.length > 1
                ? `<circle cx="${endX}" cy="${endY}" r="3" fill="#7c2d12"></circle>`
                : '';
            const endTurnLabel = turns > 1
                ? `<text x="${w - padX}" y="${h - 4}" text-anchor="end" fill="#334155" font-size="10">T${turns}</text>`
                : '';

            svg.innerHTML = `
                <line x1="${padX}" y1="${baselineY}" x2="${w - padX}" y2="${baselineY}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3 3" />
                ${uncertaintyLayer}
                ${trendLayer}
                <circle cx="${startX}" cy="${startY}" r="3" fill="#0f766e"></circle>
                ${endMarker}
                <text x="${padX}" y="${h - 4}" fill="#334155" font-size="10">T1</text>
                ${endTurnLabel}
            `;

            const finalExpected = values[values.length - 1]?.expected || currentPotential;
            const firstUncertainty = values[0] ? ((values[0].max - values[0].min) / Math.max(1, values[0].expected)) * 100 : 0;
            summary.textContent =
                `Unità: ${unitName} · Durata: ${turns} turni · Terreno attuale: ${terrainName} · ` +
                `Potenziale stimato finale: ${Math.round(finalExpected)} · Incertezza iniziale ±${Math.round(firstUncertainty / 2)}% (stima preliminare)`;
        }

        async function startAutoRecruitFromMenu() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                document.getElementById('battleStatusHint').textContent = 'Partita terminata: autoreclutamento non disponibile.';
                return;
            }

            try {
                const unitId = document.getElementById('autoRecruitUnitSelect').value;
                const turns = getAutoRecruitTurnsValue();
                const response = await fetch('http://127.0.0.1:8000/game/auto-recruit/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ unit_id: unitId, turns })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore avvio autoreclutamento');
                }

                const result = await response.json();
                transientLogLines = [];
                closeAutoRecruitMenu();
                renderBattleState(result.session);
                document.getElementById('battleStatusHint').textContent = 'Autoreclutamento avviato con successo.';
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore autoreclutamento: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function stopAutoRecruit() {
            try {
                const response = await fetch('http://127.0.0.1:8000/game/auto-recruit/stop', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore stop autoreclutamento');
                }

                const result = await response.json();
                transientLogLines = [];
                renderBattleState(result.session);
                document.getElementById('battleStatusHint').textContent = 'Autoreclutamento fermato.';
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore stop autoreclutamento: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function openInGameAdvisorMenu() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                document.getElementById('battleStatusHint').textContent = 'Partita terminata: advisor non disponibile.';
                return;
            }

            const overlay = document.getElementById('strategyAdvisorOverlay');
            const reliability = document.getElementById('strategyAdvisorReliability');
            const note = document.getElementById('strategyAdvisorNote');
            if (reliability) {
                reliability.textContent = 'Affidabilità report: analisi in corso...';
            }
            if (note) {
                note.textContent = 'Raccolta dati tattici in corso...';
            }

            if (overlay) {
                overlay.classList.add('open');
            }

            try {
                const response = await fetch('http://127.0.0.1:8000/game/in-game-advisor');
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore recupero advisor strategico');
                }

                const advisor = await response.json();
                renderInGameAdvisor(advisor);
            } catch (error) {
                if (note) {
                    note.textContent = `Errore advisor: ${error.message}`;
                }
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
            }
        }

        function closeInGameAdvisorMenu() {
            const overlay = document.getElementById('strategyAdvisorOverlay');
            if (!overlay) return;
            overlay.classList.remove('open');
        }

        function closeInGameAdvisorIfBackdrop(event) {
            if (event.target && event.target.id === 'strategyAdvisorOverlay') {
                closeInGameAdvisorMenu();
            }
        }

        function renderInGameAdvisor(advisor) {
            const top = advisor?.top_strategy || {};
            const second = advisor?.second_strategy || top;
            const worst = advisor?.worst_strategy || top;
            const reliability = advisor?.reliability || {};

            const weatherLabel = advisor?.weather_name || 'Nessuno';
            const troopStatusLabel = advisor?.troop_status_name || 'N/D';
            const meta = document.getElementById('strategyAdvisorMeta');
            if (meta) {
                meta.textContent = `Turno ${advisor?.turn || '?'} · Terreno: ${advisor?.terrain_name || 'N/D'} · Meteo: ${weatherLabel} · Stato truppe: ${troopStatusLabel}`;
            }

            const reliabilityEl = document.getElementById('strategyAdvisorReliability');
            if (reliabilityEl) {
                reliabilityEl.textContent =
                    `Affidabilità report: ${reliability.score_pct ?? '--'}% · ` +
                    `Incertezza: ${reliability.uncertainty_pct ?? '--'}% (${reliability.label || 'stima in-battle'})`;
            }

            const noteEl = document.getElementById('strategyAdvisorNote');
            if (noteEl) {
                noteEl.textContent = reliability.note || 'Analisi tattica preliminare.';
            }

            document.getElementById('advisorTopName').textContent = top.name || '---';
            document.getElementById('advisorTopScore').textContent =
                `Compatibilità stimata: ${formatAdvisorPct(top.compatibility)} · ` +
                `Confidenza: ${formatAdvisorPct(top.confidence)} · ` +
                `Distanza: ${formatAdvisorDistance(top.distance)}`;
            document.getElementById('advisorTopDesc').textContent = top.description || 'Nessuna descrizione disponibile.';

            document.getElementById('advisorSecondName').textContent = second.name || '---';
            document.getElementById('advisorSecondScore').textContent =
                `Compatibilità stimata: ${formatAdvisorPct(second.compatibility)} · ` +
                `Confidenza: ${formatAdvisorPct(second.confidence)} · ` +
                `Distanza: ${formatAdvisorDistance(second.distance)}`;
            document.getElementById('advisorSecondDesc').textContent = second.description || 'Nessuna descrizione disponibile.';

            document.getElementById('advisorWorstName').textContent = worst.name || '---';
            document.getElementById('advisorWorstScore').textContent =
                `Compatibilità stimata: ${formatAdvisorPct(worst.compatibility)} · ` +
                `Confidenza: ${formatAdvisorPct(worst.confidence)} · ` +
                `Distanza: ${formatAdvisorDistance(worst.distance)}`;
            document.getElementById('advisorWorstDesc').textContent = worst.description || 'Nessuna descrizione disponibile.';

            const warnings = advisor?.critical_warnings || [];
            const warningsBox = document.getElementById('strategyAdvisorWarnings');
            if (warningsBox) {
                if (warnings.length > 0) {
                    warningsBox.classList.add('active');
                    warningsBox.innerHTML = `<strong>⚠️ Avvisi CRITICAL:</strong><br>${warnings.join('<br>')}`;
                } else {
                    warningsBox.classList.remove('active');
                    warningsBox.innerHTML = '';
                }
            }

            updateInGameAdvisorChart(
                advisor?.army_profile || {},
                advisor?.modified_profile || {},
                top.ideal_attributes || {},
            );
        }

        function formatAdvisorPct(value) {
            const n = Number(value);
            if (!Number.isFinite(n)) return '--';
            return `${n.toFixed(1)}%`;
        }

        function formatAdvisorDistance(value) {
            const n = Number(value);
            if (!Number.isFinite(n)) return '--';
            return n.toFixed(4);
        }

        function updateInGameAdvisorChart(originalArmy, modifiedArmy, topStrategyIdeal) {
            const canvas = document.getElementById('strategyAdvisorRadarChart');
            if (!canvas || typeof Chart === 'undefined') {
                return;
            }

            const keys = Object.keys(originalArmy || {});
            if (keys.length === 0) {
                return;
            }

            const labels = keys.map(key => ADVISOR_ATTRIBUTE_NAMES[key] || key);
            const originalValues = keys.map(key => Number(originalArmy[key] || 0));
            const modifiedValues = keys.map(key => Number(modifiedArmy[key] || 0));
            const idealValues = keys.map(key => Number(topStrategyIdeal[key] || 0));

            if (inGameAdvisorRadarChart) {
                inGameAdvisorRadarChart.destroy();
            }

            const ctx = canvas.getContext('2d');
            inGameAdvisorRadarChart = new Chart(ctx, {
                type: 'radar',
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'Esercito attuale',
                            data: originalValues,
                            backgroundColor: 'rgba(233, 69, 96, 0.16)',
                            borderColor: '#e94560',
                            pointBackgroundColor: '#e94560',
                            borderWidth: 2,
                            pointRadius: 3,
                            pointHoverRadius: 5,
                        },
                        {
                            label: 'Con modificatori',
                            data: modifiedValues,
                            backgroundColor: 'rgba(102, 126, 234, 0.16)',
                            borderColor: '#667eea',
                            pointBackgroundColor: '#667eea',
                            borderWidth: 2,
                            pointRadius: 3,
                            pointHoverRadius: 5,
                        },
                        {
                            label: 'Strategia stimata ideale',
                            data: idealValues,
                            backgroundColor: 'rgba(22, 163, 74, 0.14)',
                            borderColor: '#16a34a',
                            pointBackgroundColor: '#16a34a',
                            borderDash: [5, 5],
                            borderWidth: 2,
                            pointRadius: 3,
                            pointHoverRadius: 5,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: {
                                font: { size: 11, weight: '600' },
                                padding: 12,
                            },
                        },
                    },
                    scales: {
                        r: {
                            min: 0,
                            max: 1,
                            ticks: {
                                stepSize: 0.2,
                                font: { size: 10 },
                            },
                            pointLabels: {
                                font: { size: 11, weight: '500' },
                            },
                            angleLines: { color: 'rgba(0,0,0,0.1)' },
                            grid: { color: 'rgba(0,0,0,0.05)' },
                        },
                    },
                },
            });
        }

        function renderSkillTree(sessionData) {
            const container = document.getElementById('skillTreePaths');
            if (!container) return;

            const abilitiesState = sessionData?.player?.abilities || {};
            const paths = [...new Set(SKILL_TREE_DEFINITION.map(skill => skill.path))];
            container.innerHTML = paths.map(pathName => {
                const nodes = SKILL_TREE_DEFINITION.filter(skill => skill.path === pathName).map(skill => {
                    const state = abilitiesState[skill.id];
                    const isKnown = Boolean(state);
                    const isUnlocked = Boolean(state?.unlocked);
                    const isResearching = Boolean(state?.researching && !state?.unlocked);
                    const canResearch = isKnown && !isUnlocked && !isResearching;

                    let stateClass = 'locked';
                    let stateText = 'Non disponibile';
                    if (isUnlocked) {
                        stateClass = 'unlocked';
                        stateText = 'Sbloccata';
                    } else if (isResearching) {
                        stateClass = 'researching';
                        stateText = `${state.turns_remaining} turni`;
                    } else if (isKnown) {
                        stateClass = 'locked';
                        stateText = 'Pronta ricerca';
                    }

                    const actionButton = canResearch
                        ? `<button class="skill-action-btn" type="button" onclick="researchAbilityById('${skill.id}')">Avvia ricerca</button>`
                        : `<button class="skill-action-btn" type="button" disabled>${isUnlocked ? 'Attiva' : (isResearching ? 'In ricerca' : 'Bloccata')}</button>`;

                    return `
                        <div class="skill-node ${stateClass}">
                            <h4>${skill.name}</h4>
                            <p>${skill.description}</p>
                            <div class="skill-meta">
                                <span class="skill-state-pill">${stateText}</span>
                                ${actionButton}
                            </div>
                        </div>
                    `;
                }).join('');

                return `
                    <div class="skilltree-path">
                        <h4 class="skilltree-path-title">${pathName}</h4>
                        ${nodes}
                    </div>
                `;
            }).join('');
        }

        async function recruitSelectedUnit() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                document.getElementById('battleStatusHint').textContent = 'Partita terminata: non puoi reclutare nuove unità.';
                return;
            }

            try {
                const unitId = document.getElementById('recruitSelect').value;
                const response = await fetch('http://127.0.0.1:8000/game/recruit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ unit_id: unitId })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nel reclutamento');
                }

                const result = await response.json();
                transientLogLines = [];
                renderBattleState(result.session);
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
            }
        }

        async function applyBattleStrategy() {
            try {
                const strategyId = document.getElementById('strategySelect').value;
                const response = await fetch('http://127.0.0.1:8000/game/set-strategy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ strategy_id: strategyId })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nel cambio strategia');
                }

                const result = await response.json();
                transientLogLines = [];
                renderBattleState(result.session);
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore cambio strategia: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }



        async function applyAiDifficulty() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                document.getElementById('battleStatusHint').textContent = 'Partita terminata: non puoi cambiare difficoltà IA.';
                return;
            }

            try {
                const difficulty = document.getElementById('aiDifficultySelect').value;
                const response = await fetch('http://127.0.0.1:8000/game/set-ai-difficulty', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ difficulty })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nel cambio difficoltà IA');
                }

                const result = await response.json();
                transientLogLines = [];
                renderBattleState(result.session);
                document.getElementById('battleStatusHint').textContent = `Difficoltà IA impostata su ${difficulty.toUpperCase()}.`;
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore cambio difficoltà IA: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function toggleAiKillSwitch() {
            try {
                const response = await fetch('http://127.0.0.1:8000/game/debug/ai-kill-switch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nel toggle kill switch IA');
                }

                const result = await response.json();
                transientLogLines = [];
                renderBattleState(result.session);
                const stateLabel = result.enabled ? 'attivato' : 'disattivato';
                document.getElementById('battleStatusHint').textContent = `DEBUG TEMPORANEO: kill switch IA ${stateLabel}.`;
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore kill switch IA: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function resetBattleSession() {
            await fetch('http://127.0.0.1:8000/game/reset', { method: 'DELETE' });
            transientLogLines = [];
            currentBattleState = null;
            showEmptyState('Partita resettata. Torna al simulatore o ricomincia dallo stesso setup.');
        }

        async function restartFromStoredSetup() {
            const setupRaw = sessionStorage.getItem('warAdvisorBattleSetup');
            if (!setupRaw) {
                showEmptyState();
                return;
            }
            await startBattleFromStoredSetup(JSON.parse(setupRaw));
        }

        function showEmptyState(message = null) {
            document.getElementById('battlePanel').style.display = 'none';
            document.getElementById('emptyState').style.display = 'block';
            if (message) {
                document.querySelector('#emptyState p').textContent = message;
            }
        }

