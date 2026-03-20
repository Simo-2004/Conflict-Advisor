(function () {
    function qs(root, selector) {
        return root ? root.querySelector(selector) : null;
    }

    function activateBattleBarTab(tabKey) {
        const battleBar = document.getElementById('battle_bar');
        const tabs = document.querySelectorAll('.bar-tab');
        const panes = document.querySelectorAll('.dock-pane');

        if (battleBar) {
            battleBar.dataset.activeTab = tabKey;
        }

        tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.tab === tabKey));
        panes.forEach((pane) => pane.classList.toggle('active', pane.dataset.pane === tabKey));
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

        const actionRow = qs(battleToolbar, '.action-row');
        const garrisonPreview = document.getElementById('garrisonDefensePreview');
        const toolbarRecruit = qs(battleToolbar, '.toolbar-recruit');
        const toolbarStrategy = qs(battleToolbar, '.toolbar-strategy');
        const buttonRow = qs(battleToolbar, '.button-row');
        const layoutModeRow = qs(battleToolbar, '.layout-mode-row');

        const bar = document.createElement('div');
        bar.className = 'battle_bar';
        bar.id = 'battle_bar';
        bar.innerHTML = `
            <div class="bar-tabs">
                <button class="bar-tab active" type="button" data-tab="war">⚔ Guerra</button>
                <button class="bar-tab" type="button" data-tab="view">🗺 Vista</button>
                <button class="bar-tab" type="button" data-tab="system">⚙ Sistema</button>
            </div>
            <div class="bar-content">
                <div class="dock-pane active" data-pane="war"></div>
                <div class="dock-pane" data-pane="view"></div>
                <div class="dock-pane" data-pane="system"></div>
            </div>
        `;

        document.body.appendChild(bar);
        document.body.classList.add('battle-has-dock');
        battleToolbar.classList.add('toolbar-condensed');
        bar.dataset.activeTab = 'war';

        const warPane = qs(bar, '[data-pane="war"]');
        const viewPane = qs(bar, '[data-pane="view"]');
        const systemPane = qs(bar, '[data-pane="system"]');

        moveIfPresent(actionRow, warPane);
        moveIfPresent(garrisonPreview, warPane);
        moveIfPresent(toolbarRecruit, warPane);
        moveIfPresent(toolbarStrategy, warPane);
        moveIfPresent(layoutModeRow, viewPane);
        moveIfPresent(buttonRow, systemPane);

        bar.querySelectorAll('.bar-tab').forEach((tab) => {
            tab.addEventListener('click', () => activateBattleBarTab(tab.dataset.tab));
        });

        const recruitButton = document.getElementById('recruitBtn');
        const garrisonButton = document.getElementById('actionGarrisonBtn');
        const layoutButtons = [
            document.getElementById('layoutSplitBtn'),
            document.getElementById('layoutMapBtn'),
            document.getElementById('layoutLogsBtn'),
        ];
        const settingsButton = qs(systemPane, '.settings-trigger');
        const aiButton = document.getElementById('aiKillSwitchBtn');

        if (recruitButton) recruitButton.addEventListener('click', () => activateBattleBarTab('war'));
        if (garrisonButton) garrisonButton.addEventListener('click', () => activateBattleBarTab('war'));
        layoutButtons.forEach((btn) => {
            if (btn) btn.addEventListener('click', () => activateBattleBarTab('view'));
        });
        if (settingsButton) settingsButton.addEventListener('click', () => activateBattleBarTab('system'));
        if (aiButton) aiButton.addEventListener('click', () => activateBattleBarTab('system'));
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
