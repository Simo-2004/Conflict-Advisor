/* ══════════════════════════════════════════════════════════════════
   War Advisor — Simulatore (pagina iniziale)

   Stessa logica di prima, spostata fuori da index.html: carica la config,
   raccoglie la scelta del giocatore, chiede il calcolo al backend, disegna
   il verdetto e prepara il passaggio alla battaglia.

   Le uniche aggiunte sono di presentazione: lo stato della pagina (setup /
   caricamento / pronto) che pilota testata e segnaposto, la barra della
   tesoreria e i numeri che salgono invece di comparire.
   ══════════════════════════════════════════════════════════════════ */

const ATTRIBUTE_NAMES = {
    'U1_attack': 'Attacco',
    'U2_defense': 'Difesa',
    'U3_mobility': 'Mobilità',
    'U4_stealth': 'Furtività',
    'U5_discipline': 'Disciplina',
    'U6_terrain_adapt': 'Adatt. Terreno',
    'U7_range_power': 'Potenza a Distanza',
    'U8_support': 'Supporto'
};

const API = 'http://127.0.0.1:8000';

let radarChart = null;
let selectedUnits = [];
let allUnits = [];
let allTerrains = [];
let allWeather = [];
let allTroopStatus = [];
let latestCalculation = null;
let startingBudget = 220;

window.addEventListener('DOMContentLoaded', init);

async function init() {
    document.getElementById('terrainSelect').addEventListener('change', updateButtonState);
    document.getElementById('weatherSelect').addEventListener('change', updateButtonState);
    document.getElementById('statusSelect').addEventListener('change', updateButtonState);
    await loadData();
    updateSelectedUnits();
}

// ── Caricamento dati ────────────────────────────────────────────────

async function loadData() {
    try {
        const response = await fetch(`${API}/config`);
        if (!response.ok) throw new Error('Errore nel caricamento dei dati');

        const data = await response.json();
        allUnits = data.units;
        allTerrains = data.terrains;
        allWeather = data.weather;
        allTroopStatus = data.troop_status;

        populateUnitsSelector();
        fillSelect('terrainSelect', allTerrains, '-- Seleziona un terreno --');
        fillSelect('weatherSelect', allWeather, '-- Nessuna --');
        fillSelect('statusSelect', allTroopStatus, '-- Nessuno --');
    } catch (error) {
        showError('Errore nel caricamento dei dati: ' + error.message);
    }
}

function populateUnitsSelector() {
    const container = document.getElementById('unitsContainer');
    container.innerHTML = '';

    allUnits.forEach(unit => {
        // Tutta la carta è un <label>: si clicca ovunque, non solo sulla
        // casella. La casella resta, così `:checked` continua a governare
        // lo stile e il conteggio.
        const card = document.createElement('label');
        card.className = 'unit-card';
        card.innerHTML = `
            <input type="checkbox" id="unit_${unit.id}" value="${unit.id}" onchange="updateSelectedUnits()">
            <div class="unit-info">
                <div class="unit-name">${unit.name}</div>
                <div class="unit-desc">${unit.description}</div>
            </div>
            <div class="unit-cost">${unit.cost_grux} grux</div>
        `;
        container.appendChild(card);
    });
}

function fillSelect(id, items, placeholder) {
    const select = document.getElementById(id);
    select.innerHTML = `<option value="">${placeholder}</option>`;
    items.forEach(item => {
        const option = document.createElement('option');
        option.value = item.name;
        option.textContent = item.name;
        select.appendChild(option);
    });
}

// ── Selezione e tesoreria ───────────────────────────────────────────

function updateSelectedUnits() {
    selectedUnits = [];
    document.querySelectorAll('#unitsContainer input[type="checkbox"]:checked')
        .forEach(checkbox => selectedUnits.push(checkbox.value));

    const box = document.getElementById('selectedUnitsBox');
    document.getElementById('selectedCount').textContent =
        `Unità selezionate: ${selectedUnits.length}`;
    box.classList.toggle('active', selectedUnits.length > 0);

    const spesa = getSelectedUnitsCost();
    const residuo = startingBudget - spesa;
    const budget = document.getElementById('budgetBox');

    document.getElementById('budgetFigures').innerHTML =
        `<strong>${residuo}</strong> / ${startingBudget} grux · spesi ${spesa}`;
    // Oltre budget la barra resta piena: serve a far vedere che è finita,
    // non a misurare di quanto si è sforato.
    document.getElementById('budgetFill').style.width =
        `${Math.min(100, (spesa / startingBudget) * 100)}%`;
    budget.classList.toggle('over-budget', residuo < 0);

    updateButtonState();
}

function getSelectedUnitsCost() {
    return selectedUnits.reduce((total, unitId) => {
        const unit = allUnits.find(item => item.id === unitId);
        return total + (unit ? unit.cost_grux : 0);
    }, 0);
}

function updateButtonState() {
    const terrain = document.getElementById('terrainSelect').value;
    const pronto = selectedUnits.length > 0
        && terrain !== ''
        && getSelectedUnitsCost() <= startingBudget;

    document.getElementById('calculateBtn').disabled = !pronto;
    updatePhase(pronto ? 'field' : 'army');
}

/** Accende i passi nella testata: dove sei e cosa hai già fatto. */
function updatePhase(phase) {
    if (phase !== 'done' && latestCalculation) phase = 'done';

    const stato = {
        army:  ['is-active', '', ''],
        field: ['is-done', 'is-active', ''],
        done:  ['is-done', 'is-done', 'is-active'],
    }[phase] || ['is-active', '', ''];

    document.querySelectorAll('.hero-steps li').forEach((li, i) => {
        li.className = stato[i] || '';
    });
}

// ── Calcolo ─────────────────────────────────────────────────────────

async function calculateStrategy() {
    const errorBox = document.getElementById('errorBox');
    errorBox.classList.remove('show');
    document.getElementById('loading').classList.add('show');
    document.getElementById('resultsArea').classList.remove('active');

    const terrain = document.getElementById('terrainSelect').value;
    const weather = document.getElementById('weatherSelect').value;
    const troop_status = document.getElementById('statusSelect').value;

    try {
        const response = await fetch(`${API}/calculate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                units: selectedUnits,
                terrain: terrain,
                weather: weather || null,
                troop_status: troop_status || null
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Errore nella richiesta');
        }

        const data = await response.json();
        latestCalculation = data;
        renderResults(data);
        saveSimulationForBattle(data, terrain, weather || null, troop_status || null);
    } catch (error) {
        showError(error.message);
    } finally {
        document.getElementById('loading').classList.remove('show');
    }
}

function renderResults(data) {
    const top = data.top_strategy;
    document.getElementById('topStrategyName').textContent = top.name;
    countUp('topCompatibility', top.compatibility);
    document.getElementById('topDistance').textContent = `Distanza ${top.distance.toFixed(4)}`;
    document.getElementById('topDescription').textContent = top.description || '';

    if (data.ranking && data.ranking.length >= 2) {
        const second = data.ranking[1];
        document.getElementById('secondStrategyName').textContent = second.name;
        countUp('secondCompatibility', second.compatibility);
        document.getElementById('secondDistance').textContent = `Distanza ${second.distance.toFixed(4)}`;
        document.getElementById('secondDescription').textContent = second.description || '';
    }

    if (data.ranking && data.ranking.length > 0) {
        const worst = data.ranking[data.ranking.length - 1];
        document.getElementById('worstStrategyName').textContent = worst.name;
        document.getElementById('worstCompatibility').textContent = `${worst.compatibility.toFixed(1)}%`;
        document.getElementById('worstDistance').textContent = `Distanza ${worst.distance.toFixed(4)}`;
        document.getElementById('worstDescription').textContent = worst.description || '';
    }

    const warnings = document.getElementById('warningsArea');
    if (data.critical_warnings && data.critical_warnings.length > 0) {
        warnings.innerHTML = '<strong>⚠️ Avvisi CRITICAL:</strong><br>'
            + data.critical_warnings.join('<br>');
        warnings.style.display = 'block';
    } else {
        warnings.style.display = 'none';
    }

    updateChart(data.army_profile, data.modified_profile, data.top_strategy.ideal_attributes);

    document.getElementById('resultsArea').classList.add('active');
    document.getElementById('launchArea').classList.add('active');
    document.getElementById('launchSummary').innerHTML =
        `Strategia consigliata: <strong>${top.name}</strong>`
        + ` · spesa ${data.selected_units_cost} grux, residuo ${data.remaining_grux}.`;
    updatePhase('done');
}

/** Percentuale che sale invece di comparire: il verdetto si fa guardare.
 *
 *  Il valore giusto viene scritto SUBITO, prima di animare: se i frame non
 *  arrivano — scheda in secondo piano, animazioni disattivate dal sistema —
 *  resta a schermo il numero vero e non uno zero. Un'animazione può saltare,
 *  un dato sbagliato no.
 */
function countUp(id, value) {
    const el = document.getElementById(id);
    const finale = `${value.toFixed(1)}%`;
    el.textContent = finale;

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const durata = 700;
    const inizio = performance.now();
    // Il primo passo va chiesto a rAF, non eseguito qui: chiamandolo subito
    // scriverebbe comunque lo zero iniziale sopra il valore buono, e senza
    // fotogrammi successivi resterebbe quello.
    requestAnimationFrame(function step(ora) {
        const t = Math.min(1, (ora - inizio) / durata);
        el.textContent = t < 1
            ? `${(value * (1 - Math.pow(1 - t, 3))).toFixed(1)}%`
            : finale;
        if (t < 1) requestAnimationFrame(step);
    });

    // Rete di sicurezza: se i frame si fermano a metà corsa, il numero
    // rimarrebbe congelato a un valore parziale.
    setTimeout(() => { el.textContent = finale; }, durata + 150);
}

// ── Passaggio alla battaglia ────────────────────────────────────────

function saveSimulationForBattle(calculation, terrain, weather, troopStatus) {
    const payload = {
        units: [...selectedUnits],
        terrain: terrain,
        weather: weather,
        troop_status: troopStatus,
        strategy_id: calculation.top_strategy.id,
        army_profile: calculation.army_profile,
        modified_profile: calculation.modified_profile,
        map_seed: null,
        summary: {
            top_strategy_name: calculation.top_strategy.name,
            top_strategy_compatibility: calculation.top_strategy.compatibility,
            budget_grux: calculation.budget_grux,
            selected_units_cost: calculation.selected_units_cost,
            remaining_grux: calculation.remaining_grux
        }
    };
    sessionStorage.setItem('warAdvisorBattleSetup', JSON.stringify(payload));
}

function goToBattlePage() {
    if (!latestCalculation) {
        showError('Prima esegui una simulazione strategica.');
        return;
    }
    // Percorso relativo, non l'indirizzo assoluto del backend: aprendo la
    // pagina da `localhost` il salto a `127.0.0.1` cambiava origine e il
    // sessionStorage con la simulazione restava indietro, così la battaglia
    // si apriva vuota. Le chiamate API continuano ad andare a `API`.
    window.location.href = '/battle';
}

// ── Grafico ed errori ───────────────────────────────────────────────

function updateChart(originalArmy, modifiedArmy, topStrategy) {
    const ctx = document.getElementById('radarChart').getContext('2d');
    const keys = Object.keys(originalArmy);

    if (radarChart) radarChart.destroy();

    radarChart = new Chart(ctx, {
        type: 'radar',
        data: {
            labels: keys.map(k => ATTRIBUTE_NAMES[k] || k),
            datasets: [
                {
                    label: 'Il Tuo Esercito',
                    data: keys.map(k => originalArmy[k]),
                    backgroundColor: 'rgba(233, 69, 96, 0.15)',
                    borderColor: '#e94560',
                    pointBackgroundColor: '#e94560',
                    borderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 6
                },
                {
                    label: 'Con Modificatori Terreno',
                    data: keys.map(k => modifiedArmy[k]),
                    backgroundColor: 'rgba(125, 95, 212, 0.15)',
                    borderColor: '#7d5fd4',
                    pointBackgroundColor: '#7d5fd4',
                    borderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 6
                },
                {
                    label: 'Strategia Ideale',
                    data: keys.map(k => topStrategy[k]),
                    backgroundColor: 'rgba(22, 163, 74, 0.15)',
                    borderColor: '#16a34a',
                    pointBackgroundColor: '#16a34a',
                    borderDash: [5, 5],
                    borderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: { font: { size: 11, weight: '600' }, padding: 14, boxWidth: 14 }
                }
            },
            scales: {
                r: {
                    min: 0,
                    max: 1,
                    ticks: { stepSize: 0.2, font: { size: 10 } },
                    pointLabels: { font: { size: 11, weight: '500' } },
                    angleLines: { color: 'rgba(0,0,0,0.1)' },
                    grid: { color: 'rgba(0,0,0,0.05)' }
                }
            }
        }
    });
}

function showError(msg) {
    const box = document.getElementById('errorBox');
    box.textContent = '❌ ' + msg;
    box.classList.add('show');
    document.getElementById('loading').classList.remove('show');
}
