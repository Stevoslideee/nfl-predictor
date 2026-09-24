"""Official NFL team brand colors and logo URLs, for anywhere the UI shows two teams
side by side (the win-probability bar, the field diagram) and a generic color pair
would be less recognizable than each team's own.

Colors are each team's primary brand color - public, stable facts, not fetched from
anywhere (one less network dependency, same reasoning as weather.py's hardcoded
stadium coordinates).
"""

TEAM_COLORS: dict[str, str] = {
    "ARI": "#97233F", "ATL": "#A71930", "BAL": "#241773", "BUF": "#00338D",
    "CAR": "#0085CA", "CHI": "#0B162A", "CIN": "#FB4F14", "CLE": "#311D00",
    "DAL": "#003594", "DEN": "#FB4F14", "DET": "#0076B6", "GB": "#203731",
    "HOU": "#03202F", "IND": "#002C5F", "JAX": "#101820", "KC": "#E31837",
    "LA": "#003594", "LAC": "#0080C6", "LV": "#000000", "MIA": "#008E97",
    "MIN": "#4F2683", "NE": "#002244", "NO": "#D3BC8D", "NYG": "#0B2265",
    "NYJ": "#125740", "PHI": "#004C54", "PIT": "#FFB612", "SEA": "#002244",
    "SF": "#AA0000", "TB": "#D50A0A", "TEN": "#0C2340", "WAS": "#5A1414",
}

DEFAULT_COLOR = "#3B4B63"  # neutral slate, for an unrecognized abbreviation

# ESPN's logo CDN uses ESPN's own team abbreviations, which differ from nflverse's for
# these two teams (same mismatch live.py's normalize_team() already corrects the other
# direction for) - WAS -> wsh, LA -> lar. Every other team's lowercase abbreviation
# matches directly.
_ESPN_LOGO_ABBR_FIXES = {"WAS": "wsh", "LA": "lar"}


def team_color(team: str) -> str:
    """This team's primary brand color, or a neutral default for an unknown team."""
    return TEAM_COLORS.get(team, DEFAULT_COLOR)


def logo_url(team: str) -> str:
    """ESPN's hosted logo image for this team - a stable, public CDN path."""
    abbr = _ESPN_LOGO_ABBR_FIXES.get(team, team.lower())
    return f"https://a.espncdn.com/i/teamlogos/nfl/500/{abbr}.png"


def readable_text_color(hex_color: str) -> str:
    """Black or white, whichever reads better on this background - most team colors
    are dark enough for white text, but a couple (New Orleans' gold, Pittsburgh's
    yellow) are light enough that white text would fail basic contrast."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#000000" if luminance > 0.5 else "#FFFFFF"
