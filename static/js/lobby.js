/* Lobby: host config panel, player list, start game */

connectSocket();
const gameId = window.GAME_ID;
const playerName = Session.getPlayerName();
let isHost = Session.isHost();

const configSection = document.getElementById('config-section');
const playersSection = document.getElementById('players-section');
const playerList = document.getElementById('player-list');
const playerCount = document.getElementById('player-count');
const waitingMsg = document.getElementById('waiting-msg');
const startBtn = document.getElementById('start-btn');
const startingOverlay = document.getElementById('starting-overlay');

// --- Join via socket ---
socket.emit('join_game', {
    game_id: gameId,
    player_name: playerName,
    is_host: isHost,
});

// --- Game state from server ---
socket.on('game_state', (data) => {
    isHost = data.is_host;
    Session.setHost(isHost);

    if (isHost) {
        configSection.style.display = 'block';
        waitingMsg.style.display = 'none';
        loadCategories(data.config.categories);
        applyConfig(data.config);
    } else {
        configSection.style.display = 'none';
        waitingMsg.style.display = 'block';
    }

    renderPlayers(data.players);

    // If game already started, redirect
    if (data.state === 'playing' || data.state === 'question_active' || data.state === 'question_results') {
        window.location.href = '/quiz/' + gameId;
    } else if (data.state === 'finished') {
        window.location.href = '/results/' + gameId;
    }
});

// --- Player updates ---
socket.on('player_joined', (data) => {
    renderPlayers(data.players);
});

socket.on('player_left', (data) => {
    renderPlayers(data.players);
    // Check if we became host
    if (data.new_host === socket.id) {
        isHost = true;
        Session.setHost(true);
        configSection.style.display = 'block';
        waitingMsg.style.display = 'none';
        loadCategories([]);
    }
});

function renderPlayers(players) {
    playerCount.textContent = players.length;
    playerList.innerHTML = players.map(p => {
        const hostTag = p.is_host ? '<span class="host-tag">Host</span>' : '';
        const cls = p.connected ? '' : 'disconnected';
        return `<li class="${cls}"><span>${escapeHtml(p.name)}</span>${hostTag}</li>`;
    }).join('');
}

// --- Categories ---
let categoriesLoaded = false;
async function loadCategories(selectedIds) {
    if (categoriesLoaded) return;
    try {
        const resp = await fetch('/api/categories');
        const cats = await resp.json();
        const container = document.getElementById('category-list');
        container.innerHTML = cats.map(c => {
            const checked = selectedIds.includes(c.id) ? 'checked' : '';
            return `<label><input type="checkbox" value="${c.id}" ${checked}><span>${escapeHtml(c.name)}</span></label>`;
        }).join('');
        categoriesLoaded = true;

        // Listen for changes
        container.querySelectorAll('input').forEach(cb => {
            cb.addEventListener('change', sendConfig);
        });
    } catch (err) {
        document.getElementById('category-list').innerHTML = '<p class="muted">Failed to load categories</p>';
    }
}

function applyConfig(config) {
    document.getElementById('difficulty').value = config.difficulty;
    document.getElementById('num-questions').value = config.num_questions;
    document.getElementById('num-questions-val').textContent = config.num_questions;
    document.getElementById('time-limit').value = config.time_limit;
    document.getElementById('time-limit-val').textContent = config.time_limit;
}

// --- Config changes ---
function sendConfig() {
    if (!isHost) return;
    const categories = Array.from(document.querySelectorAll('#category-list input:checked')).map(cb => parseInt(cb.value));
    const difficulty = document.getElementById('difficulty').value;
    const num_questions = parseInt(document.getElementById('num-questions').value);
    const time_limit = parseInt(document.getElementById('time-limit').value);

    socket.emit('update_config', { categories, difficulty, num_questions, time_limit });
}

document.getElementById('difficulty').addEventListener('change', sendConfig);
document.getElementById('num-questions').addEventListener('input', (e) => {
    document.getElementById('num-questions-val').textContent = e.target.value;
    sendConfig();
});
document.getElementById('time-limit').addEventListener('input', (e) => {
    document.getElementById('time-limit-val').textContent = e.target.value;
    sendConfig();
});

socket.on('config_updated', (config) => {
    if (!isHost) {
        applyConfig(config);
    }
});

// --- Start game ---
startBtn.addEventListener('click', () => {
    startBtn.disabled = true;
    socket.emit('start_game');
});

socket.on('game_starting', () => {
    startingOverlay.style.display = 'flex';
});

socket.on('game_started', (data) => {
    window.location.href = '/quiz/' + gameId;
});

// --- Delete game ---
document.getElementById('delete-btn').addEventListener('click', () => {
    if (confirm('Delete this game? All players will be removed.')) {
        socket.emit('delete_game');
    }
});

socket.on('game_deleted', () => {
    window.location.href = '/';
});
