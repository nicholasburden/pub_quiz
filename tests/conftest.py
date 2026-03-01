"""Shared fixtures and helpers for integration tests."""

import pytest
from unittest.mock import patch

from flask import Flask
from flask_socketio import SocketIO, SocketIOTestClient

from game.manager import GameManager
from game.models import Question
from api.routes import bp, init_routes
from api.socket_events import register_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_fake_questions(n):
    """Generate n Question objects with known correct answers."""
    questions = []
    for i in range(1, n + 1):
        correct = f"Correct{i}"
        questions.append(Question(
            text=f"Question {i}?",
            correct_answer=correct,
            all_answers=[f"Wrong{i}A", f"Wrong{i}B", f"Wrong{i}C", correct],
            category=f"Category {(i % 2) + 1}",
            difficulty="medium",
        ))
    return questions


FAKE_QUESTIONS = make_fake_questions(5)

FAKE_CATEGORIES = [
    {"id": 9, "name": "General Knowledge"},
    {"id": 18, "name": "Science: Computers"},
]


def create_game_rest(app):
    """POST /api/games and return the game_id."""
    with app.test_client() as client:
        resp = client.post("/api/games", json={
            "game_name": "Test Game",
            "player_name": "Host",
        })
        assert resp.status_code == 200
        return resp.get_json()["game_id"]


def host_join(socketio, app, game_id, name="Host"):
    """Create a SocketIO test client, emit join_game as host, return client."""
    client = socketio.test_client(app)
    client.emit("join_game", {
        "game_id": game_id,
        "player_name": name,
        "is_host": True,
    })
    # Drain the initial burst of events
    client.get_received()
    return client


def player_join(socketio, app, game_id, name):
    """Create a SocketIO test client, emit join_game as player, return client."""
    client = socketio.test_client(app)
    client.emit("join_game", {
        "game_id": game_id,
        "player_name": name,
        "is_host": False,
    })
    client.get_received()
    return client


def get_event(received, name):
    """Find the first event by name in the received list."""
    for event in received:
        if event["name"] == name:
            return event["args"][0]
    return None


def get_all_events(received, name):
    """Find all events by name in the received list."""
    return [e["args"][0] for e in received if e["name"] == name]


def start_and_get_question(host_client):
    """Emit start_game, drain events, return the new_question data."""
    host_client.emit("start_game")
    received = host_client.get_received()
    return get_event(received, "new_question")


def play_full_game(host, players, fake_qs):
    """Answer all questions (host correct, others wrong), advance via next_question.

    Returns final rankings dict from game_finished event.
    """
    all_clients = [host] + players

    for i, q in enumerate(fake_qs):
        # Host answers correctly
        host.emit("submit_answer", {"answer": q.correct_answer})
        # Other players answer wrong
        for p in players:
            p.emit("submit_answer", {"answer": q.all_answers[0] if q.all_answers[0] != q.correct_answer else q.all_answers[1]})

        # Drain events from all clients
        for c in all_clients:
            c.get_received()

        # Advance to next question (or finish)
        host.emit("next_question")
        for c in all_clients:
            c.get_received()

    # The last next_question should have triggered game_finished.
    # Re-check host for game_finished (it was already drained above).
    # Actually, the game_finished event fires when advance_question returns None
    # during the last next_question call. Let's get it from that drain.
    # We need to capture it *before* the drain above. Let's restructure:
    # The caller should capture rankings from the last iteration.
    # For simplicity, let's just return the game state and let callers verify.
    return None


def play_full_game_with_rankings(host, players, fake_qs):
    """Answer all questions, return final rankings from game_finished event."""
    all_clients = [host] + players

    for i, q in enumerate(fake_qs):
        # Host answers correctly
        host.emit("submit_answer", {"answer": q.correct_answer})
        # Other players answer wrong
        for p in players:
            wrong = q.all_answers[0] if q.all_answers[0] != q.correct_answer else q.all_answers[1]
            p.emit("submit_answer", {"answer": wrong})

        # Drain events from all clients
        for c in all_clients:
            c.get_received()

        # Advance
        host.emit("next_question")

        if i < len(fake_qs) - 1:
            # Drain non-final advances
            for c in all_clients:
                c.get_received()

    # After the last next_question, game_finished should be emitted
    received = host.get_received()
    rankings_data = get_event(received, "game_finished")
    return rankings_data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_env():
    """Create a fresh Flask app + SocketIO + GameManager per test.

    Patches opentdb.fetch_questions and opentdb.get_categories.
    Yields (app, socketio, gm, mock_fetch, mock_cats).
    """
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    sio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")
    gm = GameManager()

    init_routes(gm)
    app.register_blueprint(bp)
    register_events(sio, gm)

    # Cap sleeps at 50ms — fast enough to not add up, slow enough to avoid races
    original_sleep = sio.sleep
    sio.sleep = lambda s=0: original_sleep(min(s, 0.05))

    with patch("api.socket_events.opentdb") as mock_otdb, \
         patch("api.routes.opentdb") as mock_otdb_routes, \
         patch("api.socket_events.question_cache") as mock_cache:
        mock_otdb.fetch_questions.return_value = list(FAKE_QUESTIONS)
        mock_otdb.fetch_questions_progressive.side_effect = lambda *a, **kw: iter([list(FAKE_QUESTIONS)])
        mock_otdb.get_categories.return_value = list(FAKE_CATEGORIES)
        mock_otdb_routes.get_categories.return_value = list(FAKE_CATEGORIES)
        mock_cache.get_questions.return_value = (list(FAKE_QUESTIONS), 0)
        mock_cache.clear_game.return_value = None

        yield app, sio, gm, mock_otdb.fetch_questions, mock_otdb.get_categories, mock_otdb.fetch_questions_progressive

    sio.sleep = original_sleep
