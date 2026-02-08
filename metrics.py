"""Prometheus metrics for pub quiz application."""

from prometheus_client import Counter, Gauge, Histogram

# Counters
GAMES_CREATED_TOTAL = Counter(
    "pubquiz_games_created_total",
    "Total number of games created",
)
GAMES_FINISHED_TOTAL = Counter(
    "pubquiz_games_finished_total",
    "Total number of games that reached FINISHED state",
)
GAMES_DELETED_TOTAL = Counter(
    "pubquiz_games_deleted_total",
    "Total number of games explicitly deleted",
)
QUESTIONS_ANSWERED_TOTAL = Counter(
    "pubquiz_questions_answered_total",
    "Total question answers by result",
    ["result"],
)
PLAYERS_JOINED_TOTAL = Counter(
    "pubquiz_players_joined_total",
    "Total number of player joins",
)

# Gauges (updated at scrape time)
ACTIVE_GAMES = Gauge(
    "pubquiz_active_games",
    "Number of active games by state",
    ["state"],
)
CONNECTED_PLAYERS = Gauge(
    "pubquiz_connected_players",
    "Number of currently connected players across all games",
)

# Histogram
ANSWER_TIME_SECONDS = Histogram(
    "pubquiz_answer_time_seconds",
    "Time taken by players to submit an answer",
    buckets=(1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60),
)


def update_live_gauges(game_manager):
    """Read GameManager state and set gauge values. Called before each scrape."""
    from game.models import GameState

    # Reset all state labels to 0
    for state in GameState:
        ACTIVE_GAMES.labels(state=state.value).set(0)

    connected = 0
    for game in game_manager.games.values():
        ACTIVE_GAMES.labels(state=game.state.value).inc()
        connected += sum(1 for p in game.players.values() if p.connected)

    CONNECTED_PLAYERS.set(connected)
