"""A persistent record of real, forward-looking predictions, and automatic grading of
that record once real results come in.

Backtest.py answers "how accurate is the model on history" - this answers "how did the
model actually do, live, this season" - including the personnel-assumption failures a
pure win/loss accuracy number can't see (see the README: a real week-2 2026 game showed
the model can call the winner right while assuming the wrong starting QB or featured
skill player, since that's driven by depth-chart/lineup decisions no free data source
reliably exposes ahead of time). Logging every real call and grading it after the fact
turns that kind of one-off manual review into something that runs automatically.
"""

import datetime as dt
import json
from pathlib import Path

import pandas as pd

import odds as odds_mod
from data import completed_games
from predict import MatchupPrediction

LOG_PATH = Path(__file__).parent / "predictions" / "log.jsonl"

_PROP_KEYS = ("qb", "rb", "wr", "te")
_PROP_STAT_COL = {"qb": "passing_yards", "rb": "rushing_yards", "wr": "receiving_yards", "te": "receiving_yards"}
_PROP_THRESHOLD = {"qb": 150.0, "rb": 40.0, "wr": 40.0, "te": 40.0}
_LEADER_POSITION = {"qb": "QB", "rb": "RB", "wr": "WR", "te": "TE"}
_LEADER_STAT_COL = {"qb": "attempts", "rb": "rushing_yards", "wr": "receiving_yards", "te": "receiving_yards"}


def _prop_summary(prop: dict | None) -> dict | None:
    if prop is None:
        return None
    return {k: prop[k] for k in ("probability", "own_avg", "matchup_adjusted_avg", "games")}


def _player_name(player: dict | None) -> str | None:
    return player["player_name"] if player else None


def log_prediction(pred: MatchupPrediction, season: int, week: int, market_home_win_prob: float | None = None) -> None:
    """Append one real, forward-looking prediction to the log.

    Call this only for actual upcoming games (the Weekly Report tab/CLI, which predicts
    a real week's slate) - not exploratory single-game lookups or historical backtesting
    - so the log stays a genuine record of real-time calls rather than casual exploration.
    Appends rather than overwrites: re-logging the same game later in the week (as
    injury news firms up) keeps every version, graded using the latest by default.

    `market_home_win_prob`, when available (a real sportsbook line was found for this
    matchup), is stored alongside the model's own probability so the 50/50 model/market
    blend (odds.blended_probability - disclosed in the app as untested, since there's no
    historical odds archive to backtest it against) can be graded empirically against
    real results as they come in, going forward, instead of staying untested forever.
    """
    LOG_PATH.parent.mkdir(exist_ok=True)
    blended_home_win_prob = (
        odds_mod.blended_probability(pred.home_win_prob, market_home_win_prob)
        if market_home_win_prob is not None else None
    )
    record = {
        "logged_at": dt.datetime.now().isoformat(timespec="seconds"),
        "season": season,
        "week": week,
        "home_team": pred.home_team,
        "away_team": pred.away_team,
        "home_win_prob": pred.home_win_prob,
        "projected_margin": pred.projected_margin,
        "market_home_win_prob": market_home_win_prob,
        "blended_home_win_prob": blended_home_win_prob,
        "home_qb": _player_name(pred.home_qb),
        "away_qb": _player_name(pred.away_qb),
        "home_rb": _player_name(pred.home_rb),
        "away_rb": _player_name(pred.away_rb),
        "home_wr": _player_name(pred.home_wr),
        "away_wr": _player_name(pred.away_wr),
        "home_te": _player_name(pred.home_te),
        "away_te": _player_name(pred.away_te),
        "home_qb_prop": _prop_summary(pred.home_qb_prop),
        "away_qb_prop": _prop_summary(pred.away_qb_prop),
        "home_rb_prop": _prop_summary(pred.home_rb_prop),
        "away_rb_prop": _prop_summary(pred.away_rb_prop),
        "home_wr_prop": _prop_summary(pred.home_wr_prop),
        "away_wr_prop": _prop_summary(pred.away_wr_prop),
        "home_te_prop": _prop_summary(pred.home_te_prop),
        "away_te_prop": _prop_summary(pred.away_te_prop),
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_log() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    with LOG_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _latest_per_game(records: list[dict]) -> dict[tuple, dict]:
    latest: dict[tuple, dict] = {}
    for r in records:
        key = (r["season"], r["week"], r["home_team"], r["away_team"])
        if key not in latest or r["logged_at"] > latest[key]["logged_at"]:
            latest[key] = r
    return latest


def _actual_leader(team_week_hist: pd.DataFrame, team: str, position: str, stat_col: str) -> str | None:
    rows = team_week_hist[(team_week_hist["recent_team"] == team) & (team_week_hist["position"] == position)]
    if rows.empty:
        return None
    return rows.loc[rows[stat_col].idxmax(), "player_name"]


def _actual_value(team_week_hist: pd.DataFrame, player: str | None, stat_col: str) -> float | None:
    if player is None:
        return None
    rows = team_week_hist[team_week_hist["player_name"] == player]
    if rows.empty or pd.isna(rows[stat_col].iloc[0]):
        return None
    return float(rows[stat_col].iloc[0])


def grade_log(schedules: pd.DataFrame, weekly: pd.DataFrame) -> list[dict]:
    """Grade every logged prediction whose real game has finished: winner/margin
    accuracy (always gradable), plus, per position, whether the assumed player was
    actually that team's leader in that stat this game (personnel assumption) and -
    only when that assumption held - whether their real prop-threshold call was right.
    A prop is marked "N/A (personnel mismatch)" rather than silently graded wrong when
    the assumed player wasn't actually the one who played that role.
    """
    games = completed_games(schedules)
    graded = []

    for (season, week, home, away), r in _latest_per_game(load_log()).items():
        game_row = games[
            (games["season"] == season) & (games["week"] == week)
            & (games["home_team"] == home) & (games["away_team"] == away)
        ]
        if game_row.empty:
            continue  # not played yet (or not a real scheduled game)
        row = game_row.iloc[0]
        if pd.isna(row["home_score"]) or pd.isna(row["away_score"]):
            continue
        home_score, away_score = row["home_score"], row["away_score"]
        if home_score == away_score:
            continue  # ties aren't scored for winner correctness, same as backtest.py

        actual_winner = home if home_score > away_score else away
        predicted_winner = home if r["home_win_prob"] >= 0.5 else away
        actual_margin = home_score - away_score

        team_week_hist = weekly[(weekly["season"] == season) & (weekly["week"] == week)]

        personnel_checks = {}
        prop_grades = {}
        for side, team in (("home", home), ("away", away)):
            for pos_key in _PROP_KEYS:
                assumed_player = r.get(f"{side}_{pos_key}")
                actual_leader = _actual_leader(team_week_hist, team, _LEADER_POSITION[pos_key], _LEADER_STAT_COL[pos_key])
                assumption_correct = assumed_player is not None and assumed_player == actual_leader
                personnel_checks[f"{side}_{pos_key}"] = assumption_correct

                prop = r.get(f"{side}_{pos_key}_prop")
                label = f"{side}_{pos_key}"
                if prop is None:
                    continue
                if not assumption_correct:
                    prop_grades[label] = "N/A (personnel mismatch)"
                    continue
                actual_value = _actual_value(team_week_hist, assumed_player, _PROP_STAT_COL[pos_key])
                if actual_value is None:
                    prop_grades[label] = "N/A (no data)"
                    continue
                hit = actual_value >= _PROP_THRESHOLD[pos_key]
                predicted_hit = prop["probability"] >= 0.5
                prop_grades[label] = "Correct" if predicted_hit == hit else "Missed"

        graded.append(
            {
                "season": season, "week": week, "home_team": home, "away_team": away,
                "predicted_winner": predicted_winner, "actual_winner": actual_winner,
                "winner_correct": predicted_winner == actual_winner,
                "home_win_prob": r["home_win_prob"],
                "market_home_win_prob": r.get("market_home_win_prob"),
                "blended_home_win_prob": r.get("blended_home_win_prob"),
                "projected_margin": r["projected_margin"], "actual_margin": float(actual_margin),
                "margin_error": abs(r["projected_margin"] - actual_margin),
                "personnel_checks": personnel_checks,
                "prop_grades": prop_grades,
            }
        )
    return graded


def _win_accuracy_and_brier(rows: list[dict], prob_key: str) -> tuple[float, float]:
    n = len(rows)
    correct = sum((g[prob_key] >= 0.5) == (g["actual_winner"] == g["home_team"]) for g in rows)
    brier = sum((g[prob_key] - (1.0 if g["actual_winner"] == g["home_team"] else 0.0)) ** 2 for g in rows) / n
    return correct / n, brier


def summarize(graded: list[dict]) -> dict:
    """Aggregate stats across a graded list - the live, real-world counterpart to
    backtest.py's historical accuracy/Brier numbers.

    Also reports the market's own accuracy and the 50/50 blend's, over whichever subset
    of games actually had a real sportsbook line at logging time - this is how the
    blend (which the app discloses as untested, since there's no historical odds
    archive to backtest it against) gets validated: not in one shot, but by accumulating
    real graded weeks over time. Early on this subset will be small; treat it
    accordingly until enough weeks have logged with odds attached.
    """
    if not graded:
        return {}
    n = len(graded)
    accuracy, brier = _win_accuracy_and_brier(graded, "home_win_prob")
    mean_margin_error = sum(g["margin_error"] for g in graded) / n

    personnel_flags = [v for g in graded for v in g["personnel_checks"].values()]
    personnel_accuracy = sum(personnel_flags) / len(personnel_flags) if personnel_flags else None

    gradable_props = [v for g in graded for v in g["prop_grades"].values() if v in ("Correct", "Missed")]
    prop_hit_rate = gradable_props.count("Correct") / len(gradable_props) if gradable_props else None

    with_market = [g for g in graded if g.get("market_home_win_prob") is not None]
    if with_market:
        # the model's own accuracy restricted to this same subset, so all three numbers
        # are a fair apples-to-apples comparison over identical games - the model's
        # overall accuracy above (over ALL graded games) isn't directly comparable to
        # the market/blend numbers if the market-subset games happen to differ in
        # difficulty from the full set
        model_subset_accuracy, model_subset_brier = _win_accuracy_and_brier(with_market, "home_win_prob")
        market_accuracy, market_brier = _win_accuracy_and_brier(with_market, "market_home_win_prob")
        blended_accuracy, blended_brier = _win_accuracy_and_brier(with_market, "blended_home_win_prob")
    else:
        model_subset_accuracy = model_subset_brier = None
        market_accuracy = market_brier = blended_accuracy = blended_brier = None

    return {
        "games": n,
        "accuracy": accuracy,
        "brier": brier,
        "mean_margin_error": mean_margin_error,
        "personnel_assumption_accuracy": personnel_accuracy,
        "personnel_checks_total": len(personnel_flags),
        "prop_hit_rate": prop_hit_rate,
        "props_graded": len(gradable_props),
        "market_games": len(with_market),
        "model_subset_accuracy": model_subset_accuracy,
        "model_subset_brier": model_subset_brier,
        "market_accuracy": market_accuracy,
        "market_brier": market_brier,
        "blended_accuracy": blended_accuracy,
        "blended_brier": blended_brier,
    }


def main():
    from data import load_schedules, load_weekly_player_stats

    seasons = list(range(2010, dt.date.today().year + 1))
    schedules = load_schedules(seasons)
    weekly = load_weekly_player_stats(seasons)

    graded = grade_log(schedules, weekly)
    if not graded:
        print("No logged predictions have a completed real game to grade yet.")
        return

    for g in sorted(graded, key=lambda g: (g["season"], g["week"])):
        mark = "correct" if g["winner_correct"] else "MISSED"
        print(
            f"S{g['season']} W{g['week']} {g['away_team']} @ {g['home_team']}: "
            f"called {g['predicted_winner']} ({g['home_win_prob']:.0%} home) - {mark}, "
            f"actual margin {g['actual_margin']:+.0f} vs projected {g['projected_margin']:+.1f} "
            f"(error {g['margin_error']:.1f})"
        )
        mismatches = [k for k, ok in g["personnel_checks"].items() if not ok]
        if mismatches:
            print(f"    personnel mismatches: {', '.join(mismatches)}")

    summary = summarize(graded)
    print(f"\n=== Live tracking summary ({summary['games']} graded games) ===")
    print(f"Winner accuracy: {summary['accuracy']:.1%}   Brier: {summary['brier']:.4f}   Mean margin error: {summary['mean_margin_error']:.1f} pts")
    if summary["personnel_assumption_accuracy"] is not None:
        print(
            f"Personnel-assumption accuracy: {summary['personnel_assumption_accuracy']:.1%} "
            f"({summary['personnel_checks_total']} player-role checks) - how often the assumed "
            f"starter/leader actually was one, per real box scores"
        )
    if summary["prop_hit_rate"] is not None:
        print(f"Prop hit rate: {summary['prop_hit_rate']:.1%} (of {summary['props_graded']} gradable props - personnel mismatches excluded)")
    if summary["market_games"]:
        print(
            f"\nModel vs. market vs. blend, over the same {summary['market_games']} games that had a "
            f"real sportsbook line at logging time (small sample early on, treat accordingly):"
        )
        print(f"  Model:   accuracy {summary['model_subset_accuracy']:.1%}   brier {summary['model_subset_brier']:.4f}")
        print(f"  Market:  accuracy {summary['market_accuracy']:.1%}   brier {summary['market_brier']:.4f}")
        print(f"  Blended: accuracy {summary['blended_accuracy']:.1%}   brier {summary['blended_brier']:.4f}")


if __name__ == "__main__":
    main()
