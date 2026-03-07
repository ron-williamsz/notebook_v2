/**
 * Chat — interface de conversa com streaming
 */
window.Chat = {
    sessionId: null,
    isStreaming: false,

    async init(sessionId) {
        this.sessionId = sessionId;

        // Carrega histórico
        try {
            const history = await API.getChatHistory(sessionId);
            if (history && history.length) {
                document.getElementById('chat-welcome').classList.add('hidden');
                history.forEach(msg => this.appendBubble(msg.role, msg.text));
            }
        } catch (e) { /* sem histórico */ }
    },

    handleKey(event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            this.send();
        }
    },

    async send() {
        if (this.isStreaming) return;

        const input = document.getElementById('chat-input');
        const message = input.value.trim();
        if (!message) return;

        input.value = '';
        this.autoResize(input);

        const activeSkillId = Skills.activeSkillId;
        await this._stream(message, activeSkillId);
    },

    async executeSkill(skillId) {
        if (this.isStreaming) return;
        const message = 'Analise todos os documentos carregados seguindo rigorosamente as instruções e gere o relatório completo no formato especificado.';
        await this._stream(message, skillId);
    },

    async _stream(message, skillId) {
        // Esconde welcome
        const welcome = document.getElementById('chat-welcome');
        if (welcome) welcome.classList.add('hidden');

        // Bubble do usuário
        this.appendBubble('user', message);

        // Bubble do modelo (com loading indicator)
        const modelBubble = this.appendBubble('model', '');
        const contentEl = modelBubble.querySelector('.bubble-content');
        contentEl.innerHTML = '<div class="loading-indicator"><span class="spinner"></span>Processando...</div>';

        this.isStreaming = true;
        this.toggleSendBtn(false);
        this._setBrainThinking(true);

        let fullText = '';
        let firstChunk = true;

        const onChunk = (text) => {
            if (firstChunk) {
                contentEl.innerHTML = '';
                firstChunk = false;
            }
            fullText += text;
            contentEl.innerHTML = marked.parse(fullText);
            this.scrollToBottom();
        };

        const onProgress = (msg) => {
            if (firstChunk) {
                contentEl.innerHTML = `<div class="loading-indicator"><span class="spinner"></span>${msg}</div>`;
            }
        };

        const onDone = () => {
            this.isStreaming = false;
            this.toggleSendBtn(true);
            this._setBrainThinking(false);
            if (!fullText) contentEl.textContent = '(sem resposta)';
        };

        try {
            if (skillId) {
                await API.executeSkillStream(this.sessionId, skillId, message, onChunk, onDone, onProgress);
            } else {
                await API.sendMessageStream(this.sessionId, message, onChunk, onDone);
            }
        } catch (e) {
            this.isStreaming = false;
            this.toggleSendBtn(true);
            this._setBrainThinking(false);
            contentEl.textContent = 'Erro: ' + e.message;
        }
    },

    appendBubble(role, text) {
        const container = document.getElementById('chat-messages');
        const div = document.createElement('div');
        div.className = `chat-bubble chat-bubble-${role}`;
        div.innerHTML = `<div class="bubble-content markdown-content">${text ? marked.parse(text) : ''}</div>`;
        container.appendChild(div);
        this.scrollToBottom();
        return div;
    },

    scrollToBottom() {
        const el = document.getElementById('chat-messages');
        el.scrollTop = el.scrollHeight;
    },

    toggleSendBtn(enabled) {
        document.getElementById('btn-send').disabled = !enabled;
    },

    autoResize(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
    },

    _setBrainThinking(active) {
        const el = document.querySelector('.skills-hint-icon');
        if (el) el.classList.toggle('thinking', active);
    }
};
