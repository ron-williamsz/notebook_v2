/**
 * Dashboard — listagem e criação de notebooks
 */
window.Dashboard = {
    _searchTimer: null,

    async init() {
        await this.loadNotebooks();
        this._initCondSearch();
    },

    _initCondSearch() {
        const input = document.getElementById('create-cond-search');
        const list = document.getElementById('create-cond-list');
        if (!input) return;

        input.addEventListener('input', () => this._searchCond(input.value));
        input.addEventListener('focus', () => {
            if (input.value.length >= 2) this._searchCond(input.value);
        });

        document.addEventListener('click', (e) => {
            if (list && !list.contains(e.target) && e.target !== input) {
                list.classList.add('hidden');
            }
        });
    },

    _searchCond(value) {
        clearTimeout(this._searchTimer);
        const list = document.getElementById('create-cond-list');
        if (!list) return;

        if (!value || value.length < 2) {
            list.classList.add('hidden');
            return;
        }

        this._searchTimer = setTimeout(async () => {
            try {
                const results = await API.searchCondominios(value);
                if (!results.length) {
                    list.innerHTML = '<div class="autocomplete-empty">Nenhum condomínio encontrado</div>';
                } else {
                    list.innerHTML = results.map(c => `
                        <div class="autocomplete-item" data-codigo="${c.codigo}" data-nome="${Utils.escapeHtml(c.nome)}">
                            <span class="ac-code">${c.codigo}</span>
                            <span class="ac-name">${Utils.escapeHtml(c.nome)}</span>
                        </div>
                    `).join('');

                    list.querySelectorAll('.autocomplete-item').forEach(item => {
                        item.addEventListener('click', () => {
                            this._selectCond(parseInt(item.dataset.codigo), item.dataset.nome);
                        });
                    });
                }
                list.classList.remove('hidden');
            } catch (e) {
                list.classList.add('hidden');
            }
        }, 250);
    },

    _selectCond(codigo, nome) {
        document.getElementById('create-cond-search').value = `${codigo} — ${nome}`;
        document.getElementById('create-cond-codigo').value = codigo;
        document.getElementById('create-cond-nome').value = nome;
        document.getElementById('create-cond-list').classList.add('hidden');
    },

    async loadNotebooks() {
        try {
            const sessions = await API.listSessions();
            const grid = document.getElementById('notebook-grid');
            const empty = document.getElementById('empty-state');

            if (!sessions.length) {
                grid.innerHTML = '';
                empty.classList.remove('hidden');
                return;
            }

            empty.classList.add('hidden');
            grid.innerHTML = sessions.map(s => `
                <div class="notebook-card" onclick="location.href='/notebooks/${s.id}'">
                    <div class="notebook-card-emoji">${Utils.randomEmoji()}</div>
                    <div class="notebook-card-title">${Utils.escapeHtml(s.title)}</div>
                    <div class="notebook-card-meta">
                        <span>${Utils.formatDate(s.created_at)} &middot; ${s.source_count} fontes</span>
                        <button class="btn-icon btn-ghost btn-sm" onclick="event.stopPropagation(); Dashboard.deleteNotebook(${s.id})" title="Excluir">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>
                            </svg>
                        </button>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            Utils.toast('Erro ao carregar notebooks: ' + e.message, 'error');
        }
    },

    showCreateModal() {
        const modal = document.getElementById('create-modal');
        document.getElementById('notebook-title').value = '';
        document.getElementById('create-cond-search').value = '';
        document.getElementById('create-cond-codigo').value = '';
        document.getElementById('create-cond-nome').value = '';
        document.getElementById('create-mes').value = '';
        document.getElementById('create-ano').value = '';
        modal.showModal();
        document.getElementById('notebook-title').focus();
    },

    async createNotebook() {
        const titleInput = document.getElementById('notebook-title');
        const title = titleInput.value.trim();
        if (!title) {
            Utils.toast('Digite um nome para o notebook', 'warning');
            return;
        }

        const condCodigo = parseInt(document.getElementById('create-cond-codigo').value) || null;
        const condNome = document.getElementById('create-cond-nome').value || null;
        const mes = parseInt(document.getElementById('create-mes').value) || null;
        const ano = parseInt(document.getElementById('create-ano').value) || null;

        if (!condCodigo) {
            Utils.toast('Selecione um condomínio', 'warning');
            return;
        }
        if (!mes || !ano) {
            Utils.toast('Selecione o mês e o ano', 'warning');
            return;
        }

        try {
            const session = await API.createSession(title, {
                gosati_condominio_codigo: condCodigo,
                gosati_condominio_nome: condNome,
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
            await this.loadNotebooks();
        } catch (e) {
            Utils.toast('Erro ao excluir: ' + e.message, 'error');
        }
    }
};

document.addEventListener('DOMContentLoaded', () => Dashboard.init());

// Enter no modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && document.getElementById('create-modal').open) {
        const active = document.activeElement;
        // Don't submit if focus is on the condominium search (let autocomplete work)
        if (active && active.id === 'create-cond-search') return;
        Dashboard.createNotebook();
    }
});
