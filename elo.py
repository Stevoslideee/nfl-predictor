"""Team Elo ratings, updated game by game from historical results.

Same approach FiveThirtyEight popularized for NFL: home-field bonus baked into
the win-probability formula, a margin-of-victory multiplier so blowouts move
ratings more than squeakers, and between-season regression toward the mean
since rosters turn over.
"""

from dataclasses import dataclass, field

import pandas as pd

BASE_RATING = 1500.0
K_FACTOR = 35.0
HOME_FIELD_ADV = 45.0  # Elo points added to the home team's rating pre-game
SEASON_REGRESSION = 0.67  # fraction of prior rating kept when a new season starts


def expected_win_prob(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(rating_a - rating_b) / 400.0))


def mov_multiplier(point_margin: float, elo_diff_winner: float) -> float:
    return ((abs(point_margin) + 3) ** 0.8) / (7.5 + 0.006 * elo_diff_winner)


@dataclass
class EloState:
    ratings: dict[str, float] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)  # per-game snapshot for backtesting/explanation

    def get(self, team: str) -> float:
        return self.ratings.get(team, BASE_RATING)


def run_elo(games: pd.DataFrame) -> EloState:
    """Replay every completed game chronologically, updating ratings as we go."""
    state = EloState()
    current_season = None

    for row in games.itertuples():
        if current_season is not None and row.season != current_season:
            for team in list(state.ratings.keys()):
                state.ratings[team] = BASE_RATING + SEASON_REGRESSION * (
                    state.ratings[team] - BASE_RATING
                )
        current_season = row.season

        home, away = row.home_team, row.away_team
        home_elo = state.get(home)
        away_elo = state.get(away)

        pre_home_elo, pre_away_elo = home_elo, away_elo
        home_win_prob = expected_win_prob(home_elo + HOME_FIELD_ADV, away_elo)

        margin = row.home_score - row.away_score
        if margin > 0:
            actual_home = 1.0
        elif margin < 0:
            actual_home = 0.0
        else:
            actual_home = 0.5

        winner_elo_diff = (home_elo + HOME_FIELD_ADV - away_elo) if margin >= 0 else (
            away_elo - (home_elo + HOME_FIELD_ADV)
        )
        mult = mov_multiplier(margin, winner_elo_diff)

        shift = K_FACTOR * mult * (actual_home - home_win_prob)
        state.ratings[home] = home_elo + shift
        state.ratings[away] = away_elo - shift

        state.history.append(
            {
                "game_id": row.game_id,
                "season": row.season,
                "week": row.week,
                "home_team": home,
                "away_team": away,
                "home_score": row.home_score,
                "away_score": row.away_score,
                "pre_home_elo": pre_home_elo,
                "pre_away_elo": pre_away_elo,
                "home_win_prob": home_win_prob,
                "predicted_winner": home if home_win_prob >= 0.5 else away,
                "actual_winner": home if margin > 0 else (away if margin < 0 else "TIE"),
            }
        )

    return state
