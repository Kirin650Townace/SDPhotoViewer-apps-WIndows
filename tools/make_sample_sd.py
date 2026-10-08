"""動作確認用の「サンプル SD カード」を作るスクリプト.

DCIM フォルダ構成・JPEG / HEIC（キヤノンの HIF）・Exif（撮影日時・機種・
レンズ・露出・位置情報など）付きのダミー写真を生成する。

使い方:
    python tools/make_sample_sd.py             # ./sample_sd に作成
    python tools/make_sample_sd.py --count 60 --out D:/sample_sd
"""

from __future__ import annotations

import argparse
import datetime as _dt
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

try:  # HEIF（HIF）で保存できるようにする
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # noqa: BLE001
    pass
from PIL.ExifTags import Base as B
from PIL.ExifTags import GPS as G
from PIL.ExifTags import IFD
from PIL.TiffImagePlugin import IFDRational

# ---- カメラ構成（2台体制の SD カードを再現） ----
BODIES = [
    {
        "make": "Canon",
        "model": "Canon EOS R6",
        "serial": "032021000123",
        "firmware": "Firmware 1.8.1",
        "lenses": ["RF24-70mm F2.8 L IS USM", "RF70-200mm F2.8 L IS USM", "RF35mm F1.8 MACRO IS STM"],
        "files": [(1, 24, 70), (70, 200, 200), (35, 35, 35)],
    },
    {
        "make": "Canon",
        "model": "Canon EOS R5",
        "serial": "062122000456",
        "firmware": "Firmware 1.9.0",
        "lenses": ["RF15-35mm F2.8 L IS USM"],
        "files": [(15, 35, 24)],
    },
]

# ---- 場所（高松を中心に数か所） ----
PLACES = [
    ("高松市", 34.3428, 134.0466),
    ("高松港", 34.3521, 134.0497),
    ("屋島", 34.3586, 134.1024),
    ("栗林公園", 34.3297, 134.0448),
    ("東京", 35.6812, 139.7671),
]

PALETTES = [
    {"name": "sunset", "sky": [(28, 42, 92), (255, 138, 92)], "sun": (255, 214, 140), "mount": (40, 32, 56), "water": (60, 48, 74)},
    {"name": "day", "sky": [(58, 130, 214), (186, 226, 250)], "sun": (255, 250, 214), "mount": (68, 92, 78), "water": (54, 110, 156)},
    {"name": "morning", "sky": [(255, 176, 140), (255, 232, 196)], "sun": (255, 246, 214), "mount": (92, 78, 84), "water": (170, 150, 150)},
    {"name": "night", "sky": [(8, 10, 34), (30, 40, 84)], "sun": (238, 240, 220), "mount": (16, 18, 32), "water": (14, 18, 40)},
    {"name": "cloudy", "sky": [(146, 152, 162), (216, 220, 226)], "sun": (236, 238, 240), "mount": (94, 100, 108), "water": (128, 134, 142)},
]

ASPECTS = [(3, 2), (3, 2), (3, 2), (2, 3), (16, 9), (4, 3), (1, 1)]


def lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def make_scene(width: int, height: int, palette: dict, rng: random.Random) -> Image.Image:
    """それらしい風景写真を作る（グラデーション + 太陽 + 山 + 水面）。"""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img, "RGBA")
    top, bottom = palette["sky"]
    horizon = int(height * rng.uniform(0.52, 0.66))

    # 空のグラデーション
    for y in range(horizon):
        t = y / max(1, horizon - 1)
        color = (lerp(top[0], bottom[0], t), lerp(top[1], bottom[1], t), lerp(top[2], bottom[2], t))
        draw.line([(0, y), (width, y)], fill=color)

    # 星（夜）
    if palette["name"] == "night":
        for _ in range(140):
            x, y = rng.randrange(width), rng.randrange(int(horizon * 0.8))
            r = rng.uniform(0.6, 1.6)
            a = rng.randint(120, 255)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, a))

    # 太陽 / 月とその光
    sun_x = int(width * rng.uniform(0.15, 0.85))
    sun_y = int(horizon * rng.uniform(0.25, 0.62))
    sun_r = int(min(width, height) * rng.uniform(0.045, 0.085))
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for i in range(6, 0, -1):
        rr = sun_r * (1 + i * 0.5)
        alpha = int(26 / i * 2)
        gdraw.ellipse([sun_x - rr, sun_y - rr, sun_x + rr, sun_y + rr], fill=(*palette["sun"], alpha))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    draw.ellipse([sun_x - sun_r, sun_y - sun_r, sun_x + sun_r, sun_y + sun_r], fill=palette["sun"])

    # 雲
    for _ in range(rng.randint(2, 6)):
        cx, cy = rng.randrange(width), rng.randrange(int(horizon * 0.7))
        cw = rng.randint(int(width * 0.1), int(width * 0.35))
        ch = rng.randint(int(height * 0.02), int(height * 0.06))
        alpha = rng.randint(30, 90)
        base = (255, 255, 255, alpha) if palette["name"] != "night" else (200, 210, 255, alpha)
        for k in range(rng.randint(3, 6)):
            draw.ellipse(
                [cx + k * cw * 0.28 - cw * 0.2, cy + rng.randint(-ch // 2, ch // 2), cx + k * cw * 0.28 + cw * 0.6, cy + ch],
                fill=base,
            )

    # 山（奥から手前へ）
    mount_top, mount_bottom = palette["mount"], tuple(max(0, c - 22) for c in palette["mount"])
    layers = rng.randint(2, 3)
    for layer in range(layers):
        depth = (layer + 1) / (layers + 0.4)
        base_y = horizon + int(height * 0.02 * layer)
        color = tuple(int(mount_top[i] + (mount_bottom[i] - mount_top[i]) * depth) for i in range(3))
        points = [(0, base_y + rng.randint(-10, 10))]
        x = 0
        while x < width:
            step = rng.randint(int(width * 0.12), int(width * 0.3))
            peak = base_y - rng.randint(int(height * 0.04), int(height * (0.16 + 0.05 * layer)))
            points.append((x + step // 2, peak))
            points.append((x + step, base_y + rng.randint(-8, 8)))
            x += step
        points.append((width, horizon + height))
        points.append((0, horizon + height))
        draw.polygon(points, fill=color)

    # 水面
    water_top = horizon + int(height * 0.06)
    for y in range(water_top, height):
        t = (y - water_top) / max(1, height - water_top)
        color = tuple(int(palette["water"][i] * (1 - t * 0.35)) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    # 反射のきらめき
    for _ in range(rng.randint(12, 26)):
        y = rng.randint(water_top, height - 1)
        w = rng.randint(int(width * 0.03), int(width * 0.2))
        x = max(0, sun_x - w // 2 + rng.randint(-60, 60))
        alpha = rng.randint(20, 70)
        draw.line([(x, y), (min(width, x + w), y)], fill=(*palette["sun"], alpha))

    # 手前の草 / 岩
    if rng.random() < 0.6:
        ground_y = int(height * rng.uniform(0.86, 0.95))
        draw.polygon(
            [(0, height), (0, ground_y), (int(width * 0.3), ground_y - rng.randint(4, 18)), (int(width * 0.65), ground_y + 6), (width, ground_y - 10), (width, height)],
            fill=tuple(max(0, c - 30) for c in palette["mount"]),
        )

    # ビネット + 粒子（写真らしさ）
    vignette = Image.new("L", (width, height), 0)
    vdraw = ImageDraw.Draw(vignette)
    vdraw.ellipse([-width * 0.25, -height * 0.25, width * 1.25, height * 1.25], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(min(width, height) * 0.12))
    img = Image.composite(img, Image.new("RGB", (width, height), (0, 0, 0)), vignette)

    noise = Image.effect_noise((width, height), 8).convert("L")
    img = Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.035)
    return img


def build_exif(rng: random.Random, body: dict, lens: str, focal: float, dt: _dt.datetime, place, exposure: dict) -> Image.Exif:
    exif = Image.Exif()
    exif[B.Make] = body["make"]
    exif[B.Model] = body["model"]
    exif[B.Software] = body["firmware"]
    exif[B.Orientation] = 1
    exif[B.DateTime] = dt.strftime("%Y:%m:%d %H:%M:%S")
    exif[B.Artist] = ""

    sub = exif.get_ifd(IFD.Exif)
    sub[B.DateTimeOriginal] = dt.strftime("%Y:%m:%d %H:%M:%S")
    sub[B.DateTimeDigitized] = dt.strftime("%Y:%m:%d %H:%M:%S")
    sub[B.ExposureTime] = (exposure["shutter_num"], exposure["shutter_den"])
    sub[B.FNumber] = (int(round(exposure["f"] * 10)), 10)
    sub[B.ISOSpeedRatings] = exposure["iso"]
    sub[B.FocalLength] = (int(round(focal * 10)), 10)
    sub[B.FocalLengthIn35mmFilm] = int(round(focal * (1.0 if body["model"].endswith(("R5", "R6")) else 1.5)))
    sub[B.LensModel] = lens
    sub[B.LensMake] = body["make"]
    sub[B.ExposureBiasValue] = (exposure["bias10"], 10)
    sub[B.ExposureProgram] = exposure["program"]
    sub[B.MeteringMode] = 5
    sub[B.Flash] = exposure["flash"]
    sub[B.WhiteBalance] = 0
    sub[B.ExposureMode] = 0
    sub[B.SceneCaptureType] = 0
    sub[B.ColorSpace] = 1
    sub[B.BodySerialNumber] = body["serial"]
    sub[B.ApertureValue] = (int(round(exposure["f"] * 10)), 10)
    sub[B.ShutterSpeedValue] = (int(round(math.log2(max(1e-6, exposure["shutter_num"] / exposure["shutter_den"])) * -10)), 10)
    sub[B.MaxApertureValue] = (28, 10)

    if place is not None:
        lat = place[1] + rng.uniform(-0.004, 0.004)
        lon = place[2] + rng.uniform(-0.004, 0.004)
        gps = exif.get_ifd(IFD.GPSInfo)
        gps[G.GPSVersionID] = b"\x02\x03\x00\x00"
        gps[G.GPSLatitudeRef] = "N" if lat >= 0 else "S"
        gps[G.GPSLatitude] = _deg_to_rational(abs(lat))
        gps[G.GPSLongitudeRef] = "E" if lon >= 0 else "W"
        gps[G.GPSLongitude] = _deg_to_rational(abs(lon))
        gps[G.GPSAltitudeRef] = 0
        gps[G.GPSAltitude] = IFDRational(int(rng.uniform(3, 90) * 10), 10)
    return exif


def _deg_to_rational(value: float):
    deg = int(value)
    minutes_float = (value - deg) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    return (IFDRational(deg, 1), IFDRational(minutes, 1), IFDRational(int(round(seconds * 1000)), 1000))


def random_exposure(rng: random.Random) -> dict:
    shutter = rng.choice([(1, 60), (1, 125), (1, 250), (1, 400), (1, 500), (1, 1000), (1, 2000), (1, 30)])
    return {
        "shutter_num": shutter[0],
        "shutter_den": shutter[1],
        "f": rng.choice([1.8, 2.8, 2.8, 4.0, 5.6, 8.0, 11.0]),
        "iso": rng.choice([100, 200, 200, 400, 400, 800, 1600, 3200, 6400]),
        "bias10": rng.choice([0, 0, 0, 3, -3, 7, -7, 10]),
        "program": rng.choice([3, 3, 3, 4, 1]),
        "flash": 16 if rng.random() < 0.08 else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="サンプル SD カードを生成する")
    parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_sd"))
    parser.add_argument("--count", type=int, default=42)
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument("--long-edge", type=int, default=1600)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    out = os.path.abspath(args.out)
    folders = ["DCIM/100CANON", "DCIM/101CANON", "DCIM/102CANON"]
    for folder in folders:
        os.makedirs(os.path.join(out, folder), exist_ok=True)

    start = _dt.datetime(2026, 9, 12, 7, 40, 0)
    current = start
    counters = {folder: 1 for folder in folders}
    heic_counter = 1

    for i in range(args.count):
        folder = folders[i % len(folders)]
        body = BODIES[0] if rng.random() < 0.68 else BODIES[1]
        lens_index = rng.randrange(len(body["lenses"]))
        lens = body["lenses"][lens_index]
        focal = rng.uniform(*body["files"][min(lens_index, len(body["files"]) - 1)][:2])
        current += _dt.timedelta(minutes=rng.randint(1, 55))
        place = rng.choice(PLACES) if rng.random() < 0.45 else None
        palette = PALETTES[i % len(PALETTES)] if rng.random() < 0.7 else rng.choice(PALETTES)
        exposure = random_exposure(rng)

        aspect_w, aspect_h = rng.choice(ASPECTS)
        long_edge = args.long_edge
        if aspect_w >= aspect_h:
            width = long_edge
            height = int(long_edge * aspect_h / aspect_w)
        else:
            height = long_edge
            width = int(long_edge * aspect_w / aspect_h)

        image = make_scene(width, height, palette, rng)
        exif = build_exif(rng, body, lens, focal, current, place, exposure)

        is_heif = body["model"].endswith("R5") and rng.random() < 0.7
        if is_heif:
            name = f"IMG_{5000 + heic_counter:04d}.HIF"
            heic_counter += 1
            path = os.path.join(out, folder, name)
            try:
                image.save(path, "HEIF", exif=exif, quality=88)
            except Exception as exc:  # noqa: BLE001
                print(f"[!] HEIF を保存できないため JPEG にします: {exc}")
                path = os.path.join(out, folder, name.replace(".HIF", ".JPG"))
                image.save(path, "JPEG", exif=exif, quality=88, subsampling=1)
        else:
            name = f"IMG_{counters[folder]:04d}.JPG"
            path = os.path.join(out, folder, name)
            image.save(path, "JPEG", exif=exif, quality=88, subsampling=1)
            counters[folder] += 1
        # ファイルの更新時刻も撮影日時に合わせる
        stamp = current.timestamp()
        os.utime(path, (stamp, stamp))

    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _dn, fn in os.walk(out) for f in fn)
    print(f"作成しました: {out}")
    print(f"  写真 {args.count} 枚 / {total / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
