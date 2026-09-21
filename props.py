"""Player prop-style probabilities for a specific matchup - e.g. "40+ rushing yards" -
adjusted for how the SPECIFIC opponent has defended that stat recently, not just a
generic average pulled from the player's own history in isolation.

Method: fit a normal distribution to the player's trailing game log (mean and
variance from real games, not assumed), then shift that mean by how much more or less
than league-average the upcoming opponent has allowed in that stat recently. This is a
standard, simple technique (the same idea behind DFS/fantasy matchup ratings) - not a
guarantee, and not yet backtested for calibration the way the win-probability model is,
so treat the number as directional context, not a precise forecast.

With only 1-2 games, a player's own sample variance is either undefined or too noisy to
trust (a rookie's first start, a committee back who just took over volume). Rather than
hide the estimate or fabricate a spread, `prop_over_probability` blends the player's own
variance toward the real league-wide game-to-game variance for that stat/position
(`population_std`, computed from real historical games via `population_std()`) - the
less of their own history there is, the more the estimate leans on real variance from
comparable players, converging to pure self-history once there's enough of it.
"""

from statistics import NormalDist

import pandas as pd

MIN_GAMES_FOR_ESTIMATE = 1  # a single game is enough for a mean once variance is backed by league data
# "pseudo-games" of league variance blended in when the player's own sample is small. Kept
# small deliberately: 5 games is the largest trailing window used anywhere in this app, so
# a prior heavier than this would still meaningfully distort even a "fully established"
# player's own well-measured variance instead of just steadying a genuinely thin one.
SHRINKAGE_PRIOR_GAMES = 1.5


def population_std(league_hist: pd.DataFrame, position: str, stat_col: str) -> float | None:
    """Real game-to-game standard deviation for this stat among this position, across
    every player/game in `league_hist` - used to steady a specific player's estimate
    when they don't have enough of their own games to trust their own variance. Grounded
    in real games across the league, not guessed."""
    values = league_hist.loc[league_hist["position"] == position, stat_col].dropna()
    if len(values) < 2:
        return None
    return float(values.std())


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
    population_std: float | None = None,
) -> dict | None:
    """Probability this player clears `threshold` in `stat_col`, using a normal
    approximation over their own trailing games, shifted by `factor` (the opponent's
    matchup adjustment). Returns None rather than a number built on too little data.

    `population_std` (see the module docstring) steadies the variance when the player's
    own sample is small - the blend is weighted by games played vs. SHRINKAGE_PRIOR_GAMES
    "pseudo-games" of league data, so it fades out as real history accumulates.
    """
    if player_name is None:
        return None
    rows = team_hist[team_hist["player_name"] == player_name].sort_values(["season", "week"]).tail(n_games)
    values = rows[stat_col].dropna()
    games = len(values)
    if games < MIN_GAMES_FOR_ESTIMATE:
        return None

    own_mean = float(values.mean())
    own_var = float(values.var()) if games > 1 else None  # sample variance needs 2+ points

    if population_std:
        pop_var = population_std**2
        prior_games = SHRINKAGE_PRIOR_GAMES
        own_component = (own_var if own_var is not None else pop_var) * games
        blended_var = (own_component + pop_var * prior_games) / (games + prior_games)
        own_std = blended_var**0.5
    elif own_var is not None:
        own_std = own_var**0.5
    else:
        return None  # single game and no league reference to borrow variance from

    adj_mean = own_mean * factor
    adj_std = max(own_std * factor, 1.0)  # avoid a degenerate zero-variance distribution

    probability = 1 - NormalDist(adj_mean, adj_std).cdf(threshold)
    return {
        "probability": max(0.0, min(1.0, probability)),
        "own_avg": round(own_mean, 1),
        "matchup_adjusted_avg": round(adj_mean, 1),
        "matchup_factor": round(factor, 2),
        "games": games,
    }
