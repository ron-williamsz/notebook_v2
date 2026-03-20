/**
 * Admin Audit Page — Visão "Hoje" + Histórico + Exportação
 */
window.AuditPage = {
    _offset: 0,
    _limit: 50,
    _total: 0,
    _loading: false,
    _requestId: 0,
    _activeTab: 'today',

    async init() {
        this._bindFilters();
        await this._loadToday();
    },

    /* ── Tabs ── */
    switchTab(tab) {
        this._activeTab = tab;
        document.querySelectorAll('.audit-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
        document.getElementById('tab-today').style.display = tab === 'today' ? '' : 'none';
        document.getElementById('tab-history').style.display = tab === 'history' ? '' : 'none';
        if (tab === 'history' && !this._historyLoaded) {
            this._historyLoaded = true;
            this._refreshHistory();
        }
    },

    /* ── Filters ── */
    _bindFilters() {
        ['filter-user', 'filter-action', 'filter-period'].forEach(id => {
            document.getElementById(id).addEventListener('change', () => {
                this._offset = 0;
                this._refreshHistory();
            });
        });
    },

    /* ── TODAY TAB ── */
    async _loadToday() {
        const container = document.getElementById('today-summary');
        try {
            const users = await API.getAuditToday();
            if (!users.length) {
                container.innerHTML = '<p style="color:var(--text-muted); text-align:center; padding:40px">Nenhuma atividade registrada hoje.</p>';
                return;
            }

            const totalActions = users.reduce((s, u) => s + u.total_actions, 0);
            const totalSkills = users.reduce((s, u) => s + u.skills_executed.length, 0);
            const totalPipelines = users.reduce((s, u) => s + u.pipelines, 0);

            let html = `
                <div class="audit-counters" style="margin-bottom:20px">
                    <div class="audit-counter-card">
                        <span class="audit-counter-value">${users.length}</span>
                        <span class="audit-counter-label">Usuários ativos</span>
                    </div>
                    <div class="audit-counter-card">
                        <span class="audit-counter-value">${totalActions}</span>
                        <span class="audit-counter-label">Ações hoje</span>
                    </div>
                    <div class="audit-counter-card">
                        <span class="audit-counter-value">${totalSkills}</span>
                        <span class="audit-counter-label">Skills executadas</span>
                    </div>
                    <div class="audit-counter-card">
                        <span class="audit-counter-value">${totalPipelines}</span>
                        <span class="audit-counter-label">Pipelines</span>
                    </div>
                </div>
            `;

            for (const u of users) {
                html += `<div class="audit-today-user">
                    <div class="audit-today-user-header">
                        <div class="audit-today-user-info">
                            <span class="audit-today-user-name">${Utils.escapeHtml(u.user_name)}</span>
                            <span class="audit-today-user-email">${Utils.escapeHtml(u.user_email)}</span>
                        </div>
                        <div class="audit-today-user-stats">
                            <span class="audit-today-stat">${u.total_actions} ações</span>
                            ${u.last_action ? `<span class="audit-today-stat-muted">última: ${new Date(u.last_action).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'})}</span>` : ''}
                        </div>
                    </div>`;

                // Skills executadas
                if (u.skills_executed.length) {
                    html += `<div class="audit-today-skills">
                        <span class="audit-today-skills-label">Skills executadas:</span>
                        <div class="audit-today-skills-list">`;
                    for (const sk of u.skills_executed) {
                        html += `<span class="audit-today-skill-tag">${Utils.escapeHtml(sk)}</span>`;
                    }
                    html += `</div></div>`;
                }

                // Timeline do dia (ações recentes)
                html += `<div class="audit-today-actions">`;
                for (const a of u.actions) {
                    const label = this._actionLabel(a.action);
                    const color = this._actionColor(a.action);
                    let detail = '';
                    if (a.skill_name) detail = a.skill_name;
                    if (a.condominio) detail += (detail ? ' — ' : '') + a.condominio;
                    if (!detail && a.detail) detail = a.detail;

                    html += `<div class="audit-today-action-row">
                        <span class="audit-today-time">${a.time}</span>
                        <span class="audit-action-badge" style="--badge-color:${color}">${label}</span>
                        <span class="audit-today-action-detail">${detail ? Utils.escapeHtml(detail) : ''}</span>
                    </div>`;
                }
                html += `</div></div>`;
            }

            container.innerHTML = html;
        } catch (e) {
            console.error('Erro ao carregar atividade de hoje:', e);
            container.innerHTML = '<p style="color:var(--text-error); text-align:center; padding:40px">Erro ao carregar atividade de hoje.</p>';
        }
    },

    /* ── HISTORY TAB ── */
    async _refreshHistory() {
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
        }
    },

    async _loadUsers(rid) {
        try {
            const period = document.getElementById('filter-period').value;
            const users = await API.getAuditUsers(period);
            if (rid !== this._requestId) return;
            const select = document.getElementById('filter-user');
            const current = select.value;
            select.innerHTML = '<option value="">Todos os usuários</option>';
            for (const u of users) {
                const opt = document.createElement('option');
                opt.value = u.user_email;
                opt.textContent = `${u.user_name} (${u.total_actions})`;
                if (opt.value === current) opt.selected = true;
                select.appendChild(opt);
            }

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

            const btn = document.getElementById('btn-load-more');
            btn.style.display = (this._offset + this._limit < this._total) ? '' : 'none';
        } catch (e) {
            console.error('Erro ao carregar logs:', e);
        }
    },

    loadMore() {
        this._offset += this._limit;
        const rid = ++this._requestId;
        this._loadLogs(true, rid);
    },

    /* ── Export ── */
    exportCSV(period) {
        window.open(`/api/v1/audit/export?period=${period}`, '_blank');
    },

    /* ── Render helpers ── */
    _actionLabel(action) {
        const map = {
            login: 'Login', logout: 'Logout',
            create_notebook: 'Criar notebook', delete_notebook: 'Excluir notebook',
            execute_skill: 'Executar skill', execute_pipeline: 'Executar todas',
            create_skill: 'Criar skill', update_skill: 'Editar skill',
            delete_skill: 'Excluir skill', import_skill: 'Importar skill',
            change_password: 'Alterar senha', select_condominio: 'Selecionar cond.',
            change_role: 'Alterar role',
        };
        return map[action] || action;
    },

    _actionColor(action) {
        const map = {
            login: '#81c995', logout: '#aaa',
            create_notebook: '#7ba4db', delete_notebook: '#e06c75',
            execute_skill: '#daa520', execute_pipeline: '#daa520',
            create_skill: '#7ba4db', update_skill: '#7ba4db',
            delete_skill: '#e06c75', import_skill: '#7ba4db',
            change_password: '#c678dd', select_condominio: '#56b6c2',
            change_role: '#e5c07b',
        };
        return map[action] || '#aaa';
    },

    _renderEntry(item) {
        const label = this._actionLabel(item.action);
        const color = this._actionColor(item.action);
        const time = item.created_at ? new Date(item.created_at).toLocaleString('pt-BR') : '';

        let detail = '';
        if (item.details) {
            try {
                const d = JSON.parse(item.details);
                const parts = [];
                if (d.skill_name) parts.push(d.skill_name);
                if (d.condominio) parts.push(d.condominio);
                if (d.title) parts.push(d.title);
                if (d.name) parts.push(d.name);
                if (d.session_id && !parts.length) parts.push(`sessão ${d.session_id}`);
                detail = parts.join(' — ');
            } catch (e) { /* */ }
        }
        if (item.resource_id && !detail) {
            detail = `${item.resource_type || ''} #${item.resource_id}`;
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
