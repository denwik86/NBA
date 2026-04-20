"""Admin commands — only for the owner (OWNER_TELEGRAM_ID).

- /admin_seed        — load initial bracket
- /admin_sync        — force NBA data sync
- /admin_recalc      — recompute all scores
- /admin_players     — list registered players
- /admin_add_game    — manually add a game to a series
- /admin_list_games  — list all known games
"""
import logging
from functools import wraps
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

import database as db
import nba_data
import scoring
from config import OWNER_TELEGRAM_ID

log = logging.getLogger(__name__)


def owner_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != OWNER_TELEGRAM_ID:
            await update.message.reply_text("Только для админа.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


@owner_only
async def admin_seed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nba_data.seed_initial_bracket()
    await update.message.reply_text("✅ Начальная сетка загружена.")


@owner_only
async def admin_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Синхронизация с ESPN...")
    nba_data.sync_with_espn()
    await update.message.reply_text("✅ Синк выполнен.")


@owner_only
async def admin_recalc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scoring.recalculate_all()
    await update.message.reply_text("✅ Очки пересчитаны.")


@owner_only
async def admin_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    players = db.get_all_players()
    if not players:
        await update.message.reply_text("Нет зарегистрированных.")
        return
    lines = ["*Зарегистрированные игроки:*"]
    for p in players:
        lines.append(f"• {p['display_name']} (@{p['username']}) — ID `{p['telegram_id']}`")
    await update.message.reply_markdown("\n".join(lines))


@owner_only
async def admin_add_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /admin_add_game <series_id> <game_num> <away_abbr> <home_abbr> <YYYY-MM-DDTHH:MM>"""
    args = context.args
    if len(args) < 5:
        series_list = db.get_all_series()
        lines = ["*Использование:*",
                 "`/admin_add_game <series_id> <game_num> <away> <home> <UTC-time>`\n",
                 "*Пример:* `/admin_add_game 2026-R1-E3 2 ATL NYK 2026-04-21T00:00`\n",
                 "*Известные серии:*"]
        for s in series_list:
            lines.append(f"  `{s['series_id']}` — {s['team_a_abbr']} vs {s['team_b_abbr']}")
        lines.append("\n⚠️ Время в UTC. ET + 4 часа = UTC.")
        await update.message.reply_markdown("\n".join(lines))
        return

    series_id, game_num, away, home, tipoff_str = args[0], args[1], args[2].upper(), args[3].upper(), args[4]

    series = db.get_series(series_id)
    if not series:
        await update.message.reply_text(f"❌ Нет серии с ID {series_id}")
        return

    valid_abbrs = {series["team_a_abbr"], series["team_b_abbr"]}
    if {away, home} != valid_abbrs:
        await update.message.reply_text(
            f"❌ Команды {away}/{home} не в серии {series['team_a_abbr']} vs {series['team_b_abbr']}"
        )
        return

    try:
        game_num_int = int(game_num)
        if len(tipoff_str) == 16:
            tipoff_str += ":00"
        tipoff_dt = datetime.fromisoformat(tipoff_str.replace("Z", "+00:00"))
        if tipoff_dt.tzinfo is None:
            tipoff_dt = tipoff_dt.replace(tzinfo=timezone.utc)
        tipoff_utc = tipoff_dt.astimezone(timezone.utc).isoformat()
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка формата: {e}")
        return

    game_id = f"manual-{series_id}-G{game_num_int}"
    db.upsert_game(
        game_id=game_id, series_id=series_id, game_number=game_num_int,
        tipoff_utc=tipoff_utc, home_abbr=home, away_abbr=away, status="scheduled",
    )
    await update.message.reply_markdown(
        f"✅ Добавлен *Game {game_num_int}*: {away} @ {home}\n"
        f"Tipoff: `{tipoff_utc}`"
    )


@owner_only
async def admin_list_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all known games per series."""
    series_list = db.get_all_series()
    lines = ["*Все известные матчи:*\n"]
    for s in series_list:
        games = db.get_games_for_series(s["series_id"])
        lines.append(f"\n*`{s['series_id']}`* — {s['team_a_abbr']} vs {s['team_b_abbr']}")
        if not games:
            lines.append("  _(нет матчей)_")
            continue
        for g in games:
            status_icon = {"scheduled": "📅", "live": "🔴", "finished": "✅"}.get(g["status"], "?")
            lines.append(
                f"  {status_icon} G{g['game_number']}: {g['away_abbr']} @ {g['home_abbr']} "
                f"— {g['tipoff_utc'][:16]} ({g['status']})"
            )
    text = "\n".join(lines)
    for i in range(0, len(text), 3800):
        await update.message.reply_markdown(text[i:i+3800])
