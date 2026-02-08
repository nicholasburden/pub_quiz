"""GameManager: in-memory state store for all game mutations."""

import html
import secrets
import time

from config import (
    GAME_ID_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PLAYERS,
    MAX_QUESTIONS,
    MAX_TIME_LIMIT,
    MIN_QUESTIONS,
    MIN_TIME_LIMIT,
)
from game.models import Game, GameConfig, GameState, Player, Question
from game.scoring import calculate_scores
from metrics import (
    ANSWER_TIME_SECONDS,
    GAMES_CREATED_TOTAL,
    GAMES_DELETED_TOTAL,
    GAMES_FINISHED_TOTAL,
    QUESTIONS_ANSWERED_TOTAL,
)


class GameManager:
    def __init__(self):
        self.games: dict[str, Game] = {}
        self.player_game: dict[str, str] = {}  # sid -> game_id

    def create_game(self, game_name: str, player_name: str, sid: str) -> Game:
        game_id = secrets.token_hex(GAME_ID_LENGTH // 2)
        game_name = self._sanitize(game_name) or "Pub Quiz"
        player_name = self._sanitize(player_name) or "Host"

        game = Game(id=game_id, name=game_name, host_sid=sid)
        player = Player(sid=sid, name=player_name, is_host=True)
        game.players[sid] = player
        self.games[game_id] = game
        self.player_game[sid] = game_id
        GAMES_CREATED_TOTAL.inc()
        return game

    def join_game(self, game_id: str, player_name: str, sid: str) -> tuple[Game | None, str]:
        """Returns (game, error_message). Game is None on error."""
        game = self.games.get(game_id)
        if not game:
            return None, "Game not found"

        player_name = self._sanitize(player_name) or f"Player {len(game.players) + 1}"

        # Check for reconnect by name (works in any game state)
        for existing_sid, player in list(game.players.items()):
            if player.name == player_name and not player.connected:
                # Reconnect: update sid mapping
                player.sid = sid
                player.connected = True
                del game.players[existing_sid]
                game.players[sid] = player
                if existing_sid in self.player_game:
                    del self.player_game[existing_sid]
                self.player_game[sid] = game_id
                if player.is_host:
                    game.host_sid = sid
                return game, ""

        # New players can only join during lobby
        if game.state != GameState.LOBBY:
            return None, "Game already in progress"
        if len(game.players) >= MAX_PLAYERS:
            return None, "Game is full"

        # Check duplicate name
        names = [p.name for p in game.players.values()]
        if player_name in names:
            return None, "Name already taken"

        player = Player(sid=sid, name=player_name)
        game.players[sid] = player
        self.player_game[sid] = game_id
        return game, ""

    def remove_player(self, sid: str) -> tuple[Game | None, Player | None, bool]:
        """Mark a player as disconnected. Returns (game, player, game_deleted).

        Players are never fully removed on disconnect since page navigations
        cause socket disconnects. Use delete_game for explicit cleanup.
        """
        game_id = self.player_game.pop(sid, None)
        if not game_id:
            return None, None, False

        game = self.games.get(game_id)
        if not game:
            return None, None, False

        player = game.players.get(sid)
        if not player:
            return game, None, False

        player.connected = False

        if player.is_host:
            # Try to promote a connected player
            for p_sid, p in game.players.items():
                if p_sid != sid and p.connected:
                    p.is_host = True
                    player.is_host = False
                    game.host_sid = p_sid
                    break

        return game, player, False

    def delete_game(self, game_id: str, sid: str) -> bool:
        """Delete a game. Only the host can delete. Returns True if deleted."""
        game = self.games.get(game_id)
        if not game or game.host_sid != sid:
            return False
        # Remove all player mappings
        for p_sid in list(game.players.keys()):
            self.player_game.pop(p_sid, None)
        del self.games[game_id]
        GAMES_DELETED_TOTAL.inc()
        return True

    def restore_host(self, game: Game, sid: str):
        """Restore host status to the given sid, demoting the current host."""
        if game.host_sid == sid:
            return
        old_host = game.players.get(game.host_sid)
        if old_host:
            old_host.is_host = False
        player = game.players.get(sid)
        if player:
            player.is_host = True
            game.host_sid = sid

    def mark_disconnected_by_name(self, game: Game, player_name: str):
        """Mark a player as disconnected by name, so reconnect-by-name can find them.

        Handles the race where the old socket disconnect hasn't been processed yet
        but the player has already reconnected from a new page.
        """
        sanitized = self._sanitize(player_name)
        for p in game.players.values():
            if p.name == sanitized and p.connected:
                p.connected = False
                return

    def _promote_new_host(self, game: Game, old_host_sid: str):
        for p_sid, p in game.players.items():
            if p_sid != old_host_sid and p.connected:
                p.is_host = True
                game.host_sid = p_sid
                return
        # No connected players to promote; keep old host_sid

    def get_game(self, game_id: str) -> Game | None:
        return self.games.get(game_id)

    def get_player_game(self, sid: str) -> tuple[Game | None, Player | None]:
        game_id = self.player_game.get(sid)
        if not game_id:
            return None, None
        game = self.games.get(game_id)
        if not game:
            return None, None
        player = game.players.get(sid)
        return game, player

    def list_joinable_games(self) -> list[dict]:
        result = []
        for game in list(self.games.values()):
            if game.state != GameState.LOBBY:
                continue
            connected = [p for p in game.players.values() if p.connected]
            # Clean up games with no connected players
            if not connected:
                self._cleanup_game(game)
                continue
            if len(connected) < MAX_PLAYERS:
                result.append({
                    "id": game.id,
                    "name": game.name,
                    "player_count": len(connected),
                    "max_players": MAX_PLAYERS,
                    "host": next(
                        (p.name for p in connected if p.is_host), "Unknown"
                    ),
                })
        return result

    def _cleanup_game(self, game: Game):
        for p_sid in list(game.players.keys()):
            self.player_game.pop(p_sid, None)
        self.games.pop(game.id, None)

    def update_config(self, game: Game, config_data: dict):
        cfg = game.config
        if "categories" in config_data:
            cats = config_data["categories"]
            if isinstance(cats, list):
                cfg.categories = [int(c) for c in cats if str(c).isdigit()]
        if "difficulty" in config_data:
            if config_data["difficulty"] in ("easy", "medium", "hard", "mixed"):
                cfg.difficulty = config_data["difficulty"]
        if "num_questions" in config_data:
            n = int(config_data["num_questions"])
            cfg.num_questions = max(MIN_QUESTIONS, min(MAX_QUESTIONS, n))
        if "time_limit" in config_data:
            t = int(config_data["time_limit"])
            cfg.time_limit = max(MIN_TIME_LIMIT, min(MAX_TIME_LIMIT, t))

    def set_questions(self, game: Game, questions: list[Question]):
        game.questions = questions
        game.current_question_index = -1
        game.state = GameState.PLAYING

    def advance_question(self, game: Game) -> Question | None:
        game.current_question_index += 1
        idx = game.current_question_index
        if idx >= len(game.questions):
            game.state = GameState.FINISHED
            GAMES_FINISHED_TOTAL.inc()
            return None

        game.state = GameState.QUESTION_ACTIVE
        game.question_start_time = time.time()

        # Reset player answers
        for p in game.players.values():
            p.current_answer = None
            p.answer_time = None

        return game.questions[idx]

    def submit_answer(self, game: Game, sid: str, answer: str) -> bool:
        """Submit a player's answer. Returns True if accepted."""
        if game.state != GameState.QUESTION_ACTIVE:
            return False
        player = game.players.get(sid)
        if not player or player.current_answer is not None:
            return False

        player.current_answer = answer
        player.answer_time = time.time() - game.question_start_time
        ANSWER_TIME_SECONDS.observe(player.answer_time)
        return True

    def all_connected_answered(self, game: Game) -> bool:
        for p in game.players.values():
            if p.connected and p.current_answer is None:
                return False
        return True

    def calculate_question_results(self, game: Game) -> dict:
        """Calculate results for the current question. Returns results dict."""
        game.state = GameState.QUESTION_RESULTS
        question = game.questions[game.current_question_index]

        # Rank correct players by speed (fastest first)
        correct_players = [
            (p, p.answer_time)
            for p in game.players.values()
            if p.current_answer == question.correct_answer and p.answer_time is not None
        ]
        correct_players.sort(key=lambda x: x[1])
        scores = calculate_scores(correct_players)

        player_results = []
        for p in game.players.values():
            correct = p.current_answer == question.correct_answer
            earned = scores.get(id(p), 0)
            p.score += earned
            QUESTIONS_ANSWERED_TOTAL.labels(result="correct" if correct else "wrong").inc()

            player_results.append({
                "name": p.name,
                "answer": p.current_answer,
                "correct": correct,
                "score_earned": earned,
                "total_score": p.score,
                "answer_time": round(p.answer_time, 2) if p.answer_time else None,
            })

        player_results.sort(key=lambda x: x["total_score"], reverse=True)

        return {
            "correct_answer": question.correct_answer,
            "question_number": game.current_question_index + 1,
            "total_questions": len(game.questions),
            "player_results": player_results,
            "leaderboard": [
                {"name": r["name"], "score": r["total_score"]}
                for r in player_results
            ],
        }

    def get_final_rankings(self, game: Game) -> list[dict]:
        rankings = sorted(
            game.players.values(), key=lambda p: p.score, reverse=True
        )
        return [
            {"name": p.name, "score": p.score, "rank": i + 1}
            for i, p in enumerate(rankings)
        ]

    def reset_for_replay(self, game: Game):
        game.state = GameState.LOBBY
        game.questions = []
        game.current_question_index = -1
        for p in game.players.values():
            p.score = 0
            p.current_answer = None
            p.answer_time = None

    def _sanitize(self, text: str) -> str:
        text = html.escape(text.strip())
        return text[:MAX_NAME_LENGTH]
