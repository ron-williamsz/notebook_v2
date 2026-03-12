/**
 * Dashboard — lista de condomínios e notebooks
 */
window.Dashboard = {
    _allConds: [],
    _allSessions: [],
    _activeTab: 'todos',

    async init() {
        this._initTabs();
        this._initSearch();
        await Promise.all([this._loadCondominios(), this._loadSessions()]);
    },

    /* ── Tabs ── */
    _initTabs() {
        document.querySelectorAll('.dashboard-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.dashboard-tab').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this._activeTab = btn.dataset.tab;
                document.getElementById('tab-todos').classList.toggle('hidden', this._activeTab !== 'todos');
                document.getElementById('tab-meus').classList.toggle('hidden', this._activeTab !== 'meus');
                document.getElementById('dashboard-search').classList.toggle('hidden', this._activeTab !== 'todos');
                if (this._activeTab === 'meus') this._renderNotebooks();
            });
        });
    },

    /* ── Search ── */
    _initSearch() {
        const input = document.getElementById('search-input');
        if (!input) return;
        input.addEventListener('input', () => this._filterConds(input.value));
    },

    _filterConds(query) {
        const q = (query || '').toLowerCase().trim();
        const filtered = q
            ? this._allConds.filter(c =>
                String(c.codigo).includes(q) || c.nome.toLowerCase().includes(q))
            : this._allConds;
        this._renderCondList(filtered);
    },

    /* ── Load condomínios ── */
    async _loadCondominios() {
        const loading = document.getElementById('loading-cond');
        try {
            // Fetch all (no busca param = full list)
            this._allConds = await API.searchCondominios('');
            loading.classList.add('hidden');
            this._renderCondList(this._allConds);
        } catch (e) {
            loading.innerHTML = `<p style="color:var(--text-error)">Erro ao carregar condomínios: ${e.message}</p>`;
        }
    },

    /* ── Load sessions ── */
    async _loadSessions() {
        try {
            this._allSessions = await API.listSessions();
        } catch (e) {
            console.error('Erro ao carregar sessions:', e);
        }
    },

    /* ── Render condomínios list ── */
    _renderCondList(conds) {
        const list = document.getElementById('cond-list');
        const empty = document.getElementById('empty-cond');

        if (!conds.length) {
            list.innerHTML = '';
            empty.classList.remove('hidden');
            return;
        }
        empty.classList.add('hidden');

        // Build a map of cond_codigo -> sessions for badges
        const sessMap = {};
        for (const s of this._allSessions) {
            if (s.gosati_condominio_codigo) {
                if (!sessMap[s.gosati_condominio_codigo]) sessMap[s.gosati_condominio_codigo] = [];
                sessMap[s.gosati_condominio_codigo].push(s);
            }
        }

        list.innerHTML = conds.map(c => {
            const sessions = sessMap[c.codigo] || [];
            const hasSessions = sessions.length > 0;
            const badge = hasSessions
                ? `<span class="cond-badge active">${sessions.length} notebook${sessions.length > 1 ? 's' : ''}</span>`
                : '';
            return `<div class="cond-row" data-codigo="${c.codigo}" data-nome="${Utils.escapeHtml(c.nome)}">
                <span class="cond-codigo">${c.codigo}</span>
                <span class="cond-nome">${Utils.escapeHtml(c.nome)}</span>
                ${badge}
                <svg class="cond-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg>
            </div>`;
        }).join('');

        list.querySelectorAll('.cond-row').forEach(row => {
            row.addEventListener('click', () => {
                this._onCondClick(parseInt(row.dataset.codigo), row.dataset.nome);
            });
        });
    },

    /* ── Render notebooks (Meus notebooks tab) ── */
    _renderNotebooks() {
        const list = document.getElementById('notebook-list');
        const empty = document.getElementById('empty-notebooks');

        if (!this._allSessions.length) {
            list.innerHTML = '';
            empty.classList.remove('hidden');
            return;
        }
        empty.classList.add('hidden');

        const meses = ['', 'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

        list.innerHTML = this._allSessions.map(s => {
            const periodo = s.gosati_mes && s.gosati_ano
                ? `${meses[s.gosati_mes]}/${s.gosati_ano}`
                : '';
            const condCode = s.gosati_condominio_codigo || '';
            return `<div class="cond-row notebook-row" onclick="location.href='/notebooks/${s.id}'">
                <span class="cond-codigo">${condCode}</span>
                <span class="cond-nome">${Utils.escapeHtml(s.title)}</span>
                <span class="notebook-periodo">${periodo}</span>
                <span class="notebook-fontes">${s.source_count} fontes</span>
                <span class="notebook-data">${Utils.formatDate(s.created_at)}</span>
                <button class="btn-icon btn-ghost btn-sm" onclick="event.stopPropagation(); Dashboard.deleteNotebook(${s.id})" title="Excluir">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-.867 12.142A2 2 0 0 1 16.138 20H7.862a2 2 0 0 1-1.995-1.858L5 6"/>
                    </svg>
                </button>
                <svg class="cond-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg>
            </div>`;
        }).join('');
    },

    /* ── Click on condomínio ── */
    _onCondClick(codigo, nome) {
        // Check if there are existing sessions for this cond
        const existing = this._allSessions.filter(s => s.gosati_condominio_codigo === codigo);
        if (existing.length === 1) {
            // Redirect to the only existing notebook
            location.href = `/notebooks/${existing[0].id}`;
            return;
        }
        // Show modal to pick month/year (and create new notebook)
        document.getElementById('create-cond-codigo').value = codigo;
        document.getElementById('create-cond-nome').value = nome;
        document.getElementById('modal-cond-name').textContent = `${codigo} — ${nome}`;

        // Pre-fill current month - 1
        const now = new Date();
        const prevMonth = now.getMonth(); // 0-indexed = previous month
        document.getElementById('create-mes').value = prevMonth || 12;
        document.getElementById('create-ano').value = prevMonth === 0 ? now.getFullYear() - 1 : now.getFullYear();

        document.getElementById('create-modal').showModal();
    },

    /* ── Open/Create notebook ── */
    async openNotebook() {
        const codigo = parseInt(document.getElementById('create-cond-codigo').value);
        const nome = document.getElementById('create-cond-nome').value;
        const mes = parseInt(document.getElementById('create-mes').value) || null;
        const ano = parseInt(document.getElementById('create-ano').value) || null;

        if (!mes || !ano) {
            Utils.toast('Selecione o mês e o ano', 'warning');
            return;
        }

        // Check if session already exists for this cond+month+year
        const existing = this._allSessions.find(s =>
            s.gosati_condominio_codigo === codigo &&
            s.gosati_mes === mes &&
            s.gosati_ano === ano
        );
        if (existing) {
            document.getElementById('create-modal').close();
            location.href = `/notebooks/${existing.id}`;
            return;
        }

        // Create new
        const meses = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
        const title = `${nome} — ${meses[mes]}/${ano}`;

        try {
            const session = await API.createSession(title, {
                gosati_condominio_codigo: codigo,
                gosati_condominio_nome: nome,
                gosati_mes: mes,
                gosati_ano: ano,
            });
            document.getElementById('create-modal').close();
            location.href = `/notebooks/${session.id}`;
        } catch (e) {
            Utils.toast('Erro ao criar notebook: ' + e.message, 'error');
        }
    },

    async deleteNotebook(id) {
        if (!confirm('Excluir este notebook?')) return;
        try {
            await API.deleteSession(id);
            Utils.toast('Notebook excluído', 'success');
            this._allSessions = this._allSessions.filter(s => s.id !== id);
            if (this._activeTab === 'meus') this._renderNotebooks();
            else this._renderCondList(this._allConds);
        } catch (e) {
            Utils.toast('Erro ao excluir: ' + e.message, 'error');
        }
    }
};

document.addEventListener('DOMContentLoaded', () => Dashboard.init());

// Enter no modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && document.getElementById('create-modal').open) {
        Dashboard.openNotebook();
    }
});
