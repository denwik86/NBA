# 🚀 Деплой за 15 минут (Railway)

Пошагово. Railway — самый простой хостинг с бесплатным тарифом $5/мес кредита (хватает для этого бота с запасом).

---

## Шаг 1 — Создать бота в Telegram (2 минуты)

1. Открой Telegram, найди [@BotFather](https://t.me/BotFather)
2. Отправь `/newbot`
3. Придумай имя бота (например: `NBA Playoffs Predictor`)
4. Придумай username (должен заканчиваться на `bot`, например `viktar_nba_playoffs_bot`)
5. BotFather пришлёт токен вида:
   ```
   7234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
   ```
6. **Сохрани этот токен** — он нужен будет на шаге 3

### Дополнительно: узнать свой Telegram ID
1. Напиши [@userinfobot](https://t.me/userinfobot) в Telegram
2. Он пришлёт твой ID, например `123456789`
3. Это значение для `OWNER_TELEGRAM_ID`

### Дополнительно: создать групповой чат
1. Создай группу в Telegram с друзьями (всеми 5 участниками)
2. Добавь в группу своего бота
3. Сделай бота администратором (иначе он не сможет писать в группу)
4. Узнать ID группы: добавь в группу [@getidsbot](https://t.me/getidsbot), он пришлёт ID группы (обычно отрицательное число, например `-1001234567890`). Потом [@getidsbot](https://t.me/getidsbot) можно удалить.

---

## Шаг 2 — Залить код на GitHub (3 минуты)

1. Зарегистрируйся на [github.com](https://github.com) (если ещё нет)
2. Создай новый приватный репозиторий: `nba-bot`
3. Загрузи файлы. Самый простой способ — через веб-интерфейс:
   - "uploading an existing file"
   - Перетащить все файлы проекта (кроме `.env` и папки `data/`)
   - Commit

Альтернатива через терминал:
```bash
cd nba-bot
git init
git add .
git commit -m "Initial bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/nba-bot.git
git push -u origin main
```

---

## Шаг 3 — Задеплоить на Railway (5 минут)

1. Зайти на [railway.app](https://railway.app), зарегистрироваться через GitHub
2. Нажать **"New Project"** → **"Deploy from GitHub repo"**
3. Авторизовать Railway на доступ к репозиториям, выбрать `nba-bot`
4. Railway автоматически определит Python и начнёт деплой

### Добавить переменные окружения:
1. Открыть проект → вкладка **Variables**
2. Добавить:
   - `BOT_TOKEN` = токен из шага 1
   - `OWNER_TELEGRAM_ID` = твой ID
   - `GROUP_CHAT_ID` = ID группы (опционально, можно оставить пустым)
   - `TIMEZONE` = `Europe/Amsterdam` (или твой)
3. Railway автоматически перезапустит бота

### Проверить логи:
- Вкладка **Deployments** → клик по последнему деплою → **View Logs**
- Должно быть: `Bot is starting...`

---

## Шаг 4 — Пригласить друзей (2 минуты)

1. Отправь друзьям username бота (например `@viktar_nba_playoffs_bot`)
2. Каждый пишет боту `/start`
3. Готово ✅

Проверить что все зарегистрировались: `/admin_players` (только для тебя)

---

## Шаг 5 — Первый прогноз (1 минута)

1. В личке боту (или в группе): `/bracket` — увидишь все 8 серий первого раунда
2. `/schedule` — ближайшие игры
3. `/predict` — сделать прогнозы

**Важно:** Первый раунд 2026 уже стартовал 18 апреля! Успей сделать прогнозы на те серии, которые ещё не начались (Game 1 в воскресенье: Pistons-Magic, Celtics-76ers, Thunder-Suns, Spurs-Blazers).

---

## Проблемы?

**"Бот не отвечает"** → Проверь логи в Railway. Чаще всего неправильный `BOT_TOKEN`.

**"Сетка пустая, /bracket ничего не показывает"** → Выполни `/admin_seed` (только ты можешь)

**"Результаты не подтягиваются"** → Выполни `/admin_sync`. Если не помогло, ESPN мог изменить API — напиши issue.

**"Хочу пересчитать очки"** → `/admin_recalc`

---

## Локальный запуск (для разработки)

```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env
# отредактировать .env
python bot.py
```
