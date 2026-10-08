"""日本語 / English の表示切り替え."""

from __future__ import annotations

from PySide6.QtCore import QLocale, QSettings

DEFAULT_LANGUAGE = "ja"
LANGUAGE_NAMES = {"ja": "日本語", "en": "English"}

# 実行時に切り替えるため、モジュール変数で保持する
_current = DEFAULT_LANGUAGE


def available_languages() -> dict[str, str]:
    return dict(LANGUAGE_NAMES)


def system_language() -> str:
    """OS の言語設定から初期値を決める（日本語環境なら ja）。"""
    try:
        name = QLocale.system().name()  # 例: 'ja_JP', 'en_US'
    except Exception:  # noqa: BLE001
        return DEFAULT_LANGUAGE
    return "ja" if name.lower().startswith("ja") else "en"


def load_saved_language() -> str:
    """設定に保存された言語（無ければ OS の言語）を返す。"""
    settings = QSettings("SDPhotoViewer", "SDPhotoViewer")
    saved = str(settings.value("language", "") or "")
    if saved in LANGUAGE_NAMES:
        return saved
    return system_language()


def save_language(code: str) -> None:
    QSettings("SDPhotoViewer", "SDPhotoViewer").setValue("language", code)


def set_language(code: str) -> None:
    global _current
    if code in LANGUAGE_NAMES:
        _current = code


def current_language() -> str:
    return _current


def is_japanese() -> bool:
    return _current == "ja"


def tr(key: str, **kwargs) -> str:
    """翻訳文字列を取得する。未定義のキーはキー名をそのまま返す。"""
    table = _STRINGS.get(key)
    if table is None:
        return key
    text = table.get(_current) or table.get(DEFAULT_LANGUAGE) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def n_files(n: int) -> str:
    """ファイル数の表記（日本語: 42 枚 / 英語: 42 files）。"""
    return tr("unit.files", n=f"{n:,}")


def n_photos(n: int) -> str:
    return tr("unit.photos", n=f"{n:,}")


# --------------------------------------------------------------------------
# 翻訳テーブル
# --------------------------------------------------------------------------

_STRINGS: dict[str, dict[str, str]] = {
    # ---- アプリ ----
    "app.title": {"ja": "SD フォトビューア", "en": "SD Photo Viewer"},
    "app.viewer_title": {"ja": "写真ビューア", "en": "Photo Viewer"},
    # ---- 単位 ----
    "unit.files": {"ja": "{n} 枚", "en": "{n} files"},
    "unit.photos": {"ja": "写真 {n} 枚", "en": "{n} photos"},
    "unit.videos": {"ja": "動画 {n} 本", "en": "{n} videos"},
    # ---- 共通 ----
    "common.reload": {"ja": "再読み込み", "en": "Reload"},
    "common.reload_tip": {"ja": "再読み込み（F5）", "en": "Reload (F5)"},
    "common.choose_folder": {"ja": "フォルダを選択…", "en": "Choose folder…"},
    "common.loading": {"ja": "読み込み中…", "en": "Loading…"},
    "common.unknown": {"ja": "不明", "en": "Unknown"},
    "common.none": {"ja": "なし", "en": "None"},
    "common.close": {"ja": "閉じる", "en": "Close"},
    "common.play": {"ja": "再生", "en": "Play"},
    "common.video": {"ja": "動画", "en": "Video"},
    "common.photo": {"ja": "写真", "en": "Photo"},
    # ---- サイドバー ----
    "sidebar.sources": {"ja": "取り込み元", "en": "Sources"},
    "sidebar.no_source": {
        "ja": "SD カードが見つかりません。下のボタンからフォルダを選択してください。",
        "en": "No SD card found. Use the button below to choose a folder.",
    },
    "sidebar.include_fixed": {"ja": "ローカルディスクも表示", "en": "Show internal drives"},
    "sidebar.include_fixed_tip": {
        "ja": "内蔵ドライブ（C: や D: など）も一覧に表示します。\n写真が大量にある場合は読み込みに時間がかかります。",
        "en": "Also list internal drives (C:, D:, …).\nLoading can take a while if there are many files.",
    },
    "sidebar.camera_info": {"ja": "カメラ情報", "en": "Camera info"},
    "sidebar.model": {"ja": "機種", "en": "Model"},
    "sidebar.lens": {"ja": "レンズ", "en": "Lens"},
    "sidebar.period": {"ja": "撮影期間", "en": "Period"},
    "sidebar.count": {"ja": "枚数", "en": "Files"},
    "sidebar.image_size": {"ja": "画像サイズ", "en": "Resolution"},
    "sidebar.gps": {"ja": "位置情報", "en": "Location"},
    "sidebar.capacity": {"ja": "容量", "en": "Storage"},
    "sidebar.capacity_detail": {
        "ja": "容量　使用 {used} / {total}　（空き {free}）",
        "en": "Used {used} of {total} ({free} free)",
    },
    "sidebar.capacity_used": {"ja": "容量　使用 {used} / {total}", "en": "Used {used} of {total}"},
    "sidebar.folders": {"ja": "フォルダ", "en": "Folders"},
    "sidebar.all_files": {"ja": "すべてのファイル", "en": "All files"},
    "sidebar.folders_hint": {
        "ja": "取り込み元を選択すると表示されます。",
        "en": "Choose a source to see folders.",
    },
    "sidebar.filters": {"ja": "絞り込み", "en": "Filters"},
    "sidebar.reset_filters": {"ja": "絞り込みをリセット", "en": "Reset filters"},
    "sidebar.camera": {"ja": "カメラ", "en": "Camera"},
    "sidebar.all_cameras": {"ja": "すべてのカメラ", "en": "All cameras"},
    "sidebar.period_filter": {"ja": "期間で絞り込み", "en": "Filter by date"},
    "sidebar.from": {"ja": "開始", "en": "From"},
    "sidebar.to": {"ja": "終了", "en": "To"},
    "sidebar.gps_only": {"ja": "位置情報付きのみ", "en": "With location only"},
    "sidebar.sort": {"ja": "並べ替え", "en": "Sort by"},
    "sidebar.asc": {"ja": "昇順（古い順）", "en": "Ascending (oldest first)"},
    "sidebar.desc": {"ja": "降順（新しい順）", "en": "Descending (newest first)"},
    "sidebar.support": {"ja": "形式対応: {value}", "en": "Supported: {value}"},
    # ---- 並べ替えキー ----
    "sort.datetime": {"ja": "撮影日時", "en": "Taken date"},
    "sort.name": {"ja": "ファイル名", "en": "File name"},
    "sort.size": {"ja": "ファイルサイズ", "en": "File size"},
    "sort.mtime": {"ja": "更新日時", "en": "Modified date"},
    "sort.kind": {"ja": "ファイル形式", "en": "File type"},
    # ---- 検索・一覧 ----
    "gallery.search": {"ja": "ファイル名で検索", "en": "Search file name"},
    "gallery.count": {"ja": "{count} · {size}", "en": "{count} · {size}"},
    "gallery.selected": {"ja": "選択中: {count}（{size}）", "en": "Selected: {count} ({size})"},
    "gallery.detail_toggle": {"ja": "Exif 詳細", "en": "Exif details"},
    "gallery.detail_tip": {
        "ja": "タイルに表示する Exif 情報を増やします",
        "en": "Show more Exif info on each tile",
    },
    "gallery.scanning": {"ja": "スキャン中… {count} 件", "en": "Scanning… {count}"},
    "gallery.meta_progress": {
        "ja": "Exif 情報を読み込み中… {done} / {total}",
        "en": "Reading metadata… {done} / {total}",
    },
    "gallery.zoom_out_tip": {"ja": "タイルを小さく", "en": "Smaller tiles"},
    "gallery.zoom_in_tip": {"ja": "タイルを大きく", "en": "Larger tiles"},
    "gallery.theme_tip": {"ja": "ライト / ダークの切り替え", "en": "Toggle light / dark theme"},
    "gallery.language_tip": {"ja": "言語: 日本語 / English", "en": "Language: English / 日本語"},
    # ---- 空の状態 ----
    "empty.title": {"ja": "SD カードを選択してください", "en": "Choose an SD card"},
    "empty.body": {
        "ja": "左の「取り込み元」から SD カードやフォルダを選ぶと、写真がタイル状に並びます。\n"
              "フォルダをこの画面にドラッグ＆ドロップしても開けます。",
        "en": "Pick an SD card or folder under “Sources” on the left and your photos appear as tiles.\n"
              "You can also drag & drop a folder onto this window.",
    },
    "empty.no_card_title": {"ja": "SD カードが見つかりません", "en": "No SD card found"},
    "empty.no_card_body": {
        "ja": "SD カードを挿して「更新」を押してください。\n"
              "ローカルディスクの写真を見たいときは、左の「ローカルディスクも表示」をオンにするか、"
              "「フォルダを選択…」で選んでください。",
        "en": "Insert an SD card and press Reload.\n"
              "To browse photos on an internal drive, turn on “Show internal drives” on the left, "
              "or use “Choose folder…”.",
    },
    "empty.no_media_title": {"ja": "写真・動画が見つかりませんでした", "en": "No photos or videos found"},
    "empty.no_media_body": {
        "ja": "{path}\nに写真・動画が見つかりませんでした。",
        "en": "Nothing was found in\n{path}",
    },
    "empty.filtered_title": {"ja": "条件に一致する写真がありません", "en": "No files match the filters"},
    "empty.filtered_body": {
        "ja": "絞り込み条件を変更するか、リセットしてください。",
        "en": "Change the filters or reset them.",
    },
    "empty.folder_title": {"ja": "このフォルダに写真がありません", "en": "No files in this folder"},
    "empty.folder_body": {"ja": "別のフォルダを選択してください。", "en": "Choose another folder."},
    # ---- タイル ----
    "tile.no_datetime": {"ja": "日時不明", "en": "Unknown date"},
    "tile.no_camera": {"ja": "カメラ情報なし", "en": "No camera info"},
    "tile.no_lens": {"ja": "レンズ情報なし", "en": "No lens info"},
    "tile.no_preview": {"ja": "プレビューを作成できません", "en": "No preview available"},
    "tile.video_needs_ffmpeg": {"ja": "ffmpeg が必要です", "en": "ffmpeg is required"},
    "tile.tooltip_folder": {"ja": "フォルダ", "en": "Folder"},
    "tile.tooltip_taken": {"ja": "撮影日時", "en": "Taken"},
    "tile.tooltip_camera": {"ja": "カメラ", "en": "Camera"},
    "tile.tooltip_lens": {"ja": "レンズ", "en": "Lens"},
    "tile.tooltip_exposure": {"ja": "露出", "en": "Exposure"},
    "tile.tooltip_adjust": {"ja": "補正/WB", "en": "Comp./WB"},
    "tile.tooltip_image": {"ja": "画像", "en": "Image"},
    "tile.tooltip_location": {"ja": "位置情報", "en": "Location"},
    "tile.tooltip_size": {"ja": "サイズ", "en": "Size"},
    "tile.tooltip_type": {"ja": "形式", "en": "Type"},
    "tile.tooltip_duration": {"ja": "再生時間", "en": "Duration"},
    # ---- コンテキストメニュー ----
    "menu.open_large": {"ja": "大表示で開く", "en": "Open in viewer"},
    "menu.open_default": {"ja": "既定のアプリで開く", "en": "Open with default app"},
    "menu.play_video": {"ja": "動画を再生", "en": "Play video"},
    "menu.reveal": {"ja": "エクスプローラーで表示", "en": "Show in folder"},
    "menu.copy_path": {"ja": "パスをコピー", "en": "Copy path"},
    "menu.copy_exif": {"ja": "Exif 情報をコピー", "en": "Copy Exif info"},
    "menu.copy_image": {"ja": "画像をコピー", "en": "Copy image"},
    "menu.clear_selection": {"ja": "選択を解除", "en": "Clear selection"},
    "toast.copied": {"ja": "クリップボードにコピーしました", "en": "Copied to the clipboard"},
    "toast.copied_exif": {"ja": "Exif 情報をコピーしました", "en": "Exif info copied"},
    "toast.copied_image": {"ja": "サムネイル画像をコピーしました", "en": "Thumbnail copied to the clipboard"},
    "toast.wait_loading": {
        "ja": "読み込みが終わってから再度お試しください",
        "en": "Please try again once loading has finished",
    },
    "toast.scan_failed": {"ja": "スキャンに失敗しました: {error}", "en": "Scan failed: {error}"},
    "toast.folder_not_found": {"ja": "フォルダが見つかりません", "en": "Folder not found"},
    "info.local_on_title": {"ja": "ローカルディスクを表示します", "en": "Showing internal drives"},
    "info.local_on_body": {
        "ja": "内蔵ドライブの写真も一覧に出ます。枚数が多いと読み込みに時間がかかります。",
        "en": "Photos on internal drives will appear too. Loading can be slow if there are many files.",
    },
    "info.lang_switched": {"ja": "言語を切り替えました", "en": "Language switched"},
    "warn.codec_title": {"ja": "一部の形式を表示できません", "en": "Some formats cannot be shown"},
    "warn.heic": {
        "ja": "HEIC の表示に pillow-heif が必要です（pip install pillow-heif）",
        "en": "HEIC needs pillow-heif (pip install pillow-heif)",
    },
    "warn.raw": {
        "ja": "RAW のプレビューに rawpy が必要です（pip install rawpy）",
        "en": "RAW previews need rawpy (pip install rawpy)",
    },
    "warn.video": {
        "ja": "動画のサムネイルに ffmpeg が必要です（pip install imageio-ffmpeg でも可）",
        "en": "Video thumbnails need ffmpeg (or: pip install imageio-ffmpeg)",
    },
    "dialog.choose_folder": {
        "ja": "写真フォルダ（SD カード）を選択",
        "en": "Choose a photo folder (SD card)",
    },
    # ---- 取り込み元の説明 ----
    "source.card_layout": {"ja": "カメラの SD カード構成（DCIM）", "en": "Camera SD card (DCIM)"},
    "source.detected": {"ja": "{value}を検出", "en": "Detected {value}"},
    "source.free": {"ja": "空き {free} / {total}", "en": "{free} free of {total}"},
    "source.folder": {"ja": "フォルダ", "en": "Folder"},
    "source.photo_folder": {"ja": "写真フォルダ（{name}）", "en": "Photo folder ({name})"},
    "source.summary": {"ja": "写真・動画 {n} ／ {size}", "en": "{n} · {size}"},
    "source.media_root": {"ja": "{root} / {name}", "en": "{root} / {name}"},
    # ---- カメラ情報 ----
    "stats.kinds": {"ja": "JPEG {jpeg} / HEIC {heic} / RAW {raw} / 動画 {video}", "en": "JPEG {jpeg} / HEIC {heic} / RAW {raw} / Video {video}"},
    "stats.gps_count": {"ja": "{n} 枚に付与", "en": "{n} files"},
    "stats.period_range": {"ja": "{a} 〜 {b}", "en": "{a} – {b}"},
    "stats.resolution_size": {"ja": "{size}　{bytes}", "en": "{size}　{bytes}"},
    # ---- ビューア ----
    "viewer.metadata_title": {"ja": "撮影情報（Exif）", "en": "Metadata (Exif)"},
    "viewer.copy_tip": {"ja": "Exif 情報をコピー", "en": "Copy Exif info"},
    "viewer.info_tip": {"ja": "Exif 情報パネルの表示 / 非表示", "en": "Show / hide the metadata panel"},
    "viewer.open_tip": {"ja": "既定のアプリで開く", "en": "Open with default app"},
    "viewer.reveal_tip": {"ja": "エクスプローラーで表示", "en": "Show in folder"},
    "viewer.close_tip": {"ja": "閉じる（Esc）", "en": "Close (Esc)"},
    "viewer.prev_tip": {"ja": "前の写真（←）", "en": "Previous (←)"},
    "viewer.next_tip": {"ja": "次の写真（→）", "en": "Next (→)"},
    "viewer.fit": {"ja": "ウィンドウに合わせる", "en": "Fit to window"},
    "viewer.actual": {"ja": "100%", "en": "100%"},
    "viewer.play_video": {"ja": "既定のアプリで再生", "en": "Play with default app"},
    "viewer.cannot_show": {"ja": "この画像は表示できませんでした。{hint}", "en": "This file could not be shown. {hint}"},
    "viewer.hint_heic": {"ja": "HEIC の表示には pillow-heif が必要です。", "en": "Showing HEIC needs pillow-heif."},
    "viewer.hint_raw": {"ja": "RAW の表示には rawpy が必要です。", "en": "Showing RAW needs rawpy."},
    "viewer.hint_video": {
        "ja": "動画のサムネイルには ffmpeg が必要です。",
        "en": "Video thumbnails need ffmpeg.",
    },
    "viewer.load_error": {"ja": "読み込みエラー: {error}", "en": "Load error: {error}"},
    "viewer.counter": {"ja": "{index} / {total}", "en": "{index} / {total}"},
    # ---- Exif セクション ----
    "exif.section.shooting": {"ja": "撮影情報", "en": "Shooting"},
    "exif.section.camera": {"ja": "カメラ / レンズ", "en": "Camera / Lens"},
    "exif.section.image": {"ja": "画像", "en": "Image"},
    "exif.section.location": {"ja": "位置情報", "en": "Location"},
    "exif.section.file": {"ja": "ファイル", "en": "File"},
    "exif.section.video": {"ja": "動画", "en": "Video"},
    # ---- Exif 項目名 ----
    "exif.unknown": {"ja": "不明なカメラ", "en": "Unknown camera"},
    "exif.status": {"ja": "状態", "en": "Status"},
    "exif.no_exif": {"ja": "Exif 情報を読み込めませんでした", "en": "No Exif data could be read"},
    "exif.filename": {"ja": "ファイル名", "en": "File name"},
    "exif.format": {"ja": "形式", "en": "Type"},
    "exif.filesize": {"ja": "ファイルサイズ", "en": "File size"},
    "exif.folder": {"ja": "フォルダ", "en": "Folder"},
    "exif.modified": {"ja": "更新日時", "en": "Modified"},
    "exif.taken": {"ja": "撮影日時", "en": "Taken"},
    "exif.shutter": {"ja": "シャッタースピード", "en": "Shutter speed"},
    "exif.aperture": {"ja": "絞り（F値）", "en": "Aperture"},
    "exif.iso": {"ja": "ISO 感度", "en": "ISO"},
    "exif.focal": {"ja": "焦点距離", "en": "Focal length"},
    "exif.exposure_bias": {"ja": "露出補正", "en": "Exposure comp."},
    "exif.exposure_program": {"ja": "露出プログラム", "en": "Exposure program"},
    "exif.exposure_mode": {"ja": "露出モード", "en": "Exposure mode"},
    "exif.metering": {"ja": "測光モード", "en": "Metering mode"},
    "exif.white_balance": {"ja": "ホワイトバランス", "en": "White balance"},
    "exif.flash": {"ja": "フラッシュ", "en": "Flash"},
    "exif.make": {"ja": "メーカー", "en": "Make"},
    "exif.model": {"ja": "機種", "en": "Model"},
    "exif.lens": {"ja": "レンズ", "en": "Lens"},
    "exif.lens_make": {"ja": "レンズメーカー", "en": "Lens make"},
    "exif.body_serial": {"ja": "ボディシリアル", "en": "Body serial"},
    "exif.software": {"ja": "ソフトウェア", "en": "Software"},
    "exif.artist": {"ja": "撮影者", "en": "Artist"},
    "exif.copyright": {"ja": "著作権", "en": "Copyright"},
    "exif.dimensions": {"ja": "画像サイズ", "en": "Resolution"},
    "exif.aspect": {"ja": "アスペクト比", "en": "Aspect ratio"},
    "exif.megapixels": {"ja": "画素数", "en": "Megapixels"},
    "exif.color_space": {"ja": "色空間", "en": "Color space"},
    "exif.latitude": {"ja": "緯度", "en": "Latitude"},
    "exif.longitude": {"ja": "経度", "en": "Longitude"},
    "exif.altitude": {"ja": "高度", "en": "Altitude"},
    "exif.duration": {"ja": "再生時間", "en": "Duration"},
    "exif.resolve": {"ja": "地図で開く", "en": "Open in maps"},
    # ---- Exif の値 ----
    "exif.auto": {"ja": "オート", "en": "Auto"},
    "exif.manual": {"ja": "マニュアル", "en": "Manual"},
    "exif.flash_fired": {"ja": "発光", "en": "Fired"},
    "exif.flash_off": {"ja": "非発光", "en": "Did not fire"},
    "exif.program.0": {"ja": "未定義", "en": "Not defined"},
    "exif.program.1": {"ja": "マニュアル", "en": "Manual"},
    "exif.program.2": {"ja": "プログラムAE", "en": "Program AE"},
    "exif.program.3": {"ja": "絞り優先AE", "en": "Aperture priority"},
    "exif.program.4": {"ja": "シャッター優先AE", "en": "Shutter priority"},
    "exif.program.5": {"ja": "クリエイティブ", "en": "Creative"},
    "exif.program.6": {"ja": "アクション", "en": "Action"},
    "exif.program.7": {"ja": "ポートレート", "en": "Portrait"},
    "exif.program.8": {"ja": "風景", "en": "Landscape"},
    "exif.program.other": {"ja": "モード{value}", "en": "Mode {value}"},
    "exif.metering.0": {"ja": "不明", "en": "Unknown"},
    "exif.metering.1": {"ja": "平均", "en": "Average"},
    "exif.metering.2": {"ja": "中央重点", "en": "Center-weighted"},
    "exif.metering.3": {"ja": "スポット", "en": "Spot"},
    "exif.metering.4": {"ja": "マルチスポット", "en": "Multi-spot"},
    "exif.metering.5": {"ja": "評価測光", "en": "Evaluative"},
    "exif.metering.6": {"ja": "部分測光", "en": "Partial"},
    "exif.metering.255": {"ja": "その他", "en": "Other"},
    "exif.metering.other": {"ja": "測光{value}", "en": "Metering {value}"},
    "exif.wb.0": {"ja": "オート", "en": "Auto"},
    "exif.wb.1": {"ja": "マニュアル", "en": "Manual"},
    "exif.mode.0": {"ja": "オート露出", "en": "Auto exposure"},
    "exif.mode.1": {"ja": "マニュアル露出", "en": "Manual exposure"},
    "exif.mode.2": {"ja": "オートブラケット", "en": "Auto bracket"},
    "exif.cs.1": {"ja": "sRGB", "en": "sRGB"},
    "exif.cs.2": {"ja": "AdobeRGB", "en": "AdobeRGB"},
    "exif.focal_equiv": {"ja": "{mm}mm（{mm35}mm 相当）", "en": "{mm}mm ({mm35}mm equiv.)"},
    "exif.focal_plain": {"ja": "{mm}mm", "en": "{mm}mm"},
    "exif.ev": {"ja": "{value} EV", "en": "{value} EV"},
    "exif.size_b": {"ja": "{value} B", "en": "{value} B"},
    # ---- 形式の説明 ----
    "format.support": {
        "ja": "JPEG/PNG ほか（Qt） ／ HEIC{heic} ／ RAW{raw} ／ 動画{video}",
        "en": "JPEG/PNG (Qt) / HEIC {heic} / RAW {raw} / Video {video}",
    },
    "format.yes": {"ja": "対応", "en": "yes"},
    "format.no_heif": {"ja": "未導入（pip install pillow-heif）", "en": "missing (pip install pillow-heif)"},
    "format.no_rawpy": {"ja": "未導入（pip install rawpy）", "en": "missing (pip install rawpy)"},
    "format.no_video": {"ja": "未導入（pip install imageio-ffmpeg）", "en": "missing (pip install imageio-ffmpeg)"},
    "kind.jpeg": {"ja": "JPEG", "en": "JPEG"},
    "kind.heic": {"ja": "HEIC", "en": "HEIC"},
    "kind.raw": {"ja": "RAW", "en": "RAW"},
    "kind.video": {"ja": "動画", "en": "Video"},
    "kind.other": {"ja": "その他", "en": "Other"},
    # ---- アプリについて（ライセンス表示） ----
    "about.tip": {"ja": "アプリについて", "en": "About this app"},
    "about.title": {"ja": "SD フォトビューア について", "en": "About SD Photo Viewer"},
    "about.content": {
        "ja": (
            "SD フォトビューア バージョン {version}\n\n"
            "{copyright}\n\n"
            "このソフトは {license} で公開されています。どなたでも自由に使えますが、"
            "無保証です（動作の保証はしません）。再配布・改変も同じライセンスの条件で自由に行えます。"
        ),
        "en": (
            "SD Photo Viewer version {version}\n\n"
            "{copyright}\n\n"
            "This program is released under the {license}. You may use it freely, "
            "but it comes with ABSOLUTELY NO WARRANTY. Redistribution and modification "
            "are also free under the same license."
        ),
    },
    "about.source_line": {"ja": "ソースコード: {url}", "en": "Source code: {url}"},
    "about.third_party": {
        "ja": "同梱ライブラリ: PySide6（LGPLv3）／PySide6-Fluent-Widgets（GPLv3）／Pillow／numpy ほか\n詳しくは、アプリと同じフォルダの THIRD_PARTY_LICENSES.md をご覧ください。",
        "en": "Bundled libraries: PySide6 (LGPLv3) / PySide6-Fluent-Widgets (GPLv3) / Pillow / numpy, etc.\nSee THIRD_PARTY_LICENSES.md in the same folder as the app.",
    },
    "about.source_button": {"ja": "ソースコードを開く", "en": "Open source code"},
    "about.no_source": {
        "ja": "ソースコード: 公開準備中です（公開後、この欄に入手先を掲載します）",
        "en": "Source code: publication in preparation (the download link will appear here).",
    },
    "about.contact": {"ja": "連絡先: {contact}", "en": "Contact: {contact}"},
}
