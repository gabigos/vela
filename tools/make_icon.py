"""Generate the Vela application icon (assets/app.ico and app.png).

Run from the repository root:

    .venv\\Scripts\\python.exe tools\\make_icon.py

The icon mirrors the in-app logo (rounded gradient tile with a download
arrow) so the taskbar, window and executable share one identity.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)
MASTER = 1024


def _gradient(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    top = (99, 102, 241)
    bottom = (139, 92, 246)
    gradient = Image.new("RGBA", (size, size))
    pixels = gradient.load()
    for y in range(size):
        t = y / max(1, size - 1)
        row = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(size):
            pixels[x, y] = (*row, 255)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=round(size * 0.28), fill=255
    )
    image.paste(gradient, (0, 0), mask)
    return image


def _draw_arrow(image: Image.Image) -> None:
    size = image.width
    draw = ImageDraw.Draw(image)
    width = max(2, round(size * 0.068))
    white = (255, 255, 255, 255)
    cx = size / 2
    draw.line((cx, size * 0.25, cx, size * 0.625), fill=white, width=width)
    draw.line(
        (
            size * 0.315,
            size * 0.465,
            cx,
            size * 0.645,
            size * 0.685,
            size * 0.465,
        ),
        fill=white,
        width=width,
        joint="curve",
    )
    draw.line(
        (size * 0.30, size * 0.765, size * 0.70, size * 0.765),
        fill=white,
        width=width,
    )
    radius = width / 2
    for point in (
        (cx, size * 0.25),
        (size * 0.315, size * 0.465),
        (size * 0.685, size * 0.465),
        (cx, size * 0.645),
        (size * 0.30, size * 0.765),
        (size * 0.70, size * 0.765),
    ):
        draw.ellipse(
            (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
            fill=white,
        )


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = _gradient(MASTER)
    _draw_arrow(master)
    master.save(ASSETS / "app.png")
    master.save(
        ASSETS / "app.ico",
        format="ICO",
        sizes=[(size, size) for size in SIZES],
    )
    print(f"wrote {ASSETS / 'app.ico'} and {ASSETS / 'app.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
