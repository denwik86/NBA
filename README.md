# 🏀 NBA Playoffs Prediction Tournament Bot

Telegram-бот для турнира прогнозистов NBA плей-офф на 5 человек.

## 🎯 Как это работает

### Правила начисления очков
| Прогноз | Очки | Когда делается |
|---------|------|----------------|
| Победитель серии | **3** | До начала Game 1 (за 1 час) |
| Точный счёт серии (например, 4-2) | **10** | До начала Game 1 (за 1 час) |
| Результат отдельного матча | **1** | До начала каждого матча (за 1 час) |
| Нет прогноза | **0** | — |

### Порядок действий
1. Бот знает расписание плей-офф NBA и следит за ним
2. **За ~1.5 часа до Game 1 серии** — бот присылает уведомление: «Через час закрываются прогнозы на серию Cavaliers vs Raptors»
3. Каждый участник пишет свой прогноз (выбирает через inline-кнопки)
4. **В момент начала игры** — бот показывает все прогнозы всем участникам
5. После окончания матча/серии — бот автоматически подтягивает результат и считает очки
6. Таблица лидеров обновляется в реальном времени

## 📱 Команды бота

| Команда | Действие |
|---------|----------|
| `/start` | Регистрация в турнире |
| `/predict` | Сделать прогноз (показывает текущие открытые окна) |
| `/mypredictions` | Мои прогнозы |
| `/bracket` | Текущая сетка плей-офф |
| `/schedule` | Расписание ближайших игр |
| `/standings` | Таблица лидеров |
| `/reveal` | Показать прогнозы друзей (только для уже закрытых) |
| `/help` | Справка |

## 🚀 Деплой

### 1. Создать бота в Telegram
1. Написать [@BotFather](https://t.me/BotFather) в Telegram
2. `/newbot` → придумать имя → получить `BOT_TOKEN`

### 2. Локальный запуск (для теста)
```bash
git clone <repo>
cd nba-bot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Отредактировать .env — вставить BOT_TOKEN
python bot.py
```

### 3. Деплой на Railway (рекомендую, бесплатно)
1. Зарегистрироваться на [railway.app](https://railway.app)
2. New Project → Deploy from GitHub repo
3. В Variables добавить `BOT_TOKEN`
4. Railway сам увидит `Procfile` и запустит
5. Готово ✅

### 4. Альтернатива: Render.com
- New Background Worker → указать команду `python bot.py`
- Добавить env переменную `BOT_TOKEN`

## 🏗️ Архитектура

```
nba-bot/
├── bot.py                 # Точка входа, регистрация handlers
├── config.py              # Настройки, токен
├── database.py            # SQLite: игроки, серии, прогнозы, очки
├── nba_data.py            # Подтягивание сетки и результатов (ESPN API)
├── scoring.py             # Логика подсчёта очков
├── scheduler.py           # Автоматические уведомления и проверки результатов
├── handlers/
│   ├── registration.py    # /start
│   ├── predictions.py     # /predict — inline-кнопки для выбора
│   ├── info.py            # /bracket, /schedule, /standings, /mypredictions
│   └── reveal.py          # Раскрытие прогнозов после дедлайна
├── data/
│   └── tournament.db      # SQLite база (создаётся автоматически)
├── requirements.txt
├── Procfile               # для Railway/Render
├── .env.example
└── README.md
```

## 🔌 Источник данных NBA

Используется **ESPN API** (неофициальный, но публичный и надёжный):
- `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard`
- `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={id}`

Обновление сетки каждые 15 минут (через APScheduler). При старте первого раунда 2026:
- **East**: Pistons-Magic, Celtics-76ers, Knicks-Hawks, Cavaliers-Raptors
- **West**: Thunder-Suns, Spurs-Trail Blazers, Nuggets-Timberwolves, Lakers-Rockets

## ⚙️ Админ-команды (только для владельца)

- `/admin_force_close <series_id>` — принудительно закрыть прогнозы
- `/admin_reveal <series_id>` — вручную раскрыть прогнозы
- `/admin_recalc` — пересчитать очки
- `/admin_seed` — загрузить начальную сетку плей-офф

## 🔒 Приватность прогнозов

Прогнозы хранятся в базе с флагом `revealed=False`. Бот **никогда** не показывает прогноз другого игрока, пока:
- не истёк дедлайн (< 1 час до игры), ИЛИ
- игра уже началась

После дедлайна в чат автоматически падает сообщение вида:
```
🔒 Прогнозы закрыты! Cavaliers vs Raptors, Game 1
👤 Витя: Cavaliers (4-2), Game 1: Cavaliers
👤 Саша: Raptors (4-3), Game 1: Raptors
👤 Лёша: Cavaliers (4-1), Game 1: Cavaliers
...
```
