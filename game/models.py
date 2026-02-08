"""Data models for the pub quiz game."""

from dataclasses import dataclass, field
from enum import Enum


class GameState(Enum):
    LOBBY = "lobby"
    PLAYING = "playing"
    QUESTION_ACTIVE = "question_active"
    QUESTION_RESULTS = "question_results"
    FINISHED = "finished"


@dataclass
class Player:
    sid: str
    name: str
    score: int = 0
    current_answer: str | None = None
    answer_time: float | None = None
    is_host: bool = False
    connected: bool = True


@dataclass
class Question:
    text: str
    correct_answer: str
    all_answers: list[str] = field(default_factory=list)
    category: str = ""
    difficulty: str = ""


@dataclass
class GameConfig:
    categories: list[int] = field(default_factory=list)
    difficulty: str = "mixed"
    num_questions: int = 10
    time_limit: int = 30


@dataclass
class Game:
    id: str
    name: str
    state: GameState = GameState.LOBBY
    config: GameConfig = field(default_factory=GameConfig)
    host_sid: str = ""
    players: dict[str, Player] = field(default_factory=dict)
    questions: list[Question] = field(default_factory=list)
    current_question_index: int = -1
    question_start_time: float = 0.0
