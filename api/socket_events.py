"""Socket.IO event handlers for the core game flow."""

import logging
import time

from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room

from game.manager import GameManager
from game.models import GameState
from api.opentdb import opentdb
from metrics import PLAYERS_JOINED_TOTAL

logger = logging.getLogger(__name__)

# Track active timers to prevent double-execution
_active_timers: dict[str, bool] = {}  # game_id -> active


def register_events(socketio: SocketIO, gm: GameManager):

    def _players_list(game):
        return [
            {"name": p.name, "score": p.score, "is_host": p.is_host, "connected": p.connected}
            for p in game.players.values()
        ]

    def _config_dict(game):
        cfg = game.config
        return {
            "categories": cfg.categories,
            "difficulty": cfg.difficulty,
            "num_questions": cfg.num_questions,
            "time_limit": cfg.time_limit,
        }

    @socketio.on("connect")
    def on_connect():
        logger.info("Client connected: %s", request.sid)

    @socketio.on("disconnect")
    def on_disconnect():
        sid = request.sid
        logger.info("Client disconnected: %s", sid)
        game, player, deleted = gm.remove_player(sid)
        if game and player and not deleted:
            emit("player_left", {
                "name": player.name,
                "players": _players_list(game),
                "new_host": game.host_sid,
            }, room=game.id)
            # If question is active, check if all remaining answered
            if game.state == GameState.QUESTION_ACTIVE and gm.all_connected_answered(game):
                _end_question(socketio, gm, game)

    @socketio.on("join_game")
    def on_join_game(data):
        sid = request.sid
        game_id = data.get("game_id", "")
        player_name = data.get("player_name", "")
        is_host = data.get("is_host", False)

        game = gm.get_game(game_id)
        if not game:
            emit("error", {"message": "Game not found"})
            return
        orig_game = game

        if is_host:
            # Host created via REST, now connecting via socket
            # Find the pending host player and update sid
            pending_player = game.players.pop("pending", None)
            if pending_player:
                pending_player.sid = sid
                game.players[sid] = pending_player
                game.host_sid = sid
                gm.player_game[sid] = game_id
            else:
                # Reconnecting (e.g. page navigation lobby -> quiz)
                # Mark old entry disconnected so join_game can reconnect by name
                gm.mark_disconnected_by_name(game, player_name)
                game_check, error = gm.join_game(game_id, player_name, sid)
                if not game_check:
                    emit("error", {"message": error})
                    return
                # Restore host status — disconnect may have promoted another player
                gm.restore_host(game, sid)
        else:
            game, error = gm.join_game(game_id, player_name, sid)
            if not game:
                # During an active game the only valid join is a reconnect.
                # Handle the race where the old socket disconnect hasn't
                # been processed yet by marking the stale entry disconnected.
                if orig_game.state != GameState.LOBBY:
                    gm.mark_disconnected_by_name(orig_game, player_name)
                    game, error = gm.join_game(game_id, player_name, sid)
                if not game:
                    emit("error", {"message": error})
                    return

        join_room(game_id)
        PLAYERS_JOINED_TOTAL.inc()

        # Send current state to the joining player
        emit("game_state", {
            "game_id": game.id,
            "game_name": game.name,
            "state": game.state.value,
            "players": _players_list(game),
            "config": _config_dict(game),
            "is_host": game.host_sid == sid,
        })

        # If game is finished, re-send rankings so results page can render
        if game.state == GameState.FINISHED:
            rankings = gm.get_final_rankings(game)
            emit("game_finished", {"rankings": rankings})

        # Notify all players
        emit("player_joined", {
            "name": player_name,
            "players": _players_list(game),
        }, room=game_id)

    @socketio.on("update_config")
    def on_update_config(data):
        sid = request.sid
        game, player = gm.get_player_game(sid)
        if not game or not player or not player.is_host:
            return
        if game.state != GameState.LOBBY:
            return

        gm.update_config(game, data)
        emit("config_updated", _config_dict(game), room=game.id)

    @socketio.on("start_game")
    def on_start_game():
        sid = request.sid
        game, player = gm.get_player_game(sid)
        if not game or not player or not player.is_host:
            return
        if game.state != GameState.LOBBY:
            return

        emit("game_starting", {"message": "Fetching questions..."}, room=game.id)

        # Fetch questions in background to avoid blocking
        cfg = game.config
        questions = opentdb.fetch_questions(
            amount=cfg.num_questions,
            categories=cfg.categories if cfg.categories else None,
            difficulty=cfg.difficulty,
        )

        if not questions:
            emit("error", {"message": "Failed to fetch questions from OpenTDB. Please try again."})
            return

        gm.set_questions(game, questions)

        emit("game_started", {
            "total_questions": len(game.questions),
        }, room=game.id)

        # Start the first question after a brief delay
        socketio.sleep(1)
        _send_next_question(socketio, gm, game)

    @socketio.on("submit_answer")
    def on_submit_answer(data):
        sid = request.sid
        game, player = gm.get_player_game(sid)
        if not game or not player:
            return

        answer = data.get("answer", "")
        accepted = gm.submit_answer(game, sid, answer)
        if not accepted:
            return

        # Broadcast that someone answered (no reveal)
        answered_count = sum(
            1 for p in game.players.values()
            if p.connected and p.current_answer is not None
        )
        total_connected = sum(1 for p in game.players.values() if p.connected)
        emit("player_answered", {
            "answered_count": answered_count,
            "total_players": total_connected,
        }, room=game.id)

        if gm.all_connected_answered(game):
            _end_question(socketio, gm, game)

    @socketio.on("next_question")
    def on_next_question():
        sid = request.sid
        game, player = gm.get_player_game(sid)
        if not game or not player or not player.is_host:
            return
        if game.state != GameState.QUESTION_RESULTS:
            return

        # Cancel auto-advance timer
        _active_timers[game.id] = False
        _send_next_question(socketio, gm, game)

    @socketio.on("play_again")
    def on_play_again():
        sid = request.sid
        game, player = gm.get_player_game(sid)
        if not game or not player or not player.is_host:
            return
        if game.state != GameState.FINISHED:
            return

        gm.reset_for_replay(game)
        emit("game_reset", {}, room=game.id)

    @socketio.on("delete_game")
    def on_delete_game():
        sid = request.sid
        game, player = gm.get_player_game(sid)
        if not game or not player or not player.is_host:
            return

        game_id = game.id
        _active_timers.pop(game_id, None)
        emit("game_deleted", {}, room=game_id)
        gm.delete_game(game_id, sid)


def _send_next_question(socketio: SocketIO, gm: GameManager, game):
    question = gm.advance_question(game)
    if not question:
        # Game finished
        rankings = gm.get_final_rankings(game)
        socketio.emit("game_finished", {"rankings": rankings}, room=game.id)
        return

    socketio.emit("new_question", {
        "question_number": game.current_question_index + 1,
        "total_questions": len(game.questions),
        "text": question.text,
        "answers": question.all_answers,
        "category": question.category,
        "difficulty": question.difficulty,
        "time_limit": game.config.time_limit,
    }, room=game.id)

    # Start countdown timer
    _active_timers[game.id] = True
    socketio.start_background_task(_run_timer, socketio, gm, game)


def _run_timer(socketio: SocketIO, gm: GameManager, game):
    time_limit = game.config.time_limit
    question_index = game.current_question_index

    for remaining in range(time_limit - 1, -1, -1):
        socketio.sleep(1)
        # Guard: stop if game moved on or timer cancelled
        if (
            not _active_timers.get(game.id, False)
            or game.current_question_index != question_index
            or game.state != GameState.QUESTION_ACTIVE
        ):
            return

        socketio.emit("tick", {"remaining": remaining}, room=game.id)

    # Time's up - end question if still active
    if (
        _active_timers.get(game.id, False)
        and game.current_question_index == question_index
        and game.state == GameState.QUESTION_ACTIVE
    ):
        _end_question(socketio, gm, game)


def _end_question(socketio: SocketIO, gm: GameManager, game):
    _active_timers[game.id] = False

    if game.state != GameState.QUESTION_ACTIVE:
        return

    results = gm.calculate_question_results(game)
    socketio.emit("question_results", results, room=game.id)

    # Auto-advance after delay
    from config import QUESTION_RESULTS_DELAY
    _active_timers[game.id] = True
    socketio.start_background_task(_auto_advance, socketio, gm, game, QUESTION_RESULTS_DELAY)


def _auto_advance(socketio: SocketIO, gm: GameManager, game, delay: int):
    question_index = game.current_question_index
    for remaining in range(delay, 0, -1):
        if not _active_timers.get(game.id, False):
            return
        socketio.emit("next_question_countdown", {"remaining": remaining}, room=game.id)
        socketio.sleep(1)

    if (
        _active_timers.get(game.id, False)
        and game.current_question_index == question_index
        and game.state == GameState.QUESTION_RESULTS
    ):
        _active_timers[game.id] = False
        _send_next_question(socketio, gm, game)
