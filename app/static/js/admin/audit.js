/**
 * Admin Audit Page
 */
window.AuditPage = {
    _offset: 0,
    _limit: 50,
    _total: 0,
    _loading: false,
    _requestId: 0,

    async init() {
        this._bindFilters();
        await this._refresh();
    },

    _bindFilters() {
        ['filter-user', 'filter-action', 'filter-period'].forEach(id => {
            document.getElementById(id).addEventListener('change', () => {
                this._offset = 0;
                this._refresh();
            });
        });
    },

    async _refresh() {
        if (this._loading) return;
        this._loading = true;
        const rid = ++this._requestId;
        try {
            await Promise.all([this._loadCounters(rid), this._loadUsers(rid), this._loadLogs(false, rid)]);
        } finally {
            this._loading = false;
        }
    },

    _getParams() {
        const period = document.getElementById('filter-period').value;
        const user_email = document.getElementById('filter-user').value;
        const action = document.getElementById('filter-action').value;
        const params = { period, offset: this._offset, limit: this._limit };
        if (user_email) params.user_email = user_email;
        if (action) params.action = action;
        return params;
    },

    async _loadCounters(rid) {
        try {
            const period = document.getElementById('filter-period').value;
            const data = await API.getAuditCounters(period);
            if (rid !== this._requestId) return;
            const total = Object.values(data).reduce((a, b) => a + b, 0);
            document.getElementById('cnt-total').textContent = total;
            document.getElementById('cnt-logins').textContent = data.login || 0;
            document.getElementById('cnt-notebooks').textContent =
                (data.create_notebook || 0) + (data.delete_notebook || 0);
            document.getElementById('cnt-skills').textContent = data.execute_skill || 0;
            document.getElementById('cnt-pipelines').textContent = data.execute_pipeline || 0;
        } catch (e) {
            console.error('Erro ao carregar contadores:', e);
            Utils.toast('Erro ao carregar contadores de auditoria', 'error');
        }
    },

    async _loadUsers(rid) {
        try {
            const period = document.getElementById('filter-period').value;
            const users = await API.getAuditUsers(period);
            if (rid !== this._requestId) return;
            const select = document.getElementById('filter-user');
            select.innerHTML = '<option value="">Todos os usuários</option>';
            for (const u of users) {
                const opt = document.createElement('option');
                opt.value = u.user_email;
                opt.textContent = `${u.user_name} (${u.total_actions})`;
                select.appendChild(opt);
            }

            // Render users section
            const section = document.getElementById('active-users');
            const list = document.getElementById('users-list');
            if (users.length) {
                section.style.display = '';
                list.innerHTML = users.map(u => `
                    <div class="audit-user-row">
                        <span class="audit-user-name">${Utils.escapeHtml(u.user_name)}</span>
                        <span class="audit-user-email">${Utils.escapeHtml(u.user_email)}</span>
                        <span class="audit-user-actions">${u.total_actions} ações</span>
                        <span class="audit-user-last">${u.last_action ? Utils.formatDate(u.last_action) : '-'}</span>
                    </div>
                `).join('');
            }
        } catch (e) {
            console.error('Erro ao carregar usuários:', e);
            Utils.toast('Erro ao carregar usuários ativos', 'error');
        }
    },

    async _loadLogs(append = false, rid) {
        try {
            const params = this._getParams();
            const data = await API.getAuditLogs(params);
            if (rid !== undefined && rid !== this._requestId) return;
            this._total = data.total;

            const timeline = document.getElementById('audit-timeline');
            const html = data.items.map(item => this._renderEntry(item)).join('');

            if (append) {
                timeline.insertAdjacentHTML('beforeend', html);
            } else {
                timeline.innerHTML = html || '<p style="color:var(--text-muted); text-align:center; padding:40px">Nenhum registro encontrado.</p>';
            }

            // Show/hide load more
            const btn = document.getElementById('btn-load-more');
            btn.style.display = (this._offset + this._limit < this._total) ? '' : 'none';
        } catch (e) {
            console.error('Erro ao carregar logs:', e);
            Utils.toast('Erro ao carregar registros de auditoria', 'error');
        }
    },

    loadMore() {
        this._offset += this._limit;
        const rid = ++this._requestId;
        this._loadLogs(true, rid);
    },

    _renderEntry(item) {
        const actionLabels = {
            login: 'Login',
            logout: 'Logout',
            create_notebook: 'Criar notebook',
            delete_notebook: 'Excluir notebook',
            execute_skill: 'Executar skill',
            execute_pipeline: 'Executar pipeline',
            create_skill: 'Criar skill',
            update_skill: 'Editar skill',
            delete_skill: 'Excluir skill',
            import_skill: 'Importar skill',
            change_password: 'Alterar senha',
            select_condominio: 'Selecionar condomínio',
            change_role: 'Alterar role',
        };
        const actionColors = {
            login: '#81c995',
            logout: '#aaa',
            create_notebook: '#7ba4db',
            delete_notebook: '#e06c75',
            execute_skill: '#daa520',
            execute_pipeline: '#daa520',
            create_skill: '#7ba4db',
            update_skill: '#7ba4db',
            delete_skill: '#e06c75',
            import_skill: '#7ba4db',
            change_password: '#c678dd',
            select_condominio: '#56b6c2',
            change_role: '#e5c07b',
        };

        const label = actionLabels[item.action] || item.action;
        const color = actionColors[item.action] || '#aaa';
        const time = item.created_at ? new Date(item.created_at).toLocaleString('pt-BR') : '';
        let detail = '';
        if (item.details) {
            try {
                const d = JSON.parse(item.details);
                if (d.title) detail = d.title;
                if (d.name) detail = d.name;
                if (d.session_id) detail = `sessão ${d.session_id}`;
                if (d.condominio) detail = d.condominio;
            } catch (e) { /* */ }
        }
        if (item.resource_id && !detail) {
            detail = `${Utils.escapeHtml(item.resource_type || '')} #${Utils.escapeHtml(String(item.resource_id))}`;
        }

        return `<div class="audit-entry">
            <span class="audit-entry-time">${time}</span>
            <span class="audit-entry-user">${Utils.escapeHtml(item.user_name)}</span>
            <span class="audit-action-badge" style="--badge-color:${color}">${label}</span>
            <span class="audit-entry-detail">${detail ? Utils.escapeHtml(detail) : ''}</span>
            <span class="audit-entry-ip">${item.ip_address || ''}</span>
        </div>`;
    },
};

document.addEventListener('DOMContentLoaded', () => AuditPage.init());
