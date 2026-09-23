"""Renders one play's field position as an SVG diagram: ball spot, line of
scrimmage, and first-down marker on a schematic 100-yard field.

No individual player positions here - see live.get_play_by_play's docstring for
why (that data is proprietary NFL Next Gen Stats tracking, not available through
any public feed). This draws what the public play-by-play feed actually has:
down, distance, and field position.

Coordinate system matches live.get_play_by_play's abs_yard_line: 0 is the home
team's own goal line, 100 is the away team's own goal line, regardless of who
has the ball, so a fixed field diagram doesn't need to flip sides play to play.
"""

FIELD_LEFT = 100.0  # px, x-coordinate of the home team's own goal line
FIELD_RIGHT = 1100.0  # px, x-coordinate of the away team's own goal line
FIELD_TOP = 50.0
FIELD_BOTTOM = 450.0
PX_PER_YARD = (FIELD_RIGHT - FIELD_LEFT) / 100.0


def _x(abs_yard_line: float) -> float:
    return FIELD_LEFT + abs_yard_line * PX_PER_YARD


def render_field_svg(play: dict, home_team: str, away_team: str) -> str:
    """An SVG field diagram for one play dict (see live.get_play_by_play's shape).
    Falls back to a bare field (no ball/markers) if the play has no usable field
    position - a kickoff or the pre-snap moment before the first play sometimes
    lacks one."""
    yard_lines = "".join(
        f'<line x1="{FIELD_LEFT + y * PX_PER_YARD:.0f}" y1="{FIELD_TOP:.0f}" '
        f'x2="{FIELD_LEFT + y * PX_PER_YARD:.0f}" y2="{FIELD_BOTTOM:.0f}" '
        f'stroke="white" stroke-opacity="0.5" stroke-width="2"/>'
        for y in range(10, 100, 10)
    )
    yard_numbers = "".join(
        f'<text x="{FIELD_LEFT + y * PX_PER_YARD:.0f}" y="{FIELD_TOP - 12:.0f}" '
        f'fill="white" fill-opacity="0.7" font-size="20" text-anchor="middle">'
        f"{y if y <= 50 else 100 - y}</text>"
        for y in range(10, 100, 10)
    )

    markers = ""
    caption = ""
    abs_yard_line = play.get("abs_yard_line")
    possession = play.get("possession")
    if abs_yard_line is not None and possession is not None:
        ball_x = _x(abs_yard_line)
        distance = play.get("distance") or 0
        direction = 1 if possession == home_team else -1
        first_down_x = max(FIELD_LEFT, min(FIELD_RIGHT, ball_x + direction * distance * PX_PER_YARD))

        markers += (
            f'<line x1="{ball_x:.0f}" y1="{FIELD_TOP:.0f}" x2="{ball_x:.0f}" y2="{FIELD_BOTTOM:.0f}" '
            f'stroke="#4da3ff" stroke-width="3"/>'
        )
        if play.get("down"):
            markers += (
                f'<line x1="{first_down_x:.0f}" y1="{FIELD_TOP:.0f}" x2="{first_down_x:.0f}" y2="{FIELD_BOTTOM:.0f}" '
                f'stroke="#ffcc00" stroke-width="3" stroke-dasharray="8,6"/>'
            )
        markers += f'<ellipse cx="{ball_x:.0f}" cy="{(FIELD_TOP+FIELD_BOTTOM)/2:.0f}" rx="12" ry="7" fill="#7b4a24" stroke="white" stroke-width="1.5"/>'

        down_word = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(play.get("down"), "")
        if down_word:
            caption = f"{possession} ball, {down_word} & {distance}"
        else:
            caption = f"{possession} ball"

    home_label = home_team or "HOME"
    away_label = away_team or "AWAY"

    svg = f"""
<svg viewBox="0 0 1200 500" xmlns="http://www.w3.org/2000/svg" style="width:100%; height:auto; background:#0b3d0b;">
  <rect x="{FIELD_LEFT:.0f}" y="{FIELD_TOP:.0f}" width="{FIELD_RIGHT-FIELD_LEFT:.0f}" height="{FIELD_BOTTOM-FIELD_TOP:.0f}" fill="#0f5c0f"/>
  <rect x="0" y="{FIELD_TOP:.0f}" width="{FIELD_LEFT:.0f}" height="{FIELD_BOTTOM-FIELD_TOP:.0f}" fill="#123a6b"/>
  <rect x="{FIELD_RIGHT:.0f}" y="{FIELD_TOP:.0f}" width="{1200-FIELD_RIGHT:.0f}" height="{FIELD_BOTTOM-FIELD_TOP:.0f}" fill="#6b1212"/>
  <text x="{FIELD_LEFT/2:.0f}" y="{(FIELD_TOP+FIELD_BOTTOM)/2:.0f}" fill="white" font-size="28" font-weight="bold"
        text-anchor="middle" transform="rotate(-90 {FIELD_LEFT/2:.0f} {(FIELD_TOP+FIELD_BOTTOM)/2:.0f})">{home_label}</text>
  <text x="{(FIELD_RIGHT+1200)/2:.0f}" y="{(FIELD_TOP+FIELD_BOTTOM)/2:.0f}" fill="white" font-size="28" font-weight="bold"
        text-anchor="middle" transform="rotate(90 {(FIELD_RIGHT+1200)/2:.0f} {(FIELD_TOP+FIELD_BOTTOM)/2:.0f})">{away_label}</text>
  {yard_lines}
  {yard_numbers}
  <rect x="{FIELD_LEFT:.0f}" y="{FIELD_TOP:.0f}" width="{FIELD_RIGHT-FIELD_LEFT:.0f}" height="{FIELD_BOTTOM-FIELD_TOP:.0f}" fill="none" stroke="white" stroke-width="2"/>
  {markers}
</svg>
"""
    return svg, caption
