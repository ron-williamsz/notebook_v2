/**
 * Seletor de condomínio — tela pós-login
 */
window.CondSelector = {
    _searchTimer: null,
    _selected: null,

    init() {
        const input = document.getElementById('cond-search');
        const btn = document.getElementById('btn-continuar');

        input.addEventListener('input', () => this.search(input.value));
        input.addEventListener('focus', () => {
            if (input.value.length >= 2) this.search(input.value);
        });

        document.addEventListener('click', (e) => {
            const list = document.getElementById('cond-list');
            if (list && !list.contains(e.target) && e.target !== input) {
                list.classList.add('hidden');
            }
        });

        btn.addEventListener('click', () => this.confirm());

        // Se já tem valor pré-preenchido, habilitar botão
        const codigo = document.getElementById('cond-codigo').value;
        if (codigo) {
            this._selected = { codigo: parseInt(codigo), nome: '' };
            btn.disabled = false;
        }
    },

    search(value) {
        clearTimeout(this._searchTimer);
        const list = document.getElementById('cond-list');

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
                            this.select(
                                parseInt(item.dataset.codigo),
                                item.dataset.nome
                            );
                        });
                    });
                }
                list.classList.remove('hidden');
            } catch (e) {
                list.classList.add('hidden');
            }
        }, 250);
    },

    select(codigo, nome) {
        document.getElementById('cond-codigo').value = codigo;
        document.getElementById('cond-search').value = `${codigo} — ${nome}`;
        document.getElementById('cond-list').classList.add('hidden');
        document.getElementById('btn-continuar').disabled = false;
        this._selected = { codigo, nome };
    },

    async confirm() {
        if (!this._selected) return;
        const btn = document.getElementById('btn-continuar');
        btn.disabled = true;
        btn.textContent = 'Salvando...';
        try {
            await API.request('PATCH', '/auth/condominio', {
                body: this._selected,
            });
            window.location.href = '/';
        } catch (e) {
            Utils.toast('Erro ao salvar seleção: ' + e.message, 'error');
            btn.disabled = false;
            btn.textContent = 'Continuar';
        }
    },
};

document.addEventListener('DOMContentLoaded', () => CondSelector.init());
