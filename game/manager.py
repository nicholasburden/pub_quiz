"""GameManager: in-memory state store for all game mutations."""

import html
import random
import secrets
import threading
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
        if "lifelines" in config_data:
            cfg.lifelines = bool(config_data["lifelines"])

    def set_questions(self, game: Game, questions: list[Question], expected_total: int = 0):
        game.questions = questions
        game.questions_expected = expected_total or len(questions)
        game.current_question_index = -1
        game.state = GameState.PLAYING
        game.pending_first_question = True

    def append_questions(self, game: Game, new_questions: list[Question]):
        game.questions.extend(new_questions)
        game.questions_ready.set()

    def advance_question(self, game: Game) -> Question | None:
        game.current_question_index += 1
        idx = game.current_question_index
        if idx >= game.questions_expected:
            game.state = GameState.FINISHED
            GAMES_FINISHED_TOTAL.inc()
            return None

        # Question not yet loaded (background fetch in progress)
        if idx >= len(game.questions):
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
            "total_questions": game.questions_expected,
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

    def use_lifeline(self, game: Game, sid: str, lifeline_type: str) -> dict | None:
        """Use a lifeline. Returns result dict or None on failure."""
        if not game.config.lifelines:
            return None
        if game.state != GameState.QUESTION_ACTIVE:
            return None
        if lifeline_type not in ("fifty_fifty", "ask_the_audience"):
            return None

        player = game.players.get(sid)
        if not player:
            return None
        if lifeline_type in player.lifelines_used:
            return None

        question = game.questions[game.current_question_index]
        player.lifelines_used.add(lifeline_type)

        if lifeline_type == "fifty_fifty":
            wrong_answers = [a for a in question.all_answers if a != question.correct_answer]
            random.shuffle(wrong_answers)
            keep_wrong = wrong_answers[0]
            keep_answers = [question.correct_answer, keep_wrong]
            random.shuffle(keep_answers)
            return {"lifeline": "fifty_fifty", "keep_answers": keep_answers}

        # ask_the_audience
        difficulty = question.difficulty.lower()
        if difficulty == "easy":
            correct_pct = random.randint(70, 90)
        elif difficulty == "hard":
            correct_pct = random.randint(25, 50)
        else:
            correct_pct = random.randint(45, 70)

        # Check if 50:50 was already used this question by looking at current answers
        remaining_answers = question.all_answers
        if "fifty_fifty" in player.lifelines_used or self._has_fifty_fifty_active(game, sid):
            # We can't know which answers were kept from here, so use all answers
            # The client will only show the non-eliminated ones
            pass

        remaining = 100 - correct_pct
        other_answers = [a for a in remaining_answers if a != question.correct_answer]
        percentages = {question.correct_answer: correct_pct}

        for i, ans in enumerate(other_answers):
            if i == len(other_answers) - 1:
                percentages[ans] = remaining
            else:
                pct = random.randint(0, remaining)
                percentages[ans] = pct
                remaining -= pct

        return {"lifeline": "ask_the_audience", "percentages": percentages}

    def _has_fifty_fifty_active(self, game: Game, sid: str) -> bool:
        """Check if the player used 50:50 (already tracked in lifelines_used)."""
        player = game.players.get(sid)
        return player is not None and "fifty_fifty" in player.lifelines_used

    def reset_for_replay(self, game: Game):
        game.state = GameState.LOBBY
        game.questions = []
        game.questions_expected = 0
        game.current_question_index = -1
        game.pending_first_question = False
        game.last_question_results = None
        game.questions_ready = threading.Event()
        for p in game.players.values():
            p.score = 0
            p.current_answer = None
            p.answer_time = None
            p.lifelines_used = set()

    def _sanitize(self, text: str) -> str:
        text = html.escape(text.strip())
        return text[:MAX_NAME_LENGTH]
