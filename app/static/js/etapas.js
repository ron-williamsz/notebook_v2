/**
 * Etapas — cards de execução de Skills no painel central
 * Mostra lançamentos expandíveis com documentos associados
 */
window.Etapas = {
    sessionId: null,
    etapas: [],
    executing: {},
    _abortControllers: {},

    async init(sessionId) {
        this.sessionId = sessionId;
        await this.load();
    },

    async load() {
        try {
            this.etapas = await API.listEtapas(this.sessionId);
            this.render();
        } catch (e) {
            Utils.toast('Erro ao carregar etapas: ' + e.message, 'error');
        }
    },

    render() {
        const list = document.getElementById('etapas-list');
        const empty = document.getElementById('etapas-empty');

        if (!this.etapas.length) {
            list.innerHTML = '';
            empty.classList.remove('hidden');
            return;
        }

        empty.classList.add('hidden');
        list.innerHTML = this.etapas.map(e => this.renderCard(e)).join('');
    },

    renderCard(etapa) {
        const statusLabels = {
            pending: 'Pendente',
            running: 'Executando...',
            done: 'Concluído',
            error: 'Erro',
            cancelled: 'Cancelado',
        };
        const statusLabel = statusLabels[etapa.status] || etapa.status;

        let bodyHtml = '';
        if (etapa.status === 'running' && !etapa.result_text) {
            bodyHtml = `
                <div class="etapa-card-loading" id="etapa-loading-${etapa.id}">
                    <div class="spinner"></div>
                    <span id="etapa-progress-${etapa.id}">Processando...</span>
                    <button class="btn-stop" onclick="Etapas.stop(${etapa.id})" title="Parar execução">■</button>
                </div>`;
        } else if (etapa.status === 'error' && etapa.error_message) {
            bodyHtml = `<div class="etapa-card-body" style="color:var(--error)">${Utils.escapeHtml(etapa.error_message)}</div>`;
        } else if (etapa.result_text) {
            bodyHtml = `<div class="etapa-card-body" id="etapa-body-${etapa.id}">${this._renderResult(etapa)}</div>`;
        }

        const isRunning = etapa.status === 'running' || this.executing[etapa.id];
        const showExecute = etapa.status === 'pending' || etapa.status === 'error' || etapa.status === 'cancelled';
        const showRerun = etapa.status === 'done';

        let actionsHtml = '';
        if (!isRunning) {
            actionsHtml = `<div class="etapa-card-actions">
                <div>`;
            if (showExecute) {
                actionsHtml += `<button class="btn btn-primary btn-sm" onclick="Etapas.execute(${etapa.id})">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="5 3 19 12 5 21 5 3"/>
                    </svg>
                    Executar
                </button>`;
            }
            if (showRerun) {
                actionsHtml += `<button class="btn btn-outlined btn-sm" onclick="Etapas.execute(${etapa.id})">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
                    </svg>
                    Re-executar
                </button>`;
            }
            actionsHtml += `</div>
                <button class="btn btn-ghost btn-sm" onclick="Etapas.remove(${etapa.id})" title="Remover etapa" style="color:var(--text-muted)">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14H7L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>
                    </svg>
                </button>
            </div>`;
        }

        return `
            <div class="etapa-card ${etapa.status}" id="etapa-card-${etapa.id}" style="border-left: 3px solid ${etapa.skill_color}">
                <div class="etapa-card-header">
                    <span class="etapa-card-icon">${etapa.skill_icon}</span>
                    <span class="etapa-card-title">${Utils.escapeHtml(etapa.skill_name)}</span>
                    <span class="etapa-card-status ${etapa.status}">${statusLabel}</span>
                </div>
                ${bodyHtml}
                ${actionsHtml}
            </div>`;
    },

    // --- Result rendering ---

    _renderResult(etapa) {
        try {
            const data = JSON.parse(etapa.result_text);
            if (data.type === 'criterios') {
                this._currentPrestacaoSourceId = data.prestacao_source_id || null;
                let html = this._renderLancamentos(data, etapa.id);
                if (data.criterios) {
                    html += this._renderCriteriosResult(data.criterios, etapa.id, data.lancamentos);
                }
                return html;
            }
            if (data.type === 'lancamentos') {
                this._currentPrestacaoSourceId = data.prestacao_source_id || null;
                let html = this._renderLancamentos(data, etapa.id);
                if (data.analise_steps && data.analise_steps.length) {
                    html += this._renderAnaliseSteps(data.analise_steps, etapa.id);
                }
                return html;
            }
        } catch (e) {
            // Fallback: render as markdown (compatibilidade com resultados antigos)
        }
        return marked.parse(etapa.result_text);
    },

    _renderCriteriosResult(criterios, etapaId, lancamentos) {
        const resumo = criterios.resumo || {};
        const grupos = criterios.grupos || [];

        // Summary bar global
        const aprovados = resumo.aprovados || 0;
        const divergencias = resumo.divergencias || 0;
        const ausentes = resumo.itens_ausentes || 0;

        let html = `
            <div class="criterios-resumo">
                <div class="criterio-stat aprovado">
                    <span class="criterio-stat-num">${aprovados}</span>
                    <span class="criterio-stat-label">Aprovados</span>
                </div>
                <div class="criterio-stat divergencia">
                    <span class="criterio-stat-num">${divergencias}</span>
                    <span class="criterio-stat-label">Divergências</span>
                </div>
                <div class="criterio-stat ausente">
                    <span class="criterio-stat-num">${ausentes}</span>
                    <span class="criterio-stat-label">Ausentes</span>
                </div>
            </div>`;

        // Painel de Histórico — dados brutos dos lançamentos para comparação
        if (lancamentos && lancamentos.length) {
            html += this._renderHistoricoPanel(lancamentos, etapaId, this._currentPrestacaoSourceId);
        }

        // Render each criterion as a collapsible group
        for (let gi = 0; gi < grupos.length; gi++) {
            const g = grupos[gi];
            const gId = `crit-${etapaId}-${gi}`;
            const hasProblems = (g.divergencias || 0) + (g.ausentes || 0) > 0;
            const allOk = !hasProblems;

            // Group status indicator
            let statusBadge;
            if (allOk) {
                statusBadge = `<span class="criterio-badge aprovado">${g.aprovados} OK</span>`;
            } else {
                const parts = [];
                if (g.divergencias) parts.push(`<span class="criterio-badge divergencia">${g.divergencias} DIVERG.</span>`);
                if (g.ausentes) parts.push(`<span class="criterio-badge ausente">${g.ausentes} AUSENT.</span>`);
                if (g.aprovados) parts.push(`<span class="criterio-badge aprovado">${g.aprovados} OK</span>`);
                statusBadge = parts.join(' ');
            }

            // Auto-expand groups with problems
            const expanded = hasProblems;
            const chevron = expanded ? '▼' : '▶';
            const bodyClass = expanded ? '' : ' hidden';

            html += `
                <div class="criterio-grupo ${hasProblems ? 'has-problems' : 'all-ok'}">
                    <div class="criterio-grupo-header" onclick="Etapas.toggleCriterioGrupo('${gId}')">
                        <span class="criterio-grupo-chevron" id="crit-chev-${gId}">${chevron}</span>
                        <span class="criterio-grupo-nome">${Utils.escapeHtml(g.criterio_nome)}</span>
                        <span class="criterio-grupo-badges">${statusBadge}</span>
                    </div>
                    <div class="criterio-grupo-body${bodyClass}" id="crit-body-${gId}">`;

            // Items table
            const itens = g.itens || [];
            // Sort: problems first, then approved
            const sorted = [...itens].sort((a, b) => {
                const order = { 'DIVERGENCIA': 0, 'ITEM_AUSENTE': 1, 'APROVADO': 2 };
                return (order[a.resultado] ?? 2) - (order[b.resultado] ?? 2);
            });

            html += `<div class="criterio-itens-table">`;
            html += `<div class="criterio-item-header">
                        <span class="ci-col-lanc">Lanç.</span>
                        <span class="ci-col-hist">Histórico</span>
                        <span class="ci-col-valor">Valor</span>
                        <span class="ci-col-result">Status</span>
                        <span class="ci-col-detail">Detalhes</span>
                     </div>`;

            for (const r of sorted) {
                const badgeClass = r.resultado === 'APROVADO' ? 'aprovado'
                                 : r.resultado === 'DIVERGENCIA' ? 'divergencia'
                                 : 'ausente';
                const badgeLabel = r.resultado === 'APROVADO' ? 'OK'
                                 : r.resultado === 'DIVERGENCIA' ? 'DIVERG.'
                                 : 'AUSENTE';

                let detalhes = Utils.escapeHtml(r.detalhes || '');
                if (r.valores && r.valores.encontrado && r.valores.esperado) {
                    detalhes = `<span class="ci-val">Encontrado: ${Utils.escapeHtml(r.valores.encontrado)}</span> <span class="ci-val-sep">→</span> <span class="ci-val">Esperado: ${Utils.escapeHtml(r.valores.esperado)}</span>`;
                }

                const info = r.lancamento_info || {};
                const hist = Utils.escapeHtml((info.historico || '').substring(0, 50));
                const valor = parseFloat(info.valor || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 });

                html += `<div class="criterio-item-row ${badgeClass}" data-resultado="${r.resultado}">
                            <span class="ci-col-lanc">${Utils.escapeHtml(r.lancamento)}</span>
                            <span class="ci-col-hist" title="${Utils.escapeHtml(info.historico || '')}">${hist}</span>
                            <span class="ci-col-valor">R$ ${valor}</span>
                            <span class="ci-col-result"><span class="criterio-badge ${badgeClass}">${badgeLabel}</span></span>
                            <span class="ci-col-detail">${detalhes}</span>
                         </div>`;
            }

            html += `</div></div></div>`;
        }

        return html;
    },

    _renderHistoricoPanel(lancamentos, etapaId, prestacaoSourceId) {
        const panelId = `hist-panel-${etapaId}`;
        let rows = '';

        for (const lanc of lancamentos) {
            const num = Utils.escapeHtml(lanc.numero_lancamento || '');
            const hist = Utils.escapeHtml(lanc.historico || '—');
            const valor = parseFloat(lanc.valor || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 });
            const conta = Utils.escapeHtml(lanc.nome_conta || '');
            const subConta = Utils.escapeHtml(lanc.nome_sub_conta || '');
            const docCount = (lanc.documentos || []).length;
            const temDocto = lanc.tem_docto;
            const docIcon = temDocto
                ? `<span class="hist-doc-flag has" title="GoSATI: tem documento">&#10003;</span>`
                : `<span class="hist-doc-flag none" title="GoSATI: sem documento">&#10007;</span>`;

            // Destaca padrões de NF no histórico
            let histHtml = hist;
            histHtml = histHtml.replace(/(NFE?\s*\d+|NF\.?:\s*\d+|NOTA\s+FISCAL)/gi,
                '<mark class="hist-nf-ref">$1</mark>');
            histHtml = histHtml.replace(/(SEM\s+NF|S\/\s*NF|SEM\s+NOTA)/gi,
                '<mark class="hist-sem-nf">$1</mark>');

            rows += `
                <tr class="hist-row">
                    <td class="hist-col-lanc">${num}</td>
                    <td class="hist-col-hist">${histHtml}</td>
                    <td class="hist-col-valor">R$ ${valor}</td>
                    <td class="hist-col-conta" title="${conta} / ${subConta}">${conta}</td>
                    <td class="hist-col-docs">${docIcon} ${docCount}</td>
                </tr>`;
        }

        // Botão para abrir arquivo fonte da prestação
        const openFileBtn = prestacaoSourceId
            ? `<button class="btn btn-ghost btn-xs hist-open-file" onclick="event.stopPropagation(); Etapas.openViewer('/api/v1/sessions/${this.sessionId}/sources/${prestacaoSourceId}/file', 'text/plain', 'Prestação GoSATI')" title="Abrir arquivo da prestação">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                    <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
                </svg>
                Arquivo
               </button>`
            : '';

        return `
            <div class="historico-panel">
                <div class="historico-panel-header" onclick="Etapas.toggleHistoricoPanel('${panelId}')">
                    <span class="historico-panel-chevron" id="hist-chev-${panelId}">▶</span>
                    <span class="historico-panel-title">Dados do Histórico</span>
                    <span class="historico-panel-count">${lancamentos.length} lançamentos</span>
                    ${openFileBtn}
                </div>
                <div class="historico-panel-body hidden" id="hist-body-${panelId}">
                    <table class="historico-table">
                        <thead>
                            <tr>
                                <th class="hist-col-lanc">Lanç.</th>
                                <th class="hist-col-hist">Histórico</th>
                                <th class="hist-col-valor">Valor</th>
                                <th class="hist-col-conta">Conta</th>
                                <th class="hist-col-docs">Docs</th>
                            </tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>`;
    },

    toggleHistoricoPanel(panelId) {
        const body = document.getElementById(`hist-body-${panelId}`);
        const chev = document.getElementById(`hist-chev-${panelId}`);
        if (!body) return;
        const isHidden = body.classList.contains('hidden');
        body.classList.toggle('hidden');
        if (chev) chev.textContent = isHidden ? '▼' : '▶';
    },

    toggleCriterioGrupo(gId) {
        const body = document.getElementById(`crit-body-${gId}`);
        const chev = document.getElementById(`crit-chev-${gId}`);
        if (!body) return;
        const isHidden = body.classList.contains('hidden');
        body.classList.toggle('hidden');
        if (chev) chev.textContent = isHidden ? '▼' : '▶';
    },

    _renderAnaliseSteps(steps, etapaId) {
        return steps.map((step, idx) => {
            const secId = `step-${etapaId}-${idx}`;
            return `
                <div class="lanc-section">
                    <div class="lanc-section-header" onclick="Etapas.toggleSection('${secId}', 'step')">
                        <span class="lanc-section-chevron" id="step-sec-chev-${secId}">▼</span>
                        <span class="lanc-section-title">${Utils.escapeHtml(step.title)}</span>
                    </div>
                    <div class="lanc-section-body" id="step-sec-body-${secId}">
                        <div class="analise-content">${marked.parse(step.response || '')}</div>
                    </div>
                </div>`;
        }).join('');
    },

    _renderLancamentos(data, etapaId) {
        const count = data.lancamentos ? data.lancamentos.length : 0;
        if (!count) {
            return '<div class="lanc-empty">Nenhum lançamento encontrado para este filtro.</div>';
        }

        const rows = data.lancamentos.map((lanc, idx) => {
            const valor = parseFloat(lanc.valor || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 });
            const dataStr = this._formatDate(lanc.data);
            const hasDoctos = lanc.documentos && lanc.documentos.length > 0;
            const docCount = lanc.documentos ? lanc.documentos.length : 0;
            const docBadge = hasDoctos
                ? `<span class="lanc-doc-badge" title="${docCount} documento(s)">${docCount} doc${docCount > 1 ? 's' : ''}</span>`
                : `<span class="lanc-doc-badge none" title="Sem documentos">0</span>`;

            return `
                <div class="lanc-item" id="lanc-${etapaId}-${idx}">
                    <div class="lanc-row ${hasDoctos ? 'has-docs' : ''}" onclick="Etapas.toggleLanc(${etapaId}, ${idx})">
                        <span class="lanc-chevron" id="lanc-chev-${etapaId}-${idx}">▶</span>
                        <div class="lanc-info">
                            <div class="lanc-historico">${Utils.escapeHtml(lanc.historico || '—')}</div>
                            <div class="lanc-meta">
                                <span class="lanc-num">Lanç. ${Utils.escapeHtml(lanc.numero_lancamento)}</span>
                                <span class="lanc-data">${dataStr}</span>
                            </div>
                        </div>
                        <div class="lanc-valor">R$ ${valor}</div>
                        ${docBadge}
                    </div>
                    <div class="lanc-docs hidden" id="lanc-docs-${etapaId}-${idx}">
                        ${this._renderDocs(lanc.documentos || [])}
                    </div>
                </div>`;
        }).join('');

        return `
            <div class="lanc-section">
                <div class="lanc-section-header" onclick="Etapas.toggleSection(${etapaId}, 'lanc')">
                    <span class="lanc-section-chevron" id="lanc-sec-chev-${etapaId}">▶</span>
                    <span class="lanc-section-title">LANÇAMENTOS</span>
                    <span class="lanc-section-count">${count}</span>
                </div>
                <div class="lanc-section-body hidden" id="lanc-sec-body-${etapaId}">
                    <div class="lanc-list">${rows}</div>
                </div>
            </div>`;
    },

    _renderDocs(docs) {
        if (!docs.length) {
            return '<div class="lanc-docs-empty">Nenhum documento disponível</div>';
        }

        const icons = docs.map(doc => {
            const isImage = doc.mime_type && doc.mime_type.startsWith('image/');
            const isPdf = doc.mime_type === 'application/pdf';
            const fileUrl = `/api/v1/sessions/${this.sessionId}/sources/${doc.source_id}/file`;
            const safeLabel = Utils.escapeHtml(doc.label);
            const safeMime = Utils.escapeHtml(doc.mime_type || '');

            let iconSvg, iconClass;
            if (isPdf) {
                iconClass = 'lanc-doc-icon pdf';
                iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                    <path d="M9 15h6"/><path d="M9 11h6"/>
                </svg>`;
            } else if (isImage) {
                iconClass = 'lanc-doc-icon image';
                iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <polyline points="21 15 16 10 5 21"/>
                </svg>`;
            } else {
                iconClass = 'lanc-doc-icon other';
                iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                </svg>`;
            }

            return `<div class="${iconClass}" onclick="Etapas.openViewer('${fileUrl}', '${safeMime}', '${safeLabel}')" title="${safeLabel}">
                ${iconSvg}
            </div>`;
        }).join('');

        return `<div class="lanc-docs-icons">${icons}</div>`;
    },

    _formatDate(dateStr) {
        if (!dateStr) return '';
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString('pt-BR');
        } catch {
            return dateStr;
        }
    },

    toggleLanc(etapaId, idx) {
        const docs = document.getElementById(`lanc-docs-${etapaId}-${idx}`);
        const chev = document.getElementById(`lanc-chev-${etapaId}-${idx}`);
        if (!docs) return;

        const isHidden = docs.classList.contains('hidden');
        docs.classList.toggle('hidden');
        if (chev) chev.textContent = isHidden ? '▼' : '▶';
    },

    toggleSection(id, section) {
        const body = document.getElementById(`${section}-sec-body-${id}`);
        const chev = document.getElementById(`${section}-sec-chev-${id}`);
        if (!body) return;

        const isHidden = body.classList.contains('hidden');
        body.classList.toggle('hidden');
        if (chev) chev.textContent = isHidden ? '▼' : '▶';
    },

    async openViewer(url, mimeType, label) {
        const overlay = document.getElementById('doc-viewer-overlay');
        const title = document.getElementById('doc-viewer-title');
        const body = document.getElementById('doc-viewer-body');
        if (!overlay || !body) return;

        title.textContent = label;
        overlay.classList.remove('hidden');
        document.addEventListener('keydown', this._viewerEscHandler);

        // Loading spinner enquanto verifica o arquivo
        body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%"><div class="spinner"></div></div>';

        const inlineUrl = url + '?inline=1';
        let realMime = mimeType || '';

        // HEAD request: verifica existência e obtém content-type real do servidor
        try {
            const resp = await fetch(inlineUrl, { method: 'HEAD' });
            if (!resp.ok) {
                body.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);flex-direction:column;gap:12px">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:0.5">
                        <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
                    </svg>
                    <span>Documento não encontrado</span>
                </div>`;
                return;
            }
            // Usa content-type real do servidor (mais confiável que o mime salvo no JSON)
            const ct = resp.headers.get('content-type');
            if (ct) realMime = ct.split(';')[0].trim();
        } catch {
            body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">Erro ao carregar documento</div>';
            return;
        }

        const isImage = realMime.startsWith('image/');
        const isPdf = realMime === 'application/pdf';

        if (isImage) {
            const img = document.createElement('img');
            img.src = inlineUrl;
            img.alt = label;
            img.style.cssText = 'max-width:100%;max-height:100%;object-fit:contain';
            img.onerror = () => {
                body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">Falha ao carregar imagem</div>';
            };
            body.innerHTML = '';
            body.appendChild(img);
        } else if (isPdf) {
            body.innerHTML = `<iframe src="${inlineUrl}#view=FitH" style="width:100%;height:100%;border:none"></iframe>`;
        } else {
            // Fallback: tenta iframe para qualquer outro tipo
            body.innerHTML = `<iframe src="${inlineUrl}" style="width:100%;height:100%;border:none"></iframe>`;
        }
    },

    closeViewer(event) {
        if (event && event.target !== event.currentTarget) return;
        const overlay = document.getElementById('doc-viewer-overlay');
        if (overlay) overlay.classList.add('hidden');
        const body = document.getElementById('doc-viewer-body');
        if (body) body.innerHTML = '';
        document.removeEventListener('keydown', this._viewerEscHandler);
    },

    _viewerEscHandler(e) {
        if (e.key === 'Escape') Etapas.closeViewer();
    },

    // --- CRUD actions ---

    async create(skillId) {
        try {
            const etapa = await API.createEtapa(this.sessionId, skillId);
            this.etapas.push(etapa);
            this.render();
            const card = document.getElementById(`etapa-card-${etapa.id}`);
            if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            return etapa;
        } catch (e) {
            Utils.toast('Erro ao criar etapa: ' + e.message, 'error');
            return null;
        }
    },

    async execute(etapaId) {
        const etapa = this.etapas.find(e => e.id === etapaId);
        if (!etapa) return;

        this.executing[etapaId] = true;
        const abortController = new AbortController();
        this._abortControllers[etapaId] = abortController;
        etapa.status = 'running';
        etapa.result_text = null;
        etapa.error_message = null;
        this.render();

        // Acumula resultados das etapas de análise durante streaming
        const stepTexts = {};

        try {
          // 1. Enfileira no worker (independente do browser)
          await API.executeEtapa(this.sessionId, etapaId);

          // 2. Conecta ao stream de eventos via Redis PubSub
          await API.streamEtapaEvents(this.sessionId, etapaId, {
            signal: abortController.signal,
            onProgress: (msg) => {
                const progress = document.getElementById(`etapa-progress-${etapaId}`);
                if (progress) progress.textContent = msg;
            },
            onResult: (result) => {
                // Resultado estruturado (JSON lançamentos)
                this._currentPrestacaoSourceId = result.prestacao_source_id || null;
                etapa.result_text = JSON.stringify(result);

                const loading = document.getElementById(`etapa-loading-${etapaId}`);
                if (loading) loading.remove();

                let body = document.getElementById(`etapa-body-${etapaId}`);
                if (!body) {
                    const card = document.getElementById(`etapa-card-${etapaId}`);
                    if (card) {
                        const header = card.querySelector('.etapa-card-header');
                        if (header) {
                            const div = document.createElement('div');
                            div.className = 'etapa-card-body';
                            div.id = `etapa-body-${etapaId}`;
                            header.after(div);
                            body = div;
                        }
                    }
                }
                if (body) {
                    body.innerHTML = this._renderLancamentos(result, etapaId);
                }
            },
            onCriteriaResult: (criterios) => {
                // Resultado de critérios estruturados
                const loading = document.getElementById(`etapa-loading-${etapaId}`);
                if (loading) loading.remove();

                let body = document.getElementById(`etapa-body-${etapaId}`);
                if (!body) {
                    const card = document.getElementById(`etapa-card-${etapaId}`);
                    if (card) {
                        const header = card.querySelector('.etapa-card-header');
                        if (header) {
                            const div = document.createElement('div');
                            div.className = 'etapa-card-body';
                            div.id = `etapa-body-${etapaId}`;
                            header.after(div);
                            body = div;
                        }
                    }
                }
                if (body) {
                    // Extrai lancamentos do result_text já salvo
                    let lancamentos = [];
                    if (etapa.result_text) {
                        try { lancamentos = JSON.parse(etapa.result_text).lancamentos || []; } catch {}
                    }
                    body.innerHTML += this._renderCriteriosResult(criterios, etapaId, lancamentos);
                }

                // Merge into result_text
                if (etapa.result_text) {
                    try {
                        const data = JSON.parse(etapa.result_text);
                        data.type = 'criterios';
                        data.criterios = criterios;
                        etapa.result_text = JSON.stringify(data);
                    } catch (e) { /* skip */ }
                }
            },
            onStepStart: ({ index, title }) => {
                stepTexts[index] = '';
                const body = document.getElementById(`etapa-body-${etapaId}`);
                if (!body) return;

                const secId = `step-${etapaId}-${index}`;
                const section = document.createElement('div');
                section.className = 'lanc-section';
                section.id = `step-section-${secId}`;
                section.innerHTML = `
                    <div class="lanc-section-header" onclick="Etapas.toggleSection('${secId}', 'step')">
                        <span class="lanc-section-chevron" id="step-sec-chev-${secId}">▼</span>
                        <span class="lanc-section-title">${Utils.escapeHtml(title)}</span>
                        <div class="spinner spinner-sm"></div>
                    </div>
                    <div class="lanc-section-body" id="step-sec-body-${secId}">
                        <div class="analise-content" id="step-content-${secId}"></div>
                    </div>`;
                body.appendChild(section);
            },
            onStepChunk: ({ index, text }) => {
                if (stepTexts[index] === undefined) stepTexts[index] = '';
                stepTexts[index] += text;

                const secId = `step-${etapaId}-${index}`;
                const content = document.getElementById(`step-content-${secId}`);
                if (content) content.innerHTML = marked.parse(stepTexts[index]);
            },
            onDone: () => {
                delete this.executing[etapaId];
                delete this._abortControllers[etapaId];

                // Remove spinners das seções de step
                document.querySelectorAll(`[id^="step-section-step-${etapaId}"] .spinner`).forEach(s => s.remove());

                // Incorpora step results ao resultado salvo
                if (Object.keys(stepTexts).length && etapa.result_text) {
                    try {
                        const data = JSON.parse(etapa.result_text);
                        // Reconstrói analise_steps a partir dos textos acumulados
                        // (títulos vêm do DOM)
                        data.analise_steps = Object.entries(stepTexts)
                            .sort(([a], [b]) => Number(a) - Number(b))
                            .map(([idx, response]) => {
                                const secId = `step-${etapaId}-${idx}`;
                                const header = document.querySelector(`#step-section-${secId} .lanc-section-title`);
                                return {
                                    title: header ? header.textContent : `Etapa ${Number(idx) + 1}`,
                                    response,
                                };
                            });
                        etapa.result_text = JSON.stringify(data);
                    } catch (e) { /* skip */ }
                }

                if (!etapa.result_text) {
                    etapa.status = 'error';
                    etapa.error_message = 'Nenhuma resposta recebida';
                } else {
                    etapa.status = 'done';
                }
                this.render();
                // Atualiza dashboard de cobertura
                if (window.Notebook) Notebook.loadCoverage();
            },
          });
        } catch (err) {
            delete this.executing[etapaId];
            delete this._abortControllers[etapaId];
            if (err.name === 'AbortError') {
                etapa.status = 'cancelled';
                etapa.error_message = 'Execução cancelada pelo usuário';
            } else {
                etapa.status = 'error';
                etapa.error_message = err.message || 'Erro de rede durante execução';
            }
            this.render();
        }
    },

    stop(etapaId) {
        const controller = this._abortControllers[etapaId];
        if (controller) controller.abort();
    },

    async remove(etapaId) {
        if (!confirm('Remover esta etapa?')) return;
        try {
            await API.deleteEtapa(this.sessionId, etapaId);
        } catch (e) {
            // Se 404, a etapa já foi removida no backend — prosseguir com remoção local
            if (!e.message.includes('404') && !e.message.toLowerCase().includes('não encontrada')) {
                Utils.toast('Erro ao remover etapa: ' + e.message, 'error');
                return;
            }
        }
        this.etapas = this.etapas.filter(e => e.id !== etapaId);
        this.render();
        if (window.Notebook) Notebook.loadCoverage();
    },
};
