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

            // Restaura mês/ano e condomínio salvos na sessão
            this._restorePeriod();
            this._showCondLabel();

            // Listeners para salvar mês/ano ao alterar
            const mesEl = document.getElementById('etapas-mes');
            const anoEl = document.getElementById('etapas-ano');
            if (mesEl) mesEl.addEventListener('change', () => this._savePeriod());
            if (anoEl) anoEl.addEventListener('change', () => this._savePeriod());

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

    _restorePeriod() {
        const mesEl = document.getElementById('etapas-mes');
        const anoEl = document.getElementById('etapas-ano');
        if (this.session.gosati_mes && mesEl) mesEl.value = this.session.gosati_mes;
        if (this.session.gosati_ano && anoEl) anoEl.value = this.session.gosati_ano;
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

    async _savePeriod() {
        const mes = parseInt(document.getElementById('etapas-mes').value) || null;
        const ano = parseInt(document.getElementById('etapas-ano').value) || null;
        try {
            await API.saveGoSatiSelection(this.sessionId, {
                gosati_query_type: 'prestacao_contas',
                gosati_condominio_codigo: this.session.gosati_condominio_codigo,
                gosati_condominio_nome: this.session.gosati_condominio_nome,
                gosati_mes: mes,
                gosati_ano: ano,
            });
        } catch (e) {
            // silently fail
        }
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
