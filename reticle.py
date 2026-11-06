"""Reticle geometry for a transparent SVG overlay; no camera dependency."""

from html import escape

STYLES = ("crosshair", "mil-dot", "german-4", "dot", "ring")


def render_reticle(style="crosshair", color="#f3b23f", brightness=80, cx=640, cy=360):
    if style not in STYLES:
        raise ValueError(f"Unknown reticle style: {style}")
    if not isinstance(color, str) or len(color) != 7 or color[0] != "#" or any(
        ch not in "0123456789abcdefABCDEF" for ch in color[1:]
    ):
        raise ValueError("Reticle color must be a six-digit hex color")
    if not isinstance(brightness, (int, float)) or not 10 <= brightness <= 100:
        raise ValueError("Reticle brightness must be 10–100")
    parts = [f'<g stroke="{escape(color)}" fill="none" stroke-width="2" '
             f'opacity="{brightness / 100:.2f}" stroke-linecap="round">']
    if style in ("crosshair", "mil-dot", "german-4"):
        parts.append(f'<path d="M{cx-115} {cy}h230 M{cx} {cy-115}v230"/>')
        if style == "mil-dot":
            for delta in (22, 44, 66, 88):
                for x, y in ((cx-delta,cy),(cx+delta,cy),(cx,cy-delta),(cx,cy+delta)):
                    parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{escape(color)}" stroke="none"/>')
        if style == "german-4":
            parts.append(f'<path stroke-width="9" d="M{cx-115} {cy}h77 M{cx+38} {cy}h77 M{cx} {cy+38}v77"/>')
    if style == "ring":
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="42"/>')
        parts.append(f'<path d="M{cx-63} {cy}h14 M{cx+49} {cy}h14 M{cx} {cy-63}v14 M{cx} {cy+49}v14"/>')
    if style in ("dot", "ring"):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="3.5" stroke="none" fill="{escape(color)}"/>')
    parts.append("</g>")
    return "".join(parts)
