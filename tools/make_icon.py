"""アプリのアイコン（assets/app.ico / assets/app.png）を作るスクリプト.

Windows 11 のアプリタイル風に、角丸の青いタイル + 写真 + SD カードを描きます。
画像を外部から用意しなくても再生成できるようにしています。

使い方:
    python tools/make_icon.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

S = 1024          # 描画サイズ（縮小して使う）
ICON_SIZES = [16, 24, 32, 48, 64, 128, 256]

# 配色（Windows 11 のアクセントカラー系）
BG_TOP = (74, 163, 240, 255)
BG_BOTTOM = (10, 84, 158, 255)
WHITE = (255, 255, 255, 255)
SUN = (255, 190, 74, 255)
MOUNTAIN = (23, 104, 176, 255)
CARD_BLUE = (16, 92, 158, 255)


def _vertical_gradient(size: int, top, bottom) -> Image.Image:
    grad = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(1, size - 1)
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4)),
        )
    return grad


def draw_icon() -> Image.Image:
    # --- 背景（角丸タイル + グラデーション） ---
    radius = int(S * 0.225)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=radius, fill=255)

    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(_vertical_gradient(S, BG_TOP, BG_BOTTOM), (0, 0), mask)

    draw = ImageDraw.Draw(icon)

    # --- 写真カード（白い角丸） ---
    card = [int(S * 0.185), int(S * 0.205), int(S * 0.815), int(S * 0.685)]
    draw.rounded_rectangle(card, radius=int(S * 0.055), fill=WHITE)

    # カード内の絵（カードの外にはみ出さないようマスクして描く）
    inner = icon.copy()
    idraw = ImageDraw.Draw(inner)
    cx0, cy0, cx1, cy1 = card
    height = cy1 - cy0
    # 太陽
    idraw.ellipse(
        [cx0 + (cx1 - cx0) * 0.56, cy0 + height * 0.20,
         cx0 + (cx1 - cx0) * 0.78, cy0 + height * 0.42],
        fill=SUN,
    )
    # 山（2つ）
    idraw.polygon(
        [(cx0 + (cx1 - cx0) * 0.04, cy1), (cx0 + (cx1 - cx0) * 0.42, cy0 + height * 0.30),
         (cx0 + (cx1 - cx0) * 0.80, cy1)],
        fill=MOUNTAIN,
    )
    idraw.polygon(
        [(cx0 + (cx1 - cx0) * 0.46, cy1), (cx0 + (cx1 - cx0) * 0.74, cy0 + height * 0.48),
         (cx0 + (cx1 - cx0) * 1.02, cy1)],
        fill=(58, 138, 205, 255),
    )
    card_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(card_mask).rounded_rectangle(card, radius=int(S * 0.055), fill=255)
    icon.paste(inner, (0, 0), card_mask)
    draw = ImageDraw.Draw(icon)

    # --- SD カード（右下の白いバッジ・切り欠き付き） ---
    sd = [int(S * 0.575), int(S * 0.60), int(S * 0.865), int(S * 0.935)]
    notch = int(S * 0.075)
    polygon = [
        (sd[0], sd[1] + notch),
        (sd[0] + notch, sd[1]),
        (sd[2], sd[1]),
        (sd[2], sd[3]),
        (sd[0], sd[3]),
    ]
    draw.polygon(polygon, fill=WHITE)
    # 接点（青い線）
    line_top = sd[1] + int((sd[3] - sd[1]) * 0.34)
    line_bottom = line_top + int((sd[3] - sd[1]) * 0.14)
    x = sd[0] + (sd[2] - sd[0]) * 0.18
    while x < sd[2] - (sd[2] - sd[0]) * 0.12:
        draw.rounded_rectangle(
            [x, line_top, x + (sd[2] - sd[0]) * 0.075, line_bottom],
            radius=int(S * 0.006),
            fill=CARD_BLUE,
        )
        x += (sd[2] - sd[0]) * 0.145
    return icon


def main() -> int:
    os.makedirs(ASSETS, exist_ok=True)
    master = draw_icon()
    png_path = os.path.join(ASSETS, "app.png")
    master.resize((256, 256), Image.LANCZOS).save(png_path)
    print("saved:", os.path.relpath(png_path, ROOT))

    ico_path = os.path.join(ASSETS, "app.ico")
    master.resize((256, 256), Image.LANCZOS).save(ico_path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    print("saved:", os.path.relpath(ico_path, ROOT))
    print("  含まれるサイズ:", ", ".join(f"{s}x{s}" for s in ICON_SIZES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
