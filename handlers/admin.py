"""Admin commands — only for the owner (OWNER_TELEGRAM_ID).

- /admin_seed              — load initial first-round bracket
- /admin_sync              — force NBA data sync from ESPN
- /admin_recalc            — recompute all scores
- /admin_players           — list registered players
- /admin_add_series        — add a new playoff series (Round 2+)
- /admin_add_game          — add a single game to a series
- /admin_list_games        — list all known games
- /admin_set_result        — manually set a single game result + award points
- /admin_set_series_result — manually set a series result + award points
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
async def admin_add_series(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually add a new playoff series (Round 2, 3, Finals)."""
    args = context.args
    if len(args) < 8:
        existing = db.get_all_series()
        existing_ids = sorted({s["series_id"] for s in existing})
        lines = ["*Использование:*",
                 "`/admin_add_series <series_id> <round> <conf> <team_a> <seed_a> <team_b> <seed_b> <UTC-time>`\n",
                 "*Пример (Round 2 East NYK vs CLE):*",
                 "`/admin_add_series 2026-R2-E1 2 East NYK 3 CLE 4 2026-05-06T00:00`\n",
                 "*Naming convention:*",
                 "  `2026-R2-E1`, `2026-R2-E2` — Round 2 East",
                 "  `2026-R2-W1`, `2026-R2-W2` — Round 2 West",
                 "  `2026-R3-E1` — East Conference Finals",
                 "  `2026-R3-W1` — West Conference Finals",
                 "  `2026-R4-F1` — NBA Finals\n",
                 "*Уже существующие серии:*"]
        for sid in existing_ids:
            lines.append(f"  `{sid}`")
        await update.message.reply_markdown("\n".join(lines))
        return

    series_id, round_num, conference = args[0], args[1], args[2]
    team_a, seed_a = args[3].upper(), args[4]
    team_b, seed_b = args[5].upper(), args[6]
    tipoff_str = args[7]

    try:
        round_int = int(round_num)
        seed_a_int = int(seed_a)
        seed_b_int = int(seed_b)
        if len(tipoff_str) == 16:
            tipoff_str += ":00"
        tipoff_dt = datetime.fromisoformat(tipoff_str.replace("Z", "+00:00"))
        if tipoff_dt.tzinfo is None:
            tipoff_dt = tipoff_dt.replace(tzinfo=timezone.utc)
        tipoff_utc = tipoff_dt.astimezone(timezone.utc).isoformat()
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка формата: {e}")
        return

    existing = db.get_series(series_id)
    action = "Обновлена" if existing else "Добавлена"

    name_lookup = {
        "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "CLE": "Cleveland Cavaliers",
        "DET": "Detroit Pistons", "MIN": "Minnesota Timberwolves", "NYK": "New York Knicks",
        "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "TOR": "Toronto Raptors",
        "DEN": "Denver Nuggets", "HOU": "Houston Rockets", "LAL": "Los Angeles Lakers",
        "OKC": "Oklahoma City Thunder", "PHX": "Phoenix Suns", "POR": "Portland Trail Blazers",
        "SAS": "San Antonio Spurs",
    }
    team_a_name = name_lookup.get(team_a, team_a)
    team_b_name = name_lookup.get(team_b, team_b)

    db.upsert_series(
        series_id=series_id,
        round_num=round_int,
        conference=conference,
        team_a_name=team_a_name, team_a_abbr=team_a, team_a_seed=seed_a_int,
        team_b_name=team_b_name, team_b_abbr=team_b, team_b_seed=seed_b_int,
        game1_tipoff=tipoff_utc,
    )

    await update.message.reply_markdown(
        f"✅ {action} серия *{series_id}*\n"
        f"Round {round_int} ({conference})\n"
        f"#{seed_a_int} {team_a_name} vs #{seed_b_int} {team_b_name}\n"
        f"Game 1 tipoff: `{tipoff_utc}`\n\n"
        f"Теперь добавь матчи: `/admin_add_game {series_id} 1 <away> <home> {tipoff_str}` "
        f"для G1, и так же для G2-G7.\n\n"
        f"После этого ESPN-синк будет автоматически подтягивать результаты по парам команд."
    )


@owner_only
async def admin_add_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /admin_add_game <series_id> <game_num> <away_abbr> <home_abbr> <YYYY-MM-DDTHH:MM>"""
    args = context.args
    if len(args) < 5:
        series_list = db.get_all_series()
        lines = ["*Использование:*",
                 "`/admin_add_game <series_id> <game_num> <away> <home> <UTC-time>`\n",
                 "*Пример:* `/admin_add_game 2026-R2-E1 1 CLE NYK 2026-05-06T00:00`\n",
                 "*Известные серии:*"]
        for s in series_list:
            lines.append(f"  `{s['series_id']}` — {s['team_a_abbr']} vs {s['team_b_abbr']}")
        lines.append("\n⚠️ Время в UTC. ET + 4 часа = UTC.")
        await update.message.reply_markdown("\n".join(lines))
        return

    series_id, game_num = args[0], args[1]
    away, home = args[2].upper(), args[3].upper()
    tipoff_str = args[4]

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


@owner_only
async def admin_set_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually set a game result. Usage:
       /admin_set_result <game_id> <winner_abbr> <home_score> <away_score>
    """
    args = context.args
    if len(args) < 4:
        await update.message.reply_markdown(
            "*Использование:*\n"
            "`/admin_set_result <game_id> <winner> <home_score> <away_score>`\n\n"
            "*Пример:* `/admin_set_result manual-2026-R1-E3-G1 NYK 113 102`\n\n"
            "Найти game_id: /admin_list_games"
        )
        return

    game_id, winner_abbr = args[0], args[1].upper()
    try:
        home_score = int(args[2])
        away_score = int(args[3])
    except ValueError:
        await update.message.reply_text("❌ Счёт должен быть числом.")
        return

    game = db.get_game(game_id)
    if not game:
        await update.message.reply_text(
            f"❌ Нет игры `{game_id}`. /admin_list_games", parse_mode="Markdown"
        )
        return

    valid_teams = {game["home_abbr"], game["away_abbr"]}
    if winner_abbr not in valid_teams:
        await update.message.reply_text(
            f"❌ {winner_abbr} не в этой игре ({game['home_abbr']} vs {game['away_abbr']})."
        )
        return

    if winner_abbr == game["home_abbr"] and home_score <= away_score:
        await update.message.reply_text(
            f"⚠️ {winner_abbr} победитель, но счёт {home_score}-{away_score} говорит об обратном."
        )
        return
    if winner_abbr == game["away_abbr"] and away_score <= home_score:
        await update.message.reply_text(
            f"⚠️ {winner_abbr} победитель, но счёт {home_score}-{away_score} говорит об обратном."
        )
        return

    db.set_game_result(game_id, winner_abbr, home_score, away_score)
    scoring.award_game_points(game_id)

    preds = db.get_all_game_predictions(game_id)
    msg = [f"✅ Результат сохранён: *{game['away_abbr']} {away_score} - {home_score} {game['home_abbr']}*",
           f"🏆 Победитель: *{winner_abbr}*\n"]
    if preds:
        msg.append("_Очки начислены:_")
        for p in preds:
            pts = p["points_awarded"] or 0
            emoji = "✅" if pts > 0 else "❌"
            msg.append(f"{emoji} {p['display_name']}: {p['winner_abbr']} → *{pts} pts*")
    else:
        msg.append("_(никто не делал прогноз)_")

    await update.message.reply_markdown("\n".join(msg))


@owner_only
async def admin_set_series_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually set a series result. Usage:
       /admin_set_series_result <series_id> <winner_abbr> <wins_a> <wins_b>
    """
    args = context.args
    if len(args) < 4:
        await update.message.reply_markdown(
            "*Использование:*\n"
            "`/admin_set_series_result <series_id> <winner> <wins_team_a> <wins_team_b>`\n\n"
            "*Пример:* `/admin_set_series_result 2026-R1-E3 NYK 4 2`\n"
            "_wins_team_a_ = победы у team_a (та, что первая в серии)\n"
            "_wins_team_b_ = победы у team_b\n\n"
            "Список серий: /admin_list_games"
        )
        return

    series_id, winner_abbr = args[0], args[1].upper()
    try:
        wins_a = int(args[2])
        wins_b = int(args[3])
    except ValueError:
        await update.message.reply_text("❌ Победы должны быть числом.")
        return

    series = db.get_series(series_id)
    if not series:
        await update.message.reply_text(f"❌ Нет серии `{series_id}`.", parse_mode="Markdown")
        return

    valid = {series["team_a_abbr"], series["team_b_abbr"]}
    if winner_abbr not in valid:
        await update.message.reply_text(
            f"❌ {winner_abbr} не в серии ({series['team_a_abbr']} vs {series['team_b_abbr']})."
        )
        return

    if wins_a + wins_b < 4 or wins_a + wins_b > 7:
        await update.message.reply_text(f"⚠️ Сумма побед {wins_a+wins_b} странная.")
        return
    if winner_abbr == series["team_a_abbr"] and wins_a < 4:
        await update.message.reply_text(f"⚠️ {winner_abbr} победитель, но < 4 побед.")
        return
    if winner_abbr == series["team_b_abbr"] and wins_b < 4:
        await update.message.reply_text(f"⚠️ {winner_abbr} победитель, но < 4 побед.")
        return

    db.set_series_result(series_id, winner_abbr, wins_a, wins_b)
    scoring.award_series_points(series_id)

    preds = db.get_all_series_predictions(series_id)
    msg = [f"✅ Серия закрыта: *{series['team_a_abbr']} vs {series['team_b_abbr']}*",
           f"🏆 Победитель: *{winner_abbr}* ({wins_a}-{wins_b})\n"]
    if preds:
        msg.append("_Очки за серию:_")
        for p in preds:
            pts = p["points_awarded"] or 0
            emoji = "🎯" if pts == 13 else ("✅" if pts == 3 else "❌")
            msg.append(
                f"{emoji} {p['display_name']}: {p['winner_abbr']} "
                f"{p['score_winner']}-{p['score_loser']} → *{pts} pts*"
            )
    else:
        msg.append("_(никто не ставил)_")

    await update.message.reply_markdown("\n".join(msg))
