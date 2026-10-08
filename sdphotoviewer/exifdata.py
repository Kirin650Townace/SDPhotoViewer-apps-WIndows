"""Exif 情報の読み取りと日本語表示用の整形."""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass

from PIL import Image
from PIL.ExifTags import Base as _B
from PIL.ExifTags import GPS as _G
from PIL.ExifTags import IFD as _IFD

from . import i18n
from .compat import RAWPY_AVAILABLE

# --------------------------------------------------------------------------
# データ構造
# --------------------------------------------------------------------------


@dataclass
class ExifInfo:
    """1枚の写真から読み取った撮影情報。"""

    # ファイル
    width: int | None = None
    height: int | None = None
    file_size: int = 0
    format_name: str = ""

    # 撮影
    datetime_original: _dt.datetime | None = None
    exposure_time: float | None = None
    f_number: float | None = None
    iso: int | None = None
    focal_length: float | None = None
    focal_length_35: int | None = None
    exposure_bias: float | None = None
    exposure_program: int | None = None
    metering_mode: int | None = None
    flash: bool | None = None
    white_balance: int | None = None
    exposure_mode: int | None = None
    light_source: int | None = None
    subject_distance: float | None = None
    digital_zoom: float | None = None
    scene_capture_type: int | None = None
    color_space: int | None = None

    # カメラ / レンズ
    make: str = ""
    model: str = ""
    lens: str = ""
    lens_make: str = ""
    body_serial: str = ""
    software: str = ""
    artist: str = ""
    copyright: str = ""

    # 動画
    duration: float | None = None

    # 位置情報
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_alt: float | None = None

    raw: bool = False
    parsed: bool = False

    # ---- 表示用 ----
    @property
    def camera_name(self) -> str:
        make = (self.make or "").strip()
        model = (self.model or "").strip()
        if not model:
            return make or i18n.tr("exif.unknown")
        if make and not model.lower().startswith(make.lower()):
            return f"{make} {model}"
        return model

    @property
    def has_gps(self) -> bool:
        return self.gps_lat is not None and self.gps_lon is not None

    @property
    def datetime_text(self) -> str:
        if self.datetime_original is None:
            return ""
        return self.datetime_original.strftime("%Y/%m/%d %H:%M:%S")

    @property
    def datetime_text_short(self) -> str:
        if self.datetime_original is None:
            return ""
        return self.datetime_original.strftime("%Y/%m/%d %H:%M")

    @property
    def dimensions_text(self) -> str:
        if not self.width or not self.height:
            return ""
        mp = self.width * self.height / 1_000_000
        return f"{self.width}×{self.height}（{mp:.1f}MP）"

    @property
    def duration_text(self) -> str:
        if self.duration is None:
            return ""
        from .imaging import fmt_duration

        return fmt_duration(self.duration)

    @property
    def exposure_text(self) -> str:
        parts = []
        if self.exposure_time:
            parts.append(fmt_shutter(self.exposure_time))
        if self.f_number:
            parts.append(f"F{self.f_number:g}")
        if self.iso:
            parts.append(f"ISO{self.iso}")
        if self.focal_length:
            parts.append(f"{self.focal_length:g}mm")
        return " · ".join(parts)

    @property
    def aspect_ratio_text(self) -> str:
        if not self.width or not self.height:
            return ""
        from math import gcd

        g = gcd(self.width, self.height)
        w, h = self.width // g, self.height // g
        # 3:2 → 1.5 のような見やすい表記に丸める
        ratio = self.width / self.height
        for label, value in (("16:9", 16 / 9), ("3:2", 3 / 2), ("4:3", 4 / 3), ("1:1", 1.0), ("2:3", 2 / 3), ("3:4", 3 / 4), ("9:16", 9 / 16)):
            if abs(ratio - value) < 0.01:
                return label
        if w < 100 and h < 100:
            return f"{w}:{h}"
        if ratio >= 1:
            return f"{ratio:.2f}:1"
        return f"1:{1 / ratio:.2f}"


# --------------------------------------------------------------------------
# 読み取り
# --------------------------------------------------------------------------

_EXIF_DT_FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M", "%Y-%m-%d %H:%M")


def _tag(mapping, name: str, tag_number: int):
    """Exif タグを名前で取り出す（Pillow のバージョン差をタグ番号で吸収）。"""
    tag = getattr(_B, name, tag_number)
    try:
        return mapping.get(tag)
    except Exception:  # noqa: BLE001
        return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, (tuple, list)) and len(value) == 2:
            num, den = value
            return float(num) / float(den) if den else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _to_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        if not value:
            return None
        value = value[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "ignore").strip("\x00").strip()
        except Exception:  # noqa: BLE001
            return ""
    return str(value).strip("\x00").strip()


def _parse_datetime(value) -> _dt.datetime | None:
    text = _to_text(value)
    if not text:
        return None
    text = text.strip()
    for fmt in _EXIF_DT_FORMATS:
        try:
            return _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    # "2026:03:12 10:23:11+09:00" のような形式
    try:
        return _dt.datetime.fromisoformat(text.replace(":", "-", 2))
    except ValueError:
        return None


def _gps_decimal(values, ref) -> float | None:
    try:
        if not values:
            return None
        parts = [float(v) for v in values[:3]]
        while len(parts) < 3:
            parts.append(0.0)
        deg = parts[0] + parts[1] / 60.0 + parts[2] / 3600.0
        if str(ref).upper() in ("S", "W"):
            deg = -deg
        return deg
    except (TypeError, ValueError, IndexError):
        return None


def parse_exif(path: str, file_size: int = 0) -> ExifInfo:
    """ファイルから Exif を読み取る。失敗しても例外は投げない。"""
    info = ExifInfo(file_size=file_size or _safe_size(path))
    info.format_name = os.path.splitext(path)[1].lstrip(".").upper()
    ext = os.path.splitext(path)[1].lower()
    if ext in {".cr2", ".cr3", ".nef", ".dng", ".arw", ".orf", ".rw2", ".raf"}:
        info.raw = True

    try:
        with Image.open(path) as img:
            if not info.width or not info.height:
                info.width, info.height = img.size
            if info.format_name in ("", "JPG"):
                info.format_name = (img.format or info.format_name or "").upper()
            try:
                exif = img.getexif()
            except Exception:  # noqa: BLE001
                exif = None
            if exif:
                try:
                    _read_exif(info, exif)
                except Exception:  # noqa: BLE001
                    # 一部の項目が読めなくても、読めた分だけは表示する
                    pass
    except Exception:  # noqa: BLE001
        # Pillow で開けない RAW などは rawpy で最低限の情報だけ取得
        if info.raw and RAWPY_AVAILABLE:
            _read_raw_meta(info, path)

    info.parsed = True
    return info


def _read_exif(info: ExifInfo, exif) -> None:
    ifd0 = exif
    sub = {}
    try:
        sub = dict(exif.get_ifd(_IFD.Exif))
    except Exception:  # noqa: BLE001
        sub = {}
    merged = dict(ifd0)
    merged.update(sub)

    info.make = _to_text(ifd0.get(_B.Make))
    info.model = _to_text(ifd0.get(_B.Model))
    info.software = _to_text(ifd0.get(_B.Software))
    info.artist = _to_text(ifd0.get(_B.Artist))
    info.copyright = _to_text(ifd0.get(_B.Copyright))

    info.datetime_original = (
        _parse_datetime(merged.get(_B.DateTimeOriginal))
        or _parse_datetime(merged.get(_B.DateTimeDigitized))
        or _parse_datetime(ifd0.get(_B.DateTime))
    )
    info.exposure_time = _to_float(merged.get(_B.ExposureTime))
    info.f_number = _to_float(merged.get(_B.FNumber))
    info.iso = _to_int(merged.get(_B.ISOSpeedRatings)) or _to_int(merged.get(0x8833))  # ISO 感度
    info.focal_length = _to_float(merged.get(_B.FocalLength))
    info.focal_length_35 = _to_int(merged.get(_B.FocalLengthIn35mmFilm))
    info.exposure_bias = _to_float(merged.get(_B.ExposureBiasValue))
    info.exposure_program = _to_int(merged.get(_B.ExposureProgram))
    info.metering_mode = _to_int(merged.get(_B.MeteringMode))
    info.white_balance = _to_int(merged.get(_B.WhiteBalance))
    info.exposure_mode = _to_int(merged.get(_B.ExposureMode))
    info.light_source = _to_int(merged.get(_B.LightSource))
    info.digital_zoom = _to_float(merged.get(_B.DigitalZoomRatio))
    info.scene_capture_type = _to_int(merged.get(_B.SceneCaptureType))
    info.color_space = _to_int(merged.get(_B.ColorSpace))
    info.body_serial = _to_text(merged.get(_B.BodySerialNumber))
    info.lens = _to_text(merged.get(_B.LensModel)) or _to_text(merged.get(_B.LensSpecification))
    info.lens_make = _to_text(merged.get(_B.LensMake))

    flash = merged.get(_B.Flash)
    if flash is not None:
        try:
            info.flash = bool(int(flash) & 1)
        except (TypeError, ValueError):
            info.flash = None

    # 0xA002 / 0xA003（ExifImageWidth / ExifImageHeight）
    px = _to_int(_tag(merged, "PixelXDimension", 0xA002))
    py = _to_int(_tag(merged, "PixelYDimension", 0xA003))
    if px and py:
        info.width, info.height = px, py

    # 位置情報（読み取れなくても他の情報は活かす）
    try:
        gps = dict(exif.get_ifd(_IFD.GPSInfo))
    except Exception:  # noqa: BLE001
        gps = {}
    if gps:
        lat_ref = gps.get(_G.GPSLatitudeRef) or _tag(gps, "GPSLatitudeRef", 1)
        lon_ref = gps.get(_G.GPSLongitudeRef) or _tag(gps, "GPSLongitudeRef", 3)
        info.gps_lat = _gps_decimal(gps.get(_G.GPSLatitude) or _tag(gps, "GPSLatitude", 2), lat_ref)
        info.gps_lon = _gps_decimal(gps.get(_G.GPSLongitude) or _tag(gps, "GPSLongitude", 4), lon_ref)
        alt = _to_float(gps.get(_G.GPSAltitude) or _tag(gps, "GPSAltitude", 6))
        if alt is not None and _to_int(gps.get(_G.GPSAltitudeRef) or _tag(gps, "GPSAltitudeRef", 5)) == 1:
            alt = -alt
        info.gps_alt = alt


def _read_raw_meta(info: ExifInfo, path: str) -> None:
    try:  # pragma: no cover - 環境依存
        import rawpy

        with rawpy.imread(path) as raw:
            info.width = info.width or raw.sizes.width
            info.height = info.height or raw.sizes.height
    except Exception:  # noqa: BLE001
        pass


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


# --------------------------------------------------------------------------
# 表示用の整形
# --------------------------------------------------------------------------

_EXPOSURE_PROGRAM = {
    0: "未定義",
    1: "マニュアル",
    2: "プログラムAE",
    3: "絞り優先AE",
    4: "シャッター優先AE",
    5: "クリエイティブ",
    6: "アクション",
    7: "ポートレート",
    8: "風景",
}

_METERING = {
    0: "不明",
    1: "平均",
    2: "中央重点",
    3: "スポット",
    4: "マルチスポット",
    5: "評価測光",
    6: "部分測光",
    255: "その他",
}


def fmt_shutter(seconds: float | None) -> str:
    if not seconds:
        return ""
    if seconds >= 1:
        return f"{seconds:g}s"
    denom = round(1 / seconds)
    return f"1/{denom}s"


def fmt_size(num_bytes: int | float) -> str:
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return ""


def fmt_gps(lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        return ""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.5f}°{ns}, {abs(lon):.5f}°{ew}"


def ExposureProgramLabel(value: int | None) -> str:
    if value is None:
        return ""
    key = f"exif.program.{int(value)}"
    text = i18n.tr(key)
    if text != key:
        return text
    return i18n.tr("exif.program.other", value=value)


def metering_label(value: int | None) -> str:
    if value is None:
        return ""
    key = f"exif.metering.{int(value)}"
    text = i18n.tr(key)
    if text != key:
        return text
    return i18n.tr("exif.metering.other", value=value)


def white_balance_label(value: int | None) -> str:
    if value is None:
        return ""
    return i18n.tr(f"exif.wb.{int(value)}") if int(value) in (0, 1) else str(value)


def exposure_mode_label(value: int | None) -> str:
    if value is None:
        return ""
    return i18n.tr(f"exif.mode.{int(value)}") if int(value) in (0, 1, 2) else str(value)


def color_space_label(value: int | None) -> str:
    if value is None:
        return ""
    return {1: i18n.tr("exif.cs.1"), 2: i18n.tr("exif.cs.2"), 65535: i18n.tr("exif.cs.2")}.get(int(value), str(value))


def flash_label(value: bool | None) -> str:
    if value is None:
        return ""
    return i18n.tr("exif.flash_fired") if value else i18n.tr("exif.flash_off")


def ev_label(value: float | None) -> str:
    if value is None:
        return ""
    return i18n.tr("exif.ev", value=f"{value:+.1f}".replace("+0.0", "±0.0"))


def focal_label(info: ExifInfo) -> str:
    if not info.focal_length:
        return ""
    if info.focal_length_35 and abs(info.focal_length_35 - info.focal_length) > 0.5:
        return i18n.tr("exif.focal_equiv", mm=f"{info.focal_length:g}", mm35=info.focal_length_35)
    return i18n.tr("exif.focal_plain", mm=f"{info.focal_length:g}")


def exif_text_for_clipboard(info: ExifInfo, file_name: str = "") -> str:
    """「Exif をコピー」用のテキスト。"""
    t = i18n.tr
    rows: list[tuple[str, str]] = []
    if file_name:
        rows.append((t("exif.filename"), file_name))
    pairs = [
        (t("exif.taken"), info.datetime_text),
        (t("tile.tooltip_camera"), info.camera_name),
        (t("exif.lens"), info.lens),
        (t("exif.shutter"), fmt_shutter(info.exposure_time)),
        (t("exif.aperture"), f"F{info.f_number:g}" if info.f_number else ""),
        (t("exif.iso"), f"ISO {info.iso}" if info.iso else ""),
        (t("exif.focal"), focal_label(info)),
        (t("exif.exposure_bias"), ev_label(info.exposure_bias)),
        (t("exif.exposure_program"), ExposureProgramLabel(info.exposure_program)),
        (t("exif.metering"), metering_label(info.metering_mode)),
        (t("exif.white_balance"), white_balance_label(info.white_balance)),
        (t("exif.flash"), flash_label(info.flash)),
        (t("exif.dimensions"), info.dimensions_text),
        (t("exif.filesize"), fmt_size(info.file_size)),
        (t("tile.tooltip_location"), fmt_gps(info.gps_lat, info.gps_lon)),
        (t("exif.body_serial"), info.body_serial),
        (t("exif.software"), info.software),
    ]
    rows.extend((k, v) for k, v in pairs if v)
    return "\n".join(f"{k}: {v}" for k, v in rows)
