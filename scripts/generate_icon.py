from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "frontend" / "assets"
SVG_PATH = ASSETS_DIR / "app-icon.svg"
PNG_PATH = ASSETS_DIR / "app-icon.png"
ICO_PATH = ASSETS_DIR / "app-icon.ico"


SVG_SOURCE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <rect x="12" y="12" width="232" height="232" rx="46" fill="#11171c" stroke="#44cdfc" stroke-width="6"/>
  <path d="M128 35 C76 50 54 150 75 203 C86 228 110 234 128 226 C146 234 170 228 181 203 C202 150 180 50 128 35 Z" fill="none" stroke="#edf6f8" stroke-width="7" stroke-linejoin="round"/>
  <path d="M128 53 C91 69 76 151 91 194 C99 214 115 219 128 212 C141 219 157 214 165 194 C180 151 165 69 128 53 Z" fill="none" stroke="#5fd7ff" stroke-width="4" stroke-linejoin="round"/>
  <path d="M128 70 L128 201" stroke="#5fd7ff" stroke-width="5" stroke-linecap="round"/>
  <g stroke="#d7e2e7" stroke-width="3" stroke-linecap="round" opacity=".78">
    <path d="M102 88 L83 111"/>
    <path d="M94 122 L76 138"/>
    <path d="M95 158 L80 171"/>
    <path d="M105 189 L91 202"/>
    <path d="M154 88 L173 111"/>
    <path d="M162 122 L180 138"/>
    <path d="M161 158 L176 171"/>
    <path d="M151 189 L165 202"/>
  </g>
  <g fill="#11171c" stroke="#ff646b" stroke-width="5">
    <circle cx="109" cy="118" r="8"/>
    <circle cx="147" cy="118" r="8"/>
    <circle cx="103" cy="151" r="8"/>
    <circle cx="153" cy="151" r="8"/>
    <circle cx="113" cy="181" r="8"/>
    <circle cx="143" cy="181" r="8"/>
  </g>
</svg>
"""


def cubic_point(p0, p1, p2, p3, t: float) -> tuple[float, float]:
    u = 1 - t
    return (
        (u ** 3) * p0[0] + 3 * (u ** 2) * t * p1[0] + 3 * u * (t ** 2) * p2[0] + (t ** 3) * p3[0],
        (u ** 3) * p0[1] + 3 * (u ** 2) * t * p1[1] + 3 * u * (t ** 2) * p2[1] + (t ** 3) * p3[1],
    )


def cubic_samples(p0, p1, p2, p3, steps: int) -> list[tuple[float, float]]:
    return [cubic_point(p0, p1, p2, p3, i / steps) for i in range(steps + 1)]


def draw_icon(size: int) -> Image.Image:
    scale = size / 256

    def xy(x: float, y: float) -> tuple[int, int]:
        return round(x * scale), round(y * scale)

    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return (*xy(x0, y0), *xy(x1, y1))

    def width(value: float) -> int:
        return max(1, round(value * scale))

    def points(values: list[tuple[float, float]]) -> list[tuple[int, int]]:
        return [xy(x, y) for x, y in values]

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        box(12, 12, 244, 244),
        radius=round(46 * scale),
        fill=(17, 23, 28, 255),
        outline=(68, 205, 252, 255),
        width=width(6),
    )

    top = (128, 35)
    bottom = (128, 226)
    outer = cubic_samples(top, (76, 50), (54, 150), bottom, 54)
    outer += cubic_samples(bottom, (202, 150), (180, 50), top, 54)[1:]
    outer.append(top)
    draw.line(points(outer), fill=(237, 246, 248, 255), width=width(7), joint="curve")

    inner_top = (128, 53)
    inner_bottom = (128, 212)
    inner = cubic_samples(inner_top, (91, 69), (76, 151), inner_bottom, 48)
    inner += cubic_samples(inner_bottom, (180, 151), (165, 69), inner_top, 48)[1:]
    inner.append(inner_top)
    draw.line(points(inner), fill=(95, 215, 255, 255), width=width(4), joint="curve")

    draw.line([xy(128, 70), xy(128, 201)], fill=(95, 215, 255, 255), width=width(5))

    slot_color = (215, 226, 231, 190)
    slots = [
        ((102, 88), (83, 111)),
        ((94, 122), (76, 138)),
        ((95, 158), (80, 171)),
        ((105, 189), (91, 202)),
    ]
    for start, end in slots:
        draw.line([xy(*start), xy(*end)], fill=slot_color, width=width(3))
        mirrored = ((256 - start[0], start[1]), (256 - end[0], end[1]))
        draw.line([xy(*mirrored[0]), xy(*mirrored[1])], fill=slot_color, width=width(3))

    for cx, cy in [(109, 118), (147, 118), (103, 151), (153, 151), (113, 181), (143, 181)]:
        draw.ellipse(box(cx - 8, cy - 8, cx + 8, cy + 8), fill=(17, 23, 28, 255), outline=(255, 100, 107, 255), width=width(5))

    return image


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    SVG_PATH.write_text(SVG_SOURCE, encoding="utf-8")

    image = draw_icon(1024)
    image.save(PNG_PATH)
    image.save(
        ICO_PATH,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    print(f"Wrote {SVG_PATH}")
    print(f"Wrote {PNG_PATH}")
    print(f"Wrote {ICO_PATH}")


if __name__ == "__main__":
    main()
