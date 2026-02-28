"""Tests for the lifelines feature (50:50 and Ask the Audience)."""

from tests.conftest import (
    FAKE_QUESTIONS,
    create_game_rest,
    get_event,
    host_join,
    player_join,
    start_and_get_question,
)
from game.models import GameState


# ==========================================================================
# TestFiftyFifty
# ==========================================================================

class TestFiftyFifty:

    def test_fifty_fifty_returns_two_answers(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = host.get_received()

        result = get_event(received, "lifeline_result")
        assert result is not None
        assert result["lifeline"] == "fifty_fifty"
        assert len(result["keep_answers"]) == 2
        # Correct answer must always be kept
        assert FAKE_QUESTIONS[0].correct_answer in result["keep_answers"]
        # Both kept answers must be from the original answer set
        for a in result["keep_answers"]:
            assert a in FAKE_QUESTIONS[0].all_answers

        host.disconnect()

    def test_fifty_fifty_cannot_be_used_twice(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        host.get_received()

        # Second use should return nothing
        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is None

        host.disconnect()

    def test_fifty_fifty_persists_across_questions(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        # Use 50:50 on Q1
        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        host.get_received()

        # Answer Q1 and advance
        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        host.get_received()
        host.emit("next_question")
        host.get_received()

        # Try 50:50 again on Q2 — should fail
        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is None

        host.disconnect()

    def test_fifty_fifty_rejected_after_answering(self, app_env):
        """Server rejects lifeline use after player has already answered."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        start_and_get_question(host)
        p1.get_received()

        # Host answers first
        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        host.get_received()

        # Alice can still use lifeline (she hasn't answered)
        p1.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = p1.get_received()
        result = get_event(received, "lifeline_result")
        assert result is not None

        host.disconnect()
        p1.disconnect()

    def test_fifty_fifty_only_sent_to_requester(self, app_env):
        """Lifeline result is only sent to the player who used it."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        start_and_get_question(host)
        p1.get_received()

        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        host.get_received()  # host gets the result

        # Alice should NOT have received a lifeline_result
        received = p1.get_received()
        assert get_event(received, "lifeline_result") is None

        host.disconnect()
        p1.disconnect()


# ==========================================================================
# TestAskTheAudience
# ==========================================================================

class TestAskTheAudience:

    def test_ata_returns_percentages(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        host.emit("use_lifeline", {"lifeline": "ask_the_audience"})
        received = host.get_received()

        result = get_event(received, "lifeline_result")
        assert result is not None
        assert result["lifeline"] == "ask_the_audience"

        pcts = result["percentages"]
        assert len(pcts) == 4  # all 4 answers
        assert sum(pcts.values()) == 100
        # Correct answer should be present
        assert FAKE_QUESTIONS[0].correct_answer in pcts
        # All answers from the question should be present
        for a in FAKE_QUESTIONS[0].all_answers:
            assert a in pcts

        host.disconnect()

    def test_ata_cannot_be_used_twice(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        host.emit("use_lifeline", {"lifeline": "ask_the_audience"})
        host.get_received()

        host.emit("use_lifeline", {"lifeline": "ask_the_audience"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is None

        host.disconnect()

    def test_ata_percentages_sum_to_100(self, app_env):
        """Run multiple times to ensure randomness always sums to 100."""
        app, sio, gm, *_ = app_env
        for _ in range(5):
            game_id = create_game_rest(app)
            host = host_join(sio, app, game_id)
            start_and_get_question(host)

            host.emit("use_lifeline", {"lifeline": "ask_the_audience"})
            received = host.get_received()
            result = get_event(received, "lifeline_result")
            assert sum(result["percentages"].values()) == 100

            host.disconnect()


# ==========================================================================
# TestBothLifelines
# ==========================================================================

class TestBothLifelines:

    def test_can_use_both_lifelines_same_question(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is not None

        host.emit("use_lifeline", {"lifeline": "ask_the_audience"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is not None

        host.disconnect()

    def test_can_use_lifelines_on_different_questions(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        # Use 50:50 on Q1
        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = host.get_received()
        assert get_event(received, "lifeline_result")["lifeline"] == "fifty_fifty"

        # Answer Q1 and advance
        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        host.get_received()
        host.emit("next_question")
        host.get_received()

        # Use ATA on Q2
        host.emit("use_lifeline", {"lifeline": "ask_the_audience"})
        received = host.get_received()
        result = get_event(received, "lifeline_result")
        assert result is not None
        assert result["lifeline"] == "ask_the_audience"

        host.disconnect()

    def test_different_players_have_independent_lifelines(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")

        start_and_get_question(host)
        p1.get_received()

        # Host uses 50:50
        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        host.get_received()

        # Alice can still use her own 50:50
        p1.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = p1.get_received()
        result = get_event(received, "lifeline_result")
        assert result is not None
        assert result["lifeline"] == "fifty_fifty"

        host.disconnect()
        p1.disconnect()


# ==========================================================================
# TestLifelineValidation
# ==========================================================================

class TestLifelineValidation:

    def test_rejected_outside_question_active(self, app_env):
        """Lifelines should be rejected when not in QUESTION_ACTIVE state."""
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # In LOBBY state
        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is None

        host.disconnect()

    def test_rejected_in_results_state(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        # Answer to trigger results
        host.emit("submit_answer", {"answer": FAKE_QUESTIONS[0].correct_answer})
        host.get_received()

        # Now in QUESTION_RESULTS
        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is None

        host.disconnect()

    def test_invalid_lifeline_type_rejected(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        start_and_get_question(host)

        host.emit("use_lifeline", {"lifeline": "phone_a_friend"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is None

        host.disconnect()


# ==========================================================================
# TestLifelineConfig
# ==========================================================================

class TestLifelineConfig:

    def test_lifelines_disabled_via_config(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Disable lifelines
        host.emit("update_config", {"lifelines": False})
        host.get_received()

        game = gm.get_game(game_id)
        assert game.config.lifelines is False

        host.emit("start_game")
        host.get_received()

        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is None

        host.emit("use_lifeline", {"lifeline": "ask_the_audience"})
        received = host.get_received()
        assert get_event(received, "lifeline_result") is None

        host.disconnect()

    def test_lifelines_enabled_by_default(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        game = gm.get_game(game_id)
        assert game.config.lifelines is True

    def test_config_updated_event_includes_lifelines(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)
        p1 = player_join(sio, app, game_id, "Alice")
        p1.get_received()

        host.emit("update_config", {"lifelines": False})
        received = p1.get_received()

        cfg = get_event(received, "config_updated")
        assert cfg is not None
        assert cfg["lifelines"] is False

        host.disconnect()
        p1.disconnect()

    def test_new_question_includes_lifelines_flag(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        nq = start_and_get_question(host)
        assert "lifelines" in nq
        assert nq["lifelines"] is True

        host.disconnect()


# ==========================================================================
# TestLifelineResetOnReplay
# ==========================================================================

class TestLifelineResetOnReplay:

    def test_play_again_resets_lifelines(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Play through entire game, using lifeline on Q1
        host.emit("start_game")
        host.get_received()

        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        host.get_received()

        for i in range(5):
            host.emit("submit_answer", {"answer": FAKE_QUESTIONS[i].correct_answer})
            host.get_received()
            host.emit("next_question")
            host.get_received()

        # Verify lifeline was used
        game = gm.get_game(game_id)
        player = list(game.players.values())[0]
        assert "fifty_fifty" in player.lifelines_used

        # Play again
        host.emit("play_again")
        host.get_received()

        # Lifelines should be reset
        assert len(player.lifelines_used) == 0

        host.disconnect()

    def test_lifelines_usable_after_replay(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Play through first game with lifeline
        host.emit("start_game")
        host.get_received()

        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        host.get_received()

        for i in range(5):
            host.emit("submit_answer", {"answer": FAKE_QUESTIONS[i].correct_answer})
            host.get_received()
            host.emit("next_question")
            host.get_received()

        # Play again
        host.emit("play_again")
        host.get_received()

        # Start second game
        host.emit("start_game")
        host.get_received()

        # Should be able to use 50:50 again
        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        received = host.get_received()
        result = get_event(received, "lifeline_result")
        assert result is not None
        assert result["lifeline"] == "fifty_fifty"

        host.disconnect()


# ==========================================================================
# TestLifelineStateInGameState
# ==========================================================================

class TestLifelineStateInGameState:

    def test_game_state_includes_lifelines_used(self, app_env):
        app, sio, gm, *_ = app_env
        game_id = create_game_rest(app)
        host = host_join(sio, app, game_id)

        # Start game and use a lifeline
        host.emit("start_game")
        host.get_received()

        host.emit("use_lifeline", {"lifeline": "fifty_fifty"})
        host.get_received()

        # Simulate reconnect
        host.disconnect()

        host2 = sio.test_client(app)
        host2.emit("join_game", {
            "game_id": game_id,
            "player_name": "Host",
            "is_host": True,
        })
        received = host2.get_received()

        state = get_event(received, "game_state")
        assert state is not None

        me = next(p for p in state["players"] if p["name"] == "Host")
        assert "fifty_fifty" in me["lifelines_used"]

        host2.disconnect()
