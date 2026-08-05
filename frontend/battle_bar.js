(function () {
    function qs(root, selector) {
        return root ? root.querySelector(selector) : null;
    }

    function activateBattleBarTab(tabKey) {
        const battleBar = document.getElementById('battle_bar');
        const tabs = document.querySelectorAll('.bar-tab');
        const panes = document.querySelectorAll('.dock-pane');

        // Esci dalla pick mode se si cambia tab
        if (window.LegionsPanel && tabKey !== 'legions') {
            window.LegionsPanel.exitPickMode();
        }

        if (battleBar) {
            battleBar.dataset.activeTab = tabKey;
        }

        tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.tab === tabKey));
        panes.forEach((pane) => pane.classList.toggle('active', pane.dataset.pane === tabKey));

        // Aggiorna il pannello legioni quando diventa visibile
        if (tabKey === 'legions' && window.LegionsPanel && typeof currentBattleState !== 'undefined' && currentBattleState) {
            window.LegionsPanel.update(currentBattleState);
        }
    }

    function moveIfPresent(node, target) {
        if (node && target) {
            target.appendChild(node);
        }
    }

    function buildBattleBar() {
        const battlePanel = document.getElementById('battlePanel');
        const battleToolbar = qs(battlePanel, '.battle-toolbar');
        if (!battlePanel || !battleToolbar) return;
        if (document.getElementById('battle_bar')) return;

        const tacticalLegionSelectWrap = qs(battleToolbar, '.tactical-legion-select-wrap');
        const actionRow = qs(battleToolbar, '.action-row');
        const garrisonPreview = document.getElementById('garrisonDefensePreview');
        const abilityCard = document.getElementById('abilityResearchBtn');
        const toolbarRecruit = qs(battleToolbar, '.toolbar-recruit');
        const toolbarStrategy = qs(battleToolbar, '.toolbar-strategy');
        const buttonRow = qs(battleToolbar, '.button-row');
        const layoutModeRow = qs(battleToolbar, '.layout-mode-row');

        const bar = document.createElement('div');
        bar.className = 'battle_bar';
        bar.id = 'battle_bar';
        bar.innerHTML = `
            <div class="bar-tabs">
                <button class="bar-tab active" type="button" data-tab="war">&#9876; Guerra</button>
                <button class="bar-tab" type="button" data-tab="legions">&#9776; Legioni</button>
                <button class="bar-tab" type="button" data-tab="view">&#9783; Vista</button>
                <button class="bar-tab" type="button" data-tab="system">&#9881; Sistema</button>
            </div>
            <div class="bar-content">
                <div class="dock-pane active" data-pane="war"></div>
                <div class="dock-pane" data-pane="legions"></div>
                <div class="dock-pane" data-pane="view"></div>
                <div class="dock-pane" data-pane="system"></div>
            </div>
        `;

        document.body.appendChild(bar);
        document.body.classList.add('battle-has-dock');
        battleToolbar.classList.add('toolbar-condensed');
        bar.dataset.activeTab = 'war';

        const warPane = qs(bar, '[data-pane="war"]');
        const legionsPane = qs(bar, '[data-pane="legions"]');
        const viewPane = qs(bar, '[data-pane="view"]');
        const systemPane = qs(bar, '[data-pane="system"]');

        moveIfPresent(tacticalLegionSelectWrap, warPane);
        moveIfPresent(actionRow, warPane);
        moveIfPresent(garrisonPreview, warPane);
        moveIfPresent(abilityCard, warPane);
        moveIfPresent(toolbarRecruit, warPane);
        moveIfPresent(toolbarStrategy, warPane);
        moveIfPresent(layoutModeRow, viewPane);
        moveIfPresent(buttonRow, systemPane);

        // Monta il pannello Legioni nel pane dedicato
        if (window.LegionsPanel && legionsPane) {
            const initialState = (typeof currentBattleState !== 'undefined') ? currentBattleState : null;
            window.LegionsPanel.mount(legionsPane, initialState);
        }

        // Resize handle laterale
        initDockResize(bar);

        bar.querySelectorAll('.bar-tab').forEach((tab) => {
            tab.addEventListener('click', () => activateBattleBarTab(tab.dataset.tab));
        });

        const recruitButton = document.getElementById('recruitBtn');
        const autoRecruitButton = document.getElementById('autoRecruitBtn');
        const garrisonButton = document.getElementById('actionGarrisonBtn');
        const layoutButtons = [
            document.getElementById('layoutSplitBtn'),
            document.getElementById('layoutMapBtn'),
            document.getElementById('layoutLogsBtn'),
        ];
        const settingsButton = qs(systemPane, '.settings-trigger');
        const aiButton = document.getElementById('aiKillSwitchBtn');

        if (recruitButton) recruitButton.addEventListener('click', () => activateBattleBarTab('war'));
        if (autoRecruitButton) autoRecruitButton.addEventListener('click', () => activateBattleBarTab('war'));
        if (garrisonButton) garrisonButton.addEventListener('click', () => activateBattleBarTab('war'));
        layoutButtons.forEach((btn) => {
            if (btn) btn.addEventListener('click', () => activateBattleBarTab('view'));
        });
        if (settingsButton) settingsButton.addEventListener('click', () => activateBattleBarTab('system'));
        if (aiButton) aiButton.addEventListener('click', () => activateBattleBarTab('system'));
    }

    function initDockResize(bar) {
        const handle = document.createElement('div');
        handle.className = 'dock-resize-handle';
        handle.title = 'Trascina per ridimensionare il pannello';
        bar.appendChild(handle);

        const MIN_W = 240;
        const MAX_W = 560;
        let dragging = false;

        handle.addEventListener('mousedown', (e) => {
            e.preventDefault();
            dragging = true;
            document.body.classList.add('dock-resizing');
        });

        window.addEventListener('mousemove', (e) => {
            if (!dragging) return;
            // La barra inizia a left:14px, quindi la larghezza = mouseX - 14
            const newW = Math.min(MAX_W, Math.max(MIN_W, e.clientX - 14));
            document.documentElement.style.setProperty('--dock-width', `${newW}px`);
        });

        window.addEventListener('mouseup', () => {
            if (dragging) {
                dragging = false;
                document.body.classList.remove('dock-resizing');
            }
        });
    }

    function tryBuildBattleBar() {
        if (document.getElementById('battlePanel')) {
            buildBattleBar();
        }
    }

    window.addEventListener('DOMContentLoaded', () => {
        tryBuildBattleBar();
        setTimeout(tryBuildBattleBar, 250);
        setTimeout(tryBuildBattleBar, 800);
    });
})();
