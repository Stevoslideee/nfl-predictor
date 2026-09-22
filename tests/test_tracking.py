import pandas as pd
import pytest

import tracking
from predict import MatchupPrediction


def _pred(home_win_prob=0.7, projected_margin=6.0, home_qb="M.Stafford", away_qb="J.Dart",
          home_rb="K.Williams", away_rb="T.Tracy", home_wr="P.Nacua", away_wr="M.Nabers",
          home_te="C.Parkinson", away_te="I.Likely"):
    def p(name):
        return {"player_name": name} if name else None

    def prop(prob, avg):
        return {"probability": prob, "own_avg": avg, "matchup_adjusted_avg": avg, "games": 5}

    return MatchupPrediction(
        home_team="LA", away_team="NYG", home_elo=1560.0, away_elo=1450.0,
        home_win_prob=home_win_prob, projected_margin=projected_margin,
        home_qb=p(home_qb), away_qb=p(away_qb),
        home_skill=[], away_skill=[],
        home_rb=p(home_rb), away_rb=p(away_rb),
        home_wr=p(home_wr), away_wr=p(away_wr),
        home_te=p(home_te), away_te=p(away_te),
        head_to_head=pd.DataFrame(), home_injuries=pd.DataFrame(), away_injuries=pd.DataFrame(),
        home_qb_status=None, away_qb_status=None,
        home_qb_prop=prop(0.76, 270.0), away_qb_prop=prop(0.71, 189.2),
        home_rb_prop=prop(0.71, 56.8), away_rb_prop=prop(0.76, 64.0),
        home_wr_prop=prop(0.83, 96.4), away_wr_prop=prop(0.71, 68.0),
        home_te_prop=prop(0.23, 38.8), away_te_prop=prop(0.94, 78.0),
    )


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    monkeypatch.setattr(tracking, "LOG_PATH", tmp_path / "predictions" / "log.jsonl")
    yield


def test_log_and_load_round_trip():
    tracking.log_prediction(_pred(), season=2026, week=2)
    records = tracking.load_log()
    assert len(records) == 1
    assert records[0]["home_team"] == "LA"
    assert records[0]["home_qb"] == "M.Stafford"
    assert records[0]["home_qb_prop"]["own_avg"] == 270.0


def test_latest_per_game_keeps_most_recent():
    records = [
        {"season": 2026, "week": 2, "home_team": "LA", "away_team": "NYG", "logged_at": "2026-09-18T10:00:00", "home_qb": "OldGuess"},
        {"season": 2026, "week": 2, "home_team": "LA", "away_team": "NYG", "logged_at": "2026-09-21T09:00:00", "home_qb": "NewGuess"},
    ]
    latest = tracking._latest_per_game(records)
    assert latest[(2026, 2, "LA", "NYG")]["home_qb"] == "NewGuess"


def _schedule_row():
    return pd.DataFrame([{
        "game_id": "g1", "season": 2026, "week": 2, "home_team": "LA", "away_team": "NYG",
        "home_score": 28, "away_score": 6, "gameday": "2026-09-21",
    }])


def _weekly_row(player, position, team, **stats):
    base = dict(
        player_name=player, position=position, recent_team=team, season=2026, week=2,
        completions=0, attempts=0, passing_yards=0, passing_tds=0, interceptions=0,
        carries=0, rushing_yards=0, rushing_tds=0, receptions=0, targets=0,
        receiving_yards=0, receiving_tds=0,
    )
    base.update(stats)
    return base


def test_grade_log_correct_winner_and_matching_personnel():
    tracking.log_prediction(_pred(home_win_prob=0.72), season=2026, week=2)
    weekly = pd.DataFrame([
        _weekly_row("M.Stafford", "QB", "LA", attempts=31, passing_yards=327),
        _weekly_row("K.Williams", "RB", "LA", rushing_yards=85),
        _weekly_row("P.Nacua", "WR", "LA", receiving_yards=100),  # matches assumption this time
        _weekly_row("C.Parkinson", "TE", "LA", receiving_yards=15),
        _weekly_row("J.Dart", "QB", "NYG", attempts=5, passing_yards=20),  # did NOT lead - Winston did
        _weekly_row("J.Winston", "QB", "NYG", attempts=27, passing_yards=111),
        _weekly_row("T.Tracy", "RB", "NYG", rushing_yards=0),
        _weekly_row("C.Skattebo", "RB", "NYG", rushing_yards=36),
        _weekly_row("M.Nabers", "WR", "NYG", receiving_yards=1),
        _weekly_row("I.Likely", "TE", "NYG", receiving_yards=33),
    ])
    graded = tracking.grade_log(_schedule_row(), weekly)
    assert len(graded) == 1
    g = graded[0]
    assert g["winner_correct"] is True
    assert g["actual_margin"] == 22.0
    assert g["margin_error"] == abs(6.0 - 22.0)

    # LA side: home_qb and home_rb and home_wr assumptions all matched the real leader
    assert g["personnel_checks"]["home_qb"] is True
    assert g["personnel_checks"]["home_rb"] is True
    assert g["personnel_checks"]["home_wr"] is True
    # NYG side: away_qb (Dart) and away_rb (Tracy) assumptions did NOT match reality
    assert g["personnel_checks"]["away_qb"] is False
    assert g["personnel_checks"]["away_rb"] is False

    # a mismatched personnel assumption must not be silently graded as a prop miss
    assert g["prop_grades"]["away_qb"] == "N/A (personnel mismatch)"
    assert g["prop_grades"]["away_rb"] == "N/A (personnel mismatch)"
    # a correctly-assumed player's prop CAN be graded normally
    assert g["prop_grades"]["home_qb"] in ("Correct", "Missed")


def test_grade_log_skips_unplayed_games():
    tracking.log_prediction(_pred(), season=2026, week=2)
    unplayed = pd.DataFrame([{
        "game_id": "g1", "season": 2026, "week": 2, "home_team": "LA", "away_team": "NYG",
        "home_score": None, "away_score": None, "gameday": "2026-09-21",
    }])
    weekly = pd.DataFrame(columns=["season", "week", "recent_team", "position", "player_name", "rushing_yards", "receiving_yards", "passing_yards", "attempts"])
    assert tracking.grade_log(unplayed, weekly) == []


def test_grade_log_skips_ties():
    tracking.log_prediction(_pred(), season=2026, week=2)
    tie = pd.DataFrame([{
        "game_id": "g1", "season": 2026, "week": 2, "home_team": "LA", "away_team": "NYG",
        "home_score": 20, "away_score": 20, "gameday": "2026-09-21",
    }])
    weekly = pd.DataFrame(columns=["season", "week", "recent_team", "position", "player_name", "rushing_yards", "receiving_yards", "passing_yards", "attempts"])
    assert tracking.grade_log(tie, weekly) == []


def test_summarize_empty():
    assert tracking.summarize([]) == {}


def test_summarize_aggregates():
    graded = [
        {"winner_correct": True, "home_win_prob": 0.7, "home_team": "LA", "actual_winner": "LA", "margin_error": 5.0,
         "personnel_checks": {"home_qb": True, "away_qb": False}, "prop_grades": {"home_qb": "Correct", "away_qb": "Missed"}},
        {"winner_correct": False, "home_win_prob": 0.6, "home_team": "SF", "actual_winner": "MIA", "margin_error": 10.0,
         "personnel_checks": {"home_qb": True}, "prop_grades": {"home_qb": "N/A (personnel mismatch)"}},
    ]
    summary = tracking.summarize(graded)
    assert summary["games"] == 2
    assert summary["accuracy"] == 0.5
    assert summary["mean_margin_error"] == 7.5
    assert summary["personnel_checks_total"] == 3
    assert abs(summary["personnel_assumption_accuracy"] - (2 / 3)) < 1e-9
    assert summary["props_graded"] == 2  # the N/A entry is excluded
    assert summary["prop_hit_rate"] == 0.5
    assert summary["market_games"] == 0  # neither row has market data
    assert summary["market_accuracy"] is None


def test_log_prediction_stores_market_and_blended_probability():
    tracking.log_prediction(_pred(home_win_prob=0.7), season=2026, week=2, market_home_win_prob=0.5)
    record = tracking.load_log()[0]
    assert record["market_home_win_prob"] == 0.5
    assert record["blended_home_win_prob"] == 0.6  # (0.7 + 0.5) / 2


def test_log_prediction_without_market_data_stores_none():
    tracking.log_prediction(_pred(), season=2026, week=2)
    record = tracking.load_log()[0]
    assert record["market_home_win_prob"] is None
    assert record["blended_home_win_prob"] is None


def test_grade_log_carries_market_and_blended_probability_through():
    tracking.log_prediction(_pred(home_win_prob=0.72), season=2026, week=2, market_home_win_prob=0.6)
    weekly = pd.DataFrame([
        _weekly_row("M.Stafford", "QB", "LA", attempts=31, passing_yards=327),
        _weekly_row("K.Williams", "RB", "LA", rushing_yards=85),
        _weekly_row("P.Nacua", "WR", "LA", receiving_yards=100),
        _weekly_row("C.Parkinson", "TE", "LA", receiving_yards=15),
        _weekly_row("J.Dart", "QB", "NYG", attempts=27, passing_yards=200),
        _weekly_row("T.Tracy", "RB", "NYG", rushing_yards=40),
        _weekly_row("M.Nabers", "WR", "NYG", receiving_yards=50),
        _weekly_row("I.Likely", "TE", "NYG", receiving_yards=30),
    ])
    graded = tracking.grade_log(_schedule_row(), weekly)
    assert len(graded) == 1
    assert graded[0]["market_home_win_prob"] == 0.6
    assert abs(graded[0]["blended_home_win_prob"] - 0.66) < 1e-9  # (0.72 + 0.6) / 2


def test_summarize_computes_fair_model_market_blend_comparison_on_shared_subset():
    # game 1 has market data; game 2 doesn't - the market/blend comparison must only use
    # game 1, and the model's own accuracy in that comparison must ALSO be restricted to
    # game 1 (not silently computed over both games), so all three numbers are apples-to-apples
    graded = [
        {
            "winner_correct": True, "home_win_prob": 0.7, "home_team": "LA", "actual_winner": "LA",
            "margin_error": 5.0, "personnel_checks": {}, "prop_grades": {},
            "market_home_win_prob": 0.5, "blended_home_win_prob": 0.6,
        },
        {
            "winner_correct": False, "home_win_prob": 0.6, "home_team": "SF", "actual_winner": "MIA",
            "margin_error": 10.0, "personnel_checks": {}, "prop_grades": {},
            "market_home_win_prob": None, "blended_home_win_prob": None,
        },
    ]
    summary = tracking.summarize(graded)
    assert summary["market_games"] == 1
    # model's overall accuracy (both games): 1/2 correct = 50%
    assert summary["accuracy"] == 0.5
    # model's accuracy on the market-only subset (game 1 alone, which was correct): 100%
    assert summary["model_subset_accuracy"] == 1.0
    # market (0.5, home team LA actually won) is also "correct" by the >=0.5 threshold
    assert summary["market_accuracy"] == 1.0
    assert summary["blended_accuracy"] == 1.0
