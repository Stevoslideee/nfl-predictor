"""Combine team Elo ratings with recent QB form into a matchup prediction.

Beyond the base Elo + QB-form model, four context adjustments are applied, each kept
small and each backtested (see backtest.py) rather than picked arbitrarily:

- QB injury: if the usual starter is listed Out/Doubtful, swap in whoever's next in
  line at QB (by recent snap volume) instead of pretending the starter is playing.
- Rest days: a real, if modest, scheduling edge for the more-rested team.
- Divisional games: historically closer/more upset-prone, so confidence is dampened
  rather than the pick being flipped.
- Weather: high wind or extreme cold suppresses passing offense and adds variance,
  which closes the gap between favorite and underdog rather than favoring either side.
"""

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

import injuries as injuries_mod
import player_stats
import props as props_mod
import weather as weather_mod
from elo import HOME_FIELD_ADV, EloState, expected_win_prob, run_elo

RB_PROP_YARDS = 40.0
WR_PROP_YARDS = 40.0
QB_PROP_YARDS = 150.0

LEAGUE_AVG_PASSER_RATING = 90.0
ELO_PER_PASSER_RATING_POINT = 3.0  # how many Elo points one passer-rating point differential is worth
MAX_QB_ELO_ADJUSTMENT = 60.0  # cap so one great/bad QB game stretch can't dominate the model
ELO_POINTS_PER_SPREAD_POINT = 25.0  # rough Elo-diff -> projected scoring margin conversion

REST_ELO_PER_DAY = 4.0  # Elo points per day of rest advantage
MAX_REST_ADJUSTMENT = 20.0  # cap - rest matters, but modestly, per the analytics literature

DIV_GAME_DAMPENING = 0.15  # fraction the model's margin is pulled toward even for a divisional game

WIND_DAMPENING_THRESHOLD_MPH = 20.0
WIND_DAMPENING_FRACTION = 0.15
COLD_DAMPENING_THRESHOLD_F = 25.0
COLD_DAMPENING_FRACTION = 0.10


@dataclass
class MatchupPrediction:
    home_team: str
    away_team: str
    home_elo: float
    away_elo: float
    home_win_prob: float
    projected_margin: float  # positive = home team favored by this many points
    home_qb: dict
    away_qb: dict
    home_skill: list
    away_skill: list
    home_rb: dict | None
    away_rb: dict | None
    home_wr: dict | None
    away_wr: dict | None
    home_te: dict | None
    away_te: dict | None
    head_to_head: pd.DataFrame
    home_injuries: pd.DataFrame
    away_injuries: pd.DataFrame
    home_qb_status: str | None
    away_qb_status: str | None
    home_qb_note: str | None = None  # set when the starter's stats were swapped for a backup's
    away_qb_note: str | None = None
    context_notes: list = field(default_factory=list)  # plain-English: rest/division/weather effects applied
    home_qb_prop: dict | None = None  # probability of clearing QB_PROP_YARDS passing yards, vs. this opponent
    away_qb_prop: dict | None = None
    home_rb_prop: dict | None = None  # probability of clearing RB_PROP_YARDS rushing yards, vs. this opponent
    away_rb_prop: dict | None = None
    home_wr_prop: dict | None = None  # probability of clearing WR_PROP_YARDS receiving yards, vs. this opponent
    away_wr_prop: dict | None = None


def elo_state_as_of(schedules: pd.DataFrame, season: int, week: int) -> EloState:
    """Team Elo ratings from every completed game before this season/week.

    Rebuilding this is the expensive part of a prediction (it replays the full game
    history). All games in the same week share an identical cutoff, so callers scoring
    a whole week's slate should compute this once and pass it to predict_matchup via
    the elo_state parameter, rather than letting each call rebuild it from scratch.
    """
    from data import completed_games

    games = completed_games(schedules)
    games = games[(games["season"] < season) | ((games["season"] == season) & (games["week"] < week))]
    return run_elo(games)


def weekly_hist_as_of(weekly: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """Player weekly stats from every game before this season/week.

    Like elo_state_as_of, this is the expensive part of a prediction to redo per game -
    callers scoring a whole week's slate should compute it once and pass it to
    predict_matchup via the weekly_hist parameter.
    """
    return player_stats.before_cutoff(weekly, season, week)


def qb_elo_adjustment(home_form: dict, away_form: dict) -> float:
    """Backtesting (see backtest.py and the README) found that comparing trailing passer
    rating straight against a league average - every single game, established starter or
    not - actively hurt accuracy on held-out seasons: Elo is fit game-by-game on real
    outcomes, so it already reflects an established starter's level, and layering a noisy
    5-game rating on top of that just adds noise. What Elo genuinely can't have absorbed
    yet is a NEW starter (a rookie's first start, a just-inserted injury replacement), so
    the adjustment is weighted by how little of the team's recent QB history this player
    accounts for (player_stats.QB_TENURE_WINDOW) - full strength for a brand-new starter,
    fading to near zero for an established one where Elo is already the better signal.
    """
    home_rating = home_form.get("passer_rating") or LEAGUE_AVG_PASSER_RATING
    away_rating = away_form.get("passer_rating") or LEAGUE_AVG_PASSER_RATING
    home_weight = max(0.0, 1.0 - (home_form.get("tenure") or 0) / player_stats.QB_TENURE_WINDOW)
    away_weight = max(0.0, 1.0 - (away_form.get("tenure") or 0) / player_stats.QB_TENURE_WINDOW)
    weighted_home = LEAGUE_AVG_PASSER_RATING + (home_rating - LEAGUE_AVG_PASSER_RATING) * home_weight
    weighted_away = LEAGUE_AVG_PASSER_RATING + (away_rating - LEAGUE_AVG_PASSER_RATING) * away_weight
    raw = (weighted_home - weighted_away) * ELO_PER_PASSER_RATING_POINT
    return max(-MAX_QB_ELO_ADJUSTMENT, min(MAX_QB_ELO_ADJUSTMENT, raw))


def rest_elo_adjustment(home_rest: float | None, away_rest: float | None) -> float:
    """Elo points favoring the more-rested team - a real but modest scheduling edge."""
    if home_rest is None or away_rest is None:
        return 0.0
    raw = (home_rest - away_rest) * REST_ELO_PER_DAY
    return max(-MAX_REST_ADJUSTMENT, min(MAX_REST_ADJUSTMENT, raw))


def divisional_dampening_factor(div_game: bool) -> float:
    """Multiply the final margin by this - divisional games run closer than the raw
    numbers suggest, so confidence is pulled toward a coin flip, not toward either team."""
    return (1.0 - DIV_GAME_DAMPENING) if div_game else 1.0


def weather_dampening_factor(temp_f: float | None, wind_mph: float | None) -> float:
    """Multiply the final margin by this - high wind or extreme cold suppress passing
    offense and add variance, which closes the gap between favorite and underdog."""
    factor = 1.0
    if wind_mph is not None and wind_mph >= WIND_DAMPENING_THRESHOLD_MPH:
        factor *= 1.0 - WIND_DAMPENING_FRACTION
    if temp_f is not None and temp_f <= COLD_DAMPENING_THRESHOLD_F:
        factor *= 1.0 - COLD_DAMPENING_FRACTION
    return factor


def game_context(schedules: pd.DataFrame, home_team: str, away_team: str, season: int, week: int) -> dict:
    """Division/rest/weather facts for this exact scheduled matchup. Falls back to
    neutral values (no adjustment) if the matchup isn't found on the real schedule -
    e.g. a hypothetical pairing that was never actually scheduled."""
    row = schedules[
        (schedules["season"] == season)
        & (schedules["week"] == week)
        & (schedules["home_team"] == home_team)
        & (schedules["away_team"] == away_team)
    ]
    if row.empty:
        return {"div_game": False, "home_rest": None, "away_rest": None, "roof": None, "temp": None, "wind": None, "gameday": None}

    r = row.iloc[0]

    def _get(col):
        val = r.get(col)
        return float(val) if pd.notna(val) else None

    return {
        "div_game": bool(r.get("div_game")) if pd.notna(r.get("div_game")) else False,
        "home_rest": _get("home_rest"),
        "away_rest": _get("away_rest"),
        "roof": r.get("roof") if pd.notna(r.get("roof")) else None,
        "temp": _get("temp"),
        "wind": _get("wind"),
        "gameday": r.get("gameday") if pd.notna(r.get("gameday")) else None,
    }


def _live_forecast_date(context: dict, home_team: str) -> str | None:
    """The date to fetch a live forecast for, or None if this game doesn't need one
    (indoor, already has actual weather, too far out, or already in the past)."""
    if not weather_mod.is_outdoor(context["roof"], home_team):
        return None
    if context["temp"] is not None or context["wind"] is not None:
        return None
    gameday = context.get("gameday")
    if not gameday:
        return None
    try:
        game_date = str(gameday)[:10]
        if dt.date.fromisoformat(game_date) < dt.date.today():
            return None
    except ValueError:
        return None
    return game_date


def _resolve_weather(context: dict, home_team: str) -> tuple[float | None, float | None, bool]:
    """(temp_f, wind_mph, is_live_forecast). Prefers the schedule's own actual weather
    (populated for games already played); falls back to a live forecast for outdoor
    games that haven't happened yet. Returns (None, None, False) for indoor games or
    when neither source has anything."""
    if weather_mod.is_outdoor(context["roof"], home_team) and (context["temp"] is not None or context["wind"] is not None):
        return context["temp"], context["wind"], False

    game_date = _live_forecast_date(context, home_team)
    if game_date is None:
        return None, None, False

    forecast = weather_mod.get_forecast(home_team, game_date)
    if forecast is None:
        return None, None, False
    return forecast["temp_f"], forecast["wind_mph"], True


def prefetch_weather_for_matchups(
    schedules: pd.DataFrame, matchups: list[tuple[str, str]], season: int, week: int
) -> None:
    """Warm the weather cache for a batch of upcoming games before scoring them one by
    one. Without this, a Weekly Report or season recap covering the current week pays
    each outdoor team's forecast latency sequentially inside the per-game loop - this
    fetches them all concurrently up front instead. Safe/cheap to call even when nothing
    needs a live forecast (indoor games, already-played weeks).
    """
    needed = []
    for home, away in matchups:
        context = game_context(schedules, home, away, season, week)
        game_date = _live_forecast_date(context, home)
        if game_date is not None:
            needed.append((home, game_date))
    weather_mod.prefetch_forecasts(needed)


def _effective_qb(weekly_hist: pd.DataFrame, team: str, qb_form: dict, qb_status: str | None) -> tuple[dict, str | None]:
    """The QB whose stats should actually drive the prediction: the usual starter,
    unless they're Out/Doubtful, in which case whoever's next in line by recent snaps."""
    if qb_status not in ("Out", "Doubtful"):
        return qb_form, None

    starter_name = qb_form.get("player_name")
    backup = player_stats.backup_qb_form(weekly_hist, team, starter_name) if starter_name else None
    if backup is None:
        neutral = {"player_name": None, "games": 0, "passer_rating": None, "pass_yards_per_game": None, "tenure": 0}
        return neutral, f"{starter_name} is {qb_status.lower()} - no data on the likely replacement, using league-average QB"
    return backup, f"{starter_name} is {qb_status.lower()} - using {backup['player_name']}'s recent form instead"


def defense_hist_as_of(team_stats: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """Defense-allowed view of team stats, filtered to before this season/week - the
    team-level analog of weekly_hist_as_of, used to opponent-adjust player prop odds."""
    from data import defense_allowed_view

    return player_stats.before_cutoff(defense_allowed_view(team_stats), season, week)


def head_to_head(schedules: pd.DataFrame, team_a: str, team_b: str, n_games: int = 5) -> pd.DataFrame:
    from data import completed_games

    games = completed_games(schedules)
    mask = ((games["home_team"] == team_a) & (games["away_team"] == team_b)) | (
        (games["home_team"] == team_b) & (games["away_team"] == team_a)
    )
    cols = ["season", "week", "home_team", "away_team", "home_score", "away_score"]
    return games.loc[mask, cols].tail(n_games).reset_index(drop=True)


def predict_matchup(
    schedules: pd.DataFrame,
    weekly: pd.DataFrame,
    home_team: str,
    away_team: str,
    season: int,
    week: int,
    injuries: pd.DataFrame | None = None,
    elo_state: EloState | None = None,
    weekly_hist: pd.DataFrame | None = None,
    team_stats: pd.DataFrame | None = None,
    defense_hist: pd.DataFrame | None = None,
) -> MatchupPrediction:
    if elo_state is None:
        elo_state = elo_state_as_of(schedules, season, week)
    if weekly_hist is None:
        weekly_hist = weekly_hist_as_of(weekly, season, week)
    if defense_hist is None and team_stats is not None:
        defense_hist = defense_hist_as_of(team_stats, season, week)
    home_elo = elo_state.get(home_team)
    away_elo = elo_state.get(away_team)

    home_snapshot = player_stats.team_form_snapshot(weekly_hist, home_team)
    away_snapshot = player_stats.team_form_snapshot(weekly_hist, away_team)
    home_qb = home_snapshot["qb"]
    away_qb = away_snapshot["qb"]

    if injuries is not None and not injuries.empty:
        home_injuries = injuries_mod.team_injury_report(injuries, home_team, season, week)
        away_injuries = injuries_mod.team_injury_report(injuries, away_team, season, week)
        home_qb_status = injuries_mod.starting_qb_status(home_injuries, home_qb["player_name"])
        away_qb_status = injuries_mod.starting_qb_status(away_injuries, away_qb["player_name"])
    else:
        home_injuries = away_injuries = pd.DataFrame()
        home_qb_status = away_qb_status = None

    effective_home_qb, home_qb_note = _effective_qb(weekly_hist, home_team, home_qb, home_qb_status)
    effective_away_qb, away_qb_note = _effective_qb(weekly_hist, away_team, away_qb, away_qb_status)
    qb_adjustment = qb_elo_adjustment(effective_home_qb, effective_away_qb)

    context = game_context(schedules, home_team, away_team, season, week)
    context_notes = []

    rest_adj = rest_elo_adjustment(context["home_rest"], context["away_rest"])
    if abs(rest_adj) >= 2:
        rested_team = home_team if rest_adj > 0 else away_team
        context_notes.append(f"{rested_team} has a rest advantage ({context['home_rest']:.0f} vs {context['away_rest']:.0f} days)")

    div_factor = divisional_dampening_factor(context["div_game"])
    if context["div_game"]:
        context_notes.append("Divisional game - historically closer than the raw numbers suggest")

    temp_f, wind_mph, is_forecast = _resolve_weather(context, home_team)
    weather_factor = weather_dampening_factor(temp_f, wind_mph)
    if weather_factor < 1.0:
        bits = []
        if wind_mph is not None and wind_mph >= WIND_DAMPENING_THRESHOLD_MPH:
            bits.append(f"{wind_mph:.0f} mph wind")
        if temp_f is not None and temp_f <= COLD_DAMPENING_THRESHOLD_F:
            bits.append(f"{temp_f:.0f}°F")
        source = "forecast" if is_forecast else "actual"
        context_notes.append(f"Weather ({source}): {', '.join(bits)} - likely to suppress passing and tighten the game")

    raw_diff = (home_elo + HOME_FIELD_ADV + qb_adjustment + rest_adj) - away_elo
    elo_diff = raw_diff * div_factor * weather_factor

    home_win_prob = expected_win_prob(elo_diff, 0.0)
    projected_margin = elo_diff / ELO_POINTS_PER_SPREAD_POINT

    home_qb_prop = away_qb_prop = home_rb_prop = away_rb_prop = home_wr_prop = away_wr_prop = None
    if defense_hist is not None and not defense_hist.empty:
        home_hist = weekly_hist[weekly_hist["recent_team"] == home_team]
        away_hist = weekly_hist[weekly_hist["recent_team"] == away_team]

        def _name(player: dict | None) -> str | None:
            return player["player_name"] if player else None

        home_qb_prop = props_mod.prop_over_probability(
            home_hist, effective_home_qb.get("player_name"), "passing_yards", QB_PROP_YARDS,
            factor=props_mod.matchup_factor(defense_hist, away_team, "passing_yards_allowed"),
        )
        away_qb_prop = props_mod.prop_over_probability(
            away_hist, effective_away_qb.get("player_name"), "passing_yards", QB_PROP_YARDS,
            factor=props_mod.matchup_factor(defense_hist, home_team, "passing_yards_allowed"),
        )
        home_rb_prop = props_mod.prop_over_probability(
            home_hist, _name(home_snapshot["rb"]), "rushing_yards", RB_PROP_YARDS,
            factor=props_mod.matchup_factor(defense_hist, away_team, "rushing_yards_allowed"),
        )
        away_rb_prop = props_mod.prop_over_probability(
            away_hist, _name(away_snapshot["rb"]), "rushing_yards", RB_PROP_YARDS,
            factor=props_mod.matchup_factor(defense_hist, home_team, "rushing_yards_allowed"),
        )
        home_wr_prop = props_mod.prop_over_probability(
            home_hist, _name(home_snapshot["wr"]), "receiving_yards", WR_PROP_YARDS,
            factor=props_mod.matchup_factor(defense_hist, away_team, "receiving_yards_allowed"),
        )
        away_wr_prop = props_mod.prop_over_probability(
            away_hist, _name(away_snapshot["wr"]), "receiving_yards", WR_PROP_YARDS,
            factor=props_mod.matchup_factor(defense_hist, home_team, "receiving_yards_allowed"),
        )

    return MatchupPrediction(
        home_team=home_team,
        away_team=away_team,
        home_elo=round(home_elo, 1),
        away_elo=round(away_elo, 1),
        home_win_prob=round(home_win_prob, 3),
        projected_margin=round(projected_margin, 1),
        home_qb=effective_home_qb,
        away_qb=effective_away_qb,
        home_skill=home_snapshot["skill"],
        away_skill=away_snapshot["skill"],
        home_rb=home_snapshot["rb"],
        away_rb=away_snapshot["rb"],
        home_wr=home_snapshot["wr"],
        away_wr=away_snapshot["wr"],
        home_te=home_snapshot["te"],
        away_te=away_snapshot["te"],
        head_to_head=head_to_head(schedules, home_team, away_team),
        home_injuries=home_injuries,
        away_injuries=away_injuries,
        home_qb_status=home_qb_status,
        away_qb_status=away_qb_status,
        home_qb_note=home_qb_note,
        away_qb_note=away_qb_note,
        context_notes=context_notes,
        home_qb_prop=home_qb_prop,
        away_qb_prop=away_qb_prop,
        home_rb_prop=home_rb_prop,
        away_rb_prop=away_rb_prop,
        home_wr_prop=home_wr_prop,
        away_wr_prop=away_wr_prop,
    )
