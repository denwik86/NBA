"""SQLite layer for the NBA prediction tournament.

Schema overview:
- players: registered tournament participants (telegram users)
- series: every playoff series (e.g. Cavaliers vs Raptors Round 1)
- games: individual games within a series
- series_predictions: predictions for series winner + exact score (3 + 10 pts)
- game_predictions: predictions for individual games (1 pt)
- revealed_flags: track which series/game predictions have been revealed to the group

All timestamps stored as ISO-8601 UTC strings for portability.
"""
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from config import DB_PATH


def _ensure_db_dir():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)


@contextmanager
def get_conn():
    _ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS players (
                telegram_id  INTEGER PRIMARY KEY,
                username     TEXT,
                display_name TEXT NOT NULL,
                registered_at TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS series (
                series_id     TEXT PRIMARY KEY,
                round_num     INTEGER NOT NULL,  -- 1,2,3,4 (Finals)
                conference    TEXT,              -- East/West/Finals
                team_a_name   TEXT NOT NULL,
                team_a_abbr   TEXT NOT NULL,
                team_a_seed   INTEGER,
                team_b_name   TEXT NOT NULL,
                team_b_abbr   TEXT NOT NULL,
                team_b_seed   INTEGER,
                game1_tipoff  TEXT,              -- ISO UTC
                winner_abbr   TEXT,              -- filled when series ends
                final_score_a INTEGER,           -- e.g. 4 if team A won 4-2
                final_score_b INTEGER,
                status        TEXT DEFAULT 'pending',  -- pending|in_progress|finished
                revealed      INTEGER DEFAULT 0        -- 1 after deadline passed
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS games (
                game_id      TEXT PRIMARY KEY,
                series_id    TEXT NOT NULL,
                game_number  INTEGER NOT NULL,  -- 1..7
                tipoff_utc   TEXT NOT NULL,
                home_abbr    TEXT,
                away_abbr    TEXT,
                winner_abbr  TEXT,              -- filled when game ends
                home_score   INTEGER,
                away_score   INTEGER,
                status       TEXT DEFAULT 'scheduled', -- scheduled|live|finished|cancelled
                revealed     INTEGER DEFAULT 0,
                FOREIGN KEY(series_id) REFERENCES series(series_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS series_predictions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id      INTEGER NOT NULL,
                series_id      TEXT NOT NULL,
                winner_abbr    TEXT NOT NULL,
                score_winner   INTEGER NOT NULL,  -- always 4 for BO7
                score_loser    INTEGER NOT NULL,  -- 0,1,2,3
                submitted_at   TEXT NOT NULL,
                points_awarded INTEGER,            -- null until series ends
                UNIQUE(player_id, series_id),
                FOREIGN KEY(player_id) REFERENCES players(telegram_id),
                FOREIGN KEY(series_id) REFERENCES series(series_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS game_predictions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id      INTEGER NOT NULL,
                game_id        TEXT NOT NULL,
                winner_abbr    TEXT NOT NULL,
                submitted_at   TEXT NOT NULL,
                points_awarded INTEGER,
                UNIQUE(player_id, game_id),
                FOREIGN KEY(player_id) REFERENCES players(telegram_id),
                FOREIGN KEY(game_id) REFERENCES games(game_id)
            )
        """)

        # For tracking which notifications have been sent (avoid duplicates)
        c.execute("""
            CREATE TABLE IF NOT EXISTS notifications_sent (
                key         TEXT PRIMARY KEY,
                sent_at     TEXT NOT NULL
            )
        """)


# ---------- Players ----------

def add_player(telegram_id: int, username: str, display_name: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO players(telegram_id, username, display_name, registered_at) "
            "VALUES (?, ?, ?, ?)",
            (telegram_id, username, display_name, _now_iso()),
        )


def get_player(telegram_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return row


def get_all_players() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM players ORDER BY registered_at").fetchall()


# ---------- Series ----------

def upsert_series(
    series_id: str,
    round_num: int,
    conference: str,
    team_a_name: str, team_a_abbr: str, team_a_seed: int,
    team_b_name: str, team_b_abbr: str, team_b_seed: int,
    game1_tipoff: str,
):
    """Insert or update a series. Does not overwrite winner/final_score if already set."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT series_id FROM series WHERE series_id = ?", (series_id,)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE series SET
                    round_num=?, conference=?,
                    team_a_name=?, team_a_abbr=?, team_a_seed=?,
                    team_b_name=?, team_b_abbr=?, team_b_seed=?,
                    game1_tipoff=COALESCE(?, game1_tipoff)
                WHERE series_id = ?
            """, (round_num, conference, team_a_name, team_a_abbr, team_a_seed,
                  team_b_name, team_b_abbr, team_b_seed, game1_tipoff, series_id))
        else:
            conn.execute("""
                INSERT INTO series(
                    series_id, round_num, conference,
                    team_a_name, team_a_abbr, team_a_seed,
                    team_b_name, team_b_abbr, team_b_seed,
                    game1_tipoff
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (series_id, round_num, conference,
                  team_a_name, team_a_abbr, team_a_seed,
                  team_b_name, team_b_abbr, team_b_seed,
                  game1_tipoff))


def set_series_result(series_id: str, winner_abbr: str, score_a: int, score_b: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE series SET winner_abbr=?, final_score_a=?, final_score_b=?, status='finished' "
            "WHERE series_id = ?",
            (winner_abbr, score_a, score_b, series_id),
        )


def set_series_revealed(series_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE series SET revealed = 1 WHERE series_id = ?", (series_id,))


def get_series(series_id: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM series WHERE series_id = ?", (series_id,)).fetchone()


def get_all_series(round_num: Optional[int] = None) -> list:
    with get_conn() as conn:
        if round_num is None:
            return conn.execute("SELECT * FROM series ORDER BY round_num, game1_tipoff").fetchall()
        return conn.execute(
            "SELECT * FROM series WHERE round_num = ? ORDER BY game1_tipoff",
            (round_num,),
        ).fetchall()


def get_pending_series() -> list:
    """Series that haven't started yet and predictions are still open/relevant."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM series WHERE status = 'pending' ORDER BY game1_tipoff"
        ).fetchall()


# ---------- Games ----------

def upsert_game(
    game_id: str, series_id: str, game_number: int,
    tipoff_utc: str, home_abbr: str, away_abbr: str,
    status: str = "scheduled",
):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO games(game_id, series_id, game_number, tipoff_utc, home_abbr, away_abbr, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                tipoff_utc=excluded.tipoff_utc,
                home_abbr=excluded.home_abbr,
                away_abbr=excluded.away_abbr,
                status=CASE WHEN games.status='finished' THEN games.status ELSE excluded.status END
        """, (game_id, series_id, game_number, tipoff_utc, home_abbr, away_abbr, status))


def set_game_result(game_id: str, winner_abbr: str, home_score: int, away_score: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE games SET winner_abbr=?, home_score=?, away_score=?, status='finished' "
            "WHERE game_id = ?",
            (winner_abbr, home_score, away_score, game_id),
        )


def set_game_revealed(game_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE games SET revealed = 1 WHERE game_id = ?", (game_id,))


def get_game(game_id: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()


def get_games_for_series(series_id: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM games WHERE series_id = ? ORDER BY game_number",
            (series_id,),
        ).fetchall()


def get_upcoming_games(limit: int = 10) -> list:
    """Games that are scheduled and haven't tipped off yet."""
    now = _now_iso()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM games WHERE status='scheduled' AND tipoff_utc > ? "
            "ORDER BY tipoff_utc LIMIT ?",
            (now, limit),
        ).fetchall()


# ---------- Predictions ----------

def save_series_prediction(player_id: int, series_id: str, winner_abbr: str,
                            score_winner: int, score_loser: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO series_predictions(player_id, series_id, winner_abbr, score_winner, score_loser, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, series_id) DO UPDATE SET
                winner_abbr=excluded.winner_abbr,
                score_winner=excluded.score_winner,
                score_loser=excluded.score_loser,
                submitted_at=excluded.submitted_at
        """, (player_id, series_id, winner_abbr, score_winner, score_loser, _now_iso()))


def get_series_prediction(player_id: int, series_id: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM series_predictions WHERE player_id=? AND series_id=?",
            (player_id, series_id),
        ).fetchone()


def get_all_series_predictions(series_id: str) -> list:
    """Joined with players for display."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT sp.*, p.display_name, p.username
            FROM series_predictions sp
            JOIN players p ON p.telegram_id = sp.player_id
            WHERE sp.series_id = ?
            ORDER BY p.display_name
        """, (series_id,)).fetchall()


def save_game_prediction(player_id: int, game_id: str, winner_abbr: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO game_predictions(player_id, game_id, winner_abbr, submitted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id, game_id) DO UPDATE SET
                winner_abbr=excluded.winner_abbr,
                submitted_at=excluded.submitted_at
        """, (player_id, game_id, winner_abbr, _now_iso()))


def get_game_prediction(player_id: int, game_id: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM game_predictions WHERE player_id=? AND game_id=?",
            (player_id, game_id),
        ).fetchone()


def get_all_game_predictions(game_id: str) -> list:
    with get_conn() as conn:
        return conn.execute("""
            SELECT gp.*, p.display_name, p.username
            FROM game_predictions gp
            JOIN players p ON p.telegram_id = gp.player_id
            WHERE gp.game_id = ?
            ORDER BY p.display_name
        """, (game_id,)).fetchall()


def update_prediction_points(table: str, pk_id: int, points: int):
    assert table in ("series_predictions", "game_predictions")
    with get_conn() as conn:
        conn.execute(f"UPDATE {table} SET points_awarded=? WHERE id=?", (points, pk_id))


# ---------- Standings ----------

def get_standings() -> list:
    """Return list of dicts: {player_id, display_name, total_points, series_points, game_points}."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                p.telegram_id,
                p.display_name,
                p.username,
                COALESCE(SUM(sp.points_awarded), 0) AS series_points,
                (SELECT COALESCE(SUM(points_awarded), 0)
                   FROM game_predictions
                  WHERE player_id = p.telegram_id) AS game_points
            FROM players p
            LEFT JOIN series_predictions sp ON sp.player_id = p.telegram_id
            GROUP BY p.telegram_id
        """).fetchall()
        result = []
        for r in rows:
            total = (r["series_points"] or 0) + (r["game_points"] or 0)
            result.append({
                "telegram_id": r["telegram_id"],
                "display_name": r["display_name"],
                "username": r["username"],
                "series_points": r["series_points"] or 0,
                "game_points": r["game_points"] or 0,
                "total_points": total,
            })
        result.sort(key=lambda x: -x["total_points"])
        return result


# ---------- Notifications tracking ----------

def was_notified(key: str) -> bool:
    with get_conn() as conn:
        r = conn.execute("SELECT 1 FROM notifications_sent WHERE key=?", (key,)).fetchone()
        return r is not None


def mark_notified(key: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO notifications_sent(key, sent_at) VALUES (?, ?)",
            (key, _now_iso()),
        )


# ---------- helpers ----------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
