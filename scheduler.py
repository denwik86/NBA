"""Background scheduler jobs.

Jobs:
1. sync_nba_data_job — every 15 min: pulls fresh games/results from ESPN
2. check_deadlines_job — every 1 min: finds series/games whose deadline is ~approaching or passed,
                         sends notifications / reveal messages
3. check_results_job — every 5 min: when games/series finish, awards points, posts to group

Notifications:
- 24h before tipoff: "reminder, predictions open for X"
- 2h before tipoff: "predictions close in ~1h!"
- At tipoff (= deadline already passed): REVEAL all predictions to group
- After finish: post results + updated standings
"""
import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot
from telegram.error import TelegramError

import database as db
import nba_data
import scoring
from config import (
    DEADLINE_MINUTES_BEFORE,
    GROUP_CHAT_ID,
    SCHEDULE_SYNC_INTERVAL,
    DEADLINE_CHECK_INTERVAL,
    RESULTS_CHECK_INTERVAL,
)

log = logging.getLogger(__name__)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -------------- Jobs --------------

async def sync_nba_data_job(context):
    try:
        nba_data.sync_with_espn()
    except Exception as e:
        log.exception("NBA sync failed: %s", e)


async def check_deadlines_job(context):
    """Send reminders + reveal messages when deadlines hit."""
    bot = context.bot
    now = _now()

    # --- Series deadlines (Game 1 tipoff) ---
    for s in db.get_all_series():
        if not s["game1_tipoff"]:
            continue
        tipoff = _parse_iso(s["game1_tipoff"])
        deadline = tipoff - timedelta(minutes=DEADLINE_MINUTES_BEFORE)

        # 24h reminder: "start making your series prediction"
        if timedelta(hours=23, minutes=59) < tipoff - now <= timedelta(hours=24):
            key = f"series-24h-{s['series_id']}"
            if not db.was_notified(key):
                await _broadcast(bot,
                    f"⏳ *{_format_date_local(tipoff)}* стартует серия\n"
                    f"*{s['team_a_name']} vs {s['team_b_name']}*\n"
                    f"Можно делать прогноз на серию + Game 1. Сделай: /predict"
                )
                db.mark_notified(key)

        # ~Just before deadline (between 2h and 1h remaining): "last hour!"
        if timedelta(minutes=DEADLINE_MINUTES_BEFORE) < tipoff - now <= timedelta(
                minutes=DEADLINE_MINUTES_BEFORE + 60):
            key = f"series-deadline-warning-{s['series_id']}"
            if not db.was_notified(key):
                await _broadcast(bot,
                    f"🚨 Через ~{DEADLINE_MINUTES_BEFORE+30} минут закрываются прогнозы на серию\n"
                    f"*{s['team_a_abbr']} vs {s['team_b_abbr']}* (Game 1 в {_format_date_local(tipoff)})\n"
                    f"Быстрее: /predict"
                )
                db.mark_notified(key)

        # Deadline passed — REVEAL all series predictions (once)
        if now >= deadline and not s["revealed"]:
            await _reveal_series(bot, s["series_id"])
            db.set_series_revealed(s["series_id"])

    # --- Game deadlines (per-game tipoffs) ---
    for g in _get_all_recent_and_upcoming_games():
        if not g["tipoff_utc"]:
            continue
        tipoff = _parse_iso(g["tipoff_utc"])
        deadline = tipoff - timedelta(minutes=DEADLINE_MINUTES_BEFORE)

        # Reminder 2h before tipoff (1h before deadline)
        if timedelta(minutes=DEADLINE_MINUTES_BEFORE) < tipoff - now <= timedelta(
                minutes=DEADLINE_MINUTES_BEFORE + 60):
            key = f"game-warning-{g['game_id']}"
            if not db.was_notified(key):
                await _broadcast(bot,
                    f"⏱ Скоро закрываются прогнозы на *Game {g['game_number']}*: "
                    f"{g['away_abbr']} @ {g['home_abbr']} "
                    f"({_format_date_local(tipoff)})\n/predict"
                )
                db.mark_notified(key)

        # Deadline passed — reveal game predictions (once)
        if now >= deadline and not g["revealed"]:
            await _reveal_game(bot, g["game_id"])
            db.set_game_revealed(g["game_id"])


async def check_results_job(context):
    """Award points when games/series finish, post results."""
    bot = context.bot
    # Award game points for any newly-finished games
    for g in _get_all_recent_finished_games():
        # Only notify if we haven't already
        key = f"game-result-{g['game_id']}"
        if db.was_notified(key):
            continue
        scoring.award_game_points(g["game_id"])
        await _post_game_result(bot, g["game_id"])
        db.mark_notified(key)

    # Award series points for newly-finished series
    for s in db.get_all_series():
        if s["status"] != "finished":
            continue
        key = f"series-result-{s['series_id']}"
        if db.was_notified(key):
            continue
        scoring.award_series_points(s["series_id"])
        await _post_series_result(bot, s["series_id"])
        db.mark_notified(key)


# -------------- helpers --------------

def _get_all_recent_and_upcoming_games():
    """Games within ±2 days of now — enough to catch upcoming deadlines and just-finished."""
    from datetime import timedelta
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM games
            WHERE tipoff_utc >= ? AND tipoff_utc <= ?
        """, (
            (_now() - timedelta(days=2)).isoformat(),
            (_now() + timedelta(days=5)).isoformat(),
        )).fetchall()
    return rows


def _get_all_recent_finished_games():
    with db.get_conn() as conn:
        return conn.execute("""
            SELECT * FROM games
            WHERE status='finished' AND winner_abbr IS NOT NULL
            ORDER BY tipoff_utc DESC LIMIT 20
        """).fetchall()


async def _broadcast(bot: Bot, markdown_text: str):
    """Send message to group chat if configured, else to each player individually."""
    if GROUP_CHAT_ID:
        try:
            await bot.send_message(int(GROUP_CHAT_ID), markdown_text, parse_mode="Markdown")
            return
        except TelegramError as e:
            log.warning("Failed group broadcast: %s — falling back to DMs", e)

    for p in db.get_all_players():
        try:
            await bot.send_message(p["telegram_id"], markdown_text, parse_mode="Markdown")
        except TelegramError as e:
            log.warning("Failed DM to %s: %s", p["telegram_id"], e)


async def _reveal_series(bot: Bot, series_id: str):
    s = db.get_series(series_id)
    preds = db.get_all_series_predictions(series_id)
    lines = [f"🔒 *Прогнозы закрыты — Series {s['team_a_name']} vs {s['team_b_name']}*\n"]
    players = db.get_all_players()
    predicted_ids = {p["player_id"] for p in preds}
    for p in preds:
        lines.append(f"👤 *{p['display_name']}*: {p['winner_abbr']} "
                     f"{p['score_winner']}-{p['score_loser']}")
    for pl in players:
        if pl["telegram_id"] not in predicted_ids:
            lines.append(f"🚫 *{pl['display_name']}*: не проставил — 0 очков")
    await _broadcast(bot, "\n".join(lines))


async def _reveal_game(bot: Bot, game_id: str):
    g = db.get_game(game_id)
    s = db.get_series(g["series_id"])
    preds = db.get_all_game_predictions(game_id)
    lines = [f"🔒 *Прогнозы закрыты — Game {g['game_number']}:* "
             f"{g['away_abbr']} @ {g['home_abbr']} _({s['team_a_abbr']} vs {s['team_b_abbr']})_\n"]
    players = db.get_all_players()
    predicted_ids = {p["player_id"] for p in preds}
    for p in preds:
        lines.append(f"👤 *{p['display_name']}*: {p['winner_abbr']}")
    for pl in players:
        if pl["telegram_id"] not in predicted_ids:
            lines.append(f"🚫 *{pl['display_name']}*: не проставил — 0 очков")
    await _broadcast(bot, "\n".join(lines))


async def _post_game_result(bot: Bot, game_id: str):
    g = db.get_game(game_id)
    s = db.get_series(g["series_id"])
    preds = db.get_all_game_predictions(game_id)
    lines = [
        f"🏁 *Game {g['game_number']} — результат:*",
        f"{g['away_abbr']} {g['away_score']} — {g['home_score']} {g['home_abbr']}",
        f"🏆 Победитель: *{g['winner_abbr']}*\n",
    ]
    if preds:
        lines.append("_Очки за этот матч:_")
        for p in preds:
            pts = p["points_awarded"] or 0
            emoji = "✅" if pts > 0 else "❌"
            lines.append(f"{emoji} {p['display_name']}: {p['winner_abbr']} → {pts} pts")

    # Append quick standings
    lines.append("\n" + _format_standings_summary())
    await _broadcast(bot, "\n".join(lines))


async def _post_series_result(bot: Bot, series_id: str):
    s = db.get_series(series_id)
    preds = db.get_all_series_predictions(series_id)
    lines = [
        f"🎯 *Серия завершена:* {s['team_a_name']} vs {s['team_b_name']}",
        f"🏆 Победитель: *{s['winner_abbr']}* "
        f"({s['final_score_a']}-{s['final_score_b']})\n",
    ]
    if preds:
        lines.append("_Очки за серию (победитель +3, точный счёт +10):_")
        for p in preds:
            pts = p["points_awarded"] or 0
            if pts == 13:
                emoji, note = "🎯", "ТОЧНЫЙ СЧЁТ!"
            elif pts == 3:
                emoji, note = "✅", "победитель"
            else:
                emoji, note = "❌", "мимо"
            lines.append(
                f"{emoji} {p['display_name']}: {p['winner_abbr']} "
                f"{p['score_winner']}-{p['score_loser']} → *{pts} pts* ({note})"
            )
    lines.append("\n" + _format_standings_summary())
    await _broadcast(bot, "\n".join(lines))


def _format_standings_summary() -> str:
    standings = db.get_standings()
    if not standings:
        return ""
    medals = ["🥇", "🥈", "🥉"] + ["  "] * 10
    lines = ["*🏆 Таблица лидеров:*"]
    for i, p in enumerate(standings):
        lines.append(f"{medals[i]} {p['display_name']} — {p['total_points']} pts")
    return "\n".join(lines)


def _format_date_local(dt: datetime) -> str:
    from zoneinfo import ZoneInfo
    from config import TIMEZONE
    return dt.astimezone(ZoneInfo(TIMEZONE)).strftime("%a %d %b, %H:%M %Z")


# -------------- Scheduler setup --------------

def register_jobs(application):
    job_queue = application.job_queue
    job_queue.run_repeating(sync_nba_data_job, interval=SCHEDULE_SYNC_INTERVAL * 60, first=10)
    job_queue.run_repeating(check_deadlines_job, interval=DEADLINE_CHECK_INTERVAL * 60, first=15)
    job_queue.run_repeating(check_results_job, interval=RESULTS_CHECK_INTERVAL * 60, first=30)
    log.info("Background jobs registered")
