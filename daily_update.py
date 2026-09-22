"""Meant to run once a day, unattended (see the Windows Scheduled Task set up alongside
this file) - logs fresh predictions for the current week's real games and re-grades
anything that's finished, so the live tracking record in the app stays current without
anyone having to remember to open it.

Logging every day, not just once a week, is deliberate: re-running the same game
mid-week captures how the prediction moved as injury news firmed up (each entry is
timestamped and appended, never overwritten - see tracking.log_prediction), which is
useful context tracking.py doesn't otherwise have.

Everything is appended to predictions/daily_run.log instead of printed, since a
scheduled task has no visible console to print to.
"""

import datetime as dt
import json
import subprocess
import traceback
from pathlib import Path

import injuries as injuries_mod
import live
import odds as odds_mod
import tracking
from data import load_injuries, load_schedules, load_weekly_player_stats
from predict import elo_state_as_of, prefetch_weather_for_matchups, predict_matchup, weekly_hist_as_of

LOG_FILE = Path(__file__).parent / "predictions" / "daily_run.log"
NOTIFIED_WEEKS_PATH = Path(__file__).parent / "predictions" / "notified_weeks.json"
SEASONS = list(range(2010, dt.date.today().year + 1))


def _log(f, message: str) -> None:
    f.write(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {message}\n")


def _load_notified_weeks() -> set[tuple]:
    if not NOTIFIED_WEEKS_PATH.exists():
        return set()
    with NOTIFIED_WEEKS_PATH.open(encoding="utf-8") as f:
        return {tuple(k) for k in json.load(f)}


def _save_notified_weeks(weeks: set[tuple]) -> None:
    with NOTIFIED_WEEKS_PATH.open("w", encoding="utf-8") as f:
        json.dump([list(k) for k in sorted(weeks)], f)


PWSH_EXE = r"C:\Program Files\PowerShell\7\pwsh.exe"  # BurntToast is installed here (CurrentUser scope), not
# under legacy Windows PowerShell 5.1's separate module path - "powershell" would silently fail to find it.


def send_toast(title: str, message: str) -> None:
    """A Windows desktop notification via the BurntToast PowerShell module - fully
    local, no external service or credentials needed (unlike email). Escapes single
    quotes since the message is embedded in a single-quoted PowerShell string."""
    safe_title = title.replace("'", "''")
    safe_message = message.replace("'", "''")
    script = f"Import-Module BurntToast; New-BurntToastNotification -Text '{safe_title}', '{safe_message}'"
    subprocess.run([PWSH_EXE, "-NoProfile", "-Command", script], check=True, timeout=30, capture_output=True)


def _build_live_injury_lookup(game: dict):
    """Same idea as app.py's build_live_injury_lookup, minus the Streamlit caching (a
    plain script, no @st.cache_data available) - one real fetch per game per daily run
    is cheap enough it doesn't need its own cache.

    Skips a game that's already Final - see app.py's build_live_injury_lookup for why
    (a live feed reflects a team's CURRENT status, not their status before a game
    that's already been decided; applying it retroactively leaked future information
    into an already-final week's tracked prediction, caught by hand when the live
    tracking record's Brier score for week 2 changed between two same-day runs).
    """
    game_id = game.get("game_id")
    if game_id is None or game.get("status") == "Final":
        return None
    injuries_by_team = live.get_injuries(game_id)
    if not injuries_by_team:
        return None

    def lookup(team, qb_name):
        report = injuries_by_team.get(team)
        return injuries_mod.starting_qb_status(report, qb_name) if report is not None else None

    return lookup


def run(f) -> None:
    scoreboard = live.get_scoreboard(week=None, season=None)
    season, week = scoreboard.get("season"), scoreboard.get("week")
    if not season or not week:
        _log(f, "Couldn't determine the current season/week from ESPN's scoreboard - skipping today's logging.")
        return

    games = scoreboard["games"]
    _log(f, f"Season {season}, Week {week}: {len(games)} games found.")
    if not games:
        return

    schedules = load_schedules(SEASONS)
    weekly = load_weekly_player_stats(SEASONS)
    injuries = load_injuries([season - 1, season])
    elo_state = elo_state_as_of(schedules, season, week)
    weekly_hist = weekly_hist_as_of(weekly, season, week)

    matchups = [(g["home_team"], g["away_team"]) for g in games]
    prefetch_weather_for_matchups(schedules, matchups, season, week)

    try:
        market_games = odds_mod.fetch_odds()
    except odds_mod.OddsApiError as e:
        _log(f, f"No odds available ({e}) - logging model-only predictions.")
        market_games = []

    logged = 0
    for g in games:
        home, away = g["home_team"], g["away_team"]
        try:
            pred = predict_matchup(
                schedules, weekly, home, away, season, week,
                injuries=injuries, elo_state=elo_state, weekly_hist=weekly_hist,
                live_injury_lookup=_build_live_injury_lookup(g),
            )
            match = odds_mod.find_matchup(market_games, home, away)
            tracking.log_prediction(pred, season, week, market_home_win_prob=match["home_win_prob"] if match else None)
            logged += 1
        except Exception as e:
            _log(f, f"  Failed to predict/log {away} @ {home}: {e.__class__.__name__}: {e}")
    _log(f, f"Logged {logged}/{len(games)} predictions for week {week}.")

    graded = tracking.grade_log(schedules, weekly)
    summary = tracking.summarize(graded)
    if summary:
        _log(
            f,
            f"Running tally: {summary['games']} graded games, "
            f"winner accuracy {summary['accuracy']:.1%}, Brier {summary['brier']:.4f}"
            + (
                f", personnel-assumption accuracy {summary['personnel_assumption_accuracy']:.1%}"
                if summary["personnel_assumption_accuracy"] is not None else ""
            ),
        )

    # One notification per week, sent the first time every game in it has a real
    # graded result - not one per game, since games finish on different days and a
    # ping after just Thursday's game would be noise ahead of the real weekly picture.
    week_graded = [g for g in graded if g["season"] == season and g["week"] == week]
    if week_graded and len(week_graded) == len(games):
        week_key = (season, week)
        notified = _load_notified_weeks()
        if week_key not in notified:
            week_summary = tracking.summarize(week_graded)
            message = f"{week_summary['games']}/{len(games)} games graded, {week_summary['accuracy']:.0%} winner accuracy"
            if week_summary["personnel_assumption_accuracy"] is not None:
                message += f", {week_summary['personnel_assumption_accuracy']:.0%} personnel accuracy"
            try:
                send_toast(f"NFL Predictor - Week {week} graded", message)
                _log(f, f"Sent notification: {message}")
            except Exception as e:
                _log(f, f"Notification failed ({e.__class__.__name__}: {e}) - it'll retry next run.")
            else:
                notified.add(week_key)
                _save_notified_weeks(notified)


def main():
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        try:
            run(f)
        except Exception:
            _log(f, "Daily update crashed:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
