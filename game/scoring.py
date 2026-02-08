"""Scoring logic for the pub quiz."""

from config import BASE_SCORE, MAX_SPEED_BONUS


def calculate_score(correct: bool, answer_time: float, time_limit: int) -> int:
    """Calculate score for an answer.

    Correct: 1000 base + up to 500 speed bonus (linear decay over time limit).
    Wrong / no answer: 0 points.
    """
    if not correct:
        return 0

    elapsed = max(0.0, min(answer_time, float(time_limit)))
    fraction_remaining = 1.0 - (elapsed / float(time_limit))
    speed_bonus = int(MAX_SPEED_BONUS * fraction_remaining)
    return BASE_SCORE + speed_bonus
