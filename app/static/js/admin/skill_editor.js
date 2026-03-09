/**
 * Skill Editor — CRUD de skills na área admin
 */
window.SkillEditor = {
    skillId: null,
    skill: null,
    steps: [],
    criteria: [],
    examples: [],
    saving: false,

    async init() {
        this.skillId = window.SKILL_ID || 0;

        if (this.skillId > 0) {
            await this.loadSkill();
            document.getElementById('page-title').textContent = 'Editar Skill';
            document.getElementById('btn-delete').classList.remove('hidden');
            document.getElementById('btn-export').classList.remove('hidden');
        }
    },

    async loadSkill() {
        try {
            this.skill = await API.getSkill(this.skillId);
            document.getElementById('skill-name').value = this.skill.name;
            document.getElementById('skill-desc').value = this.skill.description;
            document.getElementById('skill-icon').value = this.skill.icon;
            document.getElementById('skill-color').value = this.skill.color;
            document.getElementById('skill-macro').value = this.skill.macro_instruction;

            // Execution mode
            const modeSelect = document.getElementById('skill-execution-mode');
            if (modeSelect) modeSelect.value = this.skill.execution_mode || 'chat';
            this.onModeChange();

            // Deep-copy para não compartilhar referência
            this.steps = (this.skill.steps || []).map(s => ({ ...s }));
            this.criteria = (this.skill.criteria || []).map(c => ({
                nome: c.nome,
                tipo: c.tipo,
                config_json: c.config_json,
                is_active: c.is_active !== false,
            }));
            this.examples = this.skill.examples || [];
            this.renderSteps();
            this.renderCriteria();
            this.renderExamples();
            this.loadGosatiConfig();
        } catch (e) {
            Utils.toast('Erro ao carregar skill: ' + e.message, 'error');
        }
    },

    // --- Execution mode toggle ---

    onModeChange() {
        const mode = document.getElementById('skill-execution-mode').value;
        const stepsSection = document.getElementById('section-steps');
        const criteriaSection = document.getElementById('section-criteria');
        if (stepsSection) stepsSection.classList.toggle('hidden', mode === 'criterios');
        if (criteriaSection) criteriaSection.classList.toggle('hidden', mode !== 'criterios');
    },

    // --- Steps ---

    renderSteps() {
        const list = document.getElementById('steps-list');
        if (!this.steps.length) {
            list.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">Nenhuma etapa adicionada.</p>';
            return;
        }

        list.innerHTML = this.steps.map((step, i) => `
            <div class="step-item" data-id="${step.id || ''}">
                <div class="step-number">${i + 1}</div>
                <div class="step-content">
                    <input type="text" class="input" value="${Utils.escapeHtml(step.title)}"
                           placeholder="Titulo da etapa" oninput="SkillEditor.updateLocalStep(${i}, 'title', this.value)">
                    <textarea class="input" rows="2" placeholder="Instrucao especifica para esta etapa"
                              oninput="SkillEditor.updateLocalStep(${i}, 'instruction', this.value)">${Utils.escapeHtml(step.instruction)}</textarea>
                </div>
                <div class="step-actions">
                    <button class="btn-icon btn-ghost btn-danger" onclick="SkillEditor.removeStep(${i})" title="Remover etapa">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');
    },

    addStep() {
        this.steps.push({ title: '', instruction: '', expected_output: null });
        this.renderSteps();
        const inputs = document.querySelectorAll('.step-item:last-child input');
        if (inputs.length) inputs[0].focus();
    },

    updateLocalStep(index, field, value) {
        this.steps[index][field] = value;
    },

    removeStep(index) {
        this.steps.splice(index, 1);
        this.renderSteps();
    },

    _collectStepsFromDOM() {
        const stepItems = document.querySelectorAll('.step-item');
        stepItems.forEach((el, i) => {
            if (i < this.steps.length) {
                const titleInput = el.querySelector('input');
                const instrTextarea = el.querySelector('textarea');
                if (titleInput) this.steps[i].title = titleInput.value;
                if (instrTextarea) this.steps[i].instruction = instrTextarea.value;
            }
        });
    },

    async syncSteps(skillId) {
        const steps = this.steps
            .filter(s => s.title.trim())
            .map(s => ({
                title: s.title,
                instruction: s.instruction,
                expected_output: s.expected_output || null,
            }));
        await API.syncSteps(skillId, steps);
    },

    // --- Criteria ---

    _criterionDefaults(tipo) {
        if (tipo === 'presenca_documento') {
            return { documento_nome: '', palavras_chave: [], obrigatorio: true, posicao: 'todos' };
        }
        if (tipo === 'classificacao_documento') {
            return { categorias: [] };
        }
        if (tipo === 'conferencia_conteudo') {
            return { campo: '', buscar_em: '', comparar_com: '', instrucao_busca: '', tipo_comparacao: 'igualdade', tolerancia: 0.01 };
        }
        return {};
    },

    _parseCriterionConfig(c) {
        try { return JSON.parse(c.config_json || '{}'); } catch { return {}; }
    },

    addCriterion(tipo) {
        const defaults = this._criterionDefaults(tipo);
        const tipoLabels = {
            presenca_documento: 'Presenca de Documento',
            classificacao_documento: 'Classificacao de Documento',
            conferencia_conteudo: 'Conferencia de Conteudo',
        };
        this.criteria.push({
            nome: tipoLabels[tipo] || tipo,
            tipo,
            config_json: JSON.stringify(defaults),
            is_active: true,
        });
        this.renderCriteria();
        // Focus last criterion's name input
        const items = document.querySelectorAll('.criterion-item');
        if (items.length) {
            const lastInput = items[items.length - 1].querySelector('.criterion-nome');
            if (lastInput) lastInput.focus();
        }
    },

    removeCriterion(index) {
        this.criteria.splice(index, 1);
        this.renderCriteria();
    },

    renderCriteria() {
        const list = document.getElementById('criteria-list');
        if (!list) return;
        if (!this.criteria.length) {
            list.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">Nenhum criterio adicionado.</p>';
            return;
        }

        list.innerHTML = this.criteria.map((c, i) => {
            const config = this._parseCriterionConfig(c);
            const tipoLabels = {
                presenca_documento: 'Presenca',
                classificacao_documento: 'Classificacao',
                conferencia_conteudo: 'Conferencia IA',
            };
            const tipoLabel = tipoLabels[c.tipo] || c.tipo;

            let fieldsHtml = '';
            if (c.tipo === 'presenca_documento') {
                fieldsHtml = this._renderPresencaFields(i, config);
            } else if (c.tipo === 'classificacao_documento') {
                fieldsHtml = this._renderClassificacaoFields(i, config);
            } else if (c.tipo === 'conferencia_conteudo') {
                fieldsHtml = this._renderConferenciaFields(i, config);
            }

            return `
                <div class="criterion-item" style="border:1px solid var(--border); border-radius:var(--radius-sm); padding:12px; margin-bottom:8px;">
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                        <span style="font-size:0.7rem; padding:2px 8px; border-radius:var(--radius-full); background:var(--accent-subtle); color:var(--accent); font-weight:600;">${tipoLabel}</span>
                        <input type="text" class="input criterion-nome" value="${Utils.escapeHtml(c.nome)}"
                               placeholder="Nome do criterio" style="flex:1;"
                               oninput="SkillEditor.updateCriterionField(${i}, 'nome', this.value)">
                        <button class="btn-icon btn-ghost btn-danger" onclick="SkillEditor.removeCriterion(${i})" title="Remover">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                            </svg>
                        </button>
                    </div>
                    ${fieldsHtml}
                </div>`;
        }).join('');
    },

    _renderPresencaFields(idx, config) {
        return `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                <div class="form-group">
                    <label style="font-size:0.8rem;">Nome do documento</label>
                    <input type="text" class="input criterion-cfg" data-idx="${idx}" data-field="documento_nome"
                           value="${Utils.escapeHtml(config.documento_nome || '')}" placeholder="Comprovante, NF, Relatorio...">
                </div>
                <div class="form-group">
                    <label style="font-size:0.8rem;">Palavras-chave (separadas por virgula)</label>
                    <input type="text" class="input criterion-cfg" data-idx="${idx}" data-field="palavras_chave"
                           value="${Utils.escapeHtml((config.palavras_chave || []).join(', '))}" placeholder="comprovante, pagamento">
                </div>
                <div class="form-group">
                    <label style="font-size:0.8rem;">Posicao</label>
                    <select class="input criterion-cfg" data-idx="${idx}" data-field="posicao">
                        <option value="todos" ${config.posicao === 'todos' ? 'selected' : ''}>Todos</option>
                        <option value="primeiro" ${config.posicao === 'primeiro' ? 'selected' : ''}>Primeiro</option>
                        <option value="ultimo" ${config.posicao === 'ultimo' ? 'selected' : ''}>Ultimo</option>
                    </select>
                </div>
                <div class="form-group" style="display:flex; align-items:end;">
                    <label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:0.8rem;">
                        <input type="checkbox" class="criterion-cfg" data-idx="${idx}" data-field="obrigatorio"
                               ${config.obrigatorio !== false ? 'checked' : ''}>
                        Obrigatorio
                    </label>
                </div>
            </div>`;
    },

    _renderClassificacaoFields(idx, config) {
        const categorias = config.categorias || [];
        let catsHtml = categorias.map((cat, ci) => `
            <div style="display:flex; gap:8px; margin-bottom:4px; align-items:center;">
                <input type="text" class="input criterion-cat-nome" data-idx="${idx}" data-ci="${ci}"
                       value="${Utils.escapeHtml(cat.nome || '')}" placeholder="Nome da categoria" style="width:40%;">
                <input type="text" class="input criterion-cat-kw" data-idx="${idx}" data-ci="${ci}"
                       value="${Utils.escapeHtml((cat.palavras_chave || []).join(', '))}" placeholder="Palavras-chave" style="flex:1;">
                <button class="btn-icon btn-ghost btn-danger" onclick="SkillEditor.removeCriterionCat(${idx}, ${ci})" style="flex-shrink:0;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>`).join('');

        return `
            <div class="form-group">
                <label style="font-size:0.8rem;">Categorias</label>
                <div id="criterion-cats-${idx}">${catsHtml}</div>
                <button class="btn btn-outlined btn-sm" onclick="SkillEditor.addCriterionCat(${idx})" style="margin-top:4px; font-size:0.75rem;">
                    + Categoria
                </button>
            </div>`;
    },

    _renderConferenciaFields(idx, config) {
        return `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                <div class="form-group">
                    <label style="font-size:0.8rem;">Campo a buscar</label>
                    <input type="text" class="input criterion-cfg" data-idx="${idx}" data-field="campo"
                           value="${Utils.escapeHtml(config.campo || '')}" placeholder="valor, competencia, favorecido, CNPJ...">
                </div>
                <div class="form-group">
                    <label style="font-size:0.8rem;">Buscar em</label>
                    <input type="text" class="input criterion-cfg" data-idx="${idx}" data-field="buscar_em"
                           value="${Utils.escapeHtml(config.buscar_em || '')}" placeholder="comprovante, nota_fiscal, relatorio...">
                </div>
                <div class="form-group">
                    <label style="font-size:0.8rem;">Comparar com</label>
                    <select class="input criterion-cfg" data-idx="${idx}" data-field="comparar_com">
                        <option value="" ${!config.comparar_com ? 'selected' : ''}>Apenas extrair</option>
                        <option value="lancamento.valor" ${config.comparar_com === 'lancamento.valor' ? 'selected' : ''}>lancamento.valor</option>
                        <option value="lancamento.historico" ${config.comparar_com === 'lancamento.historico' ? 'selected' : ''}>lancamento.historico</option>
                        <option value="lancamento.data" ${config.comparar_com === 'lancamento.data' ? 'selected' : ''}>lancamento.data</option>
                        <option value="periodo.mes_ano" ${config.comparar_com === 'periodo.mes_ano' ? 'selected' : ''}>periodo.mes_ano</option>
                    </select>
                </div>
                <div class="form-group">
                    <label style="font-size:0.8rem;">Tipo comparacao</label>
                    <select class="input criterion-cfg" data-idx="${idx}" data-field="tipo_comparacao">
                        <option value="igualdade" ${config.tipo_comparacao === 'igualdade' ? 'selected' : ''}>Igualdade</option>
                        <option value="contem" ${config.tipo_comparacao === 'contem' ? 'selected' : ''}>Contem</option>
                        <option value="numerico" ${config.tipo_comparacao === 'numerico' ? 'selected' : ''}>Numerico</option>
                    </select>
                </div>
            </div>
            <div class="form-group" style="margin-top:8px;">
                <label style="font-size:0.8rem;">Instrucao extra para a IA (opcional)</label>
                <input type="text" class="input criterion-cfg" data-idx="${idx}" data-field="instrucao_busca"
                       value="${Utils.escapeHtml(config.instrucao_busca || '')}" placeholder="O valor aparece no campo LIQUIDO...">
            </div>`;
    },

    updateCriterionField(idx, field, value) {
        this.criteria[idx][field] = value;
    },

    addCriterionCat(idx) {
        const config = this._parseCriterionConfig(this.criteria[idx]);
        if (!config.categorias) config.categorias = [];
        config.categorias.push({ nome: '', palavras_chave: [] });
        this.criteria[idx].config_json = JSON.stringify(config);
        this.renderCriteria();
    },

    removeCriterionCat(idx, ci) {
        const config = this._parseCriterionConfig(this.criteria[idx]);
        if (config.categorias) config.categorias.splice(ci, 1);
        this.criteria[idx].config_json = JSON.stringify(config);
        this.renderCriteria();
    },

    _collectCriteriaFromDOM() {
        this.criteria.forEach((c, idx) => {
            // Collect nome
            const nomeInput = document.querySelector(`.criterion-nome[oninput*="updateCriterionField(${idx}"]`);
            // Simpler: iterate criterion-items
            const items = document.querySelectorAll('.criterion-item');
            if (items[idx]) {
                const nome = items[idx].querySelector('.criterion-nome');
                if (nome) c.nome = nome.value;
            }

            // Collect config fields
            const config = this._parseCriterionConfig(c);
            document.querySelectorAll(`.criterion-cfg[data-idx="${idx}"]`).forEach(el => {
                const field = el.dataset.field;
                if (!field) return;
                if (el.type === 'checkbox') {
                    config[field] = el.checked;
                } else if (field === 'palavras_chave') {
                    config[field] = el.value.split(',').map(v => v.trim()).filter(Boolean);
                } else if (field === 'tolerancia') {
                    config[field] = parseFloat(el.value) || 0.01;
                } else {
                    config[field] = el.value;
                }
            });

            // Collect classificacao categorias
            if (c.tipo === 'classificacao_documento') {
                const cats = [];
                document.querySelectorAll(`.criterion-cat-nome[data-idx="${idx}"]`).forEach(el => {
                    const ci = parseInt(el.dataset.ci);
                    const kwEl = document.querySelector(`.criterion-cat-kw[data-idx="${idx}"][data-ci="${ci}"]`);
                    cats.push({
                        nome: el.value,
                        palavras_chave: kwEl ? kwEl.value.split(',').map(v => v.trim()).filter(Boolean) : [],
                    });
                });
                config.categorias = cats;
            }

            c.config_json = JSON.stringify(config);
        });
    },

    async syncCriteria(skillId) {
        this._collectCriteriaFromDOM();
        const criteria = this.criteria
            .filter(c => c.nome.trim())
            .map(c => ({
                nome: c.nome,
                tipo: c.tipo,
                config_json: c.config_json,
                is_active: c.is_active !== false,
            }));
        await API.syncCriteria(skillId, criteria);
    },

    // --- Examples ---

    renderExamples() {
        const list = document.getElementById('examples-list');
        if (!this.examples.length) {
            list.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">Nenhum arquivo de exemplo.</p>';
            return;
        }

        list.innerHTML = this.examples.map(ex => `
            <div class="example-item">
                <span class="example-icon">📄</span>
                <div class="example-info">
                    <div class="example-name">${Utils.escapeHtml(ex.filename)}</div>
                    <div class="example-desc">${Utils.escapeHtml(ex.description || 'Sem descricao')}</div>
                </div>
                <button class="btn-icon btn-ghost btn-danger" onclick="SkillEditor.removeExample(${ex.id})" title="Remover">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>
        `).join('');
    },

    async exampleFileSelected(event) {
        const file = event.target.files[0];
        if (!file) return;

        const description = prompt('Descricao do exemplo (o que o LLM deve observar neste arquivo):');
        if (description === null) return;

        if (this.skillId > 0) {
            try {
                await API.uploadExample(this.skillId, file, description);
                Utils.toast('Exemplo adicionado', 'success');
                await this.loadSkill();
            } catch (e) {
                Utils.toast('Erro no upload: ' + e.message, 'error');
            }
        } else {
            Utils.toast('Salve a skill primeiro antes de adicionar exemplos', 'warning');
        }
        event.target.value = '';
    },

    async removeExample(exampleId) {
        if (!confirm('Remover este exemplo?')) return;
        try {
            await API.deleteExample(this.skillId, exampleId);
            Utils.toast('Exemplo removido', 'success');
            await this.loadSkill();
        } catch (e) {
            Utils.toast('Erro: ' + e.message, 'error');
        }
    },

    // --- Save ---

    async save() {
        if (this.saving) return;
        this.saving = true;
        const btn = document.getElementById('btn-save');
        if (btn) btn.disabled = true;

        const gosati = this.collectGosatiConfig();
        const executionMode = document.getElementById('skill-execution-mode').value;
        const data = {
            name: document.getElementById('skill-name').value.trim(),
            description: document.getElementById('skill-desc').value.trim(),
            icon: document.getElementById('skill-icon').value.trim() || '📋',
            color: document.getElementById('skill-color').value,
            macro_instruction: document.getElementById('skill-macro').value.trim(),
            execution_mode: executionMode,
            gosati_sections: gosati.sections,
            gosati_filters: gosati.filters,
        };

        if (!data.name) {
            Utils.toast('Nome obrigatorio', 'warning');
            this.saving = false;
            if (btn) btn.disabled = false;
            return;
        }

        // Coleta valores atuais do DOM
        this._collectStepsFromDOM();
        this._collectCriteriaFromDOM();

        try {
            let skill;
            if (this.skillId > 0) {
                skill = await API.updateSkill(this.skillId, data);
            } else {
                skill = await API.createSkill(data);
                this.skillId = skill.id;
                window.SKILL_ID = skill.id;
                history.replaceState(null, '', `/admin/skills/${skill.id}`);
                document.getElementById('page-title').textContent = 'Editar Skill';
                document.getElementById('btn-delete').classList.remove('hidden');
                document.getElementById('btn-export').classList.remove('hidden');
            }

            // Salva etapas e criterios
            if (executionMode === 'criterios') {
                await this.syncCriteria(skill.id);
            } else {
                await this.syncSteps(skill.id);
            }

            Utils.toast('Skill salva com sucesso!', 'success');
            await this.loadSkill();
        } catch (e) {
            Utils.toast('Erro ao salvar: ' + e.message, 'error');
        } finally {
            this.saving = false;
            if (btn) btn.disabled = false;
        }
    },

    async deleteSkill() {
        if (!confirm('Tem certeza que deseja excluir esta skill?')) return;
        try {
            await API.deleteSkill(this.skillId);
            Utils.toast('Skill excluida', 'success');
            location.href = '/admin/skills';
        } catch (e) {
            Utils.toast('Erro: ' + e.message, 'error');
        }
    },

    exportSkill() {
        if (!this.skillId) return;
        window.location.href = `/api/v1/skills/${this.skillId}/export`;
    },

    // --- GoSATI config ---

    toggleGosati() {
        const enabled = document.getElementById('gosati-enabled').checked;
        document.getElementById('gosati-config').style.display = enabled ? 'block' : 'none';
    },

    loadGosatiConfig() {
        if (!this.skill) return;
        const sections = this.skill.gosati_sections;
        const filters = this.skill.gosati_filters;

        if (sections) {
            document.getElementById('gosati-enabled').checked = true;
            document.getElementById('gosati-config').style.display = 'block';
            try {
                const s = JSON.parse(sections);
                document.querySelectorAll('.gosati-section').forEach(cb => {
                    cb.checked = !!s[cb.value];
                });
            } catch (e) {}
        }

        if (filters) {
            try {
                const f = JSON.parse(filters);
                const fields = [
                    ['nome_conta_despesas', 'gosati-filter-conta-despesas'],
                    ['nome_sub_conta', 'gosati-filter-subconta'],
                    ['historico', 'gosati-filter-historico'],
                ];
                for (const [key, id] of fields) {
                    const vals = f[key] || [];
                    const el = document.getElementById(id);
                    if (el) el.value = Array.isArray(vals) ? vals.join(', ') : vals;
                }
            } catch (e) {}
        }
    },

    collectGosatiConfig() {
        const enabled = document.getElementById('gosati-enabled').checked;
        if (!enabled) return { sections: null, filters: null };

        const sections = {};
        document.querySelectorAll('.gosati-section').forEach(cb => {
            sections[cb.value] = cb.checked;
        });

        const filtersObj = {};
        const fields = [
            ['nome_conta_despesas', 'gosati-filter-conta-despesas'],
            ['nome_sub_conta', 'gosati-filter-subconta'],
            ['historico', 'gosati-filter-historico'],
        ];
        for (const [key, id] of fields) {
            const text = document.getElementById(id).value.trim();
            if (text) {
                const values = text.split(',').map(v => v.trim().toUpperCase()).filter(Boolean);
                if (values.length) filtersObj[key] = values;
            }
        }

        const filters = Object.keys(filtersObj).length ? JSON.stringify(filtersObj) : null;

        return {
            sections: JSON.stringify(sections),
            filters: filters,
        };
    },

    async browseAccounts() {
        const condominio = parseInt(document.getElementById('browse-condominio').value);
        const mes = parseInt(document.getElementById('browse-mes').value);
        const ano = parseInt(document.getElementById('browse-ano').value);

        if (!condominio || !mes || !ano) {
            Utils.toast('Preencha condominio, mes e ano', 'warning');
            return;
        }

        const btn = document.getElementById('btn-browse-accounts');
        btn.disabled = true;
        btn.textContent = 'Consultando...';

        try {
            const result = await API.browseGoSatiAccounts(condominio, mes, ano);
            const container = document.getElementById('browse-accounts-result');
            container.style.display = 'block';

            if (!result.contas || !result.contas.length) {
                container.innerHTML = '<p style="color:var(--text-muted);">Nenhuma despesa encontrada.</p>';
                return;
            }

            let html = '';
            for (const conta of result.contas) {
                const contaEsc = Utils.escapeHtml(conta.nome_conta_despesas);
                html += `<div style="margin-bottom:8px;">`;
                html += `<div style="font-weight:600; cursor:pointer; padding:2px 4px; border-radius:4px;" class="browse-item" onclick="SkillEditor.addFilterValue('gosati-filter-conta-despesas', '${contaEsc}')">`;
                html += `+ ${contaEsc}</div>`;
                for (const sub of conta.sub_contas) {
                    const subEsc = Utils.escapeHtml(sub.nome_sub_conta);
                    html += `<div style="margin-left:20px; cursor:pointer; color:var(--text-muted); padding:2px 4px; border-radius:4px;" class="browse-item" onclick="SkillEditor.addFilterValue('gosati-filter-subconta', '${subEsc}')">`;
                    html += `+ ${subEsc} <span style="font-size:0.75rem;">(${sub.count})</span></div>`;
                }
                html += `</div>`;
            }
            container.innerHTML = html;
        } catch (e) {
            Utils.toast('Erro ao consultar: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Consultar';
        }
    },

    addFilterValue(inputId, value) {
        const input = document.getElementById(inputId);
        const current = input.value.trim();
        const values = current ? current.split(',').map(v => v.trim().toUpperCase()) : [];
        const upper = value.toUpperCase();
        if (!values.includes(upper)) {
            values.push(upper);
            input.value = values.join(', ');
            Utils.toast('Adicionado: ' + value, 'success');
        }
    },
};

document.addEventListener('DOMContentLoaded', () => SkillEditor.init());
