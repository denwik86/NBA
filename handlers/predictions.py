"""/predict — interactive prediction flow using inline buttons.

Flow:
1. /predict → bot shows a list of "open" items:
     - Series where Game 1 hasn't started yet AND no series-prediction saved yet
     - Games that haven't tipped off yet AND no game-prediction saved yet
2. User taps a series → bot asks: "Who wins the series?" (2 buttons)
3. User taps team → bot asks: "Series score? (BO7)" (7 buttons: 4-0, 4-1, ... 4-3 in favor of chosen team)
4. Prediction saved.

For games, flow is simpler:
1. /predict → user taps game → picks a team → saved.

A deadline applies: if current_time + 1h >= tipoff, the option is no longer listed (or tapping shows "closed").

Callback data format (keep short — Telegram limits callback_data to 64 bytes):
    sp|<series_id>|<winner_abbr>            (series winner pick, step 1)
    sp|<series_id>|<winner_abbr>|<w>-<l>    (series with score, step 2)
    gp|<game_id>|<winner_abbr>              (game pick)
"""
import logging
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
from config import DEADLINE_MINUTES_BEFORE

log = logging.getLogger(__name__)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _deadline_passed(tipoff_utc_str: str) -> bool:
    """True if we're within DEADLINE_MINUTES_BEFORE of tipoff (or past it)."""
    try:
        tipoff = _parse_iso(tipoff_utc_str)
    except Exception:
        return True
    deadline = tipoff - timedelta(minutes=DEADLINE_MINUTES_BEFORE)
    return datetime.now(timezone.utc) >= deadline


async def predict_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show a menu of things the user can still predict."""
    user_id = update.effective_user.id
    if not db.get_player(user_id):
        await update.message.reply_text("Сначала зарегистрируйся: /start")
        return

    buttons = []

    # 1. Open series — Game 1 hasn't tipped off yet (even if within 1h window,
    #    we still *show* it but will gate saving. For simplicity: hide if deadline passed.)
    for s in db.get_pending_series():
        game1_tipoff = s["game1_tipoff"]
        if not game1_tipoff or _deadline_passed(game1_tipoff):
            continue
        # Already predicted?
        existing = db.get_series_prediction(user_id, s["series_id"])
        prefix = "✏️" if existing else "🆕"
        label = f"{prefix} SERIES: {s['team_a_abbr']} vs {s['team_b_abbr']} (R{s['round_num']})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"psel|{s['series_id']}")])

    # 2. Open games (next 7 days, haven't tipped off, deadline not passed)
    for g in db.get_upcoming_games(limit=20):
        if _deadline_passed(g["tipoff_utc"]):
            continue
        existing = db.get_game_prediction(user_id, g["game_id"])
        prefix = "✏️" if existing else "🆕"
        series = db.get_series(g["series_id"])
        if not series:
            continue
        label = f"{prefix} GAME {g['game_number']}: {g['away_abbr']} @ {g['home_abbr']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"gsel|{g['game_id']}")])

    if not buttons:
        await update.message.reply_text(
            "Сейчас нет открытых окон для прогнозов. Бот пришлёт уведомление, когда они появятся."
        )
        return

    await update.message.reply_text(
        f"Что прогнозируем? (окно открыто до -{DEADLINE_MINUTES_BEFORE} мин от тип-оффа)\n"
        "✏️ = уже есть прогноз, можно изменить\n"
        "🆕 = ещё не проставлено",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all inline-button callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split("|")
    user_id = update.effective_user.id

    if not db.get_player(user_id):
        await query.edit_message_text("Сначала зарегистрируйся: /start")
        return

    try:
        if parts[0] == "psel":
            await _handle_series_select(query, parts[1])
        elif parts[0] == "sp":
            if len(parts) == 3:
                await _handle_series_winner_pick(query, user_id, parts[1], parts[2])
            elif len(parts) == 4:
                await _handle_series_score_pick(query, user_id, parts[1], parts[2], parts[3])
        elif parts[0] == "gsel":
            await _handle_game_select(query, parts[1])
        elif parts[0] == "gp":
            await _handle_game_pick(query, user_id, parts[1], parts[2])
        elif parts[0] == "noop":
            pass
        else:
            await query.edit_message_text("Неизвестное действие.")
    except Exception as e:
        log.exception("Callback handler error: %s", e)
        await query.edit_message_text("Ошибка, попробуй ещё раз через /predict")


async def _handle_series_select(query, series_id: str):
    s = db.get_series(series_id)
    if not s:
        await query.edit_message_text("Серия не найдена.")
        return
    if _deadline_passed(s["game1_tipoff"]):
        await query.edit_message_text("⏰ Дедлайн по этой серии уже прошёл.")
        return

    text = (f"🏀 *{s['team_a_name']} (#{s['team_a_seed']}) vs {s['team_b_name']} (#{s['team_b_seed']})*\n\n"
            f"Кто победит в серии?")
    buttons = [[
        InlineKeyboardButton(f"🏆 {s['team_a_abbr']}",
                             callback_data=f"sp|{series_id}|{s['team_a_abbr']}"),
        InlineKeyboardButton(f"🏆 {s['team_b_abbr']}",
                             callback_data=f"sp|{series_id}|{s['team_b_abbr']}"),
    ]]
    await query.edit_message_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup(buttons))


async def _handle_series_winner_pick(query, user_id: int, series_id: str, winner_abbr: str):
    s = db.get_series(series_id)
    if not s or _deadline_passed(s["game1_tipoff"]):
        await query.edit_message_text("⏰ Дедлайн прошёл.")
        return

    loser_abbr = s["team_b_abbr"] if winner_abbr == s["team_a_abbr"] else s["team_a_abbr"]
    text = (f"Ты выбрал *{winner_abbr}* 🏆\n\n"
            f"Теперь точный счёт серии?\n"
            f"(формат: {winner_abbr}-{loser_abbr})")

    buttons = []
    for loser_wins in (0, 1, 2, 3):
        score_str = f"4-{loser_wins}"
        buttons.append([InlineKeyboardButton(
            score_str,
            callback_data=f"sp|{series_id}|{winner_abbr}|4-{loser_wins}",
        )])

    await query.edit_message_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup(buttons))


async def _handle_series_score_pick(query, user_id: int, series_id: str,
                                     winner_abbr: str, score_str: str):
    s = db.get_series(series_id)
    if not s or _deadline_passed(s["game1_tipoff"]):
        await query.edit_message_text("⏰ Дедлайн прошёл, прогноз не сохранён.")
        return

    try:
        w_str, l_str = score_str.split("-")
        score_w, score_l = int(w_str), int(l_str)
    except Exception:
        await query.edit_message_text("Ошибка формата счёта.")
        return

    db.save_series_prediction(user_id, series_id, winner_abbr, score_w, score_l)
    await query.edit_message_text(
        f"✅ Прогноз сохранён!\n"
        f"Серия {s['team_a_abbr']} vs {s['team_b_abbr']}: "
        f"*{winner_abbr} {score_w}-{score_l}*\n\n"
        f"Можно менять до закрытия окна (/predict).",
        parse_mode="Markdown",
    )


async def _handle_game_select(query, game_id: str):
    g = db.get_game(game_id)
    if not g:
        await query.edit_message_text("Матч не найден.")
        return
    if _deadline_passed(g["tipoff_utc"]):
        await query.edit_message_text("⏰ Дедлайн по этому матчу уже прошёл.")
        return

    s = db.get_series(g["series_id"])
    text = (f"🏀 *Game {g['game_number']}*: "
            f"{g['away_abbr']} @ {g['home_abbr']}\n"
            f"(серия: {s['team_a_abbr']} vs {s['team_b_abbr']})\n\n"
            f"Кто победит?")
    buttons = [[
        InlineKeyboardButton(f"🏆 {g['away_abbr']}", callback_data=f"gp|{game_id}|{g['away_abbr']}"),
        InlineKeyboardButton(f"🏆 {g['home_abbr']}", callback_data=f"gp|{game_id}|{g['home_abbr']}"),
    ]]
    await query.edit_message_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup(buttons))


async def _handle_game_pick(query, user_id: int, game_id: str, winner_abbr: str):
    g = db.get_game(game_id)
    if not g or _deadline_passed(g["tipoff_utc"]):
        await query.edit_message_text("⏰ Дедлайн прошёл, прогноз не сохранён.")
        return

    db.save_game_prediction(user_id, game_id, winner_abbr)
    await query.edit_message_text(
        f"✅ Прогноз на Game {g['game_number']} сохранён: *{winner_abbr}*\n\n"
        f"Можно менять до закрытия окна (/predict).",
        parse_mode="Markdown",
    )
