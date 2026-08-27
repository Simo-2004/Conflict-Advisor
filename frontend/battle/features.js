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
                segnalaErrore(error.message);
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

        const AUTO_RECRUIT_DEFAULT_TURNS = 6;

        function handleAutoRecruitButton() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                segnalaErrore('Partita terminata: autoreclutamento non disponibile.');
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

            if (autoSelect && autoSelect.options.length > 0) {
                // Solo un piano ATTIVO detta l'unità: un piano concluso lascia
                // `unit_id` valorizzato nel payload, e riproporlo qui cancellava
                // in silenzio la scelta appena fatta dal giocatore.
                if (autoRecruitState?.enabled && autoRecruitState.unit_id) {
                    autoSelect.value = autoRecruitState.unit_id;
                } else if (!autoSelect.dataset.userPicked && recruitSelect && recruitSelect.value) {
                    // Comodità solo alla prima apertura: dopo comanda l'utente.
                    autoSelect.value = recruitSelect.value;
                }
            }

            if (turnsInput) {
                // `turns_remaining` è 0 quando nessun piano è in corso: usarlo
                // faceva partire ogni piano da 1 solo turno.
                const remaining = Number(autoRecruitState?.turns_remaining) || 0;
                const lastUsed = Number(turnsInput.dataset.lastUsed) || 0;
                const defaultTurns = autoRecruitState?.enabled && remaining > 0
                    ? remaining
                    : (lastUsed > 0 ? lastUsed : AUTO_RECRUIT_DEFAULT_TURNS);
                turnsInput.value = String(Math.max(1, Math.min(40, defaultTurns)));
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

        // La riserva sta al castello, quindi il terreno è quello della sua
        // cella. Prima si leggeva la posizione dell'armata unica, che non
        // esiste più: la funzione cadeva sempre sul default 'Pianura', ed è
        // esattamente quello che risponde anche adesso, visto che la cella del
        // castello viene forzata a Pianura alla generazione della mappa.
        // NOTA: il backend usa invece il terreno scelto allo schieramento
        // (`player_home_terrain`) per l'advisor della riserva. I due numeri
        // possono quindi divergere: non è una regressione, era già così.
        function getPlayerCurrentTerrainName() {
            const mapData = currentBattleState?.map;
            const castello = mapData?.castles?.player;
            if (!mapData || !Array.isArray(castello)) return 'Pianura';
            const [row, col] = castello;
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

            /* [ABILITY-EFFECTS] Con l'Industria dello Spionaggio il quartiermastro
               smette di andare a occhio: cooldown vero al posto della stima a due
               turni, prezzo vero delle reclute, e il piano si ferma davvero dove
               finiscono i grux invece di proseguire in una fascia di incertezza. */
            const accurate = Boolean(currentBattleState?.player?.intel?.accurate);
            const cooldown = Math.max(1, Number(currentBattleState?.player?.recruit_cooldown_turns) || 2);
            const prezzo = Number(currentBattleState?.player?.recruit_costs?.[selectedUnitId]) || 0;
            const casse = Number(currentBattleState?.player?.grux_balance) || 0;
            const recluteFinanziabili = prezzo > 0 ? Math.floor(casse / prezzo) : Infinity;

            const values = [];
            let recluteFinali = 0;
            for (let i = 0; i < turns; i += 1) {
                const previste = accurate
                    ? Math.min(Math.floor(i / cooldown) + 1, recluteFinanziabili)
                    : Math.floor((i + 2) / 2);   // approssima cooldown a 2 turni
                recluteFinali = previste;
                // Il fattore 0.95 era lo sconto per l'imprecisione: senza
                // imprecisione non ha più niente da scontare.
                const expected = currentPotential + (previste * unitPotential * (accurate ? 1 : 0.95));
                const uncertainty = accurate ? 0 : Math.max(0.14, 0.36 - (i * 0.02));
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

            // Con i dati esatti la fascia di incertezza sparisce: disegnarla a
            // spessore zero lascerebbe un filo scuro che sembra un secondo dato.
            const uncertaintyLayer = accurate
                ? ''
                : (values.length > 1
                    ? `<polygon points="${areaPoints}" fill="rgba(56, 189, 248, 0.22)"></polygon>`
                    : `<line x1="${startX}" y1="${yForValue(values[0].max)}" x2="${startX}" y2="${yForValue(values[0].min)}" stroke="rgba(56, 189, 248, 0.8)" stroke-width="3" stroke-linecap="round"></line>`);
            const trendLayer = values.length > 1
                ? `<polyline points="${expectedPoints}" fill="none" stroke="${accurate ? '#7c3aed' : '#0369a1'}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"></polyline>`
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

            if (accurate) {
                const grezze = Math.floor((turns - 1) / cooldown) + 1;
                const costo = recluteFinali * prezzo;
                const pezzi = [
                    `Unità: ${unitName}`,
                    `Durata: ${turns} turni`,
                    `Terreno: ${terrainName}`,
                    `Reclute: ${recluteFinali} (una ogni ${cooldown} turn${cooldown === 1 ? 'o' : 'i'})`,
                    `Costo: ${costo.toLocaleString('it-IT')} grux su ${casse.toLocaleString('it-IT')}`,
                ];
                if (recluteFinali < grezze) {
                    // Il piano non brucia più i turni quando le casse sono vuote:
                    // si mette in attesa degli incassi, quindi le reclute oltre
                    // il budget attuale arrivano più tardi, non è che spariscano.
                    pezzi.push(`⚠ con le casse di adesso ne finanzi ${recluteFinali} sulle ${grezze}: ` +
                               `per le altre il piano aspetta gli incassi`);
                }
                pezzi.push(`Potenziale proiettato: ${Math.round(finalExpected)}`);
                summary.textContent = pezzi.join(' · ');
                summary.classList.add('is-esatta');
            } else {
                const firstUncertainty = values[0] ? ((values[0].max - values[0].min) / Math.max(1, values[0].expected)) * 100 : 0;
                summary.textContent =
                    `Unità: ${unitName} · Durata: ${turns} turni · Terreno attuale: ${terrainName} · ` +
                    `Potenziale stimato finale: ${Math.round(finalExpected)} · Incertezza iniziale ±${Math.round(firstUncertainty / 2)}% (stima preliminare)`;
                summary.classList.remove('is-esatta');
            }
        }

        async function startAutoRecruitFromMenu() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                segnalaErrore('Partita terminata: autoreclutamento non disponibile.');
                document.getElementById('battleStatusHint').textContent = 'Partita terminata: autoreclutamento non disponibile.';
                return;
            }

            try {
                const unitSelect = document.getElementById('autoRecruitUnitSelect');
                const unitId = unitSelect.value;
                const turns = getAutoRecruitTurnsValue();
                if (!unitId) {
                    throw new Error('Seleziona un\'unità da autoreclutare.');
                }
                // Ricorda la durata scelta: alla prossima apertura si riparte da qui.
                const turnsInput = document.getElementById('autoRecruitTurnsInput');
                if (turnsInput) turnsInput.dataset.lastUsed = String(turns);

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
                segnalaErrore(error.message);
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
                segnalaErrore(error.message);
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore stop autoreclutamento: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }

        async function openInGameAdvisorMenu() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                segnalaErrore('Partita terminata: advisor non disponibile.');
                document.getElementById('battleStatusHint').textContent = 'Partita terminata: advisor non disponibile.';
                return;
            }

            const overlay = document.getElementById('strategyAdvisorOverlay');
            const body = document.getElementById('strategyAdvisorBody');
            if (body) {
                body.innerHTML = '<div class="strategy-advisor-note">Raccolta dati tattici in corso...</div>';
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
                if (body) {
                    body.innerHTML = `<div class="strategy-advisor-note">Errore advisor: ${error.message}</div>`;
                }
                segnalaErrore(error.message);
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

        function escapeAdvisorText(value) {
            return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
            }[ch]));
        }

        // Con l'Industria dello Spionaggio i numeri sono quelli veri, quindi
        // cambiano anche le parole: niente più "stimata", niente "confidenza"
        // (che a rumore azzerato varrebbe sempre quanto la compatibilità).
        function advisorCardHtml(cssClass, label, strategy, accurate) {
            const s = strategy || {};
            const pastiglie = accurate
                ? `<span class="advisor-stat is-forte">${formatAdvisorPct(s.compatibility)}</span>
                   <span class="advisor-stat">scarto ${formatAdvisorDistance(s.distance)}</span>`
                : `<span class="advisor-stat is-forte">~${formatAdvisorPct(s.compatibility)}</span>
                   <span class="advisor-stat">confidenza ${formatAdvisorPct(s.confidence)}</span>`;
            return `
                <div class="advisor-card ${cssClass}">
                    <div class="advisor-card-label">${label}</div>
                    <h4>${escapeAdvisorText(s.name || '---')}</h4>
                    <div class="advisor-card-stats">${pastiglie}</div>
                    <p>${escapeAdvisorText(s.description || 'Nessuna descrizione disponibile.')}</p>
                </div>`;
        }

        /** Un blocco advisor: stesso contenuto di sempre, ora ripetuto per ogni legione. */
        function advisorSectionHtml(report, chartId, weatherLabel, troopStatusLabel, accurate) {
            const top = report?.top_strategy || {};
            const second = report?.second_strategy || top;
            const worst = report?.worst_strategy || top;
            const reliability = report?.reliability || {};
            const isLegion = report?.scope === 'legion';

            const titolo = isLegion
                ? `⚔ ${escapeAdvisorText(report.legion_name)}`
                : `🏰 ${escapeAdvisorText(report.legion_name || 'Riserva nel castello')}`;

            // Lo stato truppe è quello DI QUESTA legione, non più uno globale.
            const statoTruppe = report.troop_status_name || troopStatusLabel;
            const cond = report.troop_condition || null;

            const dettagli = [];
            if (isLegion && report.legion_type_label) dettagli.push(escapeAdvisorText(report.legion_type_label));
            if (report.units_count != null) dettagli.push(`${report.units_count} truppe`);
            if (isLegion && report.pos) dettagli.push(`posizione (${report.pos[0]},${report.pos[1]})`);
            dettagli.push(`terreno ${escapeAdvisorText(report.terrain_name || 'N/D')}`);
            if (report.current_strength != null) dettagli.push(`forza ${report.current_strength}`);
            if (cond) dettagli.push(`fatica ${cond.fatigue} · morale ${cond.morale}`);

            const attiva = report.current_strategy_name
                ? `<span class="advisor-current-strategy">In uso: ${escapeAdvisorText(report.current_strategy_name)}</span>`
                : '';
            const badgeStato = statoTruppe
                ? `<span class="advisor-troop-status status-${escapeAdvisorText(statoTruppe)}">${escapeAdvisorText(statoTruppe)}</span>`
                : '';

            if (report?.empty) {
                return `
                    <section class="advisor-section">
                        <header class="advisor-section-head">
                            <h4>${titolo} ${badgeStato}</h4>
                            <p>${dettagli.join(' · ')}</p>
                        </header>
                        <div class="strategy-advisor-note">
                            ${isLegion
                                ? 'Legione senza truppe: nessuna valutazione tattica possibile.'
                                : 'Riserva vuota: tutte le truppe sono in campo, qui non c\'è niente da valutare.'}
                        </div>
                    </section>`;
            }

            const warnings = report?.critical_warnings || [];
            const warningsHtml = warnings.length > 0
                ? `<div class="strategy-advisor-warnings active">
                       <strong>⚠️ Avvisi CRITICAL:</strong><br>${warnings.map(escapeAdvisorText).join('<br>')}
                   </div>`
                : '';

            return `
                <section class="advisor-section">
                    <header class="advisor-section-head">
                        <h4>${titolo} ${attiva} ${badgeStato}</h4>
                        <p>${dettagli.join(' · ')} · Meteo ${escapeAdvisorText(weatherLabel)}</p>
                    </header>
                    ${affidabilitaHtml(reliability, accurate)}
                    <div class="strategy-advisor-cards">
                        ${advisorCardHtml('best', 'Consigliata ora', top, accurate)}
                        ${advisorCardHtml('alt', 'Alternativa', second, accurate)}
                        ${advisorCardHtml('worst', 'Sconsigliata', worst, accurate)}
                    </div>
                    <div class="strategy-advisor-chart-wrap">
                        <canvas id="${chartId}"></canvas>
                    </div>
                    ${warningsHtml}
                </section>`;
        }

        /* Con i dati esatti l'avviso di inaccuratezza non ha più senso e
           sparisce: al suo posto una riga verde che dice da dove arrivano i
           numeri. Senza l'abilità resta tutto com'era. */
        function affidabilitaHtml(reliability, accurate) {
            if (accurate) {
                return `
                    <div class="strategy-advisor-reliability is-esatta">
                        <span class="advisor-sigillo">🕯</span>
                        Rilevamento diretto · dati esatti
                        <span class="advisor-fonte">rete di informatori attiva</span>
                    </div>`;
            }
            return `
                <div class="strategy-advisor-reliability">
                    Affidabilità report: ${reliability.score_pct ?? '--'}% ·
                    Incertezza: ${reliability.uncertainty_pct ?? '--'}%
                    (${escapeAdvisorText(reliability.label || 'stima in-battle')})
                </div>
                <div class="strategy-advisor-note">
                    ${escapeAdvisorText(reliability.note || 'Analisi tattica preliminare.')}
                </div>`;
        }

        function renderInGameAdvisor(advisor) {
            const body = document.getElementById('strategyAdvisorBody');
            if (!body) return;

            const weatherLabel = advisor?.weather_name || 'Nessuno';
            const troopStatusLabel = advisor?.troop_status_name || 'N/D';

            const meta = document.getElementById('strategyAdvisorMeta');
            const legioni = advisor?.legions || [];
            if (meta) {
                meta.textContent =
                    `Turno ${advisor?.turn || '?'} · Meteo: ${weatherLabel} · ` +
                    `Stato truppe: ${troopStatusLabel} · ` +
                    `${legioni.length} legion${legioni.length === 1 ? 'e' : 'i'} in campo`;
            }

            const accurate = Boolean(currentBattleState?.player?.intel?.accurate);

            // Riserva prima, poi una sezione per legione nell'ordine in cui esistono.
            const reports = [advisor, ...legioni];
            body.innerHTML = spiaHtml(accurate) + reports
                .map((report, index) => advisorSectionHtml(
                    report, `advisorRadar_${index}`, weatherLabel, troopStatusLabel, accurate,
                ))
                .join('');

            // I grafici vanno ricreati dopo che i canvas sono nel DOM.
            destroyInGameAdvisorCharts();
            reports.forEach((report, index) => {
                if (report?.empty) return;
                updateInGameAdvisorChart(
                    `advisorRadar_${index}`,
                    report?.army_profile || {},
                    report?.modified_profile || {},
                    (report?.top_strategy || {}).ideal_attributes || {},
                );
            });

            body.scrollTop = 0;
        }

        /* ── Dossier sul nemico ──────────────────────────────────────
           Compare solo con l'Industria dello Spionaggio, e solo su richiesta:
           il tasto sta qui e non nel pannello laterale perché quello che
           racconta è la stessa cosa che l'advisor dice di te, vista dall'altra
           parte del campo. */

        function spiaHtml(accurate) {
            if (!accurate) return '';
            return `
                <div class="advisor-spia" id="advisorSpia">
                    <button class="advisor-spia-btn" type="button" onclick="openEnemyDossier()">
                        <span class="advisor-spia-icona">🕯</span>
                        <span class="advisor-spia-testo">
                            <b>Dossier sul nemico</b>
                            <em>quello che nessuno dovrebbe sapere</em>
                        </span>
                        <span class="advisor-spia-freccia">▸</span>
                    </button>
                </div>`;
        }

        async function openEnemyDossier() {
            const box = document.getElementById('advisorSpia');
            if (!box) return;
            box.innerHTML = '<div class="advisor-dossier-attesa">Gli informatori stanno parlando…</div>';

            try {
                const response = await fetch('http://127.0.0.1:8000/game/enemy-intel');
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore recupero dossier');
                }
                const intel = await response.json();
                if (!intel.available) {
                    box.innerHTML = `<div class="advisor-dossier-attesa">
                        Serve la ricerca «${escapeAdvisorText(intel.required_ability || 'Industria dello Spionaggio')}».
                    </div>`;
                    return;
                }
                box.innerHTML = dossierHtml(intel);
            } catch (error) {
                box.innerHTML = `<div class="advisor-dossier-attesa">Dossier non disponibile: ${escapeAdvisorText(error.message)}</div>`;
            }
        }

        function dossierRigaHtml(etichetta, valore) {
            return `
                <div class="advisor-dossier-riga">
                    <span class="advisor-dossier-etichetta">${etichetta}</span>
                    <span class="advisor-dossier-valore">${valore}</span>
                </div>`;
        }

        function dossierHtml(intel) {
            const s = intel.strategy || {};
            const best = intel.best || {};
            // La riga "non reggerebbe" c'era e non c'è più: diceva qual è la
            // strategia peggiore PER L'IA, e si leggeva come un consiglio su
            // cosa usare contro di lei. Il backend continua a mandare il dato,
            // che resta buono per chi lo sa interpretare.
            const army = intel.army || {};
            const ric = intel.research || {};

            // Se sta usando la sua strategia migliore non c'è niente da
            // sfruttare; se non lo fa, è esattamente il buco da cercare.
            const sceltaBuona = s.rank === 1;
            const giudizio = s.rank
                ? `${sceltaBuona ? 'la sua scelta migliore' : `solo ${s.rank}ª su ${s.out_of}`}`
                : '—';

            const debolezze = (intel.weaknesses || []).length
                ? `<div class="advisor-dossier-falla">
                       <b>Falle rilevate</b><br>${intel.weaknesses.map(escapeAdvisorText).join('<br>')}
                   </div>`
                : '';

            const ricerche = [];
            if (ric.in_progress) {
                ricerche.push(`in corso: <b>${escapeAdvisorText(ric.in_progress.name)}</b> fra ${ric.in_progress.turns_remaining} turni`);
            }
            if (ric.next_planned) {
                ricerche.push(`poi punta a <b>${escapeAdvisorText(ric.next_planned)}</b>`);
            }
            if ((ric.unlocked || []).length) {
                ricerche.push(`già in mano: ${ric.unlocked.map(escapeAdvisorText).join(', ')}`);
            }

            return `
                <div class="advisor-dossier">
                    <div class="advisor-dossier-testa">
                        <span class="advisor-dossier-sigillo">🕯</span>
                        <div>
                            <h4>Dossier sul nemico</h4>
                            <p>Turno ${intel.turn} · difficoltà ${escapeAdvisorText(intel.difficulty || '?')}</p>
                        </div>
                    </div>
                    <div class="advisor-dossier-corpo">
                        ${dossierRigaHtml('Sta usando',
                            `<b>${escapeAdvisorText(s.name || '—')}</b>
                             <span class="advisor-dossier-nota ${sceltaBuona ? '' : 'is-falla'}">${giudizio}</span>`)}
                        ${dossierRigaHtml('Compatibilità reale',
                            s.compatibility != null ? `${s.compatibility}%` : '—')}
                        ${dossierRigaHtml('Gli servirebbe',
                            `${escapeAdvisorText(best.name || '—')} · ${formatAdvisorPct(best.compatibility)}`)}
                        ${dossierRigaHtml('In campo',
                            `${army.units_count} unità · forza ${army.strength} · ${escapeAdvisorText(army.terrain_name || '—')}`)}
                        ${dossierRigaHtml('Composizione', escapeAdvisorText(army.composition || '—'))}
                        ${army.in_marcia
                            ? dossierRigaHtml('In arrivo', `${army.in_marcia} unità ancora per strada`)
                            : ''}
                        ${ricerche.length
                            ? dossierRigaHtml('Laboratori', ricerche.join(' · '))
                            : ''}
                    </div>
                    ${debolezze}
                </div>`;
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

        /** Distrugge i radar aperti: con una sezione per legione sono più d'uno. */
        function destroyInGameAdvisorCharts() {
            for (const chart of inGameAdvisorCharts) {
                try { chart.destroy(); } catch (_) { /* già smontato */ }
            }
            inGameAdvisorCharts = [];
        }

        function updateInGameAdvisorChart(canvasId, originalArmy, modifiedArmy, topStrategyIdeal) {
            const canvas = document.getElementById(canvasId);
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

            const ctx = canvas.getContext('2d');
            const chart = new Chart(ctx, {
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
            inGameAdvisorCharts.push(chart);
        }

        function renderSkillTree(sessionData) {
            const container = document.getElementById('skillTreePaths');
            if (!container) return;

            // L'albero si disegna dal catalogo del backend: nomi, percorsi,
            // prezzi, prerequisiti ed esclusività vivono in un posto solo
            // (gamecore/session/abilities.py). Aggiungere un'abilità là la fa
            // comparire qui senza toccare il frontend.
            const abilities = Object.values(sessionData?.player?.abilities || {});
            const paths = sessionData?.player?.ability_paths
                || [...new Set(abilities.map(item => item.path))];
            const grux = Number(sessionData?.player?.grux_balance ?? 0);

            const header = document.getElementById('skillTreeSummary');
            if (header) {
                const inProgress = abilities.find(item => item.researching);
                const unlockedCount = abilities.filter(item => item.unlocked).length;
                header.textContent = inProgress
                    ? `${unlockedCount}/${abilities.length} sbloccate · in ricerca: ${inProgress.name}`
                        + ` (${inProgress.turns_remaining} turni) · ${grux} grux`
                    : `${unlockedCount}/${abilities.length} sbloccate · nessuna ricerca in corso · ${grux} grux`;
            }

            container.innerHTML = paths.map(pathName => {
                const nodes = abilities.filter(item => item.path === pathName).map(skill => {
                    let stateClass = 'locked';
                    let stateText = 'Bloccata';
                    if (skill.unlocked) {
                        stateClass = 'unlocked';
                        stateText = 'Sbloccata';
                    } else if (skill.researching) {
                        stateClass = 'researching';
                        stateText = `${skill.turns_remaining} turni`;
                    } else if (skill.can_start) {
                        stateClass = 'ready';
                        stateText = 'Pronta';
                    } else if (skill.blocked_reason) {
                        stateText = skill.blocked_reason;
                    }

                    const actionButton = skill.can_start
                        ? `<button class="skill-action-btn" type="button" onclick="researchAbilityById('${skill.id}')">Ricerca · ${skill.grux_cost} grux</button>`
                        : `<button class="skill-action-btn" type="button" disabled>${skill.unlocked ? 'Attiva' : (skill.researching ? 'In corso' : 'Non ora')}</button>`;

                    return `
                        <div class="skill-node ${stateClass}">
                            <h4>${escapeAdvisorText(skill.name)}</h4>
                            <p>${escapeAdvisorText(skill.description)}</p>
                            <p class="skill-effect">${escapeAdvisorText(skill.effect_text)}</p>
                            <div class="skill-cost">
                                <span>⏳ ${skill.turns_required} turni</span>
                                <span>💰 ${skill.grux_cost} grux</span>
                            </div>
                            <div class="skill-meta">
                                <span class="skill-state-pill">${escapeAdvisorText(stateText)}</span>
                                ${actionButton}
                            </div>
                        </div>
                    `;
                }).join('');

                return `
                    <div class="skilltree-path">
                        <h4 class="skilltree-path-title">${escapeAdvisorText(pathName)}</h4>
                        ${nodes}
                    </div>
                `;
            }).join('');
        }

        // ══════════════════════════════════════════════════════════
        // Mercato Nero
        // ══════════════════════════════════════════════════════════

        function renderBlackMarketButton(sessionData) {
            const button = document.getElementById('blackMarketBtn');
            const label = document.getElementById('blackMarketLabel');
            if (!button || !label) return;

            const market = sessionData?.player?.black_market;
            const unlocked = Boolean(market?.unlocked);
            const offers = (market?.offers || []).filter(offer => offer.available);
            const best = offers.reduce((max, offer) => Math.max(max, offer.discount_pct), 0);

            button.classList.toggle('is-locked', !unlocked);
            if (!unlocked) {
                const research = sessionData?.player?.abilities?.black_market;
                label.textContent = research?.researching
                    ? `Contatto in arrivo · ${research.turns_remaining} turni`
                    : 'Serranda chiusa · ricerca l\'abilità';
                return;
            }
            label.textContent = offers.length
                ? `${offers.length} offerte al banco · fino a -${best}%`
                : `Banco vuoto · nuova merce fra ${market.turns_to_refresh} turni`;
        }

        function openBlackMarket() {
            const overlay = document.getElementById('blackMarketOverlay');
            if (!overlay) return;
            renderBlackMarket(currentBattleState);
            overlay.classList.add('open');
        }

        function closeBlackMarket() {
            const overlay = document.getElementById('blackMarketOverlay');
            if (!overlay) return;
            overlay.classList.remove('open');
        }

        function closeBlackMarketIfBackdrop(event) {
            if (event.target && event.target.id === 'blackMarketOverlay') {
                closeBlackMarket();
            }
        }

        function renderBlackMarket(sessionData) {
            const body = document.getElementById('blackMarketBody');
            const note = document.getElementById('blackMarketNote');
            if (!body) return;

            const market = sessionData?.player?.black_market;
            const grux = Number(sessionData?.player?.grux_balance ?? 0);

            if (!market?.unlocked) {
                const research = sessionData?.player?.abilities?.black_market;
                const attesa = research?.researching
                    ? `Il contatto arriva fra ${research.turns_remaining} turni.`
                    : 'Ricerca l\'abilità "Mercato Nero" se vuoi che qualcuno ti apra.';
                body.innerHTML = `
                    <div class="market-shut">
                        <div class="market-shut-icon" aria-hidden="true">🚪</div>
                        <p>Bussi. Nessuno risponde.</p>
                        <p class="market-shut-hint">${escapeAdvisorText(attesa)}</p>
                    </div>
                `;
                if (note) note.textContent = 'Nessun banco aperto.';
                return;
            }

            const offers = market.offers || [];
            if (!offers.length) {
                body.innerHTML = `
                    <div class="market-shut">
                        <div class="market-shut-icon" aria-hidden="true">🕳</div>
                        <p>Banco sgombro. Torna più tardi.</p>
                        <p class="market-shut-hint">Merce nuova fra ${market.turns_to_refresh} turni.</p>
                    </div>
                `;
            } else {
                body.innerHTML = `<div class="market-shelf">${offers.map(offer => {
                    const affordable = grux >= offer.total_price;
                    const buyable = offer.available && affordable;
                    let stateClass = 'is-open';
                    let stamp = '';
                    if (offer.sold) {
                        stateClass = 'is-sold';
                        stamp = '<span class="market-stamp">Venduto</span>';
                    } else if (offer.expired) {
                        stateClass = 'is-gone';
                        stamp = '<span class="market-stamp">Sfumato</span>';
                    } else if (offer.turns_left <= 2) {
                        stateClass = 'is-open is-urgent';
                    }

                    let buttonLabel = `Prendi · ${offer.total_price} grux`;
                    if (offer.sold) buttonLabel = 'Già andato';
                    else if (offer.expired) buttonLabel = 'Fuori tempo';
                    else if (!affordable) buttonLabel = `Servono ${offer.total_price} grux`;

                    return `
                        <article class="market-offer ${stateClass}">
                            ${stamp}
                            <header class="market-offer-head">
                                <span class="market-offer-name">${escapeAdvisorText(offer.unit_name)}</span>
                                <span class="market-offer-qty">×${offer.quantity}</span>
                            </header>
                            <div class="market-offer-price">
                                <span class="market-price-old">${offer.list_total}</span>
                                <span class="market-price-new">${offer.total_price}</span>
                                <span class="market-price-cut">-${offer.discount_pct}%</span>
                            </div>
                            <p class="market-offer-flavor">"${escapeAdvisorText(offer.flavor)}"</p>
                            <div class="market-offer-meta">
                                <span>${escapeAdvisorText(offer.source)}</span>
                                <span>${offer.turns_left > 0 ? `sparisce fra ${offer.turns_left} turni` : 'scaduta'}</span>
                            </div>
                            <button class="market-buy-btn" type="button" ${buyable ? '' : 'disabled'}
                                    onclick="buyBlackMarketOffer('${offer.offer_id}')">${escapeAdvisorText(buttonLabel)}</button>
                        </article>
                    `;
                }).join('')}</div>`;
            }

            if (note) {
                note.textContent = `${grux} grux in tasca · ${market.units_bought} unità passate di qui`
                    + ` · ${market.grux_saved} grux risparmiati · banco nuovo fra ${market.turns_to_refresh} turni`;
            }
        }

        // Le abilità economiche cambiano il prezzo delle reclute, ma le voci del
        // menu nascono da /config, che è statico e non sa niente della partita.
        // Senza questo il menu direbbe 80 grux e la cassa ne scalerebbe 70.
        function updateRecruitPrices(sessionData) {
            const prices = sessionData?.player?.recruit_costs;
            if (!prices) return;

            for (const selectId of ['recruitSelect', 'autoRecruitUnitSelect']) {
                const select = document.getElementById(selectId);
                if (!select) continue;
                for (const option of select.options) {
                    const unit = recruitableUnits.find(item => item.id === option.value);
                    if (!unit) continue;
                    const price = Number(prices[unit.id] ?? unit.cost_grux);
                    const discounted = price < Number(unit.cost_grux);
                    const label = discounted
                        ? `${unit.name} • ${price} grux (era ${unit.cost_grux})`
                        : `${unit.name} • ${price} grux`;
                    if (option.textContent !== label) option.textContent = label;
                }
            }
        }

        async function buyBlackMarketOffer(offerId) {
            try {
                const response = await fetch('http://127.0.0.1:8000/game/black-market/buy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ offer_id: offerId })
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Il merciaio non ci sta.');
                }

                const result = await response.json();
                transientLogLines = [];
                renderBattleState(result.session);
                renderBlackMarket(result.session);
            } catch (error) {
                segnalaErrore(error.message);
                document.getElementById('battleStatusHint').textContent = `Mercato Nero: ${error.message}`;
                transientLogLines = [`Mercato Nero: ${error.message}`];
                renderBattleState(currentBattleState);
                renderBlackMarket(currentBattleState);
            }
        }

        async function recruitSelectedUnit() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                segnalaErrore('Partita terminata: non puoi reclutare nuove unità.');
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
                segnalaErrore(error.message);
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
            }
        }

        async function applyBattleStrategy() {
            try {
                const strategyId = document.getElementById('strategySelect').value;
                // Il bersaglio è il selettore legioni della tab strategia: con una
                // legione scelta la strategia è sua, ognuna combatte con la propria.
                // Su "Generale" resta quella di sessione, che vale per la riserva
                // e per le legioni che nasceranno.
                const legionId = getStrategyTargetLegionId();
                const endpoint = legionId
                    ? 'http://127.0.0.1:8000/game/legions/set-strategy'
                    : 'http://127.0.0.1:8000/game/set-strategy';
                const payload = legionId
                    ? { legion_id: legionId, strategy_id: strategyId }
                    : { strategy_id: strategyId };

                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Errore nel cambio strategia');
                }

                const result = await response.json();
                transientLogLines = [];
                renderBattleState(result.session);
            } catch (error) {
                segnalaErrore(error.message);
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore cambio strategia: ${error.message}`];
                renderBattleState(currentBattleState);
            }
        }



        async function applyAiDifficulty() {
            if (!currentBattleState || currentBattleState.state === 'game_over') {
                segnalaErrore('Partita terminata: non puoi cambiare difficoltà IA.');
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
                segnalaErrore(error.message);
                document.getElementById('battleStatusHint').textContent = `Errore: ${error.message}`;
                transientLogLines = [`Errore cambio difficoltà IA: ${error.message}`];
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

