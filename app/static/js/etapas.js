/**
 * Etapas — cards de execução de Skills no painel central
 * Mostra lançamentos expandíveis com documentos associados
 */
window.Etapas = {
    sessionId: null,
    etapas: [],
    executing: {},

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
        };
        const statusLabel = statusLabels[etapa.status] || etapa.status;

        let bodyHtml = '';
        if (etapa.status === 'running' && !etapa.result_text) {
            bodyHtml = `
                <div class="etapa-card-loading" id="etapa-loading-${etapa.id}">
                    <div class="spinner"></div>
                    <span id="etapa-progress-${etapa.id}">Processando...</span>
                </div>`;
        } else if (etapa.status === 'error' && etapa.error_message) {
            bodyHtml = `<div class="etapa-card-body" style="color:var(--error)">${Utils.escapeHtml(etapa.error_message)}</div>`;
        } else if (etapa.result_text) {
            bodyHtml = `<div class="etapa-card-body" id="etapa-body-${etapa.id}">${this._renderResult(etapa)}</div>`;
        }

        const isRunning = etapa.status === 'running' || this.executing[etapa.id];
        const showExecute = etapa.status === 'pending' || etapa.status === 'error';
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
                let html = this._renderLancamentos(data, etapa.id);
                if (data.criterios) {
                    html += this._renderCriteriosResult(data.criterios, etapa.id);
                }
                return html;
            }
            if (data.type === 'lancamentos') {
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

    _renderCriteriosResult(criterios, etapaId) {
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

    openViewer(url, mimeType, label) {
        const overlay = document.getElementById('doc-viewer-overlay');
        const title = document.getElementById('doc-viewer-title');
        const body = document.getElementById('doc-viewer-body');
        if (!overlay || !body) return;

        title.textContent = label;
        const inlineUrl = url + '?inline=1';

        const isImage = mimeType && mimeType.startsWith('image/');
        const isPdf = mimeType === 'application/pdf';

        if (isImage) {
            body.innerHTML = `<img src="${inlineUrl}" alt="${Utils.escapeHtml(label)}"/>`;
        } else if (isPdf) {
            body.innerHTML = `<iframe src="${inlineUrl}#view=FitH"></iframe>`;
        } else {
            body.innerHTML = `<iframe src="${inlineUrl}"></iframe>`;
        }

        overlay.classList.remove('hidden');
        document.addEventListener('keydown', this._viewerEscHandler);
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
        etapa.status = 'running';
        etapa.result_text = null;
        etapa.error_message = null;
        this.render();

        // Acumula resultados das etapas de análise durante streaming
        const stepTexts = {};

        await API.executeEtapaStream(this.sessionId, etapaId, {
            onProgress: (msg) => {
                const progress = document.getElementById(`etapa-progress-${etapaId}`);
                if (progress) progress.textContent = msg;
            },
            onResult: (result) => {
                // Resultado estruturado (JSON lançamentos)
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
                    body.innerHTML += this._renderCriteriosResult(criterios, etapaId);
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
    },

    async remove(etapaId) {
        if (!confirm('Remover esta etapa?')) return;
        try {
            await API.deleteEtapa(this.sessionId, etapaId);
            this.etapas = this.etapas.filter(e => e.id !== etapaId);
            this.render();
        } catch (e) {
            Utils.toast('Erro ao remover etapa: ' + e.message, 'error');
        }
    },
};
