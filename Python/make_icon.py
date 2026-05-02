"""
Redraw the SVG-style icon (icon_2_particles) with Pillow and generate Scent.ico.
Run: py make_icon.py (from the Python/ folder)
"""

from PIL import Image, ImageDraw
from pathlib import Path

# ---- Icon data (256px coordinate system) ----
PARTICLES = [
    (95,  165, 14, "#ff5e78"),
    (160, 162, 13, "#00c9a7"),
    (128, 148, 11, "#845ef7"),
    (72,  128, 12, "#ff5e78"),
    (150, 120, 10, "#ffb800"),
    (55,  100,  8, "#845ef7"),
    (130,  92, 10, "#00c9a7"),
    (192,  86,  8, "#ff5e78"),
    (46,   65,  7, "#ffb800"),
    (175,  58,  7, "#00c9a7"),
]


def render(size: int) -> Image.Image:
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background (rounded corners)
    bg_r = max(1, int(48 * s))
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=bg_r, fill="#fff8f0")

    # Chip (rounded rectangle)
    chip_r = max(1, int(14 * s))
    draw.rounded_rectangle(
        [int(88 * s), int(188 * s), int(168 * s), int(234 * s)],
        radius=chip_r,
        fill="#ffb800",
    )

    # Particles
    for cx, cy, r, color in PARTICLES:
        cx_s = int(cx * s)
        cy_s = int(cy * s)
        r_s = max(1, int(r * s))
        draw.ellipse([cx_s - r_s, cy_s - r_s, cx_s + r_s, cy_s + r_s], fill=color)

    return img


def main():
    sizes = [256, 128, 64, 48, 32, 16]
    images = [render(sz) for sz in sizes]

    out = Path(__file__).parent / "Scent.ico"
    images[0].save(
        out,
        format="ICO",
        append_images=images[1:],
        sizes=[(sz, sz) for sz in sizes],
    )
    print(f"Created: {out}")


if __name__ == "__main__":
    main()
