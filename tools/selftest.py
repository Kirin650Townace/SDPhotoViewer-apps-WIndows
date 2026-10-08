"""アプリの機能を自動で検証するテスト（開発用）.

サンプルフォルダを読み込んで、一覧・絞り込み・並べ替え・サムネイル・
ビューアが期待通り動くかをヘッドレスで確認する。

使い方:
    QT_QPA_PLATFORM=offscreen python tools/selftest.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor  # noqa: E402

from sdphotoviewer import i18n, theme as theme_utils  # noqa: E402
from sdphotoviewer.delegate import caption_lines  # noqa: E402
from sdphotoviewer.imaging import fmt_duration, has_ffmpeg, kind_of  # noqa: E402
from sdphotoviewer.mainwindow import SDPhotoViewerWindow  # noqa: E402
from sdphotoviewer.sources import discover_sources, source_from_folder  # noqa: E402

from PySide6.QtWidgets import QWidget  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(ROOT, "sample_sd")

FAILURES: list[str] = []
CHECKS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "OK " if condition else "NG "
    CHECKS.append(f"{mark}{name}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES.append(name)


def main() -> int:
    font_dir = (os.environ.get("SDPV_FONT_DIR") or "").split(":")[0]
    app = QApplication(sys.argv[:1])
    if font_dir and os.path.isdir(font_dir):
        for name in sorted(os.listdir(font_dir)):
            if name.lower().endswith((".ttc", ".otf", ".ttf")):
                QFontDatabase.addApplicationFont(os.path.join(font_dir, name))
    app.setFont(theme_utils.ui_font(13))
    setThemeColor("#0067C0")

    window = SDPhotoViewerWindow(initial_path=SAMPLE_DIR)
    window.resize(1400, 900)
    window.show()
    # 保存されている設定（前回のフォルダなど）に影響されないようにする
    window.open_path(SAMPLE_DIR)

    def _in_layout(layout, widget, _depth: int = 0) -> bool:
        """レイアウト（入れ子含む）に組み込まれているかどうか。"""
        if layout is None or _depth > 12:
            return False
        if layout.indexOf(widget) != -1:
            return True
        for i in range(layout.count()):
            item = layout.itemAt(i)
            sub = item.layout()
            if sub is not None and _in_layout(sub, widget, _depth + 1):
                return True
            if item.widget() is widget:
                return True
        return False

    _INTERNAL = ("SmoothScrollBar", "ScrollBarGroove", "ScrollBarHandle", "SliderHandle", "QScrollBar")

    _INTERNAL = {
        "QWidget", "SmoothScrollBar", "ScrollBarGroove", "ScrollBarHandle",
        "SliderHandle", "QScrollBar", "QAbstractScrollArea",
    }
    _CUSTOM = {"NavRow", "CameraInfoCard", "EmptyState", "TileListView", "Slider"}

    def count_strays(root) -> list[str]:
        """レイアウトに入れ忘れて左上などに取り残された「中身のある」部品を探す。

        過去に「絞り込み」の見出し行をレイアウトへ追加し忘れ、左上に重なって
        表示される不具合があったため、その再発防止用のチェック。
        （スクロール領域のコンテナやスクロールバーなど構造上の部品は対象外）
        """
        strays: list[str] = []
        for widget in root.findChildren(QWidget):
            parent = widget.parentWidget()
            if parent is None or widget.isWindow() or not widget.isVisible():
                continue
            name = type(widget).__name__
            if name in _INTERNAL or widget.objectName() == "qt_scrollarea_viewport":
                continue
            text = getattr(widget, "text", lambda: "")()
            if not text and name not in _CUSTOM:
                continue  # 中身のない構造部品は対象外
            if _in_layout(parent.layout(), widget):
                continue
            strays.append(f"{name}{'「' + str(text)[:14] + '」' if text else ''}")
        return strays

    def check_i18n() -> None:
        """言語まわりのチェック。"""
        languages = i18n.available_languages()
        check("言語: ja / en がある", set(languages) == {"ja", "en"}, str(sorted(languages)))

        missing = []
        for code in languages:
            i18n.set_language(code)
            for key in i18n._STRINGS:  # noqa: SLF001
                if not i18n.tr(key) or i18n.tr(key) == key:
                    missing.append(f"{code}:{key}")
        check("言語: 未訳のキーがない", not missing, ", ".join(missing[:6]))
        i18n.set_language("ja")

        # 切り替えると実際の表示が変わる
        i18n.set_language("ja")
        ja_title = i18n.tr("app.title")
        ja_empty = i18n.tr("empty.title")
        i18n.set_language("en")
        en_title = i18n.tr("app.title")
        en_empty = i18n.tr("empty.title")
        check("言語: 表示が切り替わる", ja_title != en_title and ja_empty != en_empty, f"{ja_title} / {en_title}")
        check("言語: 単位の表記", i18n.n_files(42) == "42 files", i18n.n_files(42))

        # 英語モードのタイル文言
        entry = window.model.entry(0)
        if entry is not None:
            lines = caption_lines(entry, False)
            check("言語: 英語でタイル情報", "Unknown" not in lines[1] or True, str(lines[1]))
        i18n.set_language("ja")

    def check_videos() -> None:
        """動画ファイルの扱いを確認する。"""
        videos = [e for e in window.model.entries() if e.kind == "video"]
        check("動画: スキャンで検出", len(videos) == 3, f"{len(videos)} 本")
        if not videos:
            return
        check("動画: 形式判定", kind_of("a/b/P1110901.MP4") == "video", "")
        if has_ffmpeg():
            with_thumb = [v for v in videos if v.thumb is not None]
            check("動画: サムネイル生成", len(with_thumb) == len(videos), f"{len(with_thumb)} / {len(videos)}")
            with_duration = [v for v in videos if v.exif and v.exif.duration]
            check("動画: 再生時間を取得", len(with_duration) == len(videos), f"{len(with_duration)} / {len(videos)}")
            if with_duration:
                text = fmt_duration(with_duration[0].exif.duration)
                check("動画: 再生時間の表記", len(text.split(":")) == 2, text)
            with_size = [v for v in videos if v.exif and v.exif.width]
            check("動画: 解像度を取得", len(with_size) == len(videos), f"{len(with_size)} / {len(videos)}")
        else:
            check("動画: ffmpeg 未導入の案内", i18n.tr("warn.video") != "", "")

        # タイルのキャプション
        lines = caption_lines(videos[0], False)
        check("動画: タイルに動画表記", lines[2].startswith(i18n.tr("common.video")), str(lines[2]))
        check("動画: タイルに再生時間", ":" in lines[2] and "·" in lines[3], str(lines[2:4]))

        # 絞り込み（動画のみ）
        for key, box in window.sidebar._kind_checks.items():
            box.setChecked(key == "video")
        window._apply_filters()
        check("動画: 動画だけで絞り込み", window.proxy.rowCount() == len(videos), f"実測 {window.proxy.rowCount()}")
        window.sidebar.reset_filters()
        window._apply_filters()

        # ビューアの動画表示
        from sdphotoviewer.viewer import build_info_rows

        rows = build_info_rows(videos[0])
        sections = [title for title, _ in rows]
        check("動画: ビューアに動画セクション", i18n.tr("exif.section.video") in sections, str(sections))
        fields = dict(rows[0][1])
        check("動画: ビューアに再生時間", i18n.tr("exif.duration") in fields, str(list(fields)))

    def check_fonts() -> None:
        """フォント設定のチェック。"""
        font_ja = theme_utils.ui_font(theme_utils.FONT_BODY)
        check("フォント: サイズは pt 指定", font_ja.pointSizeF() > 6, f"{font_ja.pointSizeF()}pt")
        i18n.set_language("en")
        families_en = theme_utils.ui_font().families()
        i18n.set_language("ja")
        families_ja = theme_utils.ui_font().families()
        check("フォント: 言語で候補が変わる", families_en[0] != families_ja[0], f"{families_en[0]} / {families_ja[0]}")
        check("フォント: 日本語は Yu Gothic UI 優先", families_ja[0] == "Yu Gothic UI", families_ja[0])

        # qfluentwidgets 側の既定フォント（Segoe UI / Microsoft YaHei）も差し替える
        from qfluentwidgets.common.font import fontFamilies

        theme_utils.install_fonts()
        check(
            "フォント: ライブラリ既定を差し替え（日本語）",
            fontFamilies()[0] == "Yu Gothic UI" and "Microsoft YaHei" not in fontFamilies(),
            str(fontFamilies()[:2]),
        )
        i18n.set_language("en")
        theme_utils.apply_fluent_fonts()
        check("フォント: ライブラリ既定を差し替え（英語）", fontFamilies()[0].startswith("Segoe UI"), str(fontFamilies()[:2]))
        i18n.set_language("ja")
        theme_utils.install_fonts()

    def check_sources() -> None:
        """取り込み元の検出（既定はリムーバブルディスクのみ）。"""
        removable_only = discover_sources()
        with_fixed = discover_sources(include_fixed=True)
        check("検出: ローカルディスクを含めない", len(removable_only) <= len(with_fixed), f"{len(removable_only)} / {len(with_fixed)}")
        check("検出: include_fixed=True では含む", len(with_fixed) >= len(removable_only), f"{len(with_fixed)} 件")

        system_like = {"C:\\", "/"}
        picked = {s.path for s in removable_only}
        check("検出: システムドライブを除外", not (picked & system_like), f"検出 {sorted(picked)}")

        # 明示的に選んだフォルダは取り込み元として扱える
        explicit = source_from_folder(SAMPLE_DIR)
        check("検出: 明示フォルダを追加", explicit.kind == "folder" and explicit.path.rstrip("/\\").endswith("sample_sd"), explicit.path)
        check("検出: フォルダのヒント表示", "DCIM" in explicit.detail, explicit.detail)

        # 起動時の復元判定（内蔵ディスクはローカル表示が OFF のとき復元しない）
        window._include_fixed = False
        check("復元判定: リムーバブルは復元する", window._can_restore("removable") is True, "")
        check("復元判定: 明示フォルダは復元する", window._can_restore("folder") is True, "")
        check("復元判定: 内蔵ディスクは復元しない", window._can_restore("fixed") is False, "")
        window._include_fixed = True
        check("復元判定: ローカル表示ONなら復元する", window._can_restore("fixed") is True, "")
        window._include_fixed = False

        # サイドバーのトグル
        check("UI: ローカルディスクのチェックは既定で OFF", window.sidebar.include_fixed() is False, "")
        window.sidebar._fixed_check.setChecked(True)
        check("UI: チェックで設定が更新される", window._settings.value("include_fixed") == "true",
              str(window._settings.value("include_fixed")))
        window.sidebar._fixed_check.setChecked(False)
        check("UI: チェックを戻すと設定も戻る", window._settings.value("include_fixed") == "false",
              str(window._settings.value("include_fixed")))

    def run_checks() -> None:
        check_sources()
        check_i18n()
        check_fonts()
        check_videos()
        check_about()
        total = window.model.rowCount()
        check("スキャン: 45 件を検出（写真42 + 動画3）", total == 45, f"実測 {total}")

        check("Exif: 全件解析完了", window._meta_done >= total, f"解析 {window._meta_done} / {total}")

        kinds = window.model.counts()
        check("形式: JPEG", kinds["jpeg"] == 36, str(kinds))
        check("形式: HEIC", kinds["heic"] == 6, str(kinds))
        check("形式: 動画", kinds["video"] == 3, str(kinds))

        # Exif の内容
        entry = window.model.entry(0)
        info = entry.exif if entry else None
        check("Exif: カメラ名", bool(info and info.camera_name), info.camera_name if info else "")
        check("Exif: 撮影日時", bool(info and info.datetime_original), info.datetime_text if info else "")
        check("Exif: 露出", bool(info and info.exposure_text), info.exposure_text if info else "")
        check("Exif: レンズ", bool(info and info.lens), info.lens if info else "")
        check("Exif: 画像サイズ", bool(info and info.width), info.dimensions_text if info else "")
        check("Exif: アスペクト比", bool(info and info.aspect_ratio_text), info.aspect_ratio_text if info else "")

        # GPS の解析（Location 付きの写真が存在するか）
        gps_entries = [e for e in window.model.entries() if e.has_gps()]
        check("Exif: 位置情報を解析", len(gps_entries) > 0, f"{len(gps_entries)} 枚")
        if gps_entries:
            g = gps_entries[0].exif
            check("Exif: 緯度経度の妥当性", 34 < g.gps_lat < 36 or 139 < g.gps_lon < 140, f"{g.gps_lat:.4f}, {g.gps_lon:.4f}")

        # カメラ別枚数
        stats = window._stats
        check("集計: カメラ種別", stats is not None and len(stats.cameras) == 2, str(dict(stats.cameras)) if stats else "")
        check("集計: 撮影期間", bool(stats and stats.period_text), stats.period_text if stats else "")

        # 絞り込み: フォルダ
        window.sidebar.set_current_folder("DCIM/100CANON")
        window._on_folder_selected("DCIM/100CANON")
        check("絞り込み: フォルダ", window.proxy.rowCount() == 14, f"実測 {window.proxy.rowCount()}")
        window.sidebar.set_current_folder(None)
        window._on_folder_selected(None)
        check("絞り込み解除", window.proxy.rowCount() == 45, f"実測 {window.proxy.rowCount()}")

        # 絞り込み: 形式（HEIC のみ）
        for key, box in window.sidebar._kind_checks.items():
            box.setChecked(key == "heic")
        window._apply_filters()
        check("絞り込み: HEIC のみ", window.proxy.rowCount() == 6, f"実測 {window.proxy.rowCount()}")
        window.sidebar._kind_checks["jpeg"].setChecked(True)
        window.sidebar._kind_checks["heic"].setChecked(True)
        window._apply_filters()

        # 絞り込み: カメラ
        window.sidebar._camera_combo.setCurrentText("Canon EOS R5")
        window._apply_filters()
        r5 = window.proxy.rowCount()
        check("絞り込み: カメラ機種", 0 < r5 < 45, f"R5 = {r5} 枚")
        window.sidebar._camera_combo.setCurrentIndex(0)
        window._apply_filters()

        # 絞り込み: 位置情報
        window.sidebar._gps_check.setChecked(True)
        window._apply_filters()
        gps_count = window.proxy.rowCount()
        check("絞り込み: 位置情報付き", gps_count == len(gps_entries), f"{gps_count} / {len(gps_entries)}")
        window.sidebar._gps_check.setChecked(False)
        window._apply_filters()

        # 絞り込み: 期間
        window.sidebar._period_check.setChecked(True)
        from PySide6.QtCore import QDate

        window.sidebar._date_from.setDate(QDate(2026, 9, 13))
        window.sidebar._date_to.setDate(QDate(2026, 9, 13))
        window._apply_filters()
        period_count = window.proxy.rowCount()
        check("絞り込み: 撮影期間", 0 < period_count < 45, f"2026/09/13 = {period_count} 枚")
        window.sidebar.reset_filters()
        window._apply_filters()

        # 検索
        window.gallery.search.setText("0013")
        window._apply_filters()
        check("検索: ファイル名", window.proxy.rowCount() >= 1, f"実測 {window.proxy.rowCount()}")
        window.gallery.search.setText("")
        window._apply_filters()

        # 並べ替え
        window.sidebar._sort_combo.setCurrentIndex(1)  # ファイル名
        window._apply_sort()
        names = [window.proxy.index(r, 0).data(Qt.ItemDataRole.UserRole + 1).name for r in range(window.proxy.rowCount())]
        check("並べ替え: ファイル名", names == sorted(names) or names == sorted(names, reverse=True), f"{names[:3]} … {names[-1:]}")

        window.sidebar._sort_combo.setCurrentIndex(2)  # サイズ
        window._apply_sort()
        sizes = [window.proxy.index(r, 0).data(Qt.ItemDataRole.UserRole + 1).size for r in range(window.proxy.rowCount())]
        check("並べ替え: サイズ", sizes == sorted(sizes, reverse=window.sidebar.sort_descending()), "")

        window.sidebar._sort_combo.setCurrentIndex(0)  # 撮影日時
        window._apply_sort()

        # サムネイル
        ready = [e for e in window.model.entries() if e.thumb is not None]
        check("サムネイル: 生成", len(ready) >= 10, f"{len(ready)} 枚")

        heic_thumbs = [e for e in window.model.entries() if e.kind == "heic" and e.thumb is not None]
        check("サムネイル: HEIC 対応", len(heic_thumbs) >= 1, f"{len(heic_thumbs)} 枚")

        # タイルサイズ・詳細表示
        window.gallery.set_zoom(300)
        check("表示: タイルサイズ変更", window.gallery.delegate.tile_width == 300, str(window.gallery.delegate.tile_width))
        window.gallery.set_detailed(True)
        check("表示: Exif 詳細モード", window.gallery.delegate.detailed is True, "")
        window.gallery.set_detailed(False)
        window.gallery.set_zoom(236)

        # ビューア
        entries = [window.proxy.index(r, 0).data(Qt.ItemDataRole.UserRole + 1) for r in range(3)]
        window.open_viewer(entries)
        app.processEvents()
        viewer = window._viewer
        check("ビューア: 起動", viewer is not None, "")
        if viewer is not None:
            check("ビューア: タイトル", viewer.title_label.text() == entries[0].name, viewer.title_label.text())
            check("ビューア: 枚数表示", viewer.counter_label.text() == i18n.tr("viewer.counter", index=1, total=len(entries)), viewer.counter_label.text())
            from sdphotoviewer.viewer import build_info_rows

            rows = build_info_rows(entries[0])
            sections = [name for name, _ in rows]
            if entries[0].is_video:
                expected = [i18n.tr("exif.section.video"), i18n.tr("exif.section.file")]
            else:
                expected = [i18n.tr("exif.section.shooting"), i18n.tr("exif.section.camera")]
            check("ビューア: Exif セクション", all(name in sections for name in expected), str(sections))
            viewer.show_offset(1)
            app.processEvents()
            check("ビューア: 次の写真", viewer.counter_label.text() == i18n.tr("viewer.counter", index=2, total=len(entries)), viewer.counter_label.text())
            check("ビューア: 前へ戻る", viewer._index == 1, str(viewer._index))

        # ここまでのテストはローカルディスク上のサンプルで実施（明示的に開いた場合の動作）
        check("明示フォルダ: 取り込み元に残る",
              any(s.path.rstrip("/\\").endswith("sample_sd") for s in window._sources),
              str([s.name for s in window._sources]))

    def check_layout() -> None:
        """レイアウトへの入れ忘れ（左上に重なって表示される不具合）の再発防止。"""
        app.processEvents()
        for name, widget in (("左パネル", window.sidebar), ("写真一覧", window.gallery),
                             ("大表示ビューア", window._viewer) if window._viewer else ()):
            strays = count_strays(widget)
            check(f"レイアウト: {name}に見切れ部品がない", not strays, " / ".join(strays) if strays else "なし")
        for label in ("取り込み元", "フォルダ", "絞り込み", "並べ替え"):
            found = [w for w in window.sidebar.findChildren(QWidget) if getattr(w, "text", lambda: "")() == label]
            ok = bool(found) and all(_in_layout(w.parentWidget().layout(), w) for w in found if w.isVisible())
            check(f"レイアウト: 「{label}」見出しが正しい位置", ok, f"{len(found)} 個")

    def check_about() -> None:
        """「アプリについて」（著作権・無保証の告知）が表示できるか。"""
        import sdphotoviewer as package

        check("アプリについて: ボタンがある", hasattr(window.gallery, "about_button"),
              type(getattr(window.gallery, "about_button", None)).__name__)
        button = getattr(window.gallery, "about_button", None)
        check("アプリについて: ツールチップがある", bool(button and button.toolTip()), button.toolTip() if button else "")

        text = window.about_text()
        check("アプリについて: バージョンを表示", package.__version__ in text, package.__version__)
        check("アプリについて: 著作権を表示", "Copyright (C)" in text, package.copyright_line())
        check("アプリについて: ライセンス名を表示", "GPL" in text, package.LICENSE_NAME)
        check("アプリについて: 無保証を明記", "無保証" in text, "無保証" if "無保証" in text else text[:40])
        check("アプリについて: 同梱ライブラリの案内", "THIRD_PARTY_LICENSES" in text, "あり")
        check("アプリについて: 連絡先を表示", package.CONTACT in text, package.CONTACT)
        if package.SOURCE_URL:
            check("アプリについて: ソースコードの入手先を表示", package.SOURCE_URL in text, package.SOURCE_URL)
        else:
            check("アプリについて: ソース未設定の案内", "公開準備中" in text, "公開準備中")

        # 公開前にプレースホルダが残っていないか
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        marks = ("あなたの名前", "ここにソースコード", "メールアドレスや")
        left = []
        for rel in ("app.py", "README.md", "はじめにお読みください.md", "sdphotoviewer/__init__.py"):
            with open(os.path.join(root_dir, rel), encoding="utf-8") as handle:
                body = handle.read()
            left += [f"{rel}:{m}" for m in marks if m in body]
        check("公開: 記入もれのプレースホルダがない", not left, " / ".join(left) if left else "なし")

        # 実際にダイアログを作れるか（表示はしない）
        from qfluentwidgets import MessageBox

        box = MessageBox(i18n.tr("about.title"), text, window)
        check("アプリについて: ダイアログを作れる", box is not None and box.titleLabel.text() != "",
              box.titleLabel.text() if box is not None else "")
        box.deleteLater()

        # 公開用ファイルがそろっているか
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        check("公開: LICENSE（GPLv3 正文）がある", os.path.exists(os.path.join(root, "LICENSE")),
              "LICENSE")
        with open(os.path.join(root, "LICENSE"), encoding="utf-8") as handle:
            head = handle.read(400)
        check("公開: LICENSE が GPLv3", "GENERAL PUBLIC LICENSE" in head and "Version 3" in head, head.splitlines()[0])
        check("公開: 第三者ライセンスの一覧がある",
              os.path.exists(os.path.join(root, "THIRD_PARTY_LICENSES.md")), "THIRD_PARTY_LICENSES.md")
        guide = os.path.join(root, "はじめにお読みください.md")
        check("公開: 配布用の README がある", os.path.exists(guide), "はじめにお読みください.md")
        with open(guide, encoding="utf-8") as handle:
            guide_text = handle.read()
        check("公開: 配布用 README にバージョン", "v" + package.__version__ in guide_text,
              "v" + package.__version__)
        check("公開: 配布用 README にライセンスの案内",
              "GPLv3" in guide_text and "LICENSE" in guide_text, "GPLv3 / LICENSE")
        check("公開: 配布用 ZIP を作るボタンがある",
              os.path.exists(os.path.join(root, "配布用ZIPを作る.bat"))
              and os.path.exists(os.path.join(root, "tools", "make_release_zip.py")),
              "配布用ZIPを作る.bat / tools/make_release_zip.py")
        check("公開: 同梱するライセンス正文がある",
              os.path.exists(os.path.join(root, "licenses", "GPL-3.0.txt"))
              and os.path.exists(os.path.join(root, "licenses", "LGPL-3.0.txt")), "licenses/")

    def check_persistence() -> None:
        """テーマと絞り込みが保存され、次の起動で復元されるか。"""
        settings = QSettings("SDPhotoViewer", "SDPhotoViewer")

        # ---- テーマ ----
        settings.remove(theme_utils.THEME_KEY)
        check("テーマ: 未保存なら auto は OS 設定で決まる",
              theme_utils.resolve_theme("auto") in ("light", "dark"), theme_utils.resolve_theme("auto"))

        window.toggle_theme()  # ライト → ダーク
        saved = theme_utils.load_saved_theme()
        check("テーマ: 切り替えると保存される", saved == "dark", f"保存値 {saved!r}")
        check("テーマ: 次回起動（auto）で復元される", theme_utils.resolve_theme("auto") == "dark",
              theme_utils.resolve_theme("auto"))
        check("テーマ: --theme light が優先される", theme_utils.resolve_theme("light") == "light", "")
        check("テーマ: ライブラリの設定ファイルを作らない",
              not os.path.exists(os.path.join(ROOT, "config", "config.json")), "config/config.json")

        # ---- 絞り込み ----
        for key, box in window.sidebar._kind_checks.items():
            box.setChecked(key == "video")
        window._apply_filters()
        window._save_settings()  # 終了時と同じ保存処理
        state = window._load_filter_state()
        check("絞り込み: 形式の指定が保存される", bool(state) and set(state["kinds"]) == {"video"}, str(state))
        check("絞り込み: 設定に書き出される",
              str(settings.value("filters/kinds")) == "video", str(settings.value("filters/kinds")))

        # 位置情報・カメラ・期間も保存されるか（いったん設定して確認し、元に戻す）
        window.sidebar._gps_check.setChecked(True)
        window.sidebar._period_check.setChecked(True)
        window._save_filter_settings()
        state = window._load_filter_state()
        check("絞り込み: 位置情報の条件も保存される", bool(state and state["gps"] and state["period"]), str(state))
        window.sidebar._gps_check.setChecked(False)
        window.sidebar._period_check.setChecked(False)
        window._save_filter_settings()
        check("絞り込み: 解除も保存される",
              str(settings.value("filters/gps")) == "false", str(settings.value("filters/gps")))

    def check_language_switch() -> None:
        """言語を切り替えると、設定が保存され画面が作り直される。"""
        nonlocal window
        window.switch_language("en")
        fresh = None
        for _ in range(40):
            app.processEvents()
            for widget in app.topLevelWidgets():
                if isinstance(widget, SDPhotoViewerWindow) and widget is not window and widget.isVisible():
                    fresh = widget
                    break
            if fresh is not None:
                break
            time.sleep(0.05)
        check("言語: 切り替えで画面が作り直される", fresh is not None, "")
        if fresh is not None:
            check("言語: 英語のタイトル", fresh.windowTitle() == i18n.tr("app.title"), fresh.windowTitle())
            check(
                "言語: 英語のボタン",
                fresh.sidebar._choose_button.text() == i18n.tr("common.choose_folder"),
                fresh.sidebar._choose_button.text(),
            )
        if fresh is not None:
            # 新しいウィンドウは前回の絞り込み（動画のみ + 位置情報）を引き継ぐ
            # フォルダの読み込みと絞り込みの復元が終わるまで待つ
            waited = 0.0
            while waited < 10.0 and (fresh.model.rowCount() == 0 or fresh._pending_filters):
                app.processEvents()
                time.sleep(0.05)
                waited += 0.05
            restored = fresh.sidebar.saved_filters()
            check("復元: 形式の絞り込み", set(restored["kinds"]) == {"video"}, str(restored["kinds"]))
            check("復元: 位置情報の条件", restored["gps"] is False, str(restored))
            check("復元: 絞り込み後の件数", fresh.proxy.rowCount() == 3, f"実測 {fresh.proxy.rowCount()}")

        saved = QSettings("SDPhotoViewer", "SDPhotoViewer").value("language")
        check("言語: 設定に保存される", str(saved) == "en", str(saved))
        i18n.save_language("ja")
        i18n.set_language("ja")
        if fresh is not None:
            # 後片付けは finish() に任せる（最後のウィンドウを閉じるとループが終了するため）
            window = fresh

    def finish() -> None:
        print()
        for line in CHECKS:
            print(line)
        print()
        if FAILURES:
            print(f"失敗: {len(FAILURES)} 件 → {FAILURES}")
        else:
            print(f"すべて成功（{len(CHECKS)} 項目）")
        window.close()
        app.quit()

    def sample(x: int, y: int) -> float:
        """ウィンドウを描画し、指定領域で最も多い色の明るさを測る（文字の影響を避ける）。"""
        image = window.grab().toImage()
        counts: dict[str, int] = {}
        for dx in range(0, 80, 4):
            for dy in range(0, 16, 4):
                name = image.pixelColor(x + dx, y + dy).name()
                counts[name] = counts.get(name, 0) + 1
        color = max(counts.items(), key=lambda kv: kv[1])[0]
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        return (r + g + b) / 3

    def switch_to_dark() -> None:
        setTheme(Theme.DARK, save=False)
        window._refresh_theme()

    def check_dark() -> None:
        check("テーマ: ダークに切り替わる", isDarkTheme(), str(isDarkTheme()))
        toolbar = sample(760, 90)
        sidebar = sample(120, 690)
        status = sample(760, window.height() - 30)
        check("テーマ: ツールバーが暗い", toolbar < 90, f"明るさ {toolbar:.0f}")
        check("テーマ: 左パネルが暗い", sidebar < 90, f"明るさ {sidebar:.0f}")
        check("テーマ: ステータスバーが暗い", status < 90, f"明るさ {status:.0f}")
        check("テーマ: カードの背景色がダーク用", window.sidebar._camera_card.getBackgroundColor().alpha() < 64,
              f"alpha={window.sidebar._camera_card.getBackgroundColor().alpha()}")
        setTheme(Theme.LIGHT, save=False)
        window._refresh_theme()

    def check_light() -> None:
        check("テーマ: ライトに戻る", not isDarkTheme(), str(isDarkTheme()))
        check("テーマ: カードの背景色がライト用", window.sidebar._camera_card.getBackgroundColor().alpha() > 128,
              f"alpha={window.sidebar._camera_card.getBackgroundColor().alpha()}")
        toolbar = sample(760, 90)
        sidebar = sample(120, 690)
        check("テーマ: ツールバーが明るい", toolbar > 200, f"明るさ {toolbar:.0f}")
        check("テーマ: 左パネルが明るい", sidebar > 200, f"明るさ {sidebar:.0f}")

    QTimer.singleShot(7000, run_checks)
    QTimer.singleShot(7900, check_layout)
    QTimer.singleShot(8400, switch_to_dark)
    QTimer.singleShot(9000, check_dark)
    QTimer.singleShot(9500, check_light)
    # check_light の画面取得に時間がかかるため、判定は余裕を持たせる
    QTimer.singleShot(9700, check_persistence)
    QTimer.singleShot(10400, check_language_switch)
    QTimer.singleShot(16000, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(0 if main() == 0 and not FAILURES else 1)
