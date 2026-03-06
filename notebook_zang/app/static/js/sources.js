/**
 * Sources — upload e listagem de fontes
 */
window.Sources = {
    sessionId: null,
    sources: [],
    pendingFiles: [],

    async init(sessionId) {
        this.sessionId = sessionId;
        await this.loadSources();
    },

    async loadSources() {
        try {
            this.sources = await API.listSources(this.sessionId);
            this.render();
            Notebook.updateSourceCount(this.sources.length);
        } catch (e) {
            Utils.toast('Erro ao carregar fontes: ' + e.message, 'error');
        }
    },

    render() {
        const list = document.getElementById('source-list');
        const empty = document.getElementById('source-empty');

        if (!this.sources.length) {
            list.innerHTML = '';
            empty.classList.remove('hidden');
            return;
        }

        empty.classList.add('hidden');
        list.innerHTML = this.sources.map(s => `
            <div class="source-item">
                <div class="source-icon">${this.getIcon(s.mime_type)}</div>
                <span class="source-name" title="${Utils.escapeHtml(s.filename)}">${Utils.escapeHtml(s.filename)}</span>
                <button class="source-delete" onclick="Sources.deleteSource(${s.id})" title="Remover">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>
        `).join('');
    },

    getIcon(mimeType) {
        if (mimeType?.includes('pdf')) return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
        if (mimeType?.includes('image')) return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';
        return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    },

    showUploadModal() {
        this.pendingFiles = [];
        document.getElementById('file-input').value = '';
        document.getElementById('upload-file-list').innerHTML = '';
        document.getElementById('upload-file-list').classList.add('hidden');
        document.getElementById('btn-upload').disabled = true;
        document.getElementById('upload-modal').showModal();
    },

    closeUploadModal() {
        document.getElementById('upload-modal').close();
    },

    filesSelected(event) {
        this.pendingFiles = Array.from(event.target.files);
        this.renderPendingFiles();
    },

    dragOver(event) {
        event.preventDefault();
        event.currentTarget.classList.add('dragover');
    },

    dragLeave(event) {
        event.currentTarget.classList.remove('dragover');
    },

    drop(event) {
        event.preventDefault();
        event.currentTarget.classList.remove('dragover');
        this.pendingFiles = Array.from(event.dataTransfer.files);
        this.renderPendingFiles();
    },

    renderPendingFiles() {
        const list = document.getElementById('upload-file-list');
        if (!this.pendingFiles.length) {
            list.classList.add('hidden');
            document.getElementById('btn-upload').disabled = true;
            return;
        }

        list.classList.remove('hidden');
        list.innerHTML = this.pendingFiles.map(f => `
            <div style="display:flex; justify-content:space-between; padding:8px 12px; background:var(--bg-surface); border-radius:var(--radius-sm); font-size:0.85rem;">
                <span>${Utils.escapeHtml(f.name)}</span>
                <span style="color:var(--text-muted)">${Utils.formatBytes(f.size)}</span>
            </div>
        `).join('');
        document.getElementById('btn-upload').disabled = false;
    },

    async uploadFiles() {
        const btn = document.getElementById('btn-upload');
        btn.disabled = true;
        btn.textContent = 'Enviando...';

        try {
            for (const file of this.pendingFiles) {
                await API.uploadFile(this.sessionId, file);
            }
            Utils.toast(`${this.pendingFiles.length} arquivo(s) enviado(s)`, 'success');
            this.closeUploadModal();
            await this.loadSources();
        } catch (e) {
            Utils.toast('Erro no upload: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Fazer upload';
        }
    },

    async deleteSource(sourceId) {
        try {
            await API.deleteSource(this.sessionId, sourceId);
            Utils.toast('Fonte removida', 'success');
            await this.loadSources();
        } catch (e) {
            Utils.toast('Erro ao remover: ' + e.message, 'error');
        }
    }
};
