"""OpenTDB client with rate limiting, session tokens, and HTML decoding."""

import html
import math
import random
import time
import logging

import gevent
import requests

from config import (
    OPENTDB_API_URL,
    OPENTDB_CATEGORY_CACHE_TTL,
    OPENTDB_CATEGORY_URL,
    OPENTDB_RATE_LIMIT,
    OPENTDB_TOKEN_URL,
)
from game.models import Question

logger = logging.getLogger(__name__)


class OpenTDBClient:
    def __init__(self):
        self._token: str | None = None
        self._last_request_time: float = 0.0
        self._categories_cache: list[dict] | None = None
        self._categories_cache_time: float = 0.0

    def _rate_limit(self):
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < OPENTDB_RATE_LIMIT:
            gevent.sleep(OPENTDB_RATE_LIMIT - elapsed)
        self._last_request_time = time.time()

    def _get_token(self) -> str | None:
        if self._token:
            return self._token
        try:
            self._rate_limit()
            resp = requests.get(
                OPENTDB_TOKEN_URL,
                params={"command": "request"},
                timeout=10,
            )
            data = resp.json()
            if data.get("response_code") == 0:
                self._token = data["token"]
                return self._token
        except Exception:
            logger.exception("Failed to get OpenTDB token")
        return None

    def _reset_token(self):
        if not self._token:
            return
        try:
            self._rate_limit()
            requests.get(
                OPENTDB_TOKEN_URL,
                params={"command": "reset", "token": self._token},
                timeout=10,
            )
        except Exception:
            logger.exception("Failed to reset OpenTDB token")
            self._token = None

    def get_categories(self) -> list[dict]:
        now = time.time()
        if (
            self._categories_cache
            and now - self._categories_cache_time < OPENTDB_CATEGORY_CACHE_TTL
        ):
            return self._categories_cache

        try:
            self._rate_limit()
            resp = requests.get(OPENTDB_CATEGORY_URL, timeout=10)
            data = resp.json()
            self._categories_cache = data.get("trivia_categories", [])
            self._categories_cache_time = now
            return self._categories_cache
        except Exception:
            logger.exception("Failed to fetch categories")
            return self._categories_cache or []

    def fetch_questions_progressive(
        self,
        amount: int,
        categories: list[int] | None = None,
        difficulty: str = "mixed",
    ):
        """Yield question batches as they arrive (one per category)."""
        token = self._get_token()

        if not categories:
            batch = self._fetch_batch(amount, None, difficulty, token)
            if batch:
                yield batch
            return

        per_cat = max(1, math.floor(amount / len(categories)))
        remainder = amount - per_cat * len(categories)

        for i, cat_id in enumerate(categories):
            n = per_cat + (1 if i < remainder else 0)
            if n <= 0:
                continue
            batch = self._fetch_batch(n, cat_id, difficulty, token)
            if batch:
                yield batch

    def fetch_questions(
        self,
        amount: int,
        categories: list[int] | None = None,
        difficulty: str = "mixed",
    ) -> list[Question]:
        """Fetch questions, splitting evenly across selected categories."""
        token = self._get_token()

        if not categories:
            return self._fetch_batch(amount, None, difficulty, token)

        # Split evenly across categories
        per_cat = max(1, math.floor(amount / len(categories)))
        remainder = amount - per_cat * len(categories)

        questions: list[Question] = []
        for i, cat_id in enumerate(categories):
            n = per_cat + (1 if i < remainder else 0)
            if n <= 0:
                continue
            batch = self._fetch_batch(n, cat_id, difficulty, token)
            questions.extend(batch)

        random.shuffle(questions)
        return questions

    def _fetch_batch(
        self,
        amount: int,
        category: int | None,
        difficulty: str,
        token: str | None,
    ) -> list[Question]:
        params: dict = {"amount": amount, "type": "multiple"}
        if category:
            params["category"] = category
        if difficulty != "mixed":
            params["difficulty"] = difficulty
        if token:
            params["token"] = token

        try:
            self._rate_limit()
            resp = requests.get(OPENTDB_API_URL, params=params, timeout=15)
            data = resp.json()

            code = data.get("response_code", -1)

            # Rate limited — back off and retry once
            if code == 5:
                logger.warning("OpenTDB rate limited (code 5), backing off 10s")
                gevent.sleep(10)
                self._last_request_time = 0.0  # force full rate-limit wait on next call
                self._rate_limit()
                resp = requests.get(OPENTDB_API_URL, params=params, timeout=15)
                data = resp.json()
                code = data.get("response_code", -1)

            if code == 4:
                # Token exhausted, reset and retry once
                self._reset_token()
                token = self._get_token()
                if token:
                    params["token"] = token
                    self._rate_limit()
                    resp = requests.get(OPENTDB_API_URL, params=params, timeout=15)
                    data = resp.json()

            if data.get("response_code") not in (0, 5):
                logger.warning("OpenTDB returned code %s", data.get("response_code"))
                # Try without token
                params.pop("token", None)
                self._rate_limit()
                resp = requests.get(OPENTDB_API_URL, params=params, timeout=15)
                data = resp.json()

            results = data.get("results", [])
            return [self._parse_question(q) for q in results]
        except Exception:
            logger.exception("Failed to fetch questions from OpenTDB")
            return []

    def _parse_question(self, raw: dict) -> Question:
        text = html.unescape(raw["question"])
        correct = html.unescape(raw["correct_answer"])
        incorrect = [html.unescape(a) for a in raw["incorrect_answers"]]
        all_answers = incorrect + [correct]
        random.shuffle(all_answers)
        return Question(
            text=text,
            correct_answer=correct,
            all_answers=all_answers,
            category=html.unescape(raw.get("category", "")),
            difficulty=raw.get("difficulty", ""),
        )


# Singleton
opentdb = OpenTDBClient()
