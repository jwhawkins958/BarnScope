"""Transparent HUD layer, rendered independently of Simulator/Pi frames."""

from html import escape
import math

from reticle import render_reticle
from settings import DisplaySettings

WIDTH, HEIGHT = 1280, 720
CARDINALS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def render_hud(settings: DisplaySettings, heading=None, battery=None, recording=False):
    """Generate a compositable SVG; accepts telemetry, never camera pixels."""
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
             f'viewBox="0 0 {WIDTH} {HEIGHT}">']
    ink = "#e5bd63"
    # Magnify the reticle around the aim point, not the compass or readouts.
    parts.append(f'<g transform="translate(640 360) scale({settings.zoom}) translate(-640 -360)">')
    parts.append(render_reticle(settings.reticle_style, settings.reticle_color,
                                settings.reticle_brightness))
    parts.append("</g>")
    if settings.show_compass and heading is not None and isinstance(heading, (int, float)) and math.isfinite(heading):
        heading = heading % 360
        parts.append('<g fill="none" stroke="#e5bd63" stroke-width="1">')
        parts.append('<rect x="430" y="24" width="420" height="38" fill="#090d0a" fill-opacity=".64" stroke="none"/>')
        parts.append('<path d="M430 62h420 M634 72l6-8 6 8" stroke-width="2"/>')
        for tick in range(math.ceil((heading - 90) / 15) * 15, math.floor((heading + 90) / 15) * 15 + 1, 15):
            x = 640 + (tick - heading) * 2.2
            absolute = tick % 360
            major = absolute % 45 == 0
            parts.append(f'<path d="M{x:.2f} 62v{-13 if major else -8}"/>')
            if major:
                parts.append(f'<text x="{x:.2f}" y="43" text-anchor="middle" stroke="none" '
                             f'fill="#e5bd63" font-family="monospace" font-size="14">'
                             f'{CARDINALS[absolute // 45]}</text>')
        parts.append("</g>")
    parts.append(f'<text x="44" y="685" fill="{ink}" font-family="monospace" '
                 f'font-weight="bold" font-size="16">ZOOM {settings.zoom}X</text>')
    if settings.show_battery:
        label = "BATT N/A"
        if battery is not None and isinstance(battery, (int, float)) and math.isfinite(battery) and 0 <= battery <= 100:
            label = f"BATT {round(battery)}%"
            parts.append(f'<rect x="1167" y="63" width="61" height="13" fill="none" stroke="{ink}"/>')
            parts.append(f'<rect x="1169" y="65" width="{57 * battery / 100:.1f}" height="9" fill="{ink}"/>')
        parts.append(f'<text x="1228" y="48" fill="{ink}" font-family="monospace" '
                     f'font-weight="bold" font-size="14" text-anchor="end">{escape(label)}</text>')
    if recording:
        parts.append('<circle cx="1226" cy="678" r="8" fill="#ff5147"/>')
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")
