# Pub Quiz - Development Guide

## Overview

A real-time multiplayer pub quiz app built with Flask, Socket.IO (gevent), and vanilla JS. Players join games via browser, answer trivia questions sourced from OpenTDB, and compete on a live leaderboard. All game state is held in memory (no database).

## Quick Start

```bash
uv venv
uv pip install -r requirements.txt
source .venv/bin/activate
python app.py
```

The app runs on `http://localhost:5000` by default. On macOS, port 5000 is often taken by AirPlay Receiver — either disable it in System Settings > AirDrop & Handoff, or override the port:

```bash
python -c "
from gevent import monkey; monkey.patch_all()
from app import app, socketio
socketio.run(app, host='0.0.0.0', port=5050)
"
```

### Docker

```bash
docker compose up --build
```

## Running Tests

```bash
pytest
```

Tests use `async_mode="threading"` (not gevent) with mocked OpenTDB and question cache. See `tests/conftest.py` for shared fixtures and helpers.

## Architecture

```
app.py                  # Entry point: Flask + SocketIO + gevent setup
config.py               # All constants and defaults (ports, limits, timings, API URLs)
metrics.py              # Prometheus counters/gauges/histograms

api/
  routes.py             # REST endpoints: pages, game CRUD, category proxy
  socket_events.py      # Socket.IO event handlers: join, answer, lifelines, timers
  opentdb.py            # OpenTDB API client with rate limiting and session tokens
  question_cache.py     # Background question pre-fetcher

game/
  models.py             # Dataclasses: Game, Player, Question, GameConfig, GameState
  manager.py            # GameManager: all game state mutations
  scoring.py            # Rank-based scoring (BASE_SCORE + speed bonus)

static/
  js/                   # Per-page JS (home.js, lobby.js, quiz.js, results.js)
  css/style.css

templates/              # Jinja2 templates (base, index, lobby, quiz, results)
```

### Key Design Decisions

- **In-memory state**: All games live in `GameManager.games` dict. No database, no persistence across restarts.
- **gevent async**: The app uses gevent for async I/O (monkey-patched). Use `gevent.sleep()` not `time.sleep()` in any server-side code.
- **Socket.IO rooms**: Each game is a Socket.IO room. Players join on the lobby page and rejoin on page navigation (lobby -> quiz -> results).
- **Reconnect by name**: Players reconnect by matching their name in the game's player list. Handles page navigations and brief disconnects.
- **Progressive question fetch**: Questions can load in batches from OpenTDB while the game is in progress, with a background cache that pre-fetches common categories.
- **Host authority**: Only the host can start games, advance questions, delete games, and trigger replays.

### Game Flow

1. **Home** (`/`) — Create or join a game via REST API
2. **Lobby** (`/lobby/<game_id>`) — Host configures categories/difficulty/time, players join via Socket.IO
3. **Quiz** (`/quiz/<game_id>`) — Questions with countdown timer, lifelines (50:50, Ask the Audience), live answer tracking
4. **Results** (`/results/<game_id>`) — Final rankings, play again option

### Socket.IO Events

**Client -> Server:**
- `join_game` — Join/reconnect to a game
- `start_game` — Host starts the quiz
- `submit_answer` — Player submits an answer
- `use_lifeline` — Player uses 50:50 or Ask the Audience
- `next_question` — Host manually advances
- `update_config` — Host changes game settings
- `play_again` — Host resets for another round
- `delete_game` — Host deletes the game

**Server -> Client:**
- `game_state` — Full state sync on join
- `player_joined` / `player_left` — Roster updates
- `game_started` / `game_starting` — Game launch
- `new_question` — Question + answers + timer
- `tick` — Countdown timer tick
- `player_answered` — Anonymous answer count update
- `question_results` — Correct answer + scores + leaderboard
- `next_question_countdown` — Auto-advance countdown
- `game_finished` — Final rankings
- `lifeline_result` — 50:50 or audience poll result
- `config_updated` — Settings changed
- `game_reset` / `game_deleted` — Lifecycle events

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Home page |
| GET | `/lobby/<game_id>` | Lobby page |
| GET | `/quiz/<game_id>` | Quiz page |
| GET | `/results/<game_id>` | Results page |
| GET | `/api/games` | List joinable games |
| POST | `/api/games` | Create a new game |
| GET | `/api/categories` | Proxy OpenTDB categories |
| GET | `/metrics` | Prometheus metrics |

### Scoring

Correct answer = `BASE_SCORE` (10) + speed bonus. Speed bonus = `N-1` for fastest, `N-2` for second, ..., `0` for slowest correct answer. Wrong/no answer = 0.

### Configuration

All tunables are in `config.py`: player limits, question counts, time limits, OpenTDB rate limits, cache settings. No environment variables needed for local dev.

### External Dependencies

- **OpenTDB** (`opentdb.com`): Trivia question API. Rate limited to one request per ~5.5s. The app uses session tokens to avoid repeat questions and caches categories for 1 hour.
- **Prometheus**: Metrics exposed at `/metrics` for monitoring games, players, answer times, and cache size.
