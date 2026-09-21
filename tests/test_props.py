import math

import pandas as pd

from props import anytime_td_probability, matchup_factor, population_std, population_td_rate, prop_over_probability


def _hist(rows):
    return pd.DataFrame(rows)


def _game(player, position, season, week, rushing_yards=0.0, receiving_yards=0.0, rushing_tds=0.0, receiving_tds=0.0):
    return dict(
        player_name=player, position=position, season=season, week=week,
        rushing_yards=rushing_yards, receiving_yards=receiving_yards,
        rushing_tds=rushing_tds, receiving_tds=receiving_tds,
    )


def test_prop_over_probability_none_for_missing_player_name():
    assert prop_over_probability(_hist([]), None, "rushing_yards", 40.0) is None


def test_prop_over_probability_none_for_unknown_player():
    hist = _hist([_game("A.Back", "RB", 2024, 1, rushing_yards=50)])
    assert prop_over_probability(hist, "B.Other", "rushing_yards", 40.0) is None


def test_prop_over_probability_single_game_without_population_std_returns_none():
    hist = _hist([_game("A.Back", "RB", 2024, 1, rushing_yards=50)])
    assert prop_over_probability(hist, "A.Back", "rushing_yards", 40.0, population_std=None) is None


def test_prop_over_probability_single_game_with_population_std_uses_it_exactly():
    hist = _hist([_game("A.Back", "RB", 2024, 1, rushing_yards=50)])
    result = prop_over_probability(hist, "A.Back", "rushing_yards", 40.0, population_std=20.0)
    assert result is not None
    assert result["own_avg"] == 50.0
    assert result["games"] == 1
    assert 0.0 <= result["probability"] <= 1.0


def test_prop_over_probability_probability_bounds():
    hist = _hist([_game("A.Back", "RB", 2024, w, rushing_yards=100) for w in range(1, 6)])
    result = prop_over_probability(hist, "A.Back", "rushing_yards", 1000.0, population_std=20.0)
    assert result["probability"] == 0.0  # threshold far above anything observed
    result2 = prop_over_probability(hist, "A.Back", "rushing_yards", -1000.0, population_std=20.0)
    assert result2["probability"] == 1.0  # threshold far below anything observed


def test_prop_over_probability_shrinkage_fades_as_games_accumulate():
    # same own average and same population_std, but different sample sizes - the
    # 1-game estimate should lean fully on population variance, while the 5-game
    # estimate should lean mostly on its own (very tight, consistent) sample variance
    one_game = _hist([_game("A", "RB", 2024, 1, rushing_yards=50)])
    five_games = _hist([_game("B", "RB", 2024, w, rushing_yards=50) for w in range(1, 6)])

    pop_std = 30.0
    prop_one = prop_over_probability(one_game, "A", "rushing_yards", 40.0, population_std=pop_std)
    prop_five = prop_over_probability(five_games, "B", "rushing_yards", 40.0, population_std=pop_std)

    # five consistent games of exactly 50 yards has ~0 own variance, so shrinking only
    # slightly toward a much larger population variance should still leave it far more
    # confident (higher probability of clearing a below-average threshold) than the
    # 1-game case, which is forced to use the full population variance
    assert prop_five["probability"] > prop_one["probability"]


def test_matchup_factor_defaults_to_one_when_empty():
    # a real caller always passes a DataFrame already shaped like defense_allowed_view()'s
    # output (has the right columns, possibly zero rows) - not a bare columnless frame
    empty = pd.DataFrame(columns=["team", "season", "week", "rushing_yards_allowed"])
    assert matchup_factor(empty, "BUF", "rushing_yards_allowed") == 1.0


def test_matchup_factor_above_one_for_generous_defense():
    hist = pd.DataFrame([
        {"team": "BUF", "season": 2024, "week": 1, "rushing_yards_allowed": 200},
        {"team": "MIA", "season": 2024, "week": 1, "rushing_yards_allowed": 100},
    ])
    factor = matchup_factor(hist, "BUF", "rushing_yards_allowed")
    assert factor > 1.0  # BUF allows more than league average


def test_population_std_none_for_insufficient_data():
    hist = pd.DataFrame([_game("A.Back", "RB", 2024, 1, rushing_yards=50)])
    assert population_std(hist, "RB", "rushing_yards") is None


def test_population_std_filters_by_position():
    hist = pd.DataFrame([
        _game("A.Back", "RB", 2024, 1, rushing_yards=10),
        _game("B.Back", "RB", 2024, 2, rushing_yards=90),
        _game("C.Receiver", "WR", 2024, 1, rushing_yards=1000),  # wrong position, must be excluded
    ])
    std = population_std(hist, "RB", "rushing_yards")
    assert std is not None
    assert std == pd.Series([10.0, 90.0]).std()


def test_anytime_td_probability_none_for_missing_player():
    assert anytime_td_probability(_hist([]), None, "rushing_tds") is None


def test_anytime_td_probability_zero_rate_gives_zero_probability():
    hist = _hist([_game("A.Back", "RB", 2024, w, rushing_tds=0) for w in range(1, 6)])
    result = anytime_td_probability(hist, "A.Back", "rushing_tds")
    assert result["probability"] == 0.0


def test_anytime_td_probability_matches_poisson_formula():
    hist = _hist([_game("A.Back", "RB", 2024, w, rushing_tds=1) for w in range(1, 6)])
    result = anytime_td_probability(hist, "A.Back", "rushing_tds")
    # own_rate=1.0/game, no population blend -> P(>=1) = 1 - e^-1
    assert abs(result["probability"] - (1 - math.exp(-1.0))) < 1e-9


def test_anytime_td_probability_single_game_blends_toward_population():
    hist = _hist([_game("A.Back", "RB", 2024, 1, rushing_tds=1)])
    result = anytime_td_probability(hist, "A.Back", "rushing_tds", population_rate=0.3)
    assert result is not None
    assert 0.0 < result["probability"] < 1.0
    # blended rate should sit strictly between the population rate and the single
    # observed game's rate, not equal either extreme
    assert 0.3 < result["matchup_adjusted_avg"] < 1.0


def test_anytime_td_probability_bounds_stay_in_zero_one():
    hist = _hist([_game("A.Back", "RB", 2024, w, rushing_tds=5) for w in range(1, 6)])
    result = anytime_td_probability(hist, "A.Back", "rushing_tds", factor=3.0)
    assert 0.0 <= result["probability"] <= 1.0


def test_population_td_rate_none_for_insufficient_data():
    hist = pd.DataFrame([_game("A.Back", "RB", 2024, 1, rushing_tds=1)])
    assert population_td_rate(hist, "RB", "rushing_tds") is None


def test_population_td_rate_correct_value():
    hist = pd.DataFrame([
        _game("A.Back", "RB", 2024, 1, rushing_tds=0),
        _game("B.Back", "RB", 2024, 2, rushing_tds=2),
    ])
    assert population_td_rate(hist, "RB", "rushing_tds") == 1.0
