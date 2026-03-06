/**
 * Utilitários globais — Toast, helpers
 */
window.Utils = {
    toast(message, type = 'info', duration = 3000) {
        const container = document.getElementById('toast-container');
        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        el.textContent = message;
        container.appendChild(el);
        setTimeout(() => {
            el.style.opacity = '0';
            el.style.transform = 'translateY(10px)';
            el.style.transition = 'all 0.2s';
            setTimeout(() => el.remove(), 200);
        }, duration);
    },

    formatDate(isoString) {
        const d = new Date(isoString);
        return d.toLocaleDateString('pt-BR', {
            day: 'numeric', month: 'short', year: 'numeric'
        });
    },

    formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    randomEmoji() {
        const emojis = ['📊', '📈', '📋', '🔍', '📑', '💼', '🧮', '📝', '🗂️', '📌', '🎯', '⚡'];
        return emojis[Math.floor(Math.random() * emojis.length)];
    }
};
