/* Home page: game list polling, create/join forms */

const createForm = document.getElementById('create-form');
const gameList = document.getElementById('game-list');
const joinFormContainer = document.getElementById('join-form-container');
const joinForm = document.getElementById('join-form');
const cancelJoin = document.getElementById('cancel-join');

// Restore saved name
const savedName = Session.getPlayerName();
if (savedName) {
    document.getElementById('host-name').value = savedName;
    document.getElementById('player-name').value = savedName;
}

// --- Create game ---
createForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const gameName = document.getElementById('game-name').value.trim();
    const hostName = document.getElementById('host-name').value.trim();
    if (!gameName || !hostName) return;

    const btn = createForm.querySelector('button');
    btn.disabled = true;

    try {
        const resp = await fetch('/api/games', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_name: gameName, player_name: hostName }),
        });
        const data = await resp.json();
        if (data.error) {
            alert(data.error);
            return;
        }
        Session.setPlayerName(hostName);
        Session.setGameId(data.game_id);
        Session.setHost(true);
        window.location.href = '/lobby/' + data.game_id;
    } catch (err) {
        alert('Failed to create game');
    } finally {
        btn.disabled = false;
    }
});

// --- Game list polling ---
function renderGameList(games) {
    if (games.length === 0) {
        gameList.innerHTML = '<p class="muted">No games available. Create one!</p>';
        return;
    }
    gameList.innerHTML = games.map(g => `
        <div class="game-item" data-id="${escapeHtml(g.id)}">
            <div class="game-item-info">
                <div class="game-item-name">${escapeHtml(g.name)}</div>
                <div class="game-item-meta">Host: ${escapeHtml(g.host)} &middot; ${g.player_count}/${g.max_players} players</div>
            </div>
            <button class="btn btn-secondary">Join</button>
        </div>
    `).join('');

    gameList.querySelectorAll('.game-item').forEach(el => {
        el.addEventListener('click', () => {
            const gameId = el.dataset.id;
            document.getElementById('join-game-id').value = gameId;
            joinFormContainer.style.display = 'block';
            document.getElementById('player-name').focus();
        });
    });
}

async function pollGames() {
    try {
        const resp = await fetch('/api/games');
        const games = await resp.json();
        renderGameList(games);
    } catch (err) {
        // Silently retry
    }
}

pollGames();
setInterval(pollGames, 3000);

// --- Join game ---
joinForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const gameId = document.getElementById('join-game-id').value;
    const playerName = document.getElementById('player-name').value.trim();
    if (!gameId || !playerName) return;

    Session.setPlayerName(playerName);
    Session.setGameId(gameId);
    Session.setHost(false);
    window.location.href = '/lobby/' + gameId;
});

cancelJoin.addEventListener('click', () => {
    joinFormContainer.style.display = 'none';
});
