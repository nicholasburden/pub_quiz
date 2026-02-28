"""Integration tests for the pub quiz app."""

from tests.conftest import (
    FAKE_CATEGORIES,
    FAKE_QUESTIONS,
    create_game_rest,
    get_all_events,
    get_event,
    host_join,
    make_fake_questions,
    player_join,
    play_full_game_with_rankings,
    start_and_get_question,
)
from game.models import GameState


# ==========================================================================
# 1. TestGameCreation
# ==========================================================================

class TestGameCreation:

    def test_create_game_returns_game_id(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        assert game_id is not None
        assert len(game_id) == 6
        assert game_id in gm.games

    def test_missing_fields_returns_400(self, app_env):
        app, *_ = app_env
        with app.test_client() as client:
            # Missing both
            resp = client.post("/api/games", json={})
            assert resp.status_code == 400

            # Missing player_name
            resp = client.post("/api/games", json={"game_name": "Test"})
            assert resp.status_code == 400

            # Missing game_name
            resp = client.post("/api/games", json={"player_name": "Host"})
            assert resp.status_code == 400

            # Empty strings
            resp = client.post("/api/games", json={"game_name": "", "player_name": ""})
            assert resp.status_code == 400

    def test_host_joins_via_socket(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)

        client = sio.test_client(app)
        client.emit("join_game", {
            "game_id": game_id,
            "player_name": "Host",
            "is_host": True,
        })
        received = client.get_received()

        state = get_event(received, "game_state")
        assert state is not None
        assert state["is_host"] is True
        assert state["state"] == "lobby"
        assert len(state["players"]) == 1
        assert state["players"][0]["name"] == "Host"

        client.disconnect()

    def test_player_joins_host_gets_player_joined(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        player = player_join(sio, app, game_id, "Alice")

        received = host.get_received()
        pj = get_event(received, "player_joined")
        assert pj is not None
        assert pj["name"] == "Alice"
        assert len(pj["players"]) == 2

        host.disconnect()
        player.disconnect()

    def test_duplicate_name_rejected(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Try to join with the same name as the host
        dup = sio.test_client(app)
        dup.emit("join_game", {
            "game_id": game_id,
            "player_name": "Host",
            "is_host": False,
        })
        received = dup.get_received()
        err = get_event(received, "error")
        assert err is not None
        assert "taken" in err["message"].lower() or "Name" in err["message"]

        host.disconnect()
        dup.disconnect()


# ==========================================================================
# 2. TestGameListing
# ==========================================================================

class TestGameListing:

    def test_joinable_game_appears(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        with app.test_client() as client:
            resp = client.get("/api/games")
            games = resp.get_json()
            assert any(g["id"] == game_id for g in games)

        host.disconnect()

    def test_non_lobby_game_not_listed(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Start the game
        host.emit("start_game")
        host.get_received()

        with app.test_client() as client:
            resp = client.get("/api/games")
            games = resp.get_json()
            assert not any(g["id"] == game_id for g in games)

        host.disconnect()

    def test_all_disconnected_cleaned_up(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Disconnect the host
        host.disconnect()

        with app.test_client() as client:
            resp = client.get("/api/games")
            games = resp.get_json()
            assert not any(g["id"] == game_id for g in games)
        # Game should be cleaned up
        assert game_id not in gm.games

    def test_player_count_shows_connected_only(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")
        p2 = player_join(sio, app, game_id, "Bob")

        # Disconnect one player
        p2.disconnect()
        host.get_received()  # drain player_left

        with app.test_client() as client:
            resp = client.get("/api/games")
            games = resp.get_json()
            game_info = next(g for g in games if g["id"] == game_id)
            assert game_info["player_count"] == 2  # host + Alice

        host.disconnect()
        p1.disconnect()


# ==========================================================================
# 3. TestConfig
# ==========================================================================

class TestConfig:

    def test_host_updates_config(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")
        p1.get_received()  # drain join events

        host.emit("update_config", {
            "num_questions": 20,
            "time_limit": 45,
            "difficulty": "hard",
        })

        received = p1.get_received()
        cfg = get_event(received, "config_updated")
        assert cfg is not None
        assert cfg["num_questions"] == 20
        assert cfg["time_limit"] == 45
        assert cfg["difficulty"] == "hard"

        host.disconnect()
        p1.disconnect()

    def test_non_host_update_ignored(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")
        host.get_received()  # drain player_joined

        p1.emit("update_config", {"num_questions": 50})

        # Host should NOT receive config_updated
        received = host.get_received()
        assert get_event(received, "config_updated") is None

        # Config unchanged
        game = gm.get_game(game_id)
        assert game.config.num_questions == 10  # default

        host.disconnect()
        p1.disconnect()

    def test_values_clamped(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Below min
        host.emit("update_config", {"num_questions": 1, "time_limit": 1})
        received = host.get_received()
        cfg = get_event(received, "config_updated")
        assert cfg["num_questions"] == 5   # MIN_QUESTIONS
        assert cfg["time_limit"] == 10     # MIN_TIME_LIMIT

        # Above max
        host.emit("update_config", {"num_questions": 999, "time_limit": 999})
        received = host.get_received()
        cfg = get_event(received, "config_updated")
        assert cfg["num_questions"] == 50  # MAX_QUESTIONS
        assert cfg["time_limit"] == 60    # MAX_TIME_LIMIT

        host.disconnect()

    def test_config_only_in_lobby(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Start the game to leave LOBBY
        host.emit("start_game")
        host.get_received()

        # Try config update
        host.emit("update_config", {"num_questions": 20})
        received = host.get_received()
        assert get_event(received, "config_updated") is None

        host.disconnect()


# ==========================================================================
# 4. TestGameStart
# ==========================================================================

class TestGameStart:

    def test_start_game_emits_events(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        host.emit("start_game")
        received = host.get_received()

        assert get_event(received, "game_starting") is not None
        assert get_event(received, "game_started") is not None

        nq = get_event(received, "new_question")
        assert nq is not None
        assert nq["question_number"] == 1
        game = gm.get_game(game_id)
        assert nq["total_questions"] == game.config.num_questions

        host.disconnect()

    def test_fetch_called_with_config(self, app_env):
        app, sio, gm, mock_fetch, mock_cats, mock_fetch_prog = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        host.emit("update_config", {
            "num_questions": 15,
            "difficulty": "easy",
            "categories": [9, 18],
        })
        host.get_received()

        # Update mock to return enough questions for 15
        mock_fetch_prog.side_effect = lambda *a, **kw: iter([make_fake_questions(15)])

        host.emit("start_game")
        host.get_received()

        mock_fetch_prog.assert_called_once_with(
            amount=15,
            categories=[9, 18],
            difficulty="easy",
        )

        host.disconnect()

    def test_non_host_cannot_start(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        p1.emit("start_game")
        received = p1.get_received()

        # Should not get game_starting
        assert get_event(received, "game_starting") is None
        assert get_event(received, "game_started") is None

        # Game still in LOBBY
        game = gm.get_game(game_id)
        assert game.state == GameState.LOBBY

        host.disconnect()
        p1.disconnect()

    def test_fetch_failure_returns_error(self, app_env):
        app, sio, gm, mock_fetch, mock_cats, mock_fetch_prog = app_env
        mock_fetch_prog.side_effect = lambda *a, **kw: iter([])  # empty = failure

        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        host.emit("start_game")
        received = host.get_received()

        err = get_event(received, "error")
        assert err is not None
        assert "fetch" in err["message"].lower() or "Failed" in err["message"]

        # Game still in LOBBY
        game = gm.get_game(game_id)
        assert game.state == GameState.LOBBY

        host.disconnect()


# ==========================================================================
# 5. TestAnswering
# ==========================================================================

class TestAnswering:

    def test_submit_answer_broadcasts(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        start_and_get_question(host)
        p1.get_received()  # drain start events

        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        received = p1.get_received()

        pa = get_event(received, "player_answered")
        assert pa is not None
        assert pa["answered_count"] == 1
        assert pa["total_players"] == 2

        host.disconnect()
        p1.disconnect()

    def test_double_submit_ignored(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        host.get_received()

        # Second submit
        host.emit("submit_answer", {"answer": "Wrong1A"})
        received = host.get_received()

        # Should not get another player_answered (the double was rejected)
        assert get_event(received, "player_answered") is None

        host.disconnect()

    def test_all_answered_triggers_results(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        start_and_get_question(host)
        p1.get_received()

        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        host.get_received()

        p1.emit("submit_answer", {"answer": "Wrong1A"})

        # Check that question_results was broadcast
        received = host.get_received()
        qr = get_event(received, "question_results")
        assert qr is not None
        assert qr["correct_answer"] == FAKE_QUESTIONS[0].correct_answer

        host.disconnect()
        p1.disconnect()

    def test_correct_answer_scores(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        received = host.get_received()

        qr = get_event(received, "question_results")
        assert qr is not None
        pr = qr["player_results"][0]
        assert pr["correct"] is True
        assert pr["score_earned"] == 10  # BASE_SCORE, no speed bonus for solo

        host.disconnect()

    def test_wrong_answer_zero_score(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        host.emit("submit_answer", {"answer": "Wrong1A"})
        received = host.get_received()

        qr = get_event(received, "question_results")
        assert qr is not None
        pr = qr["player_results"][0]
        assert pr["correct"] is False
        assert pr["score_earned"] == 0

        host.disconnect()


# ==========================================================================
# 6. TestQuestionFlow
# ==========================================================================

class TestQuestionFlow:

    def test_next_question_advances(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        # Answer Q1
        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        host.get_received()

        # Advance
        host.emit("next_question")
        received = host.get_received()

        nq = get_event(received, "new_question")
        assert nq is not None
        assert nq["question_number"] == 2

        host.disconnect()

    def test_non_host_cannot_advance(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        start_and_get_question(host)
        p1.get_received()

        # Both answer
        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        p1.emit("submit_answer", {"answer": "Wrong1A"})
        host.get_received()
        p1.get_received()

        # Non-host tries to advance
        p1.emit("next_question")
        received = host.get_received()
        assert get_event(received, "new_question") is None

        host.disconnect()
        p1.disconnect()

    def test_last_question_finishes_game(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        # Play through all 5 questions
        for i in range(5):
            host.emit("submit_answer", {"answer": FAKE_QUESTIONS[i].correct_answer})
            host.get_received()
            host.emit("next_question")
            received = host.get_received()

            if i < 4:
                nq = get_event(received, "new_question")
                assert nq is not None
                assert nq["question_number"] == i + 2
            else:
                gf = get_event(received, "game_finished")
                assert gf is not None
                assert len(gf["rankings"]) == 1
                assert gf["rankings"][0]["rank"] == 1

        game = gm.get_game(game_id)
        assert game.state == GameState.FINISHED

        host.disconnect()

    def test_next_question_only_in_results_state(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        # Try next_question while in QUESTION_ACTIVE (before answering)
        host.emit("next_question")
        received = host.get_received()
        assert get_event(received, "new_question") is None

        host.disconnect()


# ==========================================================================
# 7. TestSinglePlayerLifecycle
# ==========================================================================

class TestSinglePlayerLifecycle:

    def test_full_single_player_game(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Update config
        host.emit("update_config", {"num_questions": 5, "time_limit": 30})
        host.get_received()

        # Start game
        host.emit("start_game")
        received = host.get_received()
        assert get_event(received, "game_started") is not None

        nq = get_event(received, "new_question")
        assert nq["question_number"] == 1

        cumulative_score = 0

        for i in range(5):
            q = FAKE_QUESTIONS[i]

            if i > 0:
                # After the first, new_question was from the previous next_question
                pass

            # Answer correctly
            host.emit("submit_answer", {"answer": q.correct_answer})
            received = host.get_received()

            qr = get_event(received, "question_results")
            assert qr is not None
            pr = qr["player_results"][0]
            assert pr["correct"] is True
            assert pr["score_earned"] == 10  # solo player, no speed bonus
            cumulative_score += pr["score_earned"]
            assert pr["total_score"] == cumulative_score

            # Advance
            host.emit("next_question")
            received = host.get_received()

            if i < 4:
                nq = get_event(received, "new_question")
                assert nq is not None
                assert nq["question_number"] == i + 2
            else:
                gf = get_event(received, "game_finished")
                assert gf is not None
                assert gf["rankings"][0]["score"] == cumulative_score
                assert gf["rankings"][0]["rank"] == 1

        game = gm.get_game(game_id)
        assert game.state == GameState.FINISHED
        assert cumulative_score == 50  # 5 * BASE_SCORE (10), no speed bonus solo

        host.disconnect()


# ==========================================================================
# 8. TestMultiPlayerLifecycle
# ==========================================================================

class TestMultiPlayerLifecycle:

    def test_two_players_host_wins(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Loser")

        host.emit("start_game")
        host.get_received()
        p1.get_received()

        rankings = play_full_game_with_rankings(host, [p1], FAKE_QUESTIONS)
        assert rankings is not None
        assert rankings["rankings"][0]["name"] == "Host"
        assert rankings["rankings"][0]["score"] > 0
        assert rankings["rankings"][1]["name"] == "Loser"
        assert rankings["rankings"][1]["score"] == 0

        host.disconnect()
        p1.disconnect()

    def test_three_players_mixed_rankings(self, app_env):
        app, sio, gm, mock_fetch, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")
        p2 = player_join(sio, app, game_id, "Bob")

        host.emit("start_game")
        host.get_received()
        p1.get_received()
        p2.get_received()

        # Host: always correct, Alice: correct on odd questions, Bob: always wrong
        for i in range(5):
            q = FAKE_QUESTIONS[i]

            host.emit("submit_answer", {"answer": q.correct_answer})
            if i % 2 == 1:
                p1.emit("submit_answer", {"answer": q.correct_answer})
            else:
                wrong = q.all_answers[0] if q.all_answers[0] != q.correct_answer else q.all_answers[1]
                p1.emit("submit_answer", {"answer": wrong})
            wrong = q.all_answers[0] if q.all_answers[0] != q.correct_answer else q.all_answers[1]
            p2.emit("submit_answer", {"answer": wrong})

            # Drain
            host.get_received()
            p1.get_received()
            p2.get_received()

            host.emit("next_question")

            if i < 4:
                host.get_received()
                p1.get_received()
                p2.get_received()

        received = host.get_received()
        gf = get_event(received, "game_finished")
        assert gf is not None
        rankings = gf["rankings"]
        assert rankings[0]["name"] == "Host"
        assert rankings[1]["name"] == "Alice"
        assert rankings[2]["name"] == "Bob"
        assert rankings[0]["score"] > rankings[1]["score"] > rankings[2]["score"]
        assert rankings[2]["score"] == 0

        host.disconnect()
        p1.disconnect()
        p2.disconnect()


# ==========================================================================
# 9. TestDisconnectReconnect
# ==========================================================================

class TestDisconnectReconnect:

    def test_disconnect_marks_player_disconnected(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        p1.disconnect()

        game = gm.get_game(game_id)
        # Alice should still be in players dict but disconnected
        alice = [p for p in game.players.values() if p.name == "Alice"]
        assert len(alice) == 1
        assert alice[0].connected is False

        host.disconnect()

    def test_host_disconnect_promotes_next(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")
        p1.get_received()  # drain join events

        host.disconnect()

        received = p1.get_received()
        pl = get_event(received, "player_left")
        assert pl is not None

        game = gm.get_game(game_id)
        # Alice should now be host
        new_host = game.players.get(game.host_sid)
        assert new_host is not None
        assert new_host.name == "Alice"
        assert new_host.is_host is True

        p1.disconnect()

    def test_reconnect_in_lobby(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        # Disconnect Alice
        p1.disconnect()
        host.get_received()  # drain player_left

        # Reconnect Alice with a new client
        p1_new = player_join(sio, app, game_id, "Alice")

        game = gm.get_game(game_id)
        alice = [p for p in game.players.values() if p.name == "Alice"]
        assert len(alice) == 1
        assert alice[0].connected is True

        host.disconnect()
        p1_new.disconnect()

    def test_reconnect_during_active_game(self, app_env):
        """Regression: reconnect by name must work during QUESTION_ACTIVE state."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        # Start game
        host.emit("start_game")
        host.get_received()
        p1.get_received()

        # Disconnect Alice during active question
        p1.disconnect()
        host.get_received()  # drain player_left

        # Reconnect Alice
        p1_new = player_join(sio, app, game_id, "Alice")

        game = gm.get_game(game_id)
        alice = [p for p in game.players.values() if p.name == "Alice"]
        assert len(alice) == 1
        assert alice[0].connected is True

        # Alice can still answer
        p1_new_received = p1_new.get_received()
        # She should have gotten game_state
        # (player_join re-emits game_state which we already drained in player_join helper)
        # Let's verify she can submit an answer
        q = FAKE_QUESTIONS[0]
        p1_new.emit("submit_answer", {"answer": q.correct_answer})
        # Should not get an error - just check it was accepted
        game = gm.get_game(game_id)
        alice = [p for p in game.players.values() if p.name == "Alice"]
        assert alice[0].current_answer == q.correct_answer

        host.disconnect()
        p1_new.disconnect()

    def test_game_survives_disconnect_in_finished(self, app_env):
        """Regression: game must not be deleted when player disconnects in FINISHED state."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        # Start and play through
        host.emit("start_game")
        host.get_received()
        p1.get_received()

        for i in range(5):
            host.emit("submit_answer", {"answer": FAKE_QUESTIONS[i].correct_answer})
            p1.emit("submit_answer", {"answer": "Wrong"})
            host.get_received()
            p1.get_received()
            host.emit("next_question")
            host.get_received()
            p1.get_received()

        game = gm.get_game(game_id)
        assert game.state == GameState.FINISHED

        # Alice disconnects
        p1.disconnect()

        # Game should still exist
        assert game_id in gm.games

        host.disconnect()

    def test_disconnect_during_question_remaining_answers_trigger_results(self, app_env):
        """When a player disconnects during active question, remaining answers
        should be enough to trigger question_results."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        start_and_get_question(host)
        p1.get_received()

        # Host answers
        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        host.get_received()

        # Alice disconnects (hasn't answered) — this should trigger results
        # since all *connected* players (just host) have answered
        p1.disconnect()

        received = host.get_received()
        # Should get both player_left and question_results
        qr = get_event(received, "question_results")
        assert qr is not None
        assert qr["correct_answer"] == FAKE_QUESTIONS[0].correct_answer

        host.disconnect()

    def test_rejoin_finished_game_gets_rankings(self, app_env):
        """Regression: rejoining a finished game should re-send game_finished."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Play through entire game solo
        host.emit("start_game")
        host.get_received()

        for i in range(5):
            host.emit("submit_answer", {"answer": FAKE_QUESTIONS[i].correct_answer})
            host.get_received()
            host.emit("next_question")
            host.get_received()

        game = gm.get_game(game_id)
        assert game.state == GameState.FINISHED

        # Host disconnects and reconnects (simulating page navigation)
        host.disconnect()

        host2 = sio.test_client(app)
        host2.emit("join_game", {
            "game_id": game_id,
            "player_name": "Host",
            "is_host": True,
        })
        received = host2.get_received()

        gf = get_event(received, "game_finished")
        assert gf is not None
        assert len(gf["rankings"]) == 1
        assert gf["rankings"][0]["name"] == "Host"

        host2.disconnect()


# ==========================================================================
# 10. TestPlayAgain
# ==========================================================================

class TestPlayAgain:

    def _play_to_finish(self, app_env):
        """Helper: create game, play through, return (host, game_id)."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        host.emit("start_game")
        host.get_received()

        for i in range(5):
            host.emit("submit_answer", {"answer": FAKE_QUESTIONS[i].correct_answer})
            host.get_received()
            host.emit("next_question")
            host.get_received()

        return host, game_id

    def test_play_again_resets_to_lobby(self, app_env):
        app, sio, gm, *_ = app_env
        host, game_id = self._play_to_finish(app_env)

        game = gm.get_game(game_id)
        assert game.state == GameState.FINISHED
        old_score = [p for p in game.players.values()][0].score
        assert old_score > 0

        host.emit("play_again")
        received = host.get_received()

        gr = get_event(received, "game_reset")
        assert gr is not None

        game = gm.get_game(game_id)
        assert game.state == GameState.LOBBY
        # Score reset
        for p in game.players.values():
            assert p.score == 0

        host.disconnect()

    def test_game_reset_broadcast(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        host.emit("start_game")
        host.get_received()
        p1.get_received()

        for i in range(5):
            host.emit("submit_answer", {"answer": FAKE_QUESTIONS[i].correct_answer})
            p1.emit("submit_answer", {"answer": "Wrong"})
            host.get_received()
            p1.get_received()
            host.emit("next_question")
            host.get_received()
            p1.get_received()

        host.emit("play_again")
        received = p1.get_received()
        assert get_event(received, "game_reset") is not None

        host.disconnect()
        p1.disconnect()

    def test_play_again_disconnect_doesnt_delete(self, app_env):
        """Regression: play_again then disconnect should not delete the game."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        host.emit("start_game")
        host.get_received()
        p1.get_received()

        for i in range(5):
            host.emit("submit_answer", {"answer": FAKE_QUESTIONS[i].correct_answer})
            p1.emit("submit_answer", {"answer": "Wrong"})
            host.get_received()
            p1.get_received()
            host.emit("next_question")
            host.get_received()
            p1.get_received()

        host.emit("play_again")
        host.get_received()
        p1.get_received()

        # Host disconnects (e.g. page navigation back to lobby)
        host.disconnect()

        # Game should still exist because Alice is still connected
        assert game_id in gm.games

        # Alice should now be host
        game = gm.get_game(game_id)
        alice = [p for p in game.players.values() if p.name == "Alice"]
        assert alice[0].is_host is True

        p1.disconnect()

    def test_non_host_cannot_play_again(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        host.emit("start_game")
        host.get_received()
        p1.get_received()

        for i in range(5):
            host.emit("submit_answer", {"answer": FAKE_QUESTIONS[i].correct_answer})
            p1.emit("submit_answer", {"answer": "Wrong"})
            host.get_received()
            p1.get_received()
            host.emit("next_question")
            host.get_received()
            p1.get_received()

        # Non-host tries play_again
        p1.emit("play_again")
        received = host.get_received()
        assert get_event(received, "game_reset") is None

        game = gm.get_game(game_id)
        assert game.state == GameState.FINISHED

        host.disconnect()
        p1.disconnect()


# ==========================================================================
# 11. TestDeleteGame
# ==========================================================================

class TestDeleteGame:

    def test_host_deletes_game(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        host.emit("delete_game")
        received = host.get_received()

        gd = get_event(received, "game_deleted")
        assert gd is not None
        assert game_id not in gm.games

        host.disconnect()

    def test_non_host_cannot_delete(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        p1.emit("delete_game")

        # Game still exists
        assert game_id in gm.games

        host.disconnect()
        p1.disconnect()

    def test_delete_with_multiple_players_all_notified(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")
        p2 = player_join(sio, app, game_id, "Bob")
        p1.get_received()  # drain join events
        p2.get_received()

        host.emit("delete_game")

        r1 = p1.get_received()
        r2 = p2.get_received()

        assert get_event(r1, "game_deleted") is not None
        assert get_event(r2, "game_deleted") is not None
        assert game_id not in gm.games

        host.disconnect()
        p1.disconnect()
        p2.disconnect()

    def test_delete_during_active_question(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        start_and_get_question(host)
        p1.get_received()

        host.emit("delete_game")
        received = host.get_received()

        gd = get_event(received, "game_deleted")
        assert gd is not None
        assert game_id not in gm.games

        host.disconnect()
        p1.disconnect()

    def test_old_players_disconnect_after_deletion(self, app_env):
        """After game deletion, disconnecting old players should not crash."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        host.emit("delete_game")
        host.get_received()

        # These disconnects should not raise
        p1.disconnect()
        host.disconnect()

        # No crash = pass
        assert game_id not in gm.games
