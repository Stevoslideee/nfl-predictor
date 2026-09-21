"""Backtest the model against real historical outcomes so accuracy claims are honest,
not assumed. Compares plain Elo, Elo + QB form, and Elo + QB form + context (injury
backup swaps, rest days, divisional games, weather) - each layer separately, so you can
see whether the newer context adjustments actually help or are just noise.

Run: venv\\Scripts\\python.exe backtest.py --start 2018 --end 2024
"""

import argparse
import time

import numpy as np
import pandas as pd

import player_stats
from data import completed_games, load_injuries, load_schedules, load_weekly_player_stats
from elo import HOME_FIELD_ADV, expected_win_prob, run_elo
from injuries import starting_qb_status, team_injury_report
from predict import (
    divisional_dampening_factor,
    qb_elo_adjustment,
    rest_elo_adjustment,
    weather_dampening_factor,
)


def _qb_form(weekly, team, season, week, cache):
    key = (team, season, week)
    if key not in cache:
        cache[key] = player_stats.qb_trailing_form(weekly, team, season, week)
    return cache[key]


def _effective_qb_form(weekly_before, team, qb_form, qb_status, season, week, cache):
    """Same swap-to-backup logic as predict.py's _effective_qb, but standalone here
    since backtest.py scores from a pre-built Elo history rather than calling
    predict_matchup per game."""
    if qb_status not in ("Out", "Doubtful"):
        return qb_form
    key = (team, qb_form.get("player_name"), season, week)
    if key in cache:
        return cache[key]
    backup = player_stats.backup_qb_form(weekly_before, team, qb_form.get("player_name"))
    result = backup if backup is not None else {"player_name": None, "passer_rating": None}
    cache[key] = result
    return result


def brier_score(probs: np.ndarray, outcomes: np.ndarray) -> float:
    return float(np.mean((probs - outcomes) ** 2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2015)
    parser.add_argument("--end", type=int, default=2024)
    parser.add_argument("--burn-in-seasons", type=int, default=1, help="seasons to warm up ratings before scoring")
    parser.add_argument("--skip-context", action="store_true", help="skip the slower context-adjusted variant")
    args = parser.parse_args()

    seasons = list(range(args.start, args.end + 1))
    print(f"Loading schedules, player stats, and injuries for {seasons[0]}-{seasons[-1]}...")
    schedules = load_schedules(seasons)
    weekly = load_weekly_player_stats(seasons)
    injuries = load_injuries(seasons) if not args.skip_context else pd.DataFrame()

    games = completed_games(schedules)
    games_by_id = games.set_index("game_id")
    state = run_elo(games)

    burn_in_end_season = seasons[0] + args.burn_in_seasons
    scored = [h for h in state.history if h["season"] >= burn_in_end_season and h["actual_winner"] != "TIE"]
    print(f"Scoring {len(scored)} games (excluding first {args.burn_in_seasons} season(s) as ratings warm-up)...\n")

    elo_correct = combo_correct = full_correct = 0
    elo_probs, combo_probs, full_probs, outcomes = [], [], [], []

    qb_cache: dict = {}
    swap_cache: dict = {}
    weekly_before_cache: dict = {}
    t0 = time.time()

    for i, h in enumerate(scored):
        home, away, season, week = h["home_team"], h["away_team"], h["season"], h["week"]

        elo_correct += h["predicted_winner"] == h["actual_winner"]
        elo_probs.append(h["home_win_prob"])

        home_qb = _qb_form(weekly, home, season, week, qb_cache)
        away_qb = _qb_form(weekly, away, season, week, qb_cache)
        qb_adj = qb_elo_adjustment(home_qb, away_qb)

        combo_prob = expected_win_prob(h["pre_home_elo"] + HOME_FIELD_ADV + qb_adj, h["pre_away_elo"])
        combo_pred = home if combo_prob >= 0.5 else away
        combo_correct += combo_pred == h["actual_winner"]
        combo_probs.append(combo_prob)

        if not args.skip_context:
            row = games_by_id.loc[h["game_id"]]
            div_game = bool(row.get("div_game")) if pd.notna(row.get("div_game")) else False
            home_rest = float(row["home_rest"]) if pd.notna(row.get("home_rest")) else None
            away_rest = float(row["away_rest"]) if pd.notna(row.get("away_rest")) else None
            temp = float(row["temp"]) if pd.notna(row.get("temp")) else None
            wind = float(row["wind"]) if pd.notna(row.get("wind")) else None

            eff_home_qb, eff_away_qb = home_qb, away_qb
            if not injuries.empty:
                home_report = team_injury_report(injuries, home, season, week)
                away_report = team_injury_report(injuries, away, season, week)
                home_status = starting_qb_status(home_report, home_qb.get("player_name"))
                away_status = starting_qb_status(away_report, away_qb.get("player_name"))
                if home_status in ("Out", "Doubtful") or away_status in ("Out", "Doubtful"):
                    wb_key = (season, week)
                    if wb_key not in weekly_before_cache:
                        weekly_before_cache[wb_key] = player_stats.before_cutoff(weekly, season, week)
                    weekly_before = weekly_before_cache[wb_key]
                    eff_home_qb = _effective_qb_form(weekly_before, home, home_qb, home_status, season, week, swap_cache)
                    eff_away_qb = _effective_qb_form(weekly_before, away, away_qb, away_status, season, week, swap_cache)

            full_qb_adj = qb_elo_adjustment(eff_home_qb, eff_away_qb)
            rest_adj = rest_elo_adjustment(home_rest, away_rest)
            raw_diff = (h["pre_home_elo"] + HOME_FIELD_ADV + full_qb_adj + rest_adj) - h["pre_away_elo"]
            raw_diff *= divisional_dampening_factor(div_game) * weather_dampening_factor(temp, wind)

            full_prob = expected_win_prob(raw_diff, 0.0)
            full_pred = home if full_prob >= 0.5 else away
            full_correct += full_pred == h["actual_winner"]
            full_probs.append(full_prob)

        outcomes.append(1.0 if h["actual_winner"] == home else 0.0)

        if (i + 1) % 500 == 0:
            print(f"  ...{i + 1}/{len(scored)} games scored ({time.time() - t0:.0f}s elapsed)")

    n = len(scored)
    print("\n=== Results ===")
    print(f"Games scored:                    {n}")
    print(f"Plain Elo accuracy:              {elo_correct / n:.1%}  (Brier {brier_score(np.array(elo_probs), np.array(outcomes)):.4f})")
    print(f"Elo + QB form accuracy:          {combo_correct / n:.1%}  (Brier {brier_score(np.array(combo_probs), np.array(outcomes)):.4f})")
    if not args.skip_context:
        print(f"Elo + QB + context accuracy:     {full_correct / n:.1%}  (Brier {brier_score(np.array(full_probs), np.array(outcomes)):.4f})")
    print(
        "\nFor reference: always picking the home team gets ~57-58% straight-up historically; "
        "professional closing lines hit roughly 65-67%. Anything meaningfully above chance "
        "with reasonable calibration (Brier < 0.25) means the model is doing real work."
    )


if __name__ == "__main__":
    main()
