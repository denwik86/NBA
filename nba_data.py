"""NBA data fetcher using ESPN's public API.

ESPN endpoints (no auth required):
- scoreboard:  https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD
- summary:     https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={id}
- standings:   https://site.api.espn.com/apis/site/v2/sports/basketball/nba/standings

During playoffs, the scoreboard's competitions include `seriesSummary` (e.g. "Series tied 1-1",
"Team A leads 3-2") and a `seriesGameNumber` field we can parse.

This module is deliberately defensive: ESPN occasionally changes payload structure,
so we wrap parsing in try/except and log rather than crash the bot.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

import database as db

log = logging.getLogger(__name__)

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"

# Seed NBA first round 2026 — used as fallback if ESPN parsing fails or for bootstrapping
# before the API confirms all matchups. Edit if seeds change.
FIRST_ROUND_2026 = [
    # East
    dict(series_id="2026-R1-E1", round_num=1, conference="East",
         team_a_name="Detroit Pistons", team_a_abbr="DET", team_a_seed=1,
         team_b_name="Orlando Magic",    team_b_abbr="ORL", team_b_seed=8,
         game1_tipoff="2026-04-19T22:30:00+00:00"),  # 6:30pm ET Sunday
    dict(series_id="2026-R1-E2", round_num=1, conference="East",
         team_a_name="Boston Celtics",        team_a_abbr="BOS", team_a_seed=2,
         team_b_name="Philadelphia 76ers",    team_b_abbr="PHI", team_b_seed=7,
         game1_tipoff="2026-04-19T17:00:00+00:00"),  # 1pm ET Sunday
    dict(series_id="2026-R1-E3", round_num=1, conference="East",
         team_a_name="New York Knicks",       team_a_abbr="NYK", team_a_seed=3,
         team_b_name="Atlanta Hawks",         team_b_abbr="ATL", team_b_seed=6,
         game1_tipoff="2026-04-18T22:00:00+00:00"),  # 6pm ET Saturday
    dict(series_id="2026-R1-E4", round_num=1, conference="East",
         team_a_name="Cleveland Cavaliers",   team_a_abbr="CLE", team_a_seed=4,
         team_b_name="Toronto Raptors",       team_b_abbr="TOR", team_b_seed=5,
         game1_tipoff="2026-04-18T17:00:00+00:00"),  # 1pm ET Saturday
    # West
    dict(series_id="2026-R1-W1", round_num=1, conference="West",
         team_a_name="Oklahoma City Thunder", team_a_abbr="OKC", team_a_seed=1,
         team_b_name="Phoenix Suns",          team_b_abbr="PHX", team_b_seed=8,
         game1_tipoff="2026-04-19T19:30:00+00:00"),  # 3:30pm ET Sunday
    dict(series_id="2026-R1-W2", round_num=1, conference="West",
         team_a_name="San Antonio Spurs",     team_a_abbr="SAS", team_a_seed=2,
         team_b_name="Portland Trail Blazers", team_b_abbr="POR", team_b_seed=7,
         game1_tipoff="2026-04-20T01:00:00+00:00"),  # 9pm ET Sunday
    dict(series_id="2026-R1-W3", round_num=1, conference="West",
         team_a_name="Denver Nuggets",        team_a_abbr="DEN", team_a_seed=3,
         team_b_name="Minnesota Timberwolves", team_b_abbr="MIN", team_b_seed=6,
         game1_tipoff="2026-04-18T19:30:00+00:00"),  # 3:30pm ET Saturday
    dict(series_id="2026-R1-W4", round_num=1, conference="West",
         team_a_name="Los Angeles Lakers",    team_a_abbr="LAL", team_a_seed=4,
         team_b_name="Houston Rockets",       team_b_abbr="HOU", team_b_seed=5,
         game1_tipoff="2026-04-19T00:30:00+00:00"),  # 8:30pm ET Saturday
]


def seed_initial_bracket():
    """Seed the 8 first-round series from the hardcoded list.
    Safe to call multiple times (upsert). ESPN sync will overwrite tipoffs if it has fresher data.
    """
    for s in FIRST_ROUND_2026:
        db.upsert_series(**s)
    log.info("Seeded %d first-round series", len(FIRST_ROUND_2026))


def sync_with_espn():
    """Fetch latest playoff games from ESPN over the next 14 days and upsert games + results.

    We iterate day-by-day because ESPN's scoreboard is per-day. For each game we identify which
    of our known series it belongs to by matching the two team abbreviations.
    """
    # Build lookup of series by team abbrs (frozenset -> series_id)
    series_rows = db.get_all_series()
    abbr_to_series = {}
    for s in series_rows:
        key = frozenset([s["team_a_abbr"], s["team_b_abbr"]])
        abbr_to_series[key] = s["series_id"]

    if not abbr_to_series:
        log.warning("No series in DB — seed bracket first.")
        return

    today = datetime.now(timezone.utc).date()
    for delta in range(-1, 15):  # yesterday + next 14 days
        day = today + timedelta(days=delta)
        date_str = day.strftime("%Y%m%d")
        try:
            resp = requests.get(ESPN_SCOREBOARD, params={"dates": date_str}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("ESPN fetch failed for %s: %s", date_str, e)
            continue

        for event in data.get("events", []):
            try:
                _process_event(event, abbr_to_series)
            except Exception as e:
                log.exception("Failed to process event %s: %s", event.get("id"), e)


def _process_event(event: dict, abbr_to_series: dict):
    """Parse a single ESPN event and upsert game + maybe result + maybe series result."""
    competitions = event.get("competitions", [])
    if not competitions:
        return
    comp = competitions[0]
    competitors = comp.get("competitors", [])
    if len(competitors) != 2:
        return

    # Find home / away
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    home_abbr = home.get("team", {}).get("abbreviation")
    away_abbr = away.get("team", {}).get("abbreviation")
    if not home_abbr or not away_abbr:
        return

    key = frozenset([home_abbr, away_abbr])
    series_id = abbr_to_series.get(key)
    if not series_id:
        # Not one of our tracked series (likely a different round or not yet bracketed)
        return

    game_id = f"espn-{event.get('id')}"
    tipoff = event.get("date")  # ISO 8601 UTC from ESPN
    if not tipoff:
        return

    # Figure out game number within series
    game_number = _extract_game_number(comp)

    status_type = comp.get("status", {}).get("type", {}).get("state", "pre")
    # ESPN states: pre, in, post
    our_status = {"pre": "scheduled", "in": "live", "post": "finished"}.get(status_type, "scheduled")

    db.upsert_game(
        game_id=game_id,
        series_id=series_id,
        game_number=game_number,
        tipoff_utc=tipoff,
        home_abbr=home_abbr,
        away_abbr=away_abbr,
        status=our_status,
    )

    # If game is finished and we don't yet have a winner, record it
    if our_status == "finished":
        existing = db.get_game(game_id)
        if existing and existing["winner_abbr"] is None:
            try:
                home_score = int(home.get("score", 0))
                away_score = int(away.get("score", 0))
                winner = home_abbr if home_score > away_score else away_abbr
                db.set_game_result(game_id, winner, home_score, away_score)
                log.info("Recorded result %s: %s %d - %d %s (winner %s)",
                         game_id, home_abbr, home_score, away_score, away_abbr, winner)
            except Exception as e:
                log.warning("Could not parse scores for %s: %s", game_id, e)

        # Update series-level record if series is now decided
        _maybe_finalize_series(series_id, comp)


def _extract_game_number(comp: dict) -> int:
    """Pull game number from series note like 'Game 2 - Series tied 1-1'."""
    # ESPN provides `series` object on playoff competitions.
    series_obj = comp.get("series") or {}
    game_num = series_obj.get("gameNumber")
    if isinstance(game_num, int) and 1 <= game_num <= 7:
        return game_num

    # Fallback: parse from notes
    notes = comp.get("notes", [])
    for note in notes:
        headline = note.get("headline") or note.get("text") or ""
        if "Game 1" in headline: return 1
        if "Game 2" in headline: return 2
        if "Game 3" in headline: return 3
        if "Game 4" in headline: return 4
        if "Game 5" in headline: return 5
        if "Game 6" in headline: return 6
        if "Game 7" in headline: return 7
    return 1  # safest default


def _maybe_finalize_series(series_id: str, comp: dict):
    """If series is over (one team reached 4 wins), set series result."""
    games = db.get_games_for_series(series_id)
    wins_by_team = {}
    for g in games:
        if g["winner_abbr"]:
            wins_by_team[g["winner_abbr"]] = wins_by_team.get(g["winner_abbr"], 0) + 1

    if not wins_by_team:
        return

    series = db.get_series(series_id)
    if not series or series["status"] == "finished":
        return

    for team, wins in wins_by_team.items():
        if wins >= 4:
            # Figure out loser's wins
            other_team = series["team_a_abbr"] if team != series["team_a_abbr"] else series["team_b_abbr"]
            loser_wins = wins_by_team.get(other_team, 0)
            # Normalize to final_score_a, final_score_b
            if team == series["team_a_abbr"]:
                db.set_series_result(series_id, team, wins, loser_wins)
            else:
                db.set_series_result(series_id, team, loser_wins, wins)
            log.info("Series %s finished: %s wins %d-%d", series_id, team, wins, loser_wins)
            return


def fetch_team_logo_url(abbr: str) -> Optional[str]:
    """Return ESPN's CDN URL for a team logo (best-effort, not critical)."""
    abbr_lower = abbr.lower()
    return f"https://a.espncdn.com/i/teamlogos/nba/500/{abbr_lower}.png"
