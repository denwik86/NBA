"""Configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "") or None
DEADLINE_MINUTES_BEFORE = int(os.getenv("DEADLINE_MINUTES_BEFORE", "60"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Amsterdam")

# Scoring rules
POINTS_SERIES_WINNER = 3
POINTS_EXACT_SERIES_SCORE = 10
POINTS_GAME_WINNER = 1

# Database
DB_PATH = os.getenv("DB_PATH", "data/tournament.db")

# Scheduler intervals (minutes)
SCHEDULE_SYNC_INTERVAL = 15       # how often to refresh NBA data
DEADLINE_CHECK_INTERVAL = 1       # how often to check for closing deadlines
RESULTS_CHECK_INTERVAL = 5        # how often to check for finished games

# Valid series score patterns (best of 7)
VALID_SERIES_SCORES = [
    (4, 0), (4, 1), (4, 2), (4, 3),
    (0, 4), (1, 4), (2, 4), (3, 4),
]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required. Copy .env.example to .env and fill it in.")
