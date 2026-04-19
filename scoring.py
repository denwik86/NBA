"""Scoring logic for the tournament.

Rules (per user spec):
- Correct series winner:         +3 pts
- Exact series score (e.g. 4-2): +10 pts (awarded IN ADDITION to winner bonus)
- Correct game winner:           +1 pt
- No prediction submitted:        0 pts

When a series finishes:
  award_series_points(series_id) — reads every player's prediction for that series
  and sets points_awarded.

When a game finishes:
  award_game_points(game_id)

Both are idempotent — safe to call multiple times (they recompute).
"""
import logging

import database as db

log = logging.getLogger(__name__)

POINTS_WINNER = 3
POINTS_EXACT = 10  # Given in addition to winner points — so exact correct = 13 total
POINTS_GAME = 1


def award_series_points(series_id: str):
    series = db.get_series(series_id)
    if not series or series["status"] != "finished":
        log.debug("Series %s not finished, skipping scoring", series_id)
        return

    winner = series["winner_abbr"]
    final_a = series["final_score_a"]  # wins for team A
    final_b = series["final_score_b"]  # wins for team B
    # Determine the "score line" in (winner_wins, loser_wins) format
    if winner == series["team_a_abbr"]:
        actual_winner_wins, actual_loser_wins = final_a, final_b
    else:
        actual_winner_wins, actual_loser_wins = final_b, final_a

    predictions = db.get_all_series_predictions(series_id)
    for p in predictions:
        points = 0
        if p["winner_abbr"] == winner:
            points += POINTS_WINNER
            if p["score_winner"] == actual_winner_wins and p["score_loser"] == actual_loser_wins:
                points += POINTS_EXACT
        db.update_prediction_points("series_predictions", p["id"], points)
        log.info("Series %s: player %s got %d pts (pred: %s %d-%d, actual: %s %d-%d)",
                 series_id, p["display_name"], points,
                 p["winner_abbr"], p["score_winner"], p["score_loser"],
                 winner, actual_winner_wins, actual_loser_wins)


def award_game_points(game_id: str):
    game = db.get_game(game_id)
    if not game or game["status"] != "finished" or not game["winner_abbr"]:
        return

    predictions = db.get_all_game_predictions(game_id)
    for p in predictions:
        points = POINTS_GAME if p["winner_abbr"] == game["winner_abbr"] else 0
        db.update_prediction_points("game_predictions", p["id"], points)
        log.info("Game %s: player %s got %d pts (pred: %s, actual: %s)",
                 game_id, p["display_name"], points, p["winner_abbr"], game["winner_abbr"])


def recalculate_all():
    """Recompute every score from scratch. Useful for admin fix-ups."""
    for s in db.get_all_series():
        if s["status"] == "finished":
            award_series_points(s["series_id"])
        for g in db.get_games_for_series(s["series_id"]):
            if g["status"] == "finished":
                award_game_points(g["game_id"])
