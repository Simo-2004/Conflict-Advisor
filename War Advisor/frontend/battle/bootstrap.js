        let currentBattleState = null;
        let transientLogLines = [];
        let recruitableUnits = [];
        let availableStrategies = [];
        let currentAction = 'move';
        let currentLayoutMode = 'split';
        let layoutSplitRatio = 0.7;
        let splitterDragging = false;
        let inGameAdvisorRadarChart = null;
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
        const SKILL_TREE_DEFINITION = [
            { id: 'domain_engineering', name: 'Costruzione Territoriale', path: 'Ingegneria', description: 'Costruisci ovunque nel dominio controllato.', turnsRequired: 40 },
            { id: 'fortress_doctrine', name: 'Dottrina Fortezza', path: 'Ingegneria', description: 'Placeholder abilità futura.', turnsRequired: 26 },
            { id: 'rapid_entrenchment', name: 'Trinceramento Rapido', path: 'Ingegneria', description: 'Placeholder abilità futura.', turnsRequired: 18 },
            { id: 'supply_lines', name: 'Linee di Rifornimento', path: 'Economia', description: 'Placeholder abilità futura.', turnsRequired: 20 },
            { id: 'war_industry', name: 'Industria Bellica', path: 'Economia', description: 'Placeholder abilità futura.', turnsRequired: 28 },
            { id: 'black_market', name: 'Mercato Nero', path: 'Economia', description: 'Placeholder abilità futura.', turnsRequired: 24 },
            { id: 'adaptive_command', name: 'Comando Adattivo', path: 'Tattica', description: 'Placeholder abilità futura.', turnsRequired: 16 },
            { id: 'counter_mobility', name: 'Contro-Manovra', path: 'Tattica', description: 'Placeholder abilità futura.', turnsRequired: 22 },
            { id: 'deep_recon', name: 'Ricognizione Profonda', path: 'Tattica', description: 'Placeholder abilità futura.', turnsRequired: 14 },
            { id: 'combined_arms', name: 'Armi Combinate', path: 'Tattica', description: 'Placeholder abilità futura.', turnsRequired: 30 },
        ];

        window.addEventListener('DOMContentLoaded', initBattlePage);

        async function initBattlePage() {
            setAction('move');
            document.addEventListener('keydown', handleKeyboardShortcuts);
            document.addEventListener('click', handleOutsideMenuClick);
            initHintToneObserver();
            initLayoutControls();
            applyLayoutMode();

            const garrisonSelector = document.getElementById('garrisonUnitSelect');
            if (garrisonSelector) {
                garrisonSelector.addEventListener('change', () => updateGarrisonDefensePreview());
            }

            const autoRecruitUnitSelect = document.getElementById('autoRecruitUnitSelect');
            const autoRecruitTurnsInput = document.getElementById('autoRecruitTurnsInput');
            if (autoRecruitUnitSelect) {
                autoRecruitUnitSelect.addEventListener('change', () => renderAutoRecruitForecast());
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


