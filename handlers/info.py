"""Informational commands: /schedule, /bracket, /standings, /mypredictions, /reveal."""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from config import TIMEZONE, DEADLINE_MINUTES_BEFORE

log = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo(TIMEZONE)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fmt_local(utc_str: str) -> str:
    try:
        dt = _parse_iso(utc_str).astimezone(LOCAL_TZ)
        return dt.strftime("%a %d %b, %H:%M %Z")
    except Exception:
        return utc_str


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upcoming = db.get_upcoming_games(limit=12)
    if not upcoming:
        await update.message.reply_text(
            "Расписание пока не подтянуто. Подожди пару минут (синк раз в 15 мин) или /start."
        )
        return

    lines = ["📅 *Ближайшие игры:*\n"]
    for g in upcoming:
        series = db.get_series(g["series_id"])
        if not series:
            continue
        local_time = _fmt_local(g["tipoff_utc"])
        lines.append(
            f"• *{local_time}* — {g['away_abbr']} @ {g['home_abbr']} "
            f"(Game {g['game_number']}, {series['team_a_abbr']} vs {series['team_b_abbr']})"
        )
    await update.message.reply_markdown("\n".join(lines))


async def bracket_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    series_rows = db.get_all_series()
    if not series_rows:
        await update.message.reply_text("Сетка пока пуста. Админу: /admin_seed")
        return

    # Group by round
    by_round = {}
    for s in series_rows:
        by_round.setdefault(s["round_num"], []).append(s)

    round_names = {1: "🏁 Round 1", 2: "🔥 Conference Semifinals",
                   3: "👑 Conference Finals", 4: "🏆 NBA FINALS"}

    lines = ["*🏀 NBA Playoffs Bracket*\n"]
    for rnd in sorted(by_round.keys()):
        lines.append(f"\n*{round_names.get(rnd, f'Round {rnd}')}*")
        # Sort: East first, then West, then Finals
        def _conf_key(s):
            return {"East": 0, "West": 1, "Finals": 2}.get(s["conference"], 3)
        sorted_series = sorted(by_round[rnd], key=lambda s: (_conf_key(s), s["team_a_seed"] or 99))

        current_conf = None
        for s in sorted_series:
            if s["conference"] != current_conf:
                current_conf = s["conference"]
                lines.append(f"\n_{current_conf}_:")
            if s["status"] == "finished":
                fs = f"{s['final_score_a']}-{s['final_score_b']}"
                marker = "✅" if s["winner_abbr"] == s["team_a_abbr"] else "❌"
                lines.append(
                    f"  #{s['team_a_seed']} {s['team_a_abbr']} {marker} {fs} vs "
                    f"#{s['team_b_seed']} {s['team_b_abbr']} → 🏆 {s['winner_abbr']}"
                )
            else:
                when = _fmt_local(s["game1_tipoff"]) if s["game1_tipoff"] else "TBD"
                lines.append(
                    f"  #{s['team_a_seed']} {s['team_a_abbr']} vs "
                    f"#{s['team_b_seed']} {s['team_b_abbr']} — G1 {when}"
                )

    await update.message.reply_markdown("\n".join(lines))


async def standings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    standings = db.get_standings()
    if not standings:
        await update.message.reply_text("Игроков пока нет. Жмите /start.")
        return

    medals = ["🥇", "🥈", "🥉"] + ["  "] * 10
    lines = ["*🏆 Таблица лидеров*\n"]
    for i, s in enumerate(standings):
        lines.append(
            f"{medals[i]} *{s['display_name']}* — {s['total_points']} pts  "
            f"_(серии: {s['series_points']}, матчи: {s['game_points']})_"
        )
    await update.message.reply_markdown("\n".join(lines))


async def mypredictions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.get_player(user_id):
        await update.message.reply_text("Сначала /start")
        return

    lines = ["*🎯 Мои прогнозы*\n"]

    # Series predictions
    any_series = False
    for s in db.get_all_series():
        pred = db.get_series_prediction(user_id, s["series_id"])
        if not pred:
            continue
        any_series = True
        pts = pred["points_awarded"]
        pts_str = f" — *{pts} pts*" if pts is not None else " (ожидание)"
        lines.append(
            f"• Series {s['team_a_abbr']} vs {s['team_b_abbr']}: "
            f"{pred['winner_abbr']} {pred['score_winner']}-{pred['score_loser']}{pts_str}"
        )

    if any_series:
        lines.append("")

    # Game predictions (last 15 games)
    any_game = False
    with db.get_conn() as conn:
        game_preds = conn.execute("""
            SELECT gp.*, g.game_number, g.home_abbr, g.away_abbr, g.tipoff_utc,
                   g.winner_abbr AS actual_winner, g.status,
                   s.team_a_abbr, s.team_b_abbr
            FROM game_predictions gp
            JOIN games g ON g.game_id = gp.game_id
            JOIN series s ON s.series_id = g.series_id
            WHERE gp.player_id = ?
            ORDER BY g.tipoff_utc DESC
            LIMIT 15
        """, (user_id,)).fetchall()

    for gp in game_preds:
        any_game = True
        pts = gp["points_awarded"]
        pts_str = f" — *{pts} pts*" if pts is not None else " (ожидание)"
        lines.append(
            f"• Game {gp['game_number']} ({gp['team_a_abbr']} vs {gp['team_b_abbr']}): "
            f"{gp['winner_abbr']}{pts_str}"
        )

    if not any_series and not any_game:
        lines.append("Пока нет прогнозов. /predict")

    await update.message.reply_markdown("\n".join(lines))


async def reveal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show predictions for all series/games whose deadline has passed."""
    from handlers.predictions import _deadline_passed

    lines = ["*👀 Прогнозы всех игроков (закрытые окна):*\n"]
    anything = False

    # Series
    for s in db.get_all_series():
        if not s["game1_tipoff"] or not _deadline_passed(s["game1_tipoff"]):
            continue
        preds = db.get_all_series_predictions(s["series_id"])
        if not preds:
            continue
        anything = True
        lines.append(f"\n*🏀 Series: {s['team_a_abbr']} vs {s['team_b_abbr']}*")
        for p in preds:
            pts = p["points_awarded"]
            pts_str = f" — {pts} pts" if pts is not None else ""
            lines.append(
                f"  👤 {p['display_name']}: {p['winner_abbr']} "
                f"{p['score_winner']}-{p['score_loser']}{pts_str}"
            )
        if s["status"] == "finished":
            lines.append(f"  🏆 ИТОГ: {s['winner_abbr']} {s['final_score_a']}-{s['final_score_b']}")

    # Recent games where deadline passed
    with db.get_conn() as conn:
        games = conn.execute("""
            SELECT * FROM games
            WHERE tipoff_utc < ?
            ORDER BY tipoff_utc DESC
            LIMIT 10
        """, (_now_iso(),)).fetchall()

    for g in games:
        preds = db.get_all_game_predictions(g["game_id"])
        if not preds:
            continue
        anything = True
        s = db.get_series(g["series_id"])
        lines.append(f"\n*🎯 Game {g['game_number']}: {g['away_abbr']} @ {g['home_abbr']}*"
                     f" _({s['team_a_abbr']} vs {s['team_b_abbr']})_")
        for p in preds:
            pts = p["points_awarded"]
            pts_str = f" — {pts} pts" if pts is not None else ""
            lines.append(f"  👤 {p['display_name']}: {p['winner_abbr']}{pts_str}")
        if g["status"] == "finished" and g["winner_abbr"]:
            lines.append(f"  🏆 ИТОГ: {g['winner_abbr']} ({g['home_abbr']} {g['home_score']}-{g['away_score']} {g['away_abbr']})")

    if not anything:
        lines.append("Пока нет закрытых окон — никто не сделал ни одного прогноза, либо дедлайны ещё не прошли.")

    # Telegram message limit is 4096 chars — split if needed
    text = "\n".join(lines)
    for chunk in _split_message(text, 3800):
        await update.message.reply_markdown(chunk)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_message(text: str, max_len: int):
    if len(text) <= max_len:
        return [text]
    chunks = []
    lines = text.split("\n")
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > max_len:
            chunks.append("\n".join(current))
            current, current_len = [line], len(line)
        else:
            current.append(line)
            current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks
