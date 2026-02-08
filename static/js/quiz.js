/* Quiz: question display, answer buttons, timer, results per question */

connectSocket();
const gameId = window.GAME_ID;
const playerName = Session.getPlayerName();
const isHost = Session.isHost();

const questionCounter = document.getElementById('question-counter');
const categoryBadge = document.getElementById('category-badge');
const difficultyBadge = document.getElementById('difficulty-badge');
const timerFill = document.getElementById('timer-fill');
const timerText = document.getElementById('timer-text');
const questionText = document.getElementById('question-text');
const answersContainer = document.getElementById('answers-container');
const answerStatus = document.getElementById('answer-status');
const questionSection = document.getElementById('question-section');
const resultsSection = document.getElementById('results-section');
const correctAnswerDisplay = document.getElementById('correct-answer-display');
const perPlayerResults = document.getElementById('per-player-results');
const miniLeaderboard = document.getElementById('mini-leaderboard');
const nextCountdown = document.getElementById('next-countdown');
const nextBtn = document.getElementById('next-btn');

let currentTimeLimit = 30;
let answered = false;
let selectedAnswer = null;

// --- Join game room via socket ---
socket.emit('join_game', {
    game_id: gameId,
    player_name: playerName,
    is_host: isHost,
});

// --- New question ---
socket.on('new_question', (data) => {
    answered = false;
    selectedAnswer = null;
    currentTimeLimit = data.time_limit;

    questionSection.style.display = 'block';
    resultsSection.style.display = 'none';
    answerStatus.style.display = 'none';

    questionCounter.textContent = `Question ${data.question_number} / ${data.total_questions}`;
    categoryBadge.textContent = data.category;
    difficultyBadge.textContent = data.difficulty.charAt(0).toUpperCase() + data.difficulty.slice(1);

    questionText.textContent = data.text;

    // Reset timer
    timerFill.style.transition = 'none';
    timerFill.style.width = '100%';
    timerFill.className = 'timer-fill';
    timerText.textContent = data.time_limit + 's';
    // Force reflow then animate
    void timerFill.offsetWidth;
    timerFill.style.transition = `width ${data.time_limit}s linear`;
    timerFill.style.width = '0%';

    // Render answer buttons
    answersContainer.innerHTML = data.answers.map(a => {
        return `<button class="answer-btn" data-answer="${escapeHtml(a)}">${escapeHtml(a)}</button>`;
    }).join('');

    answersContainer.querySelectorAll('.answer-btn').forEach(btn => {
        btn.addEventListener('click', () => submitAnswer(btn));
    });
});

function submitAnswer(btn) {
    if (answered) return;
    answered = true;
    selectedAnswer = btn.dataset.answer;

    // Highlight selected
    answersContainer.querySelectorAll('.answer-btn').forEach(b => {
        b.disabled = true;
    });
    btn.classList.add('selected');

    answerStatus.textContent = 'Answer submitted! Waiting for others...';
    answerStatus.style.display = 'block';

    socket.emit('submit_answer', { answer: selectedAnswer });
}

// --- Timer tick ---
socket.on('tick', (data) => {
    timerText.textContent = data.remaining + 's';

    if (data.remaining <= 5) {
        timerFill.classList.add('danger');
    } else if (data.remaining <= 10) {
        timerFill.classList.add('warning');
    }

    // Auto-disable if time ran out
    if (data.remaining <= 0 && !answered) {
        answered = true;
        answersContainer.querySelectorAll('.answer-btn').forEach(b => {
            b.disabled = true;
        });
        answerStatus.textContent = "Time's up!";
        answerStatus.style.display = 'block';
    }
});

// --- Player answered broadcast ---
socket.on('player_answered', (data) => {
    if (answered) {
        answerStatus.textContent = `${data.answered_count}/${data.total_players} answered`;
    }
});

// --- Question results ---
socket.on('question_results', (data) => {
    questionSection.style.display = 'none';
    resultsSection.style.display = 'block';

    correctAnswerDisplay.textContent = 'Correct answer: ' + data.correct_answer;

    // Show answer buttons with correct/wrong styling
    answersContainer.querySelectorAll('.answer-btn').forEach(btn => {
        if (btn.dataset.answer === data.correct_answer) {
            btn.classList.add('correct');
        } else if (btn.dataset.answer === selectedAnswer && selectedAnswer !== data.correct_answer) {
            btn.classList.add('wrong');
        }
    });

    // Per-player results
    perPlayerResults.innerHTML = data.player_results.map(r => {
        const cls = r.correct ? 'correct-result' : 'wrong-result';
        const scoreClass = r.score_earned > 0 ? 'score-earned' : 'score-zero';
        const timeStr = r.answer_time !== null ? ` (${r.answer_time}s)` : '';
        return `<div class="player-result ${cls}">
            <span>${escapeHtml(r.name)}${timeStr}</span>
            <span class="${scoreClass}">+${r.score_earned}</span>
        </div>`;
    }).join('');

    // Mini leaderboard
    miniLeaderboard.innerHTML = '<h3 style="margin-bottom:0.5rem">Leaderboard</h3>' +
        data.leaderboard.map(r => `
            <div class="mini-lb-item">
                <span>${escapeHtml(r.name)}</span>
                <span>${r.score}</span>
            </div>
        `).join('');

    // Host can skip ahead
    if (isHost) {
        nextBtn.style.display = 'inline-block';
        nextBtn.disabled = false;
    }

    nextCountdown.textContent = '';
});

// --- Next question countdown ---
socket.on('next_question_countdown', (data) => {
    nextCountdown.textContent = `Next question in ${data.remaining}s...`;
});

// --- Host skip to next ---
nextBtn.addEventListener('click', () => {
    nextBtn.disabled = true;
    socket.emit('next_question');
});

// --- Game finished ---
socket.on('game_finished', () => {
    window.location.href = '/results/' + gameId;
});

// --- Redirect if game state is different ---
socket.on('game_state', (data) => {
    if (data.state === 'lobby') {
        window.location.href = '/lobby/' + gameId;
    } else if (data.state === 'finished') {
        window.location.href = '/results/' + gameId;
    }
});
