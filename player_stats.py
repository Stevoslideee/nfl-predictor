"""Recent player-level form, used to nudge team predictions beyond a pure Elo rating.

QB play is weighted most heavily since it swings NFL outcomes more than any
other single position. Skill-position (RB/WR/TE) trailing production is
surfaced for context in the prediction explanation.
"""

import pandas as pd


def before_cutoff(df: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """Every row strictly before this season/week. Scanning the full weekly dataframe is
    the expensive part of any lookup here - a caller processing many teams for the same
    season/week (e.g. a full week's slate) should call this once and reuse the result via
    team_form_snapshot(), instead of letting each lookup filter the whole frame again."""
    return df[(df["season"] < season) | ((df["season"] == season) & (df["week"] < week))]


_before = before_cutoff  # short internal alias used throughout this module


def passer_rating(row_sum: dict) -> float:
    att = row_sum.get("attempts", 0)
    if not att:
        return 0.0
    comp, yards, td, ints = (
        row_sum.get("completions", 0),
        row_sum.get("passing_yards", 0),
        row_sum.get("passing_tds", 0),
        row_sum.get("interceptions", 0),
    )
    a = max(0.0, min(2.375, ((comp / att) - 0.3) * 5))
    b = max(0.0, min(2.375, ((yards / att) - 3) * 0.25))
    c = max(0.0, min(2.375, (td / att) * 20))
    d = max(0.0, min(2.375, 2.375 - (ints / att) * 25))
    return (a + b + c + d) / 6 * 100


def _starting_qb_from(team_hist: pd.DataFrame, n_games: int = 5, qb_hist: pd.DataFrame | None = None) -> str | None:
    """Whoever has thrown the most passes for this team over their last n_games team games,
    given a history slice already filtered to that one team.

    Using trailing volume rather than just the single most recent game avoids getting fooled
    when the presumed starter sits out a meaningless season finale (or a stretch at the end of
    a playoff run) and a backup picks up mop-up snaps right before the cutoff.

    Pass qb_hist (team_hist already filtered to position == "QB") when the caller has already
    computed it - team_form_snapshot needs that same filter again for _qb_tenure, and this
    avoids scanning the same team history for QB rows twice per prediction.
    """
    if qb_hist is None:
        qb_hist = team_hist[team_hist["position"] == "QB"]
    if qb_hist.empty:
        return None
    recent_weeks = qb_hist[["season", "week"]].drop_duplicates().sort_values(["season", "week"]).tail(n_games)
    recent_weeks = recent_weeks.reset_index(drop=True)
    recent_weeks["recency_rank"] = recent_weeks.index  # 0 = oldest of the window, higher = more recent
    recent = qb_hist.merge(recent_weeks, on=["season", "week"])

    totals = recent.groupby("player_name").agg(attempts=("attempts", "sum"), recency_rank=("recency_rank", "max"))
    # ties on attempts (e.g. a benched starter's mop-up stretch vs. a real recent start) go to
    # whoever played more recently, since that's stronger evidence of who's the current starter
    return totals.sort_values(["attempts", "recency_rank"], ascending=False).index[0]


def current_starting_qb(weekly: pd.DataFrame, team: str, season: int, week: int, n_games: int = 5) -> str | None:
    team_hist = _before(weekly, season, week)
    team_hist = team_hist[team_hist["recent_team"] == team]
    return _starting_qb_from(team_hist, n_games)


QB_TENURE_WINDOW = 15  # team-games looked back to tell an established starter from a newly-installed one


def _qb_tenure(
    team_hist: pd.DataFrame, qb: str, window: int = QB_TENURE_WINDOW, qb_hist: pd.DataFrame | None = None
) -> int:
    """How many of the team's last `window` QB-games this specific player actually
    started. Low tenure (a rookie's first start, a just-inserted injury replacement) means
    Elo hasn't had a chance to absorb this QB's level yet; high tenure (an established
    starter) means it almost certainly already has, from real outcomes with them playing.

    Pass qb_hist (see _starting_qb_from) to reuse an already-computed QB-position filter.
    """
    if qb_hist is None:
        qb_hist = team_hist[team_hist["position"] == "QB"]
    recent_weeks = qb_hist[["season", "week"]].drop_duplicates().sort_values(["season", "week"]).tail(window)
    recent = qb_hist.merge(recent_weeks, on=["season", "week"])
    return int((recent["player_name"] == qb).sum())


def _qb_form_from(team_hist: pd.DataFrame, qb: str | None, n_games: int = 5, qb_hist: pd.DataFrame | None = None) -> dict:
    if qb is None:
        return {"player_name": None, "games": 0, "passer_rating": None, "pass_yards_per_game": None, "tenure": 0}

    rows = team_hist[team_hist["player_name"] == qb].sort_values(["season", "week"]).tail(n_games)
    if rows.empty:
        return {"player_name": qb, "games": 0, "passer_rating": None, "pass_yards_per_game": None, "tenure": 0}

    totals = rows[["completions", "attempts", "passing_yards", "passing_tds", "interceptions"]].sum()
    return {
        "player_name": qb,
        "games": len(rows),
        "passer_rating": round(float(passer_rating(totals.to_dict())), 1),
        "pass_yards_per_game": round(float(rows["passing_yards"].mean()), 1),
        "pass_tds_per_game": round(float(rows["passing_tds"].mean()), 2),
        "interceptions_per_game": round(float(rows["interceptions"].mean()), 2),
        "tenure": _qb_tenure(team_hist, qb, qb_hist=qb_hist),
    }


def qb_trailing_form(weekly: pd.DataFrame, team: str, season: int, week: int, n_games: int = 5) -> dict:
    """Trailing-N-game stat line and derived passer rating for the current starting QB."""
    team_hist = _before(weekly, season, week)
    team_hist = team_hist[team_hist["recent_team"] == team]
    qb = _starting_qb_from(team_hist, n_games)
    return _qb_form_from(team_hist, qb, n_games)


def backup_qb_form(hist: pd.DataFrame, team: str, exclude_qb: str, n_games: int = 5) -> dict | None:
    """Trailing form for whoever is next in line at QB - the same volume+recency logic
    used to find the starter, just applied after excluding the (presumably injured)
    current starter. This is a real but imperfect proxy: it can only see players who've
    already taken snaps for this team recently, so a newly signed backup with zero recent
    attempts won't show up here. Returns None when no such signal exists, so the caller
    can fall back to a neutral assumption instead of fabricating one.
    """
    team_hist = hist[(hist["recent_team"] == team) & (hist["player_name"] != exclude_qb)]
    backup = _starting_qb_from(team_hist, n_games)
    if backup is None:
        return None
    return _qb_form_from(team_hist, backup, n_games)


def _player_trailing_skill_stats(
    team_hist: pd.DataFrame, player_name: str, position: str, n_games: int = 5, _cache: dict | None = None
) -> dict:
    """One player's own trailing-N-game stat line, regardless of which shared team-week
    window was used to identify them as a leader - the same "their own last N games"
    definition qb_trailing_form and props.prop_over_probability already use, so a
    displayed average and any probability built from it always agree.

    Pass _cache (a plain dict, scoped to one team_form_snapshot call) when the same
    team_hist/n_games is shared across several lookups in that call - a team's combined
    RB/WR/TE leaderboard and its own position-specific leader routinely land on the same
    player (e.g. the lead back is almost always in both), so without this the identical
    stat line gets recomputed for them twice."""
    if _cache is not None:
        key = (player_name, position)
        if key in _cache:
            return _cache[key]

    rows = team_hist[team_hist["player_name"] == player_name].sort_values(["season", "week"]).tail(n_games)
    yards = rows[["rushing_yards", "receiving_yards"]].fillna(0).sum(axis=1)
    tds = rows[["rushing_tds", "receiving_tds"]].fillna(0).sum(axis=1)
    result = {
        "player_name": player_name,
        "position": position,
        "games": len(rows),
        "yards_per_game": round(float(yards.mean()), 1) if len(rows) else 0.0,
        "tds_per_game": round(float(tds.mean()), 2) if len(rows) else 0.0,
        "carries_per_game": round(float(rows["carries"].mean()), 1) if len(rows) else 0.0,
        "rushing_yards_per_game": round(float(rows["rushing_yards"].mean()), 1) if len(rows) else 0.0,
        "receptions_per_game": round(float(rows["receptions"].mean()), 1) if len(rows) else 0.0,
        "targets_per_game": round(float(rows["targets"].mean()), 1) if len(rows) else 0.0,
        "receiving_yards_per_game": round(float(rows["receiving_yards"].mean()), 1) if len(rows) else 0.0,
    }
    if _cache is not None:
        _cache[(player_name, position)] = result
    return result


def _skill_leaders_from(
    team_hist: pd.DataFrame,
    positions: tuple[str, ...],
    n_games: int = 5,
    top_n: int = 2,
    pos_hist: pd.DataFrame | None = None,
    _cache: dict | None = None,
) -> list[dict]:
    """Combined RB/WR/TE leaderboard by trailing yards, for the general "top skill
    players" display only - see _leader_for_position() for identifying the specific
    featured player at one position, which uses whichever stat actually predicts that
    position's real-game leader best (yards and targets aren't comparable in magnitude
    across positions, so this combined ranking is just a production summary, not a
    per-position "who's featured" signal).

    Pass pos_hist (team_hist already filtered to position in `positions`) when the caller
    has already computed it, e.g. team_form_snapshot sharing it with _leader_for_position
    instead of each re-scanning the full team history separately."""
    if pos_hist is None:
        pos_hist = team_hist[team_hist["position"].isin(positions)]
    if pos_hist.empty:
        return []

    # Rank candidates over a shared recent-weeks window so multiple players are compared
    # across the same stretch of time (otherwise a "leader" could be crowned using games
    # from a very different period than the player they're being compared against).
    recent_seasons_weeks = pos_hist[["season", "week"]].drop_duplicates().sort_values(["season", "week"]).tail(n_games)
    recent = pos_hist.merge(recent_seasons_weeks, on=["season", "week"])
    recent = recent.copy()
    recent["yards"] = recent[["rushing_yards", "receiving_yards"]].fillna(0).sum(axis=1)

    ranked = (
        recent.groupby(["player_name", "position"])["yards"]
        .mean()
        .reset_index()
        .sort_values("yards", ascending=False)
        .head(top_n)
    )
    # Once we know who the leader(s) are, report each one's own trailing stats rather
    # than the shared-window numbers used only to rank them.
    return [
        _player_trailing_skill_stats(team_hist, r.player_name, r.position, n_games, _cache=_cache)
        for r in ranked.itertuples()
    ]


# Which trailing stat best predicts a position's REAL game leader, per a live-tracking
# investigation checked against ~2,400 real historical games (see README): RB by
# trailing yards (a real rushing role is yards-driven - yards clearly wins there,
# 62% vs ~50% for targets/receptions). WR and TE by trailing TARGETS instead of
# yards - receiving yardage is heavily skewed by big plays and game script, while
# targets reflect a more stable "is the offense built around this player" signal,
# and out-predicts yards for these two positions on held-out data (WR: 42.6% -> 45.6%,
# TE: 60.6% -> 63.7%). Modest gains, not a solved problem - WR especially remains hard
# to call - but real and replicated on data never touched during the comparison.
_LEADER_RANK_STAT = {"RB": "yards", "WR": "targets", "TE": "targets"}


def _leader_for_position(
    team_hist: pd.DataFrame,
    position: str,
    n_games: int = 5,
    pos_hist: pd.DataFrame | None = None,
    _cache: dict | None = None,
) -> dict | None:
    """The single most-featured player at one position, ranked by whichever trailing
    stat best predicts who actually leads that position in a real game (see
    _LEADER_RANK_STAT) - this is what drives the RB/WR/TE prop probabilities and the
    "featured player" display, so it uses the validated-best signal per position,
    unlike _skill_leaders_from's combined display-only ranking.

    Pass pos_hist (team_hist already filtered to RB/WR/TE) to skip a second full scan of
    the team history - see _skill_leaders_from's docstring. It gets filtered down to just
    this one position first, which is identical to filtering team_hist directly since
    pos_hist is already a superset of this position's rows."""
    pos_hist = pos_hist if pos_hist is not None else team_hist
    pos_hist = pos_hist[pos_hist["position"] == position]
    if pos_hist.empty:
        return None

    recent_weeks = pos_hist[["season", "week"]].drop_duplicates().sort_values(["season", "week"]).tail(n_games)
    recent = pos_hist.merge(recent_weeks, on=["season", "week"])
    recent = recent.copy()

    rank_stat = _LEADER_RANK_STAT.get(position, "yards")
    if rank_stat == "yards":
        recent["rank_value"] = recent[["rushing_yards", "receiving_yards"]].fillna(0).sum(axis=1)
    else:
        recent["rank_value"] = recent[rank_stat].fillna(0)

    ranked = recent.groupby("player_name")["rank_value"].mean().sort_values(ascending=False)
    if ranked.empty:
        return None
    return _player_trailing_skill_stats(team_hist, ranked.index[0], position, n_games, _cache=_cache)


def top_skill_players(
    weekly: pd.DataFrame,
    team: str,
    season: int,
    week: int,
    positions: tuple[str, ...] = ("RB", "WR", "TE"),
    n_games: int = 5,
    top_n: int = 2,
) -> list[dict]:
    """Trailing yards/game for the team's most-used skill-position players."""
    team_hist = _before(weekly, season, week)
    team_hist = team_hist[team_hist["recent_team"] == team]
    return _skill_leaders_from(team_hist, positions, n_games, top_n)


def team_form_snapshot(hist: pd.DataFrame, team: str, n_games: int = 5) -> dict:
    """QB trailing form plus RB/WR/TE leaders for one team, computed from a single
    team-filtered slice instead of the 5 separate full-dataframe scans that calling
    qb_trailing_form + top_skill_players independently would each repeat.

    Pass an already before_cutoff()-filtered `hist`, so a caller scoring many teams for
    the same season/week (e.g. a full week's slate) pays that filter's cost once instead
    of once per lookup per team - this is the difference between a whole week's report
    scanning the full history ~160 times versus twice (once per game side, already
    filtered by team) per team all season.
    """
    team_hist = hist[hist["recent_team"] == team]
    qb_hist = team_hist[team_hist["position"] == "QB"]
    qb = _starting_qb_from(team_hist, n_games, qb_hist=qb_hist)
    skill_pos_hist = team_hist[team_hist["position"].isin(("RB", "WR", "TE"))]
    # scoped to this one call - a team's combined-yards leaderboard and its per-position
    # leader (e.g. the lead back) routinely land on the same player; see
    # _player_trailing_skill_stats's docstring
    skill_stats_cache: dict = {}

    return {
        "qb": _qb_form_from(team_hist, qb, n_games, qb_hist=qb_hist),
        "skill": _skill_leaders_from(
            team_hist, ("RB", "WR", "TE"), n_games, top_n=2, pos_hist=skill_pos_hist, _cache=skill_stats_cache
        ),
        "rb": _leader_for_position(team_hist, "RB", n_games, pos_hist=skill_pos_hist, _cache=skill_stats_cache),
        "wr": _leader_for_position(team_hist, "WR", n_games, pos_hist=skill_pos_hist, _cache=skill_stats_cache),
        "te": _leader_for_position(team_hist, "TE", n_games, pos_hist=skill_pos_hist, _cache=skill_stats_cache),
    }


_NAME_SUFFIXES = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}

_RECENT_FORM_COLUMNS = [
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
]


def espn_name_to_nflverse(display_name: str) -> str:
    """Best-effort conversion of an ESPN full display name to nflverse's 'F.Last' format.

    E.g. "Josh Allen" -> "J.Allen", "Amon-Ra St. Brown" -> "A.St. Brown". Suffixes like
    Jr./III are dropped since nflverse doesn't include them. Not guaranteed to match for
    every player (nicknames, hyphenation edge cases) - callers should handle a miss.
    """
    tokens = display_name.split()
    if not tokens:
        return display_name
    first_initial = tokens[0][0]
    rest = [t for t in tokens[1:] if t.lower().strip(".") not in _NAME_SUFFIXES]
    return f"{first_initial}.{' '.join(rest)}"


def recent_form_for_player(
    weekly: pd.DataFrame, player_name: str, team: str, season: int, week: int, n_games: int = 5
) -> dict | None:
    """Trailing-N-game averages for any player (any position), by nflverse-style name."""
    hist = _before(weekly, season, week)
    rows = hist[(hist["recent_team"] == team) & (hist["player_name"] == player_name)]
    rows = rows.sort_values(["season", "week"]).tail(n_games)
    if rows.empty:
        return None

    available_cols = [c for c in _RECENT_FORM_COLUMNS if c in rows.columns]
    means = rows[available_cols].mean()
    return {
        "games": len(rows),
        "position": rows["position"].iloc[-1],
        **{c: round(float(means[c]), 1) for c in available_cols},
    }
