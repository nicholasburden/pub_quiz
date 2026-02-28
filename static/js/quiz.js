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
const lifelinesBar = document.getElementById('lifelines-bar');
const lifeline5050Btn = document.getElementById('lifeline-5050');
const lifelineAtaBtn = document.getElementById('lifeline-ata');
const ataOverlay = document.getElementById('ata-overlay');
const ataBars = document.getElementById('ata-bars');
const ataCloseBtn = document.getElementById('ata-close');

let currentTimeLimit = 30;
let answered = false;
let selectedAnswer = null;
let lifelinesUsed = { fifty_fifty: false, ask_the_audience: false };
let lifelinesEnabled = true;

// --- Join game room via socket ---
socket.emit('join_game', {
    game_id: gameId,
    player_name: playerName,
    is_host: isHost,
});

// --- Lifeline button handlers ---
lifeline5050Btn.addEventListener('click', () => {
    if (answered || lifelinesUsed.fifty_fifty) return;
    lifeline5050Btn.disabled = true;
    socket.emit('use_lifeline', { lifeline: 'fifty_fifty' });
});

lifelineAtaBtn.addEventListener('click', () => {
    if (answered || lifelinesUsed.ask_the_audience) return;
    lifelineAtaBtn.disabled = true;
    socket.emit('use_lifeline', { lifeline: 'ask_the_audience' });
});

ataCloseBtn.addEventListener('click', () => {
    ataOverlay.style.display = 'none';
});

// --- Lifeline result handler ---
socket.on('lifeline_result', (data) => {
    if (data.lifeline === 'fifty_fifty') {
        lifelinesUsed.fifty_fifty = true;
        lifeline5050Btn.classList.add('used');
        lifeline5050Btn.disabled = true;

        // Hide eliminated answers
        answersContainer.querySelectorAll('.answer-btn').forEach(btn => {
            if (!data.keep_answers.includes(btn.dataset.answer)) {
                btn.classList.add('eliminated');
                btn.disabled = true;
            }
        });
    } else if (data.lifeline === 'ask_the_audience') {
        lifelinesUsed.ask_the_audience = true;
        lifelineAtaBtn.classList.add('used');
        lifelineAtaBtn.disabled = true;

        // Show ATA overlay with bar chart
        const entries = Object.entries(data.percentages).sort((a, b) => b[1] - a[1]);
        ataBars.innerHTML = entries.map(([answer, pct]) => `
            <div class="ata-bar-row">
                <span class="ata-bar-label">${escapeHtml(answer)}</span>
                <div class="ata-bar-track">
                    <div class="ata-bar-fill" style="width: 0%;" data-pct="${pct}"></div>
                </div>
                <span class="ata-bar-pct">${pct}%</span>
            </div>
        `).join('');
        ataOverlay.style.display = 'flex';

        // Animate bars after a brief delay
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                ataBars.querySelectorAll('.ata-bar-fill').forEach(bar => {
                    bar.style.width = bar.dataset.pct + '%';
                });
            });
        });
    }
});

function updateLifelineButtons() {
    if (!lifelinesEnabled) {
        lifelinesBar.style.display = 'none';
        return;
    }
    lifelinesBar.style.display = 'flex';

    if (lifelinesUsed.fifty_fifty) {
        lifeline5050Btn.classList.add('used');
        lifeline5050Btn.disabled = true;
    } else {
        lifeline5050Btn.classList.remove('used');
        lifeline5050Btn.disabled = false;
    }

    if (lifelinesUsed.ask_the_audience) {
        lifelineAtaBtn.classList.add('used');
        lifelineAtaBtn.disabled = true;
    } else {
        lifelineAtaBtn.classList.remove('used');
        lifelineAtaBtn.disabled = false;
    }
}

// --- New question ---
socket.on('new_question', (data) => {
    answered = false;
    selectedAnswer = null;
    currentTimeLimit = data.time_limit;
    if (data.lifelines !== undefined) lifelinesEnabled = data.lifelines;

    questionSection.style.display = 'block';
    resultsSection.style.display = 'none';
    answerStatus.style.display = 'none';
    ataOverlay.style.display = 'none';

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

    // Show lifeline buttons with correct state
    updateLifelineButtons();
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

    // Disable lifeline buttons after answering
    lifeline5050Btn.disabled = true;
    lifelineAtaBtn.disabled = true;

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
        lifeline5050Btn.disabled = true;
        lifelineAtaBtn.disabled = true;
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
    lifelinesBar.style.display = 'none';

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

// --- Restore lifeline state from game_state on reconnect ---
socket.on('game_state', (data) => {
    if (data.state === 'lobby') {
        window.location.href = '/lobby/' + gameId;
    } else if (data.state === 'finished') {
        window.location.href = '/results/' + gameId;
    }

    // Restore lifeline config and state for this player
    if (data.config) {
        lifelinesEnabled = data.config.lifelines;
    }
    if (data.players) {
        const me = data.players.find(p => p.name === playerName);
        if (me && me.lifelines_used) {
            lifelinesUsed.fifty_fifty = me.lifelines_used.includes('fifty_fifty');
            lifelinesUsed.ask_the_audience = me.lifelines_used.includes('ask_the_audience');
        }
    }
});
