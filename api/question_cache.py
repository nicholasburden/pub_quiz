"""Pre-fetch question cache for instant game starts."""

import logging
import random
from collections import defaultdict

from config import (
    QUESTION_CACHE_BATCH_SIZE,
    QUESTION_CACHE_CATEGORIES,
    QUESTION_CACHE_TARGET_PER_BUCKET,
)

logger = logging.getLogger(__name__)

DIFFICULTIES = ["easy", "medium", "hard"]


class QuestionCache:
    def __init__(self):
        # (category_id, difficulty) -> list[Question]
        self._pool: dict[tuple[int, str], list] = defaultdict(list)
        # game_id -> set of question texts already served
        self._served: dict[str, set[str]] = defaultdict(set)

    def get_questions(self, amount, categories, difficulty, game_id):
        """Pull questions from cache.

        Returns (questions, shortfall) where shortfall is how many
        questions couldn't be provided from cache.
        """
        questions = []
        served = self._served[game_id]

        if not categories:
            # Pull from all cached categories
            buckets = self._matching_buckets(difficulty)
        else:
            buckets = self._matching_buckets(difficulty, categories)

        # Gather all available questions from matching buckets
        available = []
        for key in buckets:
            available.extend((key, i) for i in range(len(self._pool[key])))

        # Shuffle so we don't always drain the same bucket first
        random.shuffle(available)

        pulled_indices: dict[tuple[int, str], list[int]] = defaultdict(list)
        for key, idx in available:
            if len(questions) >= amount:
                break
            q = self._pool[key][idx]
            if q.text in served:
                continue
            questions.append(q)
            served.add(q.text)
            pulled_indices[key].append(idx)

        # Remove pulled questions from pool (in reverse order to preserve indices)
        for key, indices in pulled_indices.items():
            for idx in sorted(indices, reverse=True):
                self._pool[key].pop(idx)

        shortfall = max(0, amount - len(questions))
        return questions, shortfall

    def _matching_buckets(self, difficulty, categories=None):
        """Return pool keys matching the given difficulty and categories."""
        keys = []
        for key in list(self._pool.keys()):
            cat_id, diff = key
            if categories and cat_id not in categories:
                continue
            if difficulty != "mixed" and diff != difficulty:
                continue
            if self._pool[key]:
                keys.append(key)
        return keys

    def deposit(self, questions, category_id, difficulty):
        """Add fetched questions into the pool."""
        key = (category_id, difficulty)
        self._pool[key].extend(questions)

    def clear_game(self, game_id):
        """Clean up per-game duplicate tracking."""
        self._served.pop(game_id, None)

    def total_cached(self):
        """Return total question count across all buckets."""
        return sum(len(qs) for qs in self._pool.values())


# Singleton
question_cache = QuestionCache()


def start_replenishment(opentdb_client, socketio):
    """Start background greenlet that keeps the cache topped up."""

    def _replenish_loop():
        logger.info("Question cache replenishment started")
        # Get a token for the cache's own requests
        token = opentdb_client._get_token()

        while True:
            for cat_id in QUESTION_CACHE_CATEGORIES:
                for diff in DIFFICULTIES:
                    key = (cat_id, diff)
                    current = len(question_cache._pool[key])
                    if current >= QUESTION_CACHE_TARGET_PER_BUCKET:
                        continue

                    batch = opentdb_client._fetch_batch(
                        QUESTION_CACHE_BATCH_SIZE, cat_id, diff, token
                    )
                    if batch:
                        question_cache.deposit(batch, cat_id, diff)
                        logger.info(
                            "Cache replenished: (%s, %s) +%d = %d total (cache total: %d)",
                            cat_id, diff, len(batch),
                            len(question_cache._pool[key]),
                            question_cache.total_cached(),
                        )
                    else:
                        # Token might have expired, refresh it
                        token = opentdb_client._get_token()

                    # Pause between each bucket to stay within rate limits
                    socketio.sleep(2)

            # Pause between full cycles
            socketio.sleep(30)

    socketio.start_background_task(_replenish_loop)
