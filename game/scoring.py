"""Scoring logic for the pub quiz."""

from config import BASE_SCORE


def calculate_scores(correct_players: list) -> dict:
    """Calculate scores for all correct players based on speed rank.

    correct_players: list of (player, answer_time) sorted fastest-first.
    Returns {player: points_earned}.

    Correct answer: BASE_SCORE (10) + speed bonus.
    Speed bonus: slowest correct = 0, second-slowest = 1, … fastest = N-1.
    Wrong / no answer: 0 (not passed in).
    """
    n = len(correct_players)
    scores = {}
    for rank, (player, _answer_time) in enumerate(correct_players):
        speed_bonus = (n - 1) - rank  # fastest (rank 0) gets n-1
        scores[id(player)] = BASE_SCORE + speed_bonus
    return scores
