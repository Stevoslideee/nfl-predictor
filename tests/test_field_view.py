import field_view
import team_colors


def _play(abs_yard_line, possession, down=1, distance=10):
    return {"abs_yard_line": abs_yard_line, "possession": possession, "down": down, "distance": distance}


def test_render_field_svg_includes_team_labels():
    svg, caption = field_view.render_field_svg(_play(50, "BUF"), "BUF", "DET")
    assert "BUF" in svg
    assert "DET" in svg


def test_render_field_svg_caption_describes_down_and_distance():
    _, caption = field_view.render_field_svg(_play(50, "BUF", down=3, distance=7), "BUF", "DET")
    assert caption == "BUF ball, 3rd & 7"


def test_render_field_svg_first_down_marker_moves_toward_away_endzone_for_home_possession():
    # home team (BUF) driving forward should push the first-down marker to a HIGHER
    # x-coordinate than the ball (toward the away team's goal line, at abs=100)
    svg, _ = field_view.render_field_svg(_play(50, "BUF", distance=10), "BUF", "DET")
    ball_x = field_view._x(50)
    first_down_x = field_view._x(60)
    assert f'x1="{ball_x:.0f}"' in svg
    assert f'x1="{first_down_x:.0f}"' in svg


def test_render_field_svg_first_down_marker_moves_toward_home_endzone_for_away_possession():
    # away team (DET) driving forward should push the marker to a LOWER x-coordinate
    # (toward the home team's goal line, at abs=0)
    svg, _ = field_view.render_field_svg(_play(50, "DET", distance=10), "BUF", "DET")
    first_down_x = field_view._x(40)
    assert f'x1="{first_down_x:.0f}"' in svg


def test_render_field_svg_clamps_first_down_marker_to_field_bounds():
    # deep in the red zone, "10 yards to go" would overshoot the goal line - must clamp
    svg, _ = field_view.render_field_svg(_play(95, "BUF", distance=10), "BUF", "DET")
    assert f'x1="{field_view.FIELD_RIGHT:.0f}"' in svg


def test_render_field_svg_handles_missing_field_position():
    svg, caption = field_view.render_field_svg({"abs_yard_line": None, "possession": None, "down": None, "distance": None}, "BUF", "DET")
    assert caption == ""
    assert "<svg" in svg


def test_render_field_svg_uses_each_teams_own_brand_color():
    svg, _ = field_view.render_field_svg(_play(50, "BUF"), "BUF", "DET")
    assert f'fill="{team_colors.team_color("BUF")}"' in svg
    assert f'fill="{team_colors.team_color("DET")}"' in svg


def test_render_field_svg_includes_each_teams_logo():
    svg, _ = field_view.render_field_svg(_play(50, "BUF"), "BUF", "DET")
    assert team_colors.logo_url("BUF") in svg
    assert team_colors.logo_url("DET") in svg


def test_render_field_svg_handles_unknown_team_gracefully():
    # no logo/color lookup crash for a team code not in TEAM_COLORS
    svg, _ = field_view.render_field_svg(_play(50, "BUF"), "BUF", "XYZ")
    assert team_colors.DEFAULT_COLOR in svg
