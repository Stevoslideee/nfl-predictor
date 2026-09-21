"""Player prop-style probabilities for a specific matchup - e.g. "40+ rushing yards" -
adjusted for how the SPECIFIC opponent has defended that stat recently, not just a
generic average pulled from the player's own history in isolation.

Method: fit a normal distribution to the player's trailing game log (mean and
variance from real games, not assumed), then shift that mean by how much more or less
than league-average the upcoming opponent has allowed in that stat recently. This is a
standard, simple technique (the same idea behind DFS/fantasy matchup ratings) - not a
guarantee, and not yet backtested for calibration the way the win-probability model is,
so treat the number as directional context, not a precise forecast.
"""

from statistics import NormalDist

import pandas as pd

MIN_GAMES_FOR_ESTIMATE = 2  # need at least this many games to estimate variance honestly


def defense_allowed_trailing(defense_hist: pd.DataFrame, team: str, stat_col: str, n_games: int = 5) -> float | None:
    """This team's trailing average `stat_col` allowed, from a defense_allowed_view()
    table already filtered to before the game being predicted."""
    rows = defense_hist[defense_hist["team"] == team].sort_values(["season", "week"]).tail(n_games)
    if rows.empty:
        return None
    return float(rows[stat_col].mean())


def matchup_factor(defense_hist: pd.DataFrame, opponent: str, stat_col: str, n_games: int = 5) -> float:
    """>1 = opponent has allowed more than league average recently (favorable matchup),
    <1 = tougher than average. Falls back to 1.0 (no adjustment) when there isn't enough
    data to say anything, rather than guessing a direction."""
    allowed = defense_allowed_trailing(defense_hist, opponent, stat_col, n_games)
    if allowed is None or defense_hist.empty:
        return 1.0
    league_avg = float(defense_hist[stat_col].mean())
    if not league_avg:
        return 1.0
    return allowed / league_avg


def prop_over_probability(
    team_hist: pd.DataFrame,
    player_name: str | None,
    stat_col: str,
    threshold: float,
    factor: float = 1.0,
    n_games: int = 5,
) -> dict | None:
    """Probability this player clears `threshold` in `stat_col`, using a normal
    approximation over their own trailing games, shifted by `factor` (the opponent's
    matchup adjustment). Returns None rather than a number built on too little data.
    """
    if player_name is None:
        return None
    rows = team_hist[team_hist["player_name"] == player_name].sort_values(["season", "week"]).tail(n_games)
    values = rows[stat_col].dropna()
    if len(values) < MIN_GAMES_FOR_ESTIMATE:
        return None

    own_mean, own_std = float(values.mean()), float(values.std())
    adj_mean = own_mean * factor
    adj_std = max(own_std * factor, 1.0)  # avoid a degenerate zero-variance distribution

    probability = 1 - NormalDist(adj_mean, adj_std).cdf(threshold)
    return {
        "probability": max(0.0, min(1.0, probability)),
        "own_avg": round(own_mean, 1),
        "matchup_adjusted_avg": round(adj_mean, 1),
        "matchup_factor": round(factor, 2),
        "games": len(values),
    }
