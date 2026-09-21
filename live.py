"""Live and recent NFL game data from ESPN's public scoreboard/summary feeds.

No API key required. Scores and box scores update in real time while a game
is in progress, and the same endpoints return the final box score once a
game ends - so this covers both "what's happening right now" and "what just
happened," complementing the multi-season historical data in data.py.
"""

import requests

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"

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
        resp = requests.get(SCOREBOARD_URL, params=params, timeout=15)
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
        resp = requests.get(SUMMARY_URL, params={"event": game_id}, timeout=15)
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
