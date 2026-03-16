/**
 * Pipeline — Executar Todas as Skills em sequência
 * Mostra progresso em tempo real e resumo final de pendências
 */
window.Pipeline = {
    sessionId: null,
    running: false,
    _abortController: null,

    init(sessionId) {
        this.sessionId = sessionId;
    },

    async startAll() {
        if (this.running) {
            Utils.toast('Pipeline já em execução', 'error');
            return;
        }
        if (!confirm('Executar todas as skills em sequência?')) return;

        this.running = true;
        this._abortController = new AbortController();
        this._setButtonState(true);

        // Mostra painel de progresso
        this._showProgressPanel();

        try {
            // 1. Inicia pipeline no backend
            const result = await API.startPipeline(this.sessionId);

            // Atualiza painel com info das skills
            this._updateProgressSkills(result.skill_names, result.etapa_ids);

            // 2. Recarrega etapas no painel central
            await Etapas.load();

            // 3. Conecta ao SSE stream de progresso
            await API.streamPipeline(this.sessionId, {
                signal: this._abortController.signal,
                onEvent: (event) => this._handleEvent(event),
                onDone: () => this._onPipelineDone(),
            });

        } catch (err) {
            if (err.name === 'AbortError') {
                Utils.toast('Pipeline cancelado', 'info');
            } else {
                Utils.toast('Erro ao iniciar pipeline: ' + err.message, 'error');
            }
            this.running = false;
            this._setButtonState(false);
            this._hideProgressPanel();
        }
    },

    cancel() {
        if (this._abortController) {
            this._abortController.abort();
        }
        API.cancelPipeline(this.sessionId).catch(() => {});
        this.running = false;
    },

    _showProgressPanel() {
        // Remove painel anterior se existir
        const old = document.getElementById('pipeline-progress');
        if (old) old.remove();

        const panel = document.createElement('div');
        panel.id = 'pipeline-progress';
        panel.className = 'pipeline-progress';
        panel.innerHTML = `
            <div class="pipeline-header">
                <div class="pipeline-title">
                    <div class="spinner spinner-sm"></div>
                    <span>Executando todas as skills...</span>
                </div>
                <button class="btn btn-ghost btn-sm" onclick="Pipeline.cancel()" title="Cancelar">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                    </svg>
                </button>
            </div>
            <div class="pipeline-bar">
                <div class="pipeline-bar-fill" id="pipeline-bar-fill" style="width:0%"></div>
            </div>
            <div class="pipeline-status" id="pipeline-status">Preparando...</div>
            <div class="pipeline-skills-list" id="pipeline-skills-list"></div>
        `;

        // Insere no topo do painel de etapas
        const container = document.getElementById('etapas-container');
        if (container) {
            container.insertBefore(panel, container.firstChild);
        }
    },

    _hideProgressPanel() {
        const panel = document.getElementById('pipeline-progress');
        if (panel) panel.remove();
    },

    _updateProgressSkills(skillNames, etapaIds) {
        const list = document.getElementById('pipeline-skills-list');
        if (!list) return;

        list.innerHTML = skillNames.map((name, i) => `
            <div class="pipeline-skill-item" id="pipeline-skill-${i}">
                <span class="pipeline-skill-status pending" id="pipeline-skill-status-${i}">&#9679;</span>
                <span class="pipeline-skill-name">${Utils.escapeHtml(name)}</span>
                <span class="pipeline-skill-info" id="pipeline-skill-info-${i}"></span>
            </div>
        `).join('');
    },

    _handleEvent(event) {
        const statusEl = document.getElementById('pipeline-status');
        const barFill = document.getElementById('pipeline-bar-fill');

        switch (event.type) {
            case 'started':
                if (statusEl) statusEl.textContent = `Iniciando (0/${event.total})...`;
                break;

            case 'skill_start': {
                if (statusEl) statusEl.textContent = `Executando: ${event.skill_name} (${event.index + 1}/${event.total})`;
                const pct = (event.index / event.total) * 100;
                if (barFill) barFill.style.width = pct + '%';

                // Marca skill como executando
                const dot = document.getElementById(`pipeline-skill-status-${event.index}`);
                if (dot) {
                    dot.className = 'pipeline-skill-status running';
                    dot.innerHTML = '<div class="spinner spinner-xs"></div>';
                }
                break;
            }

            case 'progress': {
                const info = document.getElementById(`pipeline-skill-info-${event.index}`);
                if (info) info.textContent = event.message;
                break;
            }

            case 'skill_done': {
                const dot = document.getElementById(`pipeline-skill-status-${event.index}`);
                if (dot) {
                    dot.className = 'pipeline-skill-status done';
                    dot.innerHTML = '&#10003;';
                }
                const info = document.getElementById(`pipeline-skill-info-${event.index}`);
                if (info) info.textContent = 'Concluído';
                break;
            }

            case 'skill_error': {
                const dot = document.getElementById(`pipeline-skill-status-${event.index}`);
                if (dot) {
                    dot.className = 'pipeline-skill-status error';
                    dot.innerHTML = '&#10007;';
                }
                const info = document.getElementById(`pipeline-skill-info-${event.index}`);
                if (info) info.textContent = event.message;
                break;
            }

            case 'error': {
                if (statusEl) statusEl.textContent = `Erro: ${event.message}`;
                break;
            }

            case 'cancelled':
                if (statusEl) statusEl.textContent = 'Pipeline cancelado';
                break;
        }
    },

    async _onPipelineDone() {
        this.running = false;
        this._setButtonState(false);
        const barFill = document.getElementById('pipeline-bar-fill');
        if (barFill) barFill.style.width = '100%';

        const statusEl = document.getElementById('pipeline-status');
        if (statusEl) statusEl.textContent = 'Concluído! Carregando resumo...';

        // Remove spinner do header
        const header = document.querySelector('.pipeline-header .spinner');
        if (header) header.remove();

        // Recarrega etapas
        await Etapas.load();

        // Carrega e exibe resumo
        try {
            const summary = await API.getPipelineSummary(this.sessionId);
            this._renderSummary(summary);
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Concluído';
        }

        // Atualiza dashboard de cobertura
        if (window.Notebook) Notebook.loadCoverage();
    },

    _renderSummary(summary) {
        const panel = document.getElementById('pipeline-progress');
        if (!panel) return;

        const statusEl = document.getElementById('pipeline-status');
        if (statusEl) statusEl.textContent = `Concluído: ${summary.total_skills} skills, ${summary.total_lancamentos} lançamentos, ${summary.total_pendencias} pendência(s)`;

        // Resumo compacto — uma linha por skill
        const list = document.getElementById('pipeline-skills-list');
        if (!list) return;

        let html = '<div class="pipeline-summary-compact">';

        for (const skill of summary.skills) {
            const nPend = skill.divergencias + skill.ausentes;
            const badge = nPend > 0
                ? `<span class="pipeline-badge divergencia">${nPend} pend.</span>`
                : '<span class="pipeline-badge aprovado">OK</span>';

            html += `
                <div class="pipeline-summary-line ${nPend > 0 ? 'has-pendencias' : 'all-ok'}">
                    <span class="pipeline-skill-status done">&#10003;</span>
                    <span class="pipeline-summary-icon" style="color:${skill.skill_color}">${skill.skill_icon}</span>
                    <span class="pipeline-summary-name">${Utils.escapeHtml(skill.skill_name)}</span>
                    <span class="pipeline-summary-lancto">${skill.n_lancto} lancto</span>
                    ${badge}
                </div>`;
        }

        html += '</div>';
        list.innerHTML = html;
    },

    _setButtonState(running) {
        const btn = document.getElementById('btn-execute-all');
        if (!btn) return;
        btn.disabled = running;
        btn.textContent = running ? 'Executando...' : 'Executar todas';
    },
};
