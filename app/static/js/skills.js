/**
 * Skills — cards no painel direito do notebook
 * Seleção múltipla + botão "Executar selecionadas"
 */
window.Skills = {
    sessionId: null,
    skills: [],
    selectedIds: new Set(),

    async init(sessionId) {
        this.sessionId = sessionId;
        await this.loadSkills();
    },

    async loadSkills() {
        try {
            this.skills = await API.listSkills();
            this.render();
        } catch (e) {
            Utils.toast('Erro ao carregar skills: ' + e.message, 'error');
        }
    },

    render() {
        const grid = document.getElementById('skills-grid');
        const empty = document.getElementById('skills-empty');
        const btn = document.getElementById('btn-execute-skills');

        if (!this.skills.length) {
            grid.innerHTML = '';
            empty.classList.remove('hidden');
            if (btn) btn.disabled = true;
            return;
        }

        empty.classList.add('hidden');
        grid.innerHTML = this.skills
            .filter(s => s.is_active)
            .map(s => {
                const selected = this.selectedIds.has(s.id);
                return `
                <div class="skill-card ${selected ? 'selected' : ''}"
                     onclick="Skills.toggle(${s.id})"
                     title="${Utils.escapeHtml(s.description)}"
                     style="${selected ? `border-color: ${s.color}` : ''}">
                    <div class="skill-card-icon">${s.icon}</div>
                    <div class="skill-card-name">${Utils.escapeHtml(s.name)}</div>
                    ${selected ? '<span class="skill-card-check">✓</span>' : ''}
                </div>`;
            }).join('');

        if (btn) btn.disabled = this.selectedIds.size === 0;
    },

    toggle(skillId) {
        if (this.selectedIds.has(skillId)) {
            this.selectedIds.delete(skillId);
        } else {
            this.selectedIds.add(skillId);
        }
        this.render();
    },

    async executeSelected() {
        if (!this.selectedIds.size) return;
        const ids = [...this.selectedIds];
        this.selectedIds.clear();
        this.render();

        for (const skillId of ids) {
            const etapa = await Etapas.create(skillId);
            if (etapa) {
                Etapas.execute(etapa.id);
            }
        }
    },
};
