"""Application constants and defaults."""

# Server
HOST = "0.0.0.0"
PORT = 5000
SECRET_KEY = "pub-quiz-secret-change-me"

# Game limits
MAX_PLAYERS = 20
MAX_NAME_LENGTH = 30
GAME_ID_LENGTH = 6

# Game defaults
DEFAULT_NUM_QUESTIONS = 10
DEFAULT_TIME_LIMIT = 30
DEFAULT_DIFFICULTY = "mixed"
MIN_QUESTIONS = 5
MAX_QUESTIONS = 50
MIN_TIME_LIMIT = 10
MAX_TIME_LIMIT = 60

# Scoring
BASE_SCORE = 1000
MAX_SPEED_BONUS = 500

# Timing
QUESTION_RESULTS_DELAY = 10  # seconds before auto-advance
GAME_LIST_POLL_INTERVAL = 3000  # milliseconds

# OpenTDB
OPENTDB_API_URL = "https://opentdb.com/api.php"
OPENTDB_TOKEN_URL = "https://opentdb.com/api_token.php"
OPENTDB_CATEGORY_URL = "https://opentdb.com/api_category.php"
OPENTDB_RATE_LIMIT = 5.5  # seconds between requests
OPENTDB_CATEGORY_CACHE_TTL = 3600  # 1 hour
