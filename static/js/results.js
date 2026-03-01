/* Results: final leaderboard, podium, play again */

connectSocket();
const gameId = window.GAME_ID;
const playerName = Session.getPlayerName();
const isHost = Session.isHost();

const podiumEl = document.getElementById('podium');
const fullLeaderboard = document.getElementById('full-leaderboard');
const playAgainBtn = document.getElementById('play-again-btn');

// --- Join game room to get state ---
socket.emit('join_game', {
    game_id: gameId,
    player_name: playerName,
    is_host: isHost,
});

socket.on('game_state', (data) => {
    if (data.state === 'lobby') {
        window.location.href = '/lobby/' + gameId;
    } else if (data.state === 'question_active' || data.state === 'playing' || data.state === 'question_results') {
        window.location.href = '/quiz/' + gameId;
    }
});

// --- Receive final results ---
socket.on('game_finished', (data) => {
    renderResults(data.rankings);
});

function renderResults(rankings) {
    if (!rankings || rankings.length === 0) return;

    // Podium (top 3)
    const podiumOrder = [1, 0, 2]; // 2nd, 1st, 3rd for visual layout
    const podiumClasses = ['podium-2', 'podium-1', 'podium-3'];
    let podiumHtml = '';

    podiumOrder.forEach((idx, i) => {
        if (idx < rankings.length) {
            const r = rankings[idx];
            podiumHtml += `
                <div class="podium-place ${podiumClasses[i]}">
                    <div class="podium-bar">
                        <div class="podium-rank">${r.rank}</div>
                    </div>
                    <div class="podium-name">${escapeHtml(r.name)}</div>
                    <div class="podium-score">${r.score} pts</div>
                </div>
            `;
        }
    });
    podiumEl.innerHTML = podiumHtml;

    // Full leaderboard
    fullLeaderboard.innerHTML = rankings.map(r => `
        <li>
            <span class="lb-name">${escapeHtml(r.name)}</span>
            <span class="lb-score">${r.score} pts</span>
        </li>
    `).join('');

    // Play again (host only)
    if (isHost) {
        playAgainBtn.style.display = 'inline-block';
    }
}

// --- Play again ---
playAgainBtn.addEventListener('click', () => {
    socket.emit('play_again');
});

socket.on('game_reset', () => {
    window.location.href = '/lobby/' + gameId;
});
