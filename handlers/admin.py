"""Admin commands — only for the owner (OWNER_TELEGRAM_ID).

- /admin_seed        — load initial bracket
- /admin_sync        — force NBA data sync
- /admin_recalc      — recompute all scores
- /admin_reveal_all  — manually trigger reveal of all passed-deadline predictions
"""
import logging
from functools import wraps

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
