import re

import team_colors


def test_team_color_returns_known_hex():
    assert team_colors.team_color("BUF") == "#00338D"


def test_team_color_falls_back_to_default_for_unknown_team():
    assert team_colors.team_color("XYZ") == team_colors.DEFAULT_COLOR


def test_logo_url_applies_espn_abbreviation_fixes():
    # nflverse uses WAS/LA; ESPN's own CDN uses wsh/lar for these two teams
    assert team_colors.logo_url("WAS") == "https://a.espncdn.com/i/teamlogos/nfl/500/wsh.png"
    assert team_colors.logo_url("LA") == "https://a.espncdn.com/i/teamlogos/nfl/500/lar.png"


def test_logo_url_lowercases_for_teams_without_a_fix():
    assert team_colors.logo_url("BUF") == "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png"


def test_all_32_teams_have_a_valid_hex_color():
    hex_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
    assert len(team_colors.TEAM_COLORS) == 32
    for team, color in team_colors.TEAM_COLORS.items():
        assert hex_pattern.match(color), f"{team} has an invalid color: {color}"


def test_readable_text_color_picks_black_on_light_backgrounds():
    # New Orleans' gold and Pittsburgh's yellow are light enough that white text
    # would fail basic contrast - this is the regression this function guards against
    assert team_colors.readable_text_color(team_colors.TEAM_COLORS["NO"]) == "#000000"
    assert team_colors.readable_text_color(team_colors.TEAM_COLORS["PIT"]) == "#000000"


def test_readable_text_color_picks_white_on_dark_backgrounds():
    assert team_colors.readable_text_color(team_colors.TEAM_COLORS["LV"]) == "#FFFFFF"
    assert team_colors.readable_text_color(team_colors.TEAM_COLORS["BUF"]) == "#FFFFFF"
