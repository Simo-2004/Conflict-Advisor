
        function renderBattleState(sessionData) {
            currentBattleState = sessionData;

            if (sessionData.state === 'game_over') {
                document.getElementById('battleStatusRound').textContent = `Fine partita: ${sessionData.winner}`;
                document.getElementById('battleStatusHint').textContent = 'Il registro mostra il riepilogo completo della battaglia.';
            } else {
                document.getElementById('battleStatusRound').textContent = `Turno ${sessionData.map.turn}`;
                document.getElementById('battleStatusHint').textContent = 'Seleziona una legione e usa Presidio/Miniera/Fortifica, o premi H per i comandi rapidi.';
            }

            renderWeatherPill(sessionData);
            renderTacticalLegionSelect(sessionData);
            updateBattleStatusModePill(sessionData);
            updateTacticalActionButtons(sessionData);
            renderStrategyLegionSelect(sessionData);
            syncStrategySelectToLegion(sessionData);

            const playerLegion = buildLegionInfo(sessionData.player.units || []);
            const aiLegion = buildLegionInfo(sessionData.ai.units || []);
            renderGarrisonUnitSelector(sessionData);
            updateGarrisonDefensePreview(sessionData);

            renderEconomySide('player', sessionData.player, playerLegion,
                sessionData.map.stats.player_mines);
            renderEconomySide('ai', sessionData.ai, aiLegion,
                sessionData.map.stats.ai_mines);

            // Il pulsante riassume TUTTO l'albero, non più la sola Costruzione
            // Territoriale: quante abilità hai e cosa sta uscendo dai laboratori.
            const abilities = sessionData.player?.abilities || {};
            const abilityList = Object.values(abilities);
            const abilityCard = document.getElementById('abilityResearchBtn');
            const abilityLabel = document.getElementById('abilityLabel');
            if (abilityLabel && abilityCard) {
                const total = abilityList.length;
                const unlockedCount = abilityList.filter(item => item.unlocked).length;
                const inProgress = abilityList.find(item => item.researching);

                let statusText = 'Apri per vedere le ricerche';
                if (inProgress) {
                    statusText = `${inProgress.name} · ${inProgress.turns_remaining} turni`;
                } else if (total > 0) {
                    const ready = abilityList.filter(item => item.can_start).length;
                    statusText = ready > 0
                        ? `${unlockedCount}/${total} sbloccate · ${ready} avviabili`
                        : `${unlockedCount}/${total} sbloccate`;
                }
                abilityLabel.textContent = statusText;
                abilityCard.classList.toggle('is-unlocked', unlockedCount > 0 && !inProgress);
                abilityCard.classList.toggle('is-researching', Boolean(inProgress));
            }

            renderBlackMarketButton(sessionData);
            updateRecruitPrices(sessionData);

            // Ricerche e offerte cambiano a ogni turno: se la finestra è aperta
            // deve aggiornarsi da sola, non mostrare lo stato di quando l'hai aperta.
            if (document.getElementById('skillTreeOverlay')?.classList.contains('open')) {
                renderSkillTree(sessionData);
            }
            if (document.getElementById('blackMarketOverlay')?.classList.contains('open')) {
                renderBlackMarket(sessionData);
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

            // Il menu strategia NON viene più forzato sulla strategia globale:
            // ogni legione ha la sua, e ci pensa `syncStrategySelectToLegion`.
            // Questa riga è ciò che riportava la selezione ad Assalto Frontale
            // a ogni render, subito dopo averla cambiata.
            const strategyInfoBtn = document.getElementById('strategyInfoBtn');
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
                    // Se il piano è in pausa il motivo va detto qui: il giocatore
                    // vedeva solo il bottone acceso senza capire perché non compra.
                    const motivo = autoRecruitState.last_result === 'skipped' && autoRecruitState.last_reason
                        ? ` — in pausa: ${autoRecruitState.last_reason}`
                        : '';
                    autoRecruitBtn.title =
                        `${autoRecruitState.unit_name} (${autoRecruitState.turns_remaining} turni rimanenti)${motivo}`;
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
                return { totalUnits: 0, totalTypes: 0, composition: [] };
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

            return {
                totalUnits: unitIds.length,
                totalTypes: sorted.length,
                composition: sorted.map(([name, count]) => ({ name, count })),
            };
        }

        // Pannello "Economia e Presidi", un lato per volta.
        //
        // Le fortificazioni non stanno più qui: si contano a occhio sulla mappa,
        // e la riga "N livelli su M celle" era la meno guardata delle cinque.
        // Quello che resta è ridotto all'osso: quanti soldi hai, cosa puoi
        // costruire ancora, e chi hai in campo.
        function renderEconomySide(prefix, side, legion, mines) {
            const set = (id, text, title) => {
                const el = document.getElementById(prefix + id);
                if (!el) return;
                el.textContent = text;
                if (title !== undefined) el.title = title;
            };

            const grux = Number.isFinite(side.grux_balance) ? side.grux_balance : 0;
            set('GruxValue', grux.toLocaleString('it-IT'),
                `Speso finora in truppe: ${formatGrux(side.army_cost)}`);
            // Il nome lungo viene tagliato con i puntini: nel `title` resta intero.
            const strategia = side.strategy_name || side.strategy_id || '—';
            set('StrategyTag', strategia, strategia);

            const slot = side.available_mine_slots;
            set('MinesInfo', `⛏ ${mines}${slot ? ` · +${slot}` : ''}`,
                `Miniere attive: ${mines} · Slot ancora liberi: ${slot}`);
            set('ReserveInfo', `🛡 ${side.available_garrisons}`,
                `Guarnigioni disponibili: ${side.available_garrisons}`);

            // Condizione per esteso nel tooltip: in riga sta l'etichetta, che è
            // la parte su cui si decide qualcosa.
            const status = side.troop_status || 'N/D';
            set('LegionSummary',
                legion.totalUnits ? `${legion.totalUnits} unità · ${status}` : 'Nessuna unità in campo',
                describeTroopCondition(side));

            const chips = document.getElementById(prefix + 'LegionComposition');
            if (chips) {
                chips.replaceChildren(...legion.composition.map(({ name, count }) => {
                    const chip = document.createElement('span');
                    chip.className = 'economy-chip';
                    chip.title = `${name}: ${count}`;
                    const n = document.createElement('b');
                    n.textContent = count;
                    chip.append(n, ' ', name);
                    return chip;
                }));
            }
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

        /** Indicatore ambientale accanto al contatore turni.
         *  Colori e emoji arrivano dal backend: la UI non decide la semantica,
         *  la mostra e basta. Se il payload non li porta la pastiglia resta
         *  nascosta, così una risposta vecchia non rompe la barra di stato. */
        function renderWeatherPill(sessionData) {
            const pill = document.getElementById('battleStatusWeather');
            if (!pill) return;

            const meteo = sessionData?.weather_state;
            if (!meteo) {
                pill.hidden = true;
                return;
            }

            pill.hidden = false;
            pill.textContent = `${meteo.emoji} ${meteo.label}`;
            pill.style.color = meteo.color;
            pill.style.background = meteo.background;
            pill.style.borderColor = meteo.border;
            pill.classList.toggle('is-night', Boolean(meteo.is_night));

            // Nel tooltip anche l'effetto in numeri sulle singole truppe: è la
            // stessa tabella che il motore applica in battaglia, così si può
            // decidere quale legione muovere senza tirare a indovinare.
            const righe = [(meteo.effects || []).join(' · ')];
            const truppe = meteo.unit_effects || [];
            if (truppe.length) {
                righe.push('');
                righe.push('Effetto sulle truppe:');
                for (const riga of truppe) {
                    const segno = riga.percent > 0 ? '+' : '';
                    righe.push(`  ${riga.unit_name}: ${segno}${riga.percent}%`);
                }
            }
            righe.push('');
            righe.push(`Condizioni successive fra ${meteo.changes_in} turni`);
            pill.title = righe.join('\n');
        }

        /** Riepilogo leggibile della condizione delle truppe in riserva.
         *  Il backend valorizza sempre lo stato: "N/D" resta solo se il
         *  payload arriva monco. */
        function describeTroopCondition(side) {
            const status = side?.troop_status || 'N/D';
            const cond = side?.troop_condition;
            if (!cond) return status;
            return `${status} (fatica ${Math.round(cond.fatigue)}, morale ${Math.round(cond.morale)})`;
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
            // La posizione nell'etichetta serve a distinguere due legioni che
            // stanno sulla stessa cella: senza, la scelta è alla cieca.
            selector.innerHTML = legions.map((legion) => {
                const typeLabel = TACTICAL_LEGION_TYPE_LABELS[legion.legion_type] || 'Esercito';
                const pos = (legion.pos || []).length === 2 ? ` · ${legion.pos[0]},${legion.pos[1]}` : '';
                const truppe = (legion.units || []).length;
                return `<option value="${legion.id}">${legion.name} (${typeLabel}) — ${truppe} truppe${pos}</option>`;
            }).join('');

            if (previousValue && legions.some((legion) => legion.id === previousValue)) {
                selector.value = previousValue;
            }

            updateGarrisonCardBadge(sessionData);
        }

        /** Dove finirà il presidio, e cosa c'è già su quella cella.
         *
         *  Il presidio si lascia sotto i piedi della legione, quindi la cella
         *  è già decisa quando scegli la legione: mostrarla qui evita di
         *  scoprirlo solo dopo aver cliccato sulla mappa.
         */
        function updateGarrisonCardBadge(sessionData) {
            const badge = document.getElementById('garrisonCardBadge');
            if (!badge) return;

            const state = sessionData || currentBattleState;
            const legion = getSelectedTacticalLegion(state);
            const pos = legion ? (legion.pos || []) : [];
            if (pos.length !== 2) {
                badge.textContent = '';
                return;
            }

            const cell = state?.map?.grid?.[pos[0]]?.[pos[1]];
            const presidi = Number(cell?.garrison_strength || 0);
            const dettaglio = presidi > 0
                ? ` · ${presidi} presidi${presidi === 1 ? 'o' : ''} già qui`
                : '';
            badge.textContent = `cella ${pos[0]},${pos[1]}${dettaglio}`;
        }

        /** Valore "generale": nessuna legione, si tocca la strategia di sessione. */
        const STRATEGY_SCOPE_GENERAL = '';

        function getStrategyTargetLegionId() {
            const selector = document.getElementById('strategyLegionSelect');
            return selector && selector.value ? selector.value : null;
        }

        function getStrategyTargetLegion(sessionData) {
            const legionId = getStrategyTargetLegionId();
            if (!legionId) return null;
            return (sessionData?.player?.legions || {})[legionId] || null;
        }

        /** Popola il selettore legioni della tab strategia.
         *  Ricostruisce le opzioni ma conserva la selezione: rigenerarla
         *  senza riassegnare il valore la farebbe tornare alla prima voce. */
        function renderStrategyLegionSelect(sessionData) {
            const selector = document.getElementById('strategyLegionSelect');
            if (!selector) return;

            const legions = Object.values(sessionData?.player?.legions || {});
            const previousValue = selector.value;

            const options = [
                `<option value="${STRATEGY_SCOPE_GENERAL}">Generale (riserva e nuove legioni)</option>`,
                ...legions.map((legion) => {
                    const typeLabel = TACTICAL_LEGION_TYPE_LABELS[legion.legion_type] || 'Esercito';
                    const strategyLabel = legion.strategy_name ? ` — ${legion.strategy_name}` : '';
                    return `<option value="${legion.id}">${legion.name} (${typeLabel})${strategyLabel}</option>`;
                }),
            ];
            selector.innerHTML = options.join('');
            selector.disabled = sessionData.state === 'game_over';

            const stillThere = previousValue === STRATEGY_SCOPE_GENERAL
                || legions.some((legion) => legion.id === previousValue);
            selector.value = stillThere ? previousValue : STRATEGY_SCOPE_GENERAL;
        }

        /** Allinea il menu strategia a quella della legione scelta.
         *  Ogni legione ha la sua: senza questo il menu mostrerebbe sempre
         *  l'ultima scelta invece di ciò che quella legione sta davvero usando. */
        function syncStrategySelectToLegion(sessionData) {
            const strategySelect = document.getElementById('strategySelect');
            if (!strategySelect || !strategySelect.options.length) return;

            const legion = getStrategyTargetLegion(sessionData);
            const strategyId = legion
                ? legion.strategy_id
                : sessionData?.player?.strategy_id;
            if (!strategyId) return;

            if ([...strategySelect.options].some((opt) => opt.value === strategyId)) {
                strategySelect.value = strategyId;
            }

            // Evidenzia il menu quando mostra la strategia realmente in uso:
            // così si distingue a colpo d'occhio "questa è attiva" da
            // "sto scegliendo qualcosa che non ho ancora applicato".
            strategySelect.classList.add('strategy-select-active');
            strategySelect.dataset.activeStrategy = strategyId;

            const label = document.getElementById('strategyScopeHint');
            if (label) {
                const nome = legion ? `'${legion.name}'` : 'Generale';
                const attiva = legion ? legion.strategy_name : sessionData?.player?.strategy_name;
                label.textContent = `${nome} — in uso: ${attiva || '---'}`;
            }
        }

        /** Toglie l'evidenziazione appena l'utente sceglie una voce diversa
         *  da quella attiva: il menu smette di dire "questa è la strategia in
         *  uso" e torna a dire "questa è la strategia che stai per applicare". */
        function markStrategySelectDirty() {
            const strategySelect = document.getElementById('strategySelect');
            if (!strategySelect) return;
            const active = strategySelect.dataset.activeStrategy;
            strategySelect.classList.toggle('strategy-select-active', strategySelect.value === active);
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
            const legions = Object.values(sessionData?.player?.legions || {});

            // Un'azione è disponibile se esiste ALMENO UNA legione idonea in campo,
            // non se lo è quella nel menu a tendina: quale usare lo decide il click
            // sulla cella, quindi legarlo alla selezione bloccava azioni possibili.
            // Con Costruzione Caotica il ruolo non conta più: basta avere una
            // legione in campo. Senza questo il tasto restava spento e
            // l'abilità sembrava non fare niente.
            const anyLegion = Boolean(sessionData?.player?.build_rules?.any_legion);
            const hasAnyLegion = legions.some((lg) => (lg.pos || []).length === 2);

            const hasGarrisonable = legions.some((lg) => (lg.units || []).length >= 2);
            const hasMining = anyLegion ? hasAnyLegion : legions.some((lg) => lg.legion_type === 'mining');
            const hasConstruction = anyLegion ? hasAnyLegion : legions.some((lg) => lg.legion_type === 'construction');

            const buttons = [
                ['actionGarrisonBtn', hasGarrisonable, 'garrison'],
                ['actionMineBtn', hasMining, 'mine'],
                ['actionFortifyBtn', hasConstruction, 'fortify'],
            ];

            for (const [id, available, mode] of buttons) {
                const btn = document.getElementById(id);
                if (!btn) continue;
                btn.disabled = gameOver || !available;
                btn.classList.toggle('action-btn-armed', buildMode === mode);
            }
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

            // In modalità puntamento la mappa torna cliccabile: le celle con una
            // legione idonea all'azione vengono evidenziate.
            const buildConfig = typeof getBuildModeConfig === 'function' ? getBuildModeConfig() : null;
            const eligibleCells = buildConfig ? getEligibleBuildCells(currentBattleState) : new Map();

            mapData.grid.forEach((row, rowIndex) => {
                row.forEach((cell, colIndex) => {
                    const button = document.createElement('button');
                    button.className = `map-cell ${terrainClass(cell.terrain)}`;
                    button.type = 'button';
                    button.dataset.row = String(rowIndex);
                    button.dataset.col = String(colIndex);
                    button.title = `${cell.terrain} (${rowIndex}, ${colIndex})`;
                    button.disabled = !buildConfig;

                    if (buildConfig) {
                        button.classList.add('cell-build-target');
                        const eligibleLegion = eligibleCells.get(`${rowIndex},${colIndex}`);
                        if (eligibleLegion) {
                            button.classList.add('cell-build-ready');
                            button.title =
                                `${buildConfig.icon} ${buildConfig.label} con '${eligibleLegion.name}' — ${cell.terrain} (${rowIndex}, ${colIndex})`;
                        }
                        button.onclick = () => handleBuildCellClick(rowIndex, colIndex);
                    }

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

