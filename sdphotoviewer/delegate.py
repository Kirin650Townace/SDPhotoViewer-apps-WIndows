"""タイル表示の描画（写真・動画 + Exif 情報）.

QListView のアイテムを、Windows 11 のエクスプローラー風の
「角丸カード + サムネイル + 撮影情報」として描画する。
動画はフレーム + 再生マーク + 再生時間を表示する。
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QModelIndex, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from . import i18n, theme
from .exifdata import (
    ExposureProgramLabel,
    ev_label,
    fmt_size,
    white_balance_label,
)
from .imaging import fmt_duration, video_kind_label
from .model import EntryRole, PhotoEntry

# ---- レイアウト定数 ----
CELL_PAD = 8          # セルとカードの間の余白
CARD_INNER = 7        # カード内側の余白
GAP_THUMB_TEXT = 5    # サムネイルと文字の間隔
TEXT_LEFT = 9         # 文字の左オフセット（カード内）
LINE_GAP = 1
THUMB_ASPECT_INV = 2 / 3  # 高さ = 幅 × 2/3（3:2 の枠）


class TileMetrics:
    """タイル1枚の寸法をまとめて計算する。"""

    def __init__(self, cell_width: int, detailed: bool):
        self.cell_width = max(120, int(cell_width))
        self.detailed = detailed
        self.name_font = theme.ui_font(theme.FONT_NAME, QFont.Weight.DemiBold)
        self.body_font = theme.ui_font(theme.FONT_BODY)
        fm_name = QFontMetrics(self.name_font)
        fm_body = QFontMetrics(self.body_font)
        self.line_heights = [fm_name.height() + LINE_GAP]
        self.line_heights += [fm_body.height() + LINE_GAP] * (7 if detailed else 3)
        self.text_height = sum(self.line_heights)
        self.thumb_width = self.cell_width - (CELL_PAD + CARD_INNER) * 2
        self.thumb_height = int(round(self.thumb_width * THUMB_ASPECT_INV))
        self.card_width = self.cell_width - CELL_PAD * 2
        self.card_height = CARD_INNER + self.thumb_height + GAP_THUMB_TEXT + self.text_height + CARD_INNER
        self.cell_height = self.card_height + CELL_PAD * 2

    def size(self) -> QSize:
        return QSize(self.cell_width, self.cell_height)


def caption_lines(entry: PhotoEntry, detailed: bool) -> list[str]:
    """タイル下に表示する行（行数はモードで固定）。"""
    info = entry.exif
    dt = ""
    camera = ""
    exposure = ""
    lens = ""
    settings = ""
    image_size = fmt_size(entry.size)

    if entry.is_video:
        try:
            dt = _dt.datetime.fromtimestamp(entry.mtime).strftime("%Y/%m/%d %H:%M")
        except (OverflowError, OSError, ValueError):
            dt = ""
        duration = fmt_duration(info.duration if info else None)
        kind_text = video_kind_label(entry.name)
        header = " · ".join(bit for bit in (i18n.tr("common.video"), duration) if bit)
        resolution = ""
        if info and info.width and info.height:
            resolution = f"{info.width}×{info.height}"
        lines = [
            entry.name,
            dt or i18n.tr("tile.no_datetime"),
            header,
            f"{kind_text} · {fmt_size(entry.size)}",
        ]
        if detailed:
            lines += [
                resolution or i18n.tr("common.unknown"),
                i18n.tr("tile.tooltip_size") + f": {fmt_size(entry.size)}",
                entry.folder,
            ]
        return lines

    if info:
        dt = info.datetime_text_short
        camera = info.camera_name if (info.model or info.make) else ""
        exposure = info.exposure_text
        lens = info.lens
        bits = [ev_label(info.exposure_bias), white_balance_label(info.white_balance)]
        bits = [b for b in bits if b]
        settings = " ／ ".join(bits)
        if info.width and info.height:
            ratio = info.aspect_ratio_text
            image_size = f"{info.width}×{info.height}（{ratio}）· {fmt_size(entry.size)}"

    lines = [
        entry.name,
        dt or i18n.tr("tile.no_datetime"),
        camera or i18n.tr("tile.no_camera"),
        exposure or "—",
    ]
    if detailed:
        lines += [
            lens or i18n.tr("tile.no_lens"),
            settings or (
                i18n.tr("exif.exposure_program") + ": "
                + (ExposureProgramLabel(info.exposure_program) if info and info.exposure_program else "—")
            ),
            image_size,
        ]
    return lines


class TileDelegate(QStyledItemDelegate):
    """写真・動画のタイルを描画するデリゲート。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.detailed = False
        self.tile_width = 236
        self._icon_cache: dict[tuple[str, int], QPixmap] = {}

    # ---- 寸法 ----
    def metrics(self) -> TileMetrics:
        return TileMetrics(self.tile_width, self.detailed)

    def sizeHint(self, option, index) -> QSize:  # noqa: D102
        return self.metrics().size()

    def set_tile_width(self, width: int) -> None:
        self.tile_width = max(150, min(420, int(width)))

    def set_detailed(self, detailed: bool) -> None:
        self.detailed = bool(detailed)

    def clear_icon_cache(self) -> None:
        """テーマが変わったときにアイコンのキャッシュを捨てる。"""
        self._icon_cache.clear()

    # ---- ツールチップ ----
    def helpEvent(self, event, view, option, index) -> bool:  # noqa: D102, N802
        entry: PhotoEntry | None = index.data(EntryRole) if index.isValid() else None
        if entry is None:
            return super().helpEvent(event, view, option, index)
        from PySide6.QtWidgets import QToolTip

        QToolTip.showText(event.globalPos(), entry_tooltip(entry), view)
        return True

    # ---- 描画 ----
    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:  # noqa: D102
        entry: PhotoEntry | None = index.data(EntryRole)
        if entry is None:
            return
        m = self.metrics()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        cell = option.rect
        card = QRect(cell.x() + CELL_PAD, cell.y() + CELL_PAD, m.card_width, m.card_height)

        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        self._draw_card(painter, card, hovered, selected)

        thumb_rect = QRect(
            card.x() + CARD_INNER,
            card.y() + CARD_INNER,
            m.thumb_width,
            m.thumb_height,
        )
        self._draw_thumbnail(painter, thumb_rect, entry)
        self._draw_badges(painter, thumb_rect, entry)

        # 文字
        y = thumb_rect.bottom() + 1 + GAP_THUMB_TEXT
        lines = caption_lines(entry, self.detailed)
        fm_name = QFontMetrics(m.name_font)
        fm_body = QFontMetrics(m.body_font)
        text_left = card.x() + TEXT_LEFT
        text_width = m.card_width - TEXT_LEFT * 2
        for i, (text, height) in enumerate(zip(lines, m.line_heights)):
            if i == 0:
                painter.setFont(m.name_font)
                painter.setPen(theme.text_primary())
                elided = fm_name.elidedText(text, Qt.TextElideMode.ElideMiddle, text_width)
            else:
                painter.setFont(m.body_font)
                painter.setPen(theme.text_secondary() if i in (1, 2, 3) else theme.text_tertiary())
                elided = fm_body.elidedText(text, Qt.TextElideMode.ElideRight, text_width)
            metrics = fm_name if i == 0 else fm_body
            painter.drawText(
                QRect(text_left, y, text_width, metrics.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                elided,
            )
            y += height

        painter.restore()

    # ---- 部品ごとの描画 ----
    def _draw_card(self, painter: QPainter, card: QRect, hovered: bool, selected: bool) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(card), 9, 9)
        if selected:
            painter.fillPath(path, theme.selected_surface())
            pen = QPen(theme.accent())
            pen.setWidthF(1.6)
        elif hovered:
            painter.fillPath(path, theme.surface_hover())
            pen = QPen(theme.accent())
            pen.setWidthF(1.2)
            color = pen.color()
            color.setAlpha(150)
            pen.setColor(color)
        else:
            painter.fillPath(path, theme.surface())
            pen = QPen(theme.border())
            pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)

    def _draw_thumbnail(self, painter: QPainter, rect: QRect, entry: PhotoEntry) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 6, 6)
        painter.save()
        painter.fillPath(path, theme.thumb_bg())
        painter.setClipPath(path)

        image = entry.thumb
        if image is not None and not image.isNull():
            scaled = image.size()
            scaled.scale(rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(0, 0, scaled.width(), scaled.height())
            target.moveCenter(rect.center())
            painter.drawImage(target, image)
        else:
            message = self._placeholder_message(entry)
            icon = self._placeholder_icon(entry, 30)
            if icon is not None and not icon.isNull():
                painter.drawPixmap(
                    rect.center().x() - icon.width() // 2,
                    rect.center().y() - icon.height() // 2 - (8 if message else 0),
                    icon,
                )
            if message:
                painter.setFont(theme.ui_font(theme.FONT_SMALL))
                painter.setPen(theme.placeholder_text())
                painter.drawText(
                    rect.adjusted(6, 0, -6, 0),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom),
                    message,
                )
        painter.restore()

    def _placeholder_message(self, entry: PhotoEntry) -> str:
        if entry.thumb_state == 1:
            return i18n.tr("common.loading")
        if entry.thumb_state == 3:
            if entry.is_video:
                from .compat import has_ffmpeg

                if not has_ffmpeg():
                    return i18n.tr("tile.video_needs_ffmpeg")
            return i18n.tr("tile.no_preview")
        return ""

    def _placeholder_icon(self, entry: PhotoEntry, size: int) -> QPixmap | None:
        icon_name = "VIDEO" if entry.is_video else "PHOTO"
        key = (icon_name, size)
        pixmap = self._icon_cache.get(key)
        if pixmap is None:
            from qfluentwidgets import FluentIcon

            icon = FluentIcon.VIDEO if entry.is_video else FluentIcon.PHOTO
            pixmap = icon.icon(color=theme.placeholder_text()).pixmap(size, size)
            self._icon_cache[key] = pixmap
        return pixmap

    def _draw_badges(self, painter: QPainter, rect: QRect, entry: PhotoEntry) -> None:
        # ファイル形式チップ（JPEG 以外）
        if entry.kind in ("raw", "heic", "video"):
            label = video_kind_label(entry.name) if entry.is_video else entry.kind_text.upper()
            self._draw_chip(
                painter,
                QRect(rect.x() + 6, rect.y() + 6, 0, 0),
                label,
                theme.kind_chip_color(entry.kind),
            )

        # 動画: 再生マークと再生時間
        if entry.is_video:
            self._draw_play_badge(painter, rect)
            duration = fmt_duration(entry.exif.duration if entry.exif else None)
            if duration:
                self._draw_duration(painter, rect, duration)

        # 位置情報のピン
        if entry.has_gps():
            self._draw_pin(painter, QPointF(rect.right() - 15, rect.y() + 15))

    def _draw_chip(self, painter: QPainter, top_left: QRect, text: str, color: QColor) -> None:
        font = theme.ui_font(theme.FONT_TINY, QFont.Weight.DemiBold)
        fm = QFontMetrics(font)
        w = fm.horizontalAdvance(text) + 12
        h = fm.height() + 2
        rect = QRect(top_left.x(), top_left.y(), w, h)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 4, 4)
        bg = QColor(color)
        bg.setAlpha(230)
        painter.save()
        painter.fillPath(path, bg)
        painter.setFont(font)
        painter.setPen(theme.badge_text())
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.restore()

    def _draw_play_badge(self, painter: QPainter, rect: QRect) -> None:
        """動画の中央に半透明の円と再生マークを描く。"""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = max(14, min(rect.width(), rect.height()) * 0.16)
        center = QPointF(rect.center().x(), rect.center().y())
        bg = QColor(0, 0, 0, 130)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawEllipse(center, radius, radius)

        path = QPainterPath()
        size = radius * 0.52
        path.moveTo(center.x() - size * 0.45, center.y() - size)
        path.lineTo(center.x() + size * 0.85, center.y())
        path.lineTo(center.x() - size * 0.45, center.y() + size)
        path.closeSubpath()
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawPath(path)
        painter.restore()

    def _draw_duration(self, painter: QPainter, rect: QRect, text: str) -> None:
        font = theme.ui_font(theme.FONT_TINY, QFont.Weight.DemiBold)
        fm = QFontMetrics(font)
        w = fm.horizontalAdvance(text) + 12
        h = fm.height() + 2
        box = QRect(rect.right() - w - 6, rect.bottom() - h - 6, w, h)
        path = QPainterPath()
        path.addRoundedRect(QRectF(box), 4, 4)
        painter.save()
        painter.fillPath(path, QColor(0, 0, 0, 170))
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.restore()

    def _draw_pin(self, painter: QPainter, center: QPointF) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = QColor(0, 0, 0, 150)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawEllipse(center, 9, 9)
        path = QPainterPath()
        r = 4.2
        path.moveTo(center.x(), center.y() + 5.4)
        path.lineTo(center.x() - r, center.y() - 0.6)
        path.arcTo(QRectF(center.x() - r, center.y() - 0.6 - r, r * 2, r * 2), 200, 140)
        path.lineTo(center.x(), center.y() + 5.4)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPath(path)
        painter.setBrush(QColor("#000000"))
        painter.drawEllipse(QPointF(center.x(), center.y() - 0.4), 1.7, 1.7)
        painter.restore()


def entry_tooltip(entry: PhotoEntry) -> str:
    """タイルにマウスを重ねたときのツールチップ。"""
    t = i18n.tr
    info = entry.exif
    rows = [f"<b>{entry.name}</b>", f"{t('tile.tooltip_folder')}: {entry.folder}"]
    if info:
        if entry.is_video:
            from .imaging import fmt_duration

            duration = fmt_duration(info.duration)
            if duration:
                rows.append(f"{t('tile.tooltip_duration')}: {duration}")
            if info.width and info.height:
                rows.append(f"{t('tile.tooltip_image')}: {info.width}×{info.height}")
        else:
            if info.datetime_text:
                rows.append(f"{t('tile.tooltip_taken')}: {info.datetime_text}")
            if info.model or info.make:
                rows.append(f"{t('tile.tooltip_camera')}: {info.camera_name}")
            if info.lens:
                rows.append(f"{t('tile.tooltip_lens')}: {info.lens}")
            if info.exposure_text:
                rows.append(f"{t('tile.tooltip_exposure')}: {info.exposure_text}")
            if info.exposure_bias is not None or info.white_balance is not None:
                bits = [ev_label(info.exposure_bias), white_balance_label(info.white_balance)]
                rows.append(t("tile.tooltip_adjust") + ": " + " ／ ".join(b for b in bits if b))
            if info.width and info.height:
                rows.append(f"{t('tile.tooltip_image')}: {info.width}×{info.height}")
            if info.has_gps:
                from .exifdata import fmt_gps

                rows.append(t("tile.tooltip_location") + ": " + fmt_gps(info.gps_lat, info.gps_lon))
    rows.append(f"{t('tile.tooltip_size')}: {fmt_size(entry.size)}")
    rows.append(f"{t('tile.tooltip_type')}: {entry.kind_text if not entry.is_video else video_kind_label(entry.name)}")
    return "<br>".join(rows)
