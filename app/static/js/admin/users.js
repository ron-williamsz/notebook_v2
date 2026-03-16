/**
 * Admin Users Page
 */
window.UsersPage = {
    _roles: {},

    async init() {
        await Promise.all([this._loadRoles(), this._loadSessions()]);
    },

    async _loadRoles() {
        try {
            const roles = await API.request('GET', '/audit/roles');
            this._roles = {};
            for (const r of roles) {
                this._roles[r.user_email] = r.role;
            }
            this._renderRolesTable(roles);
        } catch (e) {
            console.error('Erro ao carregar roles:', e);
        }
    },

    _renderRolesTable(roles) {
        const tbody = document.getElementById('roles-tbody');
        if (!roles.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding:32px">Nenhum role configurado.</td></tr>';
            return;
        }
        tbody.innerHTML = roles.map(r => {
            const isAdmin = r.role === 'admin';
            const badge = isAdmin
                ? '<span class="role-badge role-admin">admin</span>'
                : '<span class="role-badge role-user">user</span>';
            const btnLabel = isAdmin ? 'Remover admin' : 'Tornar admin';
            const btnClass = isAdmin ? 'btn-danger-sm' : 'btn-success-sm';
            const newRole = isAdmin ? 'user' : 'admin';
            const updatedAt = r.updated_at ? new Date(r.updated_at).toLocaleString('pt-BR') : '-';

            return `<tr>
                <td>${Utils.escapeHtml(r.user_email)}</td>
                <td>${badge}</td>
                <td>${updatedAt}</td>
                <td>
                    <button class="btn btn-outlined btn-sm ${btnClass}" onclick="UsersPage.toggleRole('${Utils.escapeHtml(r.user_email)}', '${newRole}')">
                        ${btnLabel}
                    </button>
                </td>
            </tr>`;
        }).join('');
    },

    async toggleRole(email, newRole) {
        try {
            await API.request('PUT', '/audit/roles', { body: { user_email: email, role: newRole } });
            Utils.toast(`Role de ${email} alterado para ${newRole}`, 'success');
            await this._loadRoles();
            await this._loadSessions();
        } catch (e) {
            Utils.toast(e.message || 'Erro ao alterar role', 'error');
        }
    },

    async addRole() {
        const input = document.getElementById('new-admin-email');
        const email = input.value.trim().toLowerCase();
        if (!email || !email.includes('@')) {
            Utils.toast('Informe um email valido', 'error');
            return;
        }
        try {
            await API.request('PUT', '/audit/roles', { body: { user_email: email, role: 'admin' } });
            Utils.toast(`${email} adicionado como admin`, 'success');
            input.value = '';
            await this._loadRoles();
        } catch (e) {
            Utils.toast(e.message || 'Erro ao adicionar admin', 'error');
        }
    },

    async _loadSessions() {
        try {
            const sessions = await API.request('GET', '/audit/sessions');
            const tbody = document.getElementById('sessions-tbody');

            if (!sessions.length) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:32px">Nenhuma sessao ativa.</td></tr>';
                return;
            }

            tbody.innerHTML = sessions.map(s => {
                const roleBadge = s.role === 'admin'
                    ? '<span class="role-badge role-admin">admin</span>'
                    : '<span class="role-badge role-user">user</span>';
                const loginAt = s.created_at ? new Date(s.created_at).toLocaleString('pt-BR') : '-';
                const expiresAt = s.expires_at ? new Date(s.expires_at).toLocaleString('pt-BR') : '-';

                return `<tr>
                    <td><strong>${Utils.escapeHtml(s.user_name)}</strong></td>
                    <td>${Utils.escapeHtml(s.user_email)}</td>
                    <td>${roleBadge}</td>
                    <td>${Utils.escapeHtml(s.condominio || '-')}</td>
                    <td>${loginAt}</td>
                    <td>${expiresAt}</td>
                </tr>`;
            }).join('');
        } catch (e) {
            console.error('Erro ao carregar sessoes:', e);
            Utils.toast('Erro ao carregar sessoes ativas', 'error');
        }
    },
};

document.addEventListener('DOMContentLoaded', () => UsersPage.init());
