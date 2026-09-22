"""Compare the model's prediction against real sportsbook odds for every game
on the current (or a given) week's slate in one pass.

Run: venv\\Scripts\\python.exe weekly_report.py [--season 2026 --week 3]
"""

import argparse
import datetime as dt

import live
import odds as odds_mod
import tracking
from data import load_injuries, load_schedules, load_weekly_player_stats
from predict import MatchupPrediction, elo_state_as_of, predict_matchup, prefetch_weather_for_matchups, weekly_hist_as_of

SEASONS = list(range(2010, dt.date.today().year + 1))


def favorite(home_team: str, away_team: str, home_win_prob: float, home_margin: float | None = None):
    """Whichever team a home-team-relative probability/margin favors, named explicitly."""
    if home_win_prob >= 0.5:
        team, pct = home_team, home_win_prob * 100
    else:
        team, pct = away_team, (1 - home_win_prob) * 100
    margin = abs(home_margin) if home_margin is not None else None
    return team, pct, margin


def confidence_label(pct: float) -> str:
    """Plain-English read on how sure the model is, no percentage required."""
    if pct >= 75:
        return "Strong pick"
    if pct >= 65:
        return "Solid pick"
    if pct >= 55:
        return "Lean"
    return "Toss-up"


def attack_note(qb: dict | None, skill_players: list[dict | None]) -> str:
    """One-line read on how a team is likely to move the ball, from their own recent form."""
    bits = []
    if qb and qb.get("player_name"):
        bits.append(f"{qb['player_name']} passing ({qb['pass_yards_per_game']} yds/gm)")
    candidates = [p for p in skill_players if p]
    if candidates:
        best = max(candidates, key=lambda p: p["yards_per_game"])
        bits.append(f"{best['player_name']} carrying the load ({best['yards_per_game']} yds/gm)")
    return " + ".join(bits) if bits else "no recent data on file"


def market_check(m_team: str, m_pct: float, match: dict | None) -> str:
    """Plain-English read on whether the market agrees, no numbers required to parse.

    Plain ASCII only (no emoji/checkmarks) - this is printed to the Windows terminal by
    the CLI, whose default codepage can't encode most Unicode symbols.
    """
    if match is None:
        return "No market odds yet"
    k_team, k_pct, _ = favorite(match["home_team"], match["away_team"], match["home_win_prob"], match["home_spread"])
    if m_team != k_team:
        return f"Market disagrees - prefers {k_team}"
    if abs(m_pct - k_pct) >= 8:
        return "Market agrees, but less confident"
    return "Market agrees"


def context_summary(pred: MatchupPrediction) -> str:
    """Everything nudging this prediction beyond raw Elo + QB form: injury swaps,
    rest, division, weather - or a plain dash if nothing applied."""
    bits = [n for n in (pred.home_qb_note, pred.away_qb_note) if n]
    bits.extend(pred.context_notes)
    return " | ".join(bits) if bits else "-"


def build_report_row(pred: MatchupPrediction, home: str, away: str, match: dict | None) -> dict:
    m_team, m_pct, m_margin = favorite(home, away, pred.home_win_prob, pred.projected_margin)
    winner_line = f"{m_team} by {round(m_margin)}" if m_margin is not None else m_team

    return {
        "Matchup": f"{away} @ {home}",
        "Predicted winner": winner_line,
        "Confidence": confidence_label(m_pct),
        "vs. Market": market_check(m_team, m_pct, match),
        "Context": context_summary(pred),
        "Home attack": f"{home}: " + attack_note(pred.home_qb, [pred.home_rb, pred.home_wr, pred.home_te]),
        "Away attack": f"{away}: " + attack_note(pred.away_qb, [pred.away_rb, pred.away_wr, pred.away_te]),
    }


def build_recap_row(pred: MatchupPrediction, home: str, away: str, week: int, game: dict) -> dict:
    """A played-or-not game: what the model called before kickoff vs. what actually
    happened, for a season-so-far recap rather than a forward-looking prediction."""
    m_team, m_pct, _ = favorite(home, away, pred.home_win_prob, pred.projected_margin)

    if game["status"] == "Final" and game["home_score"] is not None:
        home_score, away_score = int(game["home_score"]), int(game["away_score"])
        final_score = f"{away} {away_score} - {home} {home_score}"
        if home_score == away_score:
            outcome = "Tie"
        else:
            actual_winner = home if home_score > away_score else away
            outcome = "Correct" if actual_winner == m_team else "Missed"
    else:
        final_score, outcome = "Not played yet", "-"

    return {
        "Week": week,
        "Matchup": f"{away} @ {home}",
        "Model called": f"{m_team} ({confidence_label(m_pct)})",
        "Final score": final_score,
        "Model vs. actual": outcome,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    args = parser.parse_args()

    scoreboard = live.get_scoreboard(week=args.week, season=args.season)
    season = args.season or scoreboard["season"]
    week = args.week or scoreboard["week"]
    print(f"Season {season}, Week {week} - {len(scoreboard['games'])} games\n")

    print("Loading model data...")
    schedules = load_schedules(SEASONS)
    weekly = load_weekly_player_stats(SEASONS)
    injuries = load_injuries([season - 1, season])
    elo_state = elo_state_as_of(schedules, season, week)
    weekly_hist = weekly_hist_as_of(weekly, season, week)

    matchups = [(g["home_team"], g["away_team"]) for g in scoreboard["games"]]
    print("Checking weather for outdoor games...")
    prefetch_weather_for_matchups(schedules, matchups, season, week)

    try:
        market_games = odds_mod.fetch_odds()
    except odds_mod.OddsApiError as e:
        print(f"No odds available: {e}")
        market_games = []

    for g in scoreboard["games"]:
        home, away = g["home_team"], g["away_team"]
        pred = predict_matchup(
            schedules, weekly, home, away, season, week,
            injuries=injuries, elo_state=elo_state, weekly_hist=weekly_hist,
        )
        match = odds_mod.find_matchup(market_games, home, away)
        row = build_report_row(pred, home, away, match)
        tracking.log_prediction(pred, season, week, market_home_win_prob=match["home_win_prob"] if match else None)

        print(row["Matchup"])
        print(f"  Predicted winner: {row['Predicted winner']}  ({row['Confidence']})")
        print(f"  {row['vs. Market']}")
        if row["Context"] != "-":
            print(f"  Context: {row['Context']}")
        print(f"  {row['Home attack']}")
        print(f"  {row['Away attack']}")
        print()

    print(
        "Attack notes are each team's own recent-form leaders, not a matchup-adjusted read - "
        "context for who's trending well, not a guarantee of this game's outcome."
    )


if __name__ == "__main__":
    main()
