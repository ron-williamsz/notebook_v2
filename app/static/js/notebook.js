/**
 * Notebook page — inicialização e orquestração
 */
window.Notebook = {
    sessionId: null,
    session: null,

    async init() {
        this.sessionId = window.SESSION_ID;
        if (!this.sessionId) return;

        try {
            this.session = await API.getSession(this.sessionId);
            document.getElementById('notebook-title').textContent = this.session.title;

            // Exibe período e condomínio (somente leitura)
            this._showPeriod();
            this._showCondLabel();

            // Inicializa Pipeline
            Pipeline.init(this.sessionId);

            // Carrega componentes em paralelo
            await Promise.all([
                Skills.init(this.sessionId),
                Etapas.init(this.sessionId),
            ]);

            // Dashboard de cobertura
            this.loadCoverage();
        } catch (e) {
            Utils.toast('Erro ao carregar notebook: ' + e.message, 'error');
        }
    },

    _showPeriod() {
        const el = document.getElementById('etapas-periodo');
        if (!el) return;
        const meses = ['', 'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
        const mes = this.session.gosati_mes;
        const ano = this.session.gosati_ano;
        if (mes && ano) {
            el.textContent = `${meses[mes]}/${ano}`;
        }
    },

    _showCondLabel() {
        const label = document.getElementById('etapas-cond-label');
        if (!label) return;
        const codigo = this.session.gosati_condominio_codigo;
        const nome = this.session.gosati_condominio_nome;
        if (codigo) {
            label.textContent = `${codigo} — ${nome || ''}`;
        }
    },

    async loadCoverage() {
        try {
            const cov = await API.getCoverage(this.sessionId);
            const dash = document.getElementById('coverage-dashboard');
            if (!dash) return;
            if (!cov.total_despesas) { dash.classList.add('hidden'); return; }

            dash.classList.remove('hidden');
            document.getElementById('coverage-total').textContent = cov.total_despesas;
            document.getElementById('coverage-analisados').textContent = cov.analisados;
            document.getElementById('coverage-pendentes').textContent = cov.pendentes;
            document.getElementById('coverage-fill').style.width = cov.percentual + '%';
        } catch (e) {
            // silently fail
        }
    },

    _savePeriod() {
        // Período agora é definido na criação do notebook (dashboard)
    },
};

/* ===== Mobile panel switching ===== */
window.MobileNav = {
    init() {
        const tabBar = document.getElementById('mobile-tab-bar');
        if (!tabBar) return;

        tabBar.addEventListener('click', (e) => {
            const tab = e.target.closest('.mobile-tab');
            if (!tab) return;
            this.switchPanel(tab.dataset.panel);
        });

        // Set initial state on mobile
        if (window.matchMedia('(max-width: 768px)').matches) {
            this.switchPanel('panel-chat');
        }

        // Handle resize: restore panels on desktop, reapply on mobile
        window.matchMedia('(max-width: 768px)').addEventListener('change', (e) => {
            const panels = document.querySelectorAll('.notebook-view > .panel');
            if (e.matches) {
                this.switchPanel('panel-chat');
            } else {
                panels.forEach(p => p.classList.remove('mobile-active'));
            }
        });
    },

    switchPanel(panelId) {
        const panels = document.querySelectorAll('.notebook-view > .panel');
        const tabs = document.querySelectorAll('.mobile-tab');

        panels.forEach(p => p.classList.remove('mobile-active'));
        tabs.forEach(t => t.classList.remove('active'));

        const target = document.getElementById(panelId);
        if (target) target.classList.add('mobile-active');

        const activeTab = document.querySelector(`.mobile-tab[data-panel="${panelId}"]`);
        if (activeTab) activeTab.classList.add('active');
    }
};

document.addEventListener('DOMContentLoaded', () => {
    Notebook.init();
    MobileNav.init();
});
