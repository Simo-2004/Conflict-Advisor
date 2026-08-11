        let currentBattleState = null;
        let transientLogLines = [];
        let recruitableUnits = [];
        let availableStrategies = [];
        let currentLayoutMode = 'split';
        let layoutSplitRatio = 0.7;
        let splitterDragging = false;
        let sidebarCollapsed = false;
        let buildMode = null;   // null | 'garrison' | 'mine' | 'fortify'
        let inGameAdvisorCharts = [];   // un radar per legione, più quello della riserva
        const ADVISOR_ATTRIBUTE_NAMES = {
            U1_attack: 'Attacco',
            U2_defense: 'Difesa',
            U3_mobility: 'Mobilità',
            U4_stealth: 'Furtività',
            U5_discipline: 'Disciplina',
            U6_terrain_adapt: 'Adatt. Terreno',
            U7_range_power: 'Potenza a Distanza',
            U8_support: 'Supporto',
        };
        // L'albero delle abilità non ha più una copia qui: nomi, percorsi,
        // descrizioni, turni, prezzi e prerequisiti arrivano dal catalogo del
        // backend (gamecore/session/abilities.py) dentro `player.abilities`.
        // Due liste da tenere allineate a mano erano già andate fuori sincrono.

        window.addEventListener('DOMContentLoaded', initBattlePage);

        async function initBattlePage() {
            document.addEventListener('keydown', handleKeyboardShortcuts);
            document.addEventListener('click', handleOutsideMenuClick);
            initHintToneObserver();
            initLayoutControls();
            applyLayoutMode();
            applySidebarCollapseState();

            const garrisonSelector = document.getElementById('garrisonUnitSelect');
            if (garrisonSelector) {
                garrisonSelector.addEventListener('change', () => updateGarrisonDefensePreview(currentBattleState));
            }

            const tacticalLegionSelect = document.getElementById('tacticalLegionSelect');
            if (tacticalLegionSelect) {
                tacticalLegionSelect.addEventListener('change', () => {
                    if (!currentBattleState) return;
                    updateBattleStatusModePill(currentBattleState);
                    updateTacticalActionButtons(currentBattleState);
                    renderGarrisonUnitSelector(currentBattleState);
                });
            }

            // Tab strategia: cambiando legione il menu mostra la SUA strategia.
            const strategyLegionSelect = document.getElementById('strategyLegionSelect');
            if (strategyLegionSelect) {
                strategyLegionSelect.addEventListener('change', () => {
                    if (!currentBattleState) return;
                    syncStrategySelectToLegion(currentBattleState);
                });
            }

            const strategySelect = document.getElementById('strategySelect');
            if (strategySelect) {
                strategySelect.addEventListener('change', markStrategySelectDirty);
            }

            const autoRecruitUnitSelect = document.getElementById('autoRecruitUnitSelect');
            const autoRecruitTurnsInput = document.getElementById('autoRecruitTurnsInput');
            if (autoRecruitUnitSelect) {
                autoRecruitUnitSelect.addEventListener('change', () => {
                    // Da qui in poi comanda la scelta dell'utente: il menu non
                    // deve più riproporre l'unità del reclutamento manuale.
                    autoRecruitUnitSelect.dataset.userPicked = '1';
                    renderAutoRecruitForecast();
                });
            }
            if (autoRecruitTurnsInput) {
                autoRecruitTurnsInput.addEventListener('input', () => renderAutoRecruitForecast());
            }

            const setupRaw = sessionStorage.getItem('warAdvisorBattleSetup');
            if (!setupRaw) {
                showEmptyState();
                return;
            }

            try {
                await loadRecruitableUnits();
                await startBattleFromStoredSetup(JSON.parse(setupRaw));
            } catch (error) {
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                document.getElementById('battlePanel').style.display = 'block';
            }
        }

        async function loadRecruitableUnits() {
            const response = await fetch('http://127.0.0.1:8000/config');
            const data = await response.json();
            recruitableUnits = data.units || [];
            availableStrategies = data.strategies || [];
            const select = document.getElementById('recruitSelect');
            select.innerHTML = recruitableUnits
                .map(unit => `<option value="${unit.id}">${unit.name} • ${unit.cost_grux} grux</option>`)
                .join('');

            const autoSelect = document.getElementById('autoRecruitUnitSelect');
            if (autoSelect) {
                autoSelect.innerHTML = recruitableUnits
                    .map(unit => `<option value="${unit.id}">${unit.name} • ${unit.cost_grux} grux</option>`)
                    .join('');
            }

            const strategySelect = document.getElementById('strategySelect');
            strategySelect.innerHTML = availableStrategies
                .map(strategy => `<option value="${strategy.id}">${strategy.name}</option>`)
                .join('');
        }

        async function startBattleFromStoredSetup(setup) {
            await fetch('http://127.0.0.1:8000/game/reset', { method: 'DELETE' });

            const freshSetup = {
                ...setup,
                map_seed: Math.floor(Math.random() * 2147483647)
            };

            const response = await fetch('http://127.0.0.1:8000/game/confirm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(freshSetup)
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Errore nell\'avvio della partita');
            }

            transientLogLines = [];
            const sessionData = await response.json();
            if (sessionData.message) {
                transientLogLines.push(sessionData.message);
            }
            renderBattleState(sessionData);
            document.getElementById('battlePanel').style.display = 'block';
            document.getElementById('emptyState').style.display = 'none';
        }


