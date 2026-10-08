"""テーマ配色とフォントのユーティリティ.

Windows 11 (ライト/ダーク) の配色にできるだけ近づけた色を返す。
色は描画時に呼び出すため、テーマを切り替えると次回の再描画で反映される。
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication
from qfluentwidgets import Theme, isDarkTheme, setTheme

from . import i18n

# 設定（QSettings）のキー
SETTINGS_ORG = "SDPhotoViewer"
SETTINGS_APP = "SDPhotoViewer"
THEME_KEY = "theme"

# ---- フォント ----
# Windows の標準 UI フォントを使う。
# 日本語環境では Yu Gothic UI（Windows 11 の日本語 UI 標準）、
# 英語環境では Segoe UI を先頭にする。
FONT_FAMILIES_JA = [
    "Yu Gothic UI",
    "Meiryo UI",
    "Meiryo",
    "MS UI Gothic",
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "Hiragino Sans",
    "Segoe UI",
    "sans-serif",
]
FONT_FAMILIES_EN = [
    "Segoe UI Variable Text",
    "Segoe UI",
    "Noto Sans",
    "Helvetica Neue",
    "Arial",
    "Yu Gothic UI",
    "sans-serif",
]

# qfluentwidgets のスタイルシートは 'Microsoft YaHei'（中国語フォント）を
# 候補に入れているため、日本語のグリフが中国語フォントで描かれてしまう。
# フォント置換で日本語フォントに差し替える。
_FONT_SUBSTITUTIONS = ("Microsoft YaHei", "Microsoft YaHei UI", "SimSun", "SimHei")

# 文字サイズ（pt）。Windows 11 の標準に近い値
FONT_NAME = 9.75   # ファイル名など強調したい文字
FONT_BODY = 9.0    # 本文
FONT_SMALL = 8.5   # 補足
FONT_TINY = 8.0    # バッジなど

_WEIGHT_ALIASES = {
    50: QFont.Weight.Normal,
    63: QFont.Weight.DemiBold,
}


def ui_font(point_size: float = FONT_BODY, weight=None) -> QFont:
    """UI 用フォント（サイズは pt 指定）。"""
    families = FONT_FAMILIES_JA if i18n.is_japanese() else FONT_FAMILIES_EN
    f = QFont()
    f.setFamilies(families)
    f.setPointSizeF(float(point_size))
    if weight is not None:
        f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def install_font_substitutions() -> None:
    """日本語環境で中国語フォントが使われないように置換を登録する。"""
    if not i18n.is_japanese():
        return
    for name in _FONT_SUBSTITUTIONS:
        QFont.insertSubstitutions(name, FONT_FAMILIES_JA)


def apply_fluent_fonts() -> None:
    """qfluentwidgets 全体の既定フォントを OS 標準のものに差し替える。

    ライブラリの初期値は ``['Segoe UI', 'Microsoft YaHei', 'PingFang SC']`` で、
    日本語の文字が中国語フォント（Microsoft YaHei）で描かれてしまう。
    ここで日本語（または英語）向けの並びに置き換える。
    ウィンドウを作る前に呼ぶこと。
    """
    families = FONT_FAMILIES_JA if i18n.is_japanese() else FONT_FAMILIES_EN
    try:
        from qfluentwidgets.common.font import setFontFamilies

        setFontFamilies(list(families), save=False)
    except Exception:  # noqa: BLE001 - ライブラリ側の変更に耐える
        pass


def install_fonts() -> None:
    """フォントまわりの初期設定をまとめて行う（置換 + ライブラリ既定の差し替え）。"""
    install_font_substitutions()
    apply_fluent_fonts()


def pick(light: str, dark: str) -> QColor:
    """テーマに応じて色を選ぶ。"""
    return QColor(dark if isDarkTheme() else light)


# ---- 面（背景） ----
def window_bg() -> QColor:
    return pick("#F3F3F3", "#202020")


def sidebar_bg() -> QColor:
    return pick("#FAFAFA", "#272727")


def surface() -> QColor:
    """カード / タイルの背景。"""
    return pick("#FFFFFF", "#2B2B2B")


def surface_hover() -> QColor:
    return pick("#FBFBFB", "#323232")


def surface_pressed() -> QColor:
    return pick("#F3F3F3", "#383838")


def thumb_bg() -> QColor:
    """サムネイルの下地（余白部分）。

    カード背景より少しだけ沈んだ色にして、縦長写真の左右の余白が
    「穴」に見えないようにする。
    """
    return pick("#EDEDED", "#262626")


def border() -> QColor:
    return pick("#E3E3E3", "#3B3B3B")


# ---- テキスト ----
def text_primary() -> QColor:
    return pick("#1A1A1A", "#FFFFFF")


def text_secondary() -> QColor:
    return pick("#5B5B5B", "#C9C9C9")


def text_tertiary() -> QColor:
    return pick("#8A8A8A", "#979797")


# ---- アクセント ----
def accent() -> QColor:
    return pick("#0067C0", "#4CC2FF")


def accent_soft() -> QColor:
    """選択行の淡いアクセント。"""
    c = accent()
    c.setAlpha(38)
    return c


def selected_surface() -> QColor:
    return pick("#E9F2FB", "#123A54")


# ---- タイル上のバッジ ----
def badge_bg() -> QColor:
    c = QColor("#000000")
    c.setAlpha(150 if not isDarkTheme() else 170)
    return c


def badge_text() -> QColor:
    return QColor("#FFFFFF")


# --------------------------------------------------------------------------
# テーマの保存と復元
# --------------------------------------------------------------------------
def load_saved_theme() -> str:
    """保存されたテーマ（"light" / "dark"）を返す。未保存なら ""。"""
    value = str(QSettings(SETTINGS_ORG, SETTINGS_APP).value(THEME_KEY, "") or "").lower()
    return value if value in ("light", "dark") else ""


def save_theme(mode: str) -> None:
    """テーマを設定に保存する（次回起動時に復元される）。"""
    if mode in ("light", "dark"):
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(THEME_KEY, mode)


def system_theme() -> str:
    """OS の設定（ダーク / ライト）を返す。判定できないときは "light"。"""
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
        if scheme == Qt.ColorScheme.Light:
            return "light"
    except Exception:  # noqa: BLE001 - Qt のバージョン差に耐える
        pass
    return "light"


def resolve_theme(mode: str = "auto") -> str:
    """実際に使うテーマを決める（--theme > 保存された設定 > OS の設定）。"""
    mode = (mode or "auto").lower()
    if mode in ("light", "dark"):
        return mode
    return load_saved_theme() or system_theme()


def apply_theme(mode: str = "auto") -> str:
    """テーマを適用する。

    qfluentwidgets の設定ファイル（相対パスの config/config.json）は使わず、
    アプリの設定（QSettings）に保存する。適用したテーマ名を返す。
    """
    resolved = resolve_theme(mode)
    setTheme(Theme.DARK if resolved == "dark" else Theme.LIGHT, save=False)
    return resolved


def kind_chip_color(kind: str) -> QColor:
    """ファイル形式チップの色。"""
    if kind == "raw":
        return QColor("#C2521B") if not isDarkTheme() else QColor("#E4762F")
    if kind == "heic":
        return QColor("#0F7B4F") if not isDarkTheme() else QColor("#2FA96C")
    if kind == "video":
        return QColor("#6B3FA0") if not isDarkTheme() else QColor("#9A6FD0")
    return QColor("#0F5A9E") if not isDarkTheme() else QColor("#4C9EE0")


# ---- サムネイル未読込時などの補助色 ----
def placeholder_text() -> QColor:
    return pick("#9A9A9A", "#8A8A8A")
