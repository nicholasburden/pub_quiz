/* Shared: socket connection, session storage, utilities */

let socket = null;
function connectSocket() {
    if (!socket) {
        socket = io();
        socket.on('error', (data) => {
            alert(data.message || 'An error occurred');
        });
    }
    return socket;
}

const Session = {
    get(key) { return sessionStorage.getItem(key); },
    set(key, val) { sessionStorage.setItem(key, val); },
    getPlayerName() { return this.get('player_name') || ''; },
    setPlayerName(name) { this.set('player_name', name); },
    getGameId() { return this.get('game_id') || ''; },
    setGameId(id) { this.set('game_id', id); },
    isHost() { return this.get('is_host') === 'true'; },
    setHost(val) { this.set('is_host', val ? 'true' : 'false'); },
};

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

