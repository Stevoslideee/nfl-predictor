"""Live and recent NFL game data from ESPN's public scoreboard/summary feeds.

No API key required. Scores and box scores update in real time while a game
is in progress, and the same endpoints return the final box score once a
game ends - so this covers both "what's happening right now" and "what just
happened," complementing the multi-season historical data in data.py.
"""

from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"

# A bare requests.get() builds a brand-new connection pool (and re-parses the OS
# certificate trust store) on every single call - measured at ~0.4-1.4s of pure
# overhead per call on this machine, independent of network latency. A shared Session
# reuses the pool and keeps the connection alive, so every call after the first one to
# the same host drops to ~0.02s (same pattern data.py already uses for nflverse).
_session = requests.Session()

TEAM_ABBR_FIXES = {"WSH": "WAS", "JAX": "JAX", "LAR": "LA"}  # ESPN vs nflverse abbreviation mismatches


def normalize_team(abbr: str) -> str:
    return TEAM_ABBR_FIXES.get(abbr, abbr)


_EMPTY_SCOREBOARD = {"season": None, "week": None, "games": []}


def get_scoreboard(week: int | None = None, season: int | None = None) -> dict:
    """Current games (or a specific week/season) with live or final scores and status.

    Returns {"season": int, "week": int, "games": [...]}. This is ESPN's unofficial,
    undocumented API - on any failure (network issue, rate limit, a changed response
    shape) this returns the same empty-but-well-formed structure rather than raising, so
    a hiccup here degrades to "no games found" instead of crashing the whole app (this
    is called unconditionally on every app load to pick a default season/week).
    """
    params = {}
    if week is not None:
        params["week"] = week
    if season is not None:
        params["dates"] = season
        params["seasontype"] = 2

    try:
        resp = _session.get(SCOREBOARD_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        games = []
        for event in data.get("events", []):
            comp = event["competitions"][0]
            status = comp["status"]["type"]
            competitors = {c["homeAway"]: c for c in comp["competitors"]}
            home, away = competitors["home"], competitors["away"]
            games.append(
                {
                    "game_id": event["id"],
                    "status": status["description"],
                    "is_live": status["state"] == "in",
                    "period": comp["status"].get("period"),
                    "clock": comp["status"].get("displayClock"),
                    "home_team": normalize_team(home["team"]["abbreviation"]),
                    "away_team": normalize_team(away["team"]["abbreviation"]),
                    "home_score": home.get("score"),
                    "away_score": away.get("score"),
                }
            )
        return {
            "season": data.get("season", {}).get("year"),
            "week": data.get("week", {}).get("number"),
            "games": games,
        }
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return dict(_EMPTY_SCOREBOARD)


def get_boxscore(game_id: str) -> dict[str, list[dict]]:
    """Live/final player box score for one game: {team_abbr: [{category, athlete, stats, labels}]}.

    Returns {} on any failure, same reasoning as get_scoreboard - a box score that can't
    be fetched should show as "no box score available," not crash the page.
    """
    try:
        resp = _session.get(SUMMARY_URL, params={"event": game_id}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        result: dict[str, list[dict]] = {}
        for team_block in data.get("boxscore", {}).get("players", []):
            team = normalize_team(team_block["team"]["abbreviation"])
            rows = []
            for category in team_block.get("statistics", []):
                labels = category.get("labels", [])
                for athlete in category.get("athletes", []):
                    rows.append(
                        {
                            "category": category["name"],
                            "player": athlete["athlete"]["displayName"],
                            "labels": labels,
                            "stats": athlete["stats"],
                        }
                    )
            result[team] = rows
        return result
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return {}


def find_game(games: list[dict], home_team: str, away_team: str) -> dict | None:
    """The full game entry for this matchup within a get_scoreboard() games list, or
    None if it's not on that scoreboard (wrong week, hasn't been scheduled with these
    exact teams, etc.) - mirrors odds.find_matchup()'s exact-pair matching. Returning
    the whole entry (not just the id) lets a caller check `status` before deciding
    whether "live" data even makes sense to use - e.g. a live injury feed reflects a
    team's CURRENT status, which is meaningless (or actively wrong) to apply to a game
    that's already final."""
    wanted = {home_team, away_team}
    for g in games:
        if {g["home_team"], g["away_team"]} == wanted:
            return g
    return None


def find_game_id(games: list[dict], home_team: str, away_team: str) -> str | None:
    """The ESPN game_id for this matchup, or None - see find_game()."""
    game = find_game(games, home_team, away_team)
    return game["game_id"] if game else None


def get_injuries(game_id: str) -> dict[str, pd.DataFrame]:
    """Live per-team injury report for one game, in the same shape as
    injuries.team_injury_report()'s output (full_name, position,
    report_primary_injury, report_status) so injuries.starting_qb_status() works
    unchanged on either source.

    This can be fresher than the cached weekly nflverse injury report - useful for a
    same-day status change that hasn't made it into the official weekly report yet, or
    into data.py's cache (which allows up to 6 hours of staleness even for the current
    season). Returns {} on any failure, same reasoning as get_boxscore.
    """
    try:
        resp = _session.get(SUMMARY_URL, params={"event": game_id}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        result: dict[str, pd.DataFrame] = {}
        for team_block in data.get("injuries", []):
            team = normalize_team(team_block["team"]["abbreviation"])
            rows = []
            for inj in team_block.get("injuries", []):
                details = inj.get("details")
                rows.append(
                    {
                        "full_name": inj["athlete"]["fullName"],
                        "position": inj["athlete"]["position"]["abbreviation"],
                        "report_primary_injury": details.get("type") if isinstance(details, dict) else None,
                        "report_status": inj["status"],
                    }
                )
            result[team] = pd.DataFrame(rows, columns=["full_name", "position", "report_primary_injury", "report_status"])
        return result
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return {}


def get_injuries_batch(game_ids: list[str]) -> dict[str, dict[str, pd.DataFrame]]:
    """get_injuries() for several games at once, fetched concurrently.

    A full week's slate is ~16 games, and each ESPN round-trip takes close to a second -
    calling get_injuries() once per game in a loop stacks up to 15+ seconds sequential
    (this is exactly what daily_update.py and the Weekly Report tab were doing, and it
    showed up as a dominant chunk of their runtime). Fetching them concurrently instead
    bounds the wait to roughly the slowest single call, same fix weather.py already uses
    for forecasts (see prefetch_forecasts).
    """
    unique_ids = list(dict.fromkeys(game_ids))
    if not unique_ids:
        return {}
    with ThreadPoolExecutor(max_workers=min(16, len(unique_ids))) as pool:
        results = pool.map(get_injuries, unique_ids)
    return dict(zip(unique_ids, results))
