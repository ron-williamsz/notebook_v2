/**
 * API Client — fetch wrapper para comunicação com o backend
 */
window.API = {
    baseUrl: '/api/v1',

    async request(method, path, options = {}) {
        const url = this.baseUrl + path;
        const config = {
            method,
            headers: {},
        };

        if (options.body && !(options.body instanceof FormData)) {
            config.headers['Content-Type'] = 'application/json';
            config.body = JSON.stringify(options.body);
        } else if (options.body) {
            config.body = options.body;
        }

        const resp = await fetch(url, config);

        if (resp.status === 401 && !path.startsWith('/auth/')) {
            window.location.href = '/login';
            throw new Error('Sessão expirada');
        }

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
            throw new Error(err.detail || err.error || `Erro ${resp.status}`);
        }

        if (resp.status === 204) return null;
        return resp.json();
    },

    // === Sessions ===
    listSessions()              { return this.request('GET', '/sessions'); },
    createSession(title, opts)  { return this.request('POST', '/sessions', { body: { title, ...opts } }); },
    getSession(id)              { return this.request('GET', `/sessions/${id}`); },
    deleteSession(id)           { return this.request('DELETE', `/sessions/${id}`); },
    getCoverage(id)             { return this.request('GET', `/sessions/${id}/coverage`); },

    // === Sources ===
    listSources(sessionId)      { return this.request('GET', `/sessions/${sessionId}/sources`); },
    uploadFile(sessionId, file) {
        const fd = new FormData();
        fd.append('file', file);
        return this.request('POST', `/sessions/${sessionId}/sources/upload`, { body: fd });
    },
    deleteSource(sessionId, sourceId) {
        return this.request('DELETE', `/sessions/${sessionId}/sources/${sourceId}`);
    },

    // === Chat ===
    async sendMessageStream(sessionId, message, onChunk, onDone) {
        const resp = await fetch(`${this.baseUrl}/sessions/${sessionId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message }),
        });
        await this._readStream(resp, onChunk, onDone);
    },

    async executeSkillStream(sessionId, skillId, message, onChunk, onDone, onProgress) {
        const resp = await fetch(`${this.baseUrl}/sessions/${sessionId}/chat/skill/${skillId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message }),
        });
        await this._readStream(resp, onChunk, onDone, onProgress);
    },

    getChatHistory(sessionId) {
        return this.request('GET', `/sessions/${sessionId}/chat/history`);
    },

    async _readStream(resp, onChunk, onDone, onProgress, onResult, onStepStart, onStepChunk, onCriteriaResult) {
        if (resp.status === 401) {
            window.location.href = '/login';
            return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data === '[DONE]') {
                        if (onDone) onDone();
                        return;
                    }
                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.criteria_result && onCriteriaResult) onCriteriaResult(parsed.criteria_result);
                        else if (parsed.result && onResult) onResult(parsed.result);
                        else if (parsed.step_start && onStepStart) onStepStart(parsed.step_start);
                        else if (parsed.step_chunk && onStepChunk) onStepChunk(parsed.step_chunk);
                        else if (parsed.text && onChunk) onChunk(parsed.text);
                        if (parsed.progress && onProgress) onProgress(parsed.progress);
                        if (parsed.error) {
                            Utils.toast(parsed.error, 'error');
                            if (onDone) onDone();
                            return;
                        }
                    } catch (e) { /* skip */ }
                }
            }
        }
        if (onDone) onDone();
    },

    // === Skills ===
    listSkills()                { return this.request('GET', '/skills'); },
    getSkill(id)                { return this.request('GET', `/skills/${id}`); },
    createSkill(data)           { return this.request('POST', '/skills', { body: data }); },
    updateSkill(id, data)       { return this.request('PUT', `/skills/${id}`, { body: data }); },
    deleteSkill(id)             { return this.request('DELETE', `/skills/${id}`); },

    // Steps
    addStep(skillId, data)      { return this.request('POST', `/skills/${skillId}/steps`, { body: data }); },
    updateStep(skillId, stepId, data) {
        return this.request('PUT', `/skills/${skillId}/steps/${stepId}`, { body: data });
    },
    deleteStep(skillId, stepId) {
        return this.request('DELETE', `/skills/${skillId}/steps/${stepId}`);
    },
    syncSteps(skillId, steps)   { return this.request('PUT', `/skills/${skillId}/steps`, { body: { steps } }); },

    // Criteria
    syncCriteria(skillId, criteria) { return this.request('PUT', `/skills/${skillId}/criteria`, { body: { criteria } }); },

    // Examples
    uploadExample(skillId, file, description) {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('description', description);
        return this.request('POST', `/skills/${skillId}/examples`, { body: fd });
    },
    deleteExample(skillId, exId) {
        return this.request('DELETE', `/skills/${skillId}/examples/${exId}`);
    },

    // === Condomínios ===
    searchCondominios(busca)    { return this.request('GET', `/condominios?busca=${encodeURIComponent(busca)}`); },
    getCondominio()             { return this.request('GET', '/auth/condominio'); },
    setCondominio(codigo, nome) { return this.request('PATCH', '/auth/condominio', { body: { codigo, nome } }); },

    // === GoSATI ===
    browseGoSatiAccounts(condominio, mes, ano) {
        return this.request('GET', `/gosati/accounts?condominio=${condominio}&mes=${mes}&ano=${ano}`);
    },
    queryGoSati(sessionId, data) {
        return this.request('POST', `/sessions/${sessionId}/gosati/source`, { body: data });
    },
    listComprovantes(sessionId, data) {
        return this.request('POST', `/sessions/${sessionId}/gosati/comprovantes`, { body: data });
    },
    downloadComprovantes(sessionId, despesas) {
        return this.request('POST', `/sessions/${sessionId}/gosati/comprovantes/download`, { body: { despesas } });
    },
    resetGoSati(sessionId) {
        return this.request('DELETE', `/sessions/${sessionId}/gosati/reset`);
    },
    resetChatCache(sessionId) {
        return this.request('DELETE', `/sessions/${sessionId}/chat/cache`);
    },

    // === Etapas ===
    listEtapas(sessionId) {
        return this.request('GET', `/sessions/${sessionId}/etapas`);
    },
    createEtapa(sessionId, skillId) {
        return this.request('POST', `/sessions/${sessionId}/etapas`, { body: { skill_id: skillId } });
    },
    async executeEtapa(sessionId, etapaId) {
        return this.request('POST', `/sessions/${sessionId}/etapas/${etapaId}/execute`);
    },
    async streamEtapaEvents(sessionId, etapaId, { onChunk, onDone, onProgress, onResult, onStepStart, onStepChunk, onCriteriaResult, signal } = {}) {
        const resp = await fetch(`${this.baseUrl}/sessions/${sessionId}/etapas/${etapaId}/stream`, { signal });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data === '[DONE]') {
                        if (onDone) onDone();
                        return;
                    }
                    try {
                        const parsed = JSON.parse(data);
                        // Handle terminal events from worker
                        if (parsed.type === 'done') {
                            if (onDone) onDone();
                            return;
                        }
                        if (parsed.type === 'error') {
                            Utils.toast(parsed.error || 'Erro na execução', 'error');
                            if (onDone) onDone();
                            return;
                        }
                        // Forward same SSE events as before
                        if (parsed.criteria_result && onCriteriaResult) onCriteriaResult(parsed.criteria_result);
                        else if (parsed.result && onResult) onResult(parsed.result);
                        else if (parsed.step_start && onStepStart) onStepStart(parsed.step_start);
                        else if (parsed.step_chunk && onStepChunk) onStepChunk(parsed.step_chunk);
                        else if (parsed.text && onChunk) onChunk(parsed.text);
                        if (parsed.progress && onProgress) onProgress(parsed.progress);
                        if (parsed.error) {
                            Utils.toast(parsed.error, 'error');
                            if (onDone) onDone();
                            return;
                        }
                    } catch { /* skip */ }
                }
            }
        }
        if (onDone) onDone();
    },
    deleteEtapa(sessionId, etapaId) {
        return this.request('DELETE', `/sessions/${sessionId}/etapas/${etapaId}`);
    },

    // === Pipeline (Executar Todas) ===
    startPipeline(sessionId) {
        return this.request('POST', `/sessions/${sessionId}/pipeline/start`);
    },
    getPipelineStatus(sessionId) {
        return this.request('GET', `/sessions/${sessionId}/pipeline/status`);
    },
    cancelPipeline(sessionId) {
        return this.request('POST', `/sessions/${sessionId}/pipeline/cancel`);
    },
    getPipelineSummary(sessionId) {
        return this.request('GET', `/sessions/${sessionId}/pipeline/summary`);
    },
    async streamPipeline(sessionId, { onEvent, onDone, signal } = {}) {
        const resp = await fetch(`${this.baseUrl}/sessions/${sessionId}/pipeline/stream`, { signal });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data === '[DONE]') {
                        if (onDone) onDone();
                        return;
                    }
                    try {
                        const parsed = JSON.parse(data);
                        if (onEvent) onEvent(parsed);
                    } catch { /* skip */ }
                }
            }
        }
        if (onDone) onDone();
    },

    // === GoSATI Selection Persistence ===
    saveGoSatiSelection(sessionId, data) {
        return this.request('PATCH', `/sessions/${sessionId}/gosati-selection`, { body: data });
    },

    // === Audit (admin) ===
    getAuditLogs(params)       { return this.request('GET', '/audit?' + new URLSearchParams(params)); },
    getAuditCounters(period)   { return this.request('GET', `/audit/counters?period=${period}`); },
    getAuditUsers(period)      { return this.request('GET', `/audit/users?period=${period}`); },
};

/**
 * Auth — autenticação (logout global)
 */
window.Auth = {
    async logout() {
        try {
            await API.request('POST', '/auth/logout');
        } catch (e) { /* ignore */ }
        window.location.href = '/login';
    },
};
