"""NBA Playoffs Prediction Tournament Bot — entry point."""
import logging

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
)

from config import BOT_TOKEN
import database as db
import nba_data
import scheduler
from handlers import registration, predictions, info, admin

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def main():
    db.init_db()
    nba_data.seed_initial_bracket()

    try:
        nba_data.sync_with_espn()
    except Exception as e:
        log.warning("Initial ESPN sync failed (will retry later): %s", e)

    app = Application.builder().token(BOT_TOKEN).build()

    # Regular user commands
    app.add_handler(CommandHandler("start", registration.start))
    app.add_handler(CommandHandler("help", registration.help_cmd))
    app.add_handler(CommandHandler("predict", predictions.predict_cmd))
    app.add_handler(CommandHandler("schedule", info.schedule_cmd))
    app.add_handler(CommandHandler("bracket", info.bracket_cmd))
    app.add_handler(CommandHandler("standings", info.standings_cmd))
    app.add_handler(CommandHandler("mypredictions", info.mypredictions_cmd))
    app.add_handler(CommandHandler("reveal", info.reveal_cmd))

    # Admin commands
    app.add_handler(CommandHandler("admin_seed", admin.admin_seed))
    app.add_handler(CommandHandler("admin_sync", admin.admin_sync))
    app.add_handler(CommandHandler("admin_recalc", admin.admin_recalc))
    app.add_handler(CommandHandler("admin_players", admin.admin_players))
    app.add_handler(CommandHandler("admin_add_series", admin.admin_add_series))
    app.add_handler(CommandHandler("admin_add_game", admin.admin_add_game))
    app.add_handler(CommandHandler("admin_list_games", admin.admin_list_games))
    app.add_handler(CommandHandler("admin_set_result", admin.admin_set_result))
    app.add_handler(CommandHandler("admin_set_series_result", admin.admin_set_series_result))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(predictions.on_callback))

    # Background jobs
    scheduler.register_jobs(app)

    log.info("Bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
