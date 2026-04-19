"""/start — register a new tournament participant."""
from telegram import Update
from telegram.ext import ContextTypes

import database as db


WELCOME = """🏀 *NBA Playoffs Prediction Tournament*

Добро пожаловать, {name}! Ты зарегистрирован в турнире прогнозистов.

*Как играть:*
• Перед каждой серией плей-офф (за ~1 час до Game 1) ты делаешь прогноз:
  – кто победит в серии → +3 очка
  – точный счёт серии (например 4-2) → +10 очков
• Перед каждым матчем серии делаешь прогноз на его победителя → +1 очко
• Нет прогноза → 0 очков

Прогнозы друзей скрыты до момента старта игры — ни подсмотреть, ни списать 😎

*Основные команды:*
/predict — сделать прогноз
/schedule — расписание ближайших игр
/bracket — сетка плей-офф
/standings — таблица лидеров
/mypredictions — мои прогнозы
/help — все команды

Погнали! Первый раунд уже начался 🔥"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    display_name = user.full_name or user.username or f"User{user.id}"
    db.add_player(user.id, user.username or "", display_name)

    await update.message.reply_markdown(
        WELCOME.format(name=display_name),
    )


HELP_TEXT = """*Команды бота:*

/predict — сделать прогноз на открытую серию/матч
/mypredictions — показать мои прогнозы
/schedule — расписание ближайших 10 игр
/bracket — текущая сетка плей-офф
/standings — таблица лидеров
/reveal — показать прогнозы друзей по уже закрытым окнам
/help — это сообщение

*Правила:*
• За 1 час до начала Game 1 серии — закрываются прогнозы на серию (3+10 очков)
• За 1 час до каждого матча — закрываются прогнозы на матч (1 очко)
• После закрытия все видят прогнозы всех
"""


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_markdown(HELP_TEXT)
