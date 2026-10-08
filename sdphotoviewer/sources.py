"""SD カード / ドライブ / フォルダの検出とフォルダ走査."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from PySide6.QtCore import QDir, QStorageInfo

from . import i18n
from .imaging import is_media

# 実体の無い（写真が入っていない）マウントは一覧から除く
_SKIP_FS = {
    "tmpfs", "devtmpfs", "devfs", "proc", "sysfs", "cgroup", "cgroup2", "overlay", "squashfs",
    "autofs", "ramfs", "debugfs", "tracefs", "securityfs", "pstore", "bpf", "configfs", "fusectl",
    "mqueue", "hugetlbfs", "nsfs", "binfmt_misc", "efivarfs", "selinuxfs", "rpc_pipefs",
}
_SKIP_PATHS = ("/etc/ssl/certs", "/etc/hosts", "/run/lock", "/boot/efi")


@dataclass
class Source:
    """左側に並べる「取り込み元」。"""

    path: str
    kind: str  # 'drive' | 'folder'
    name: str
    detail: str = ""
    removable: bool = False
    total_bytes: int | None = None
    free_bytes: int | None = None
    photo_count: int | None = None

    @property
    def id(self) -> str:
        return os.path.normcase(os.path.abspath(self.path))


@dataclass
class FolderNode:
    """フォルダツリーの1ノード。"""

    path: str
    name: str
    rel: str
    count: int = 0
    depth: int = 0
    children: list["FolderNode"] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.count + sum(c.total for c in self.children)


# --------------------------------------------------------------------------
# 取り込み元の検出
# --------------------------------------------------------------------------


def discover_sources(include_fixed: bool = False) -> list[Source]:
    """取り込み元（SD カード・USB メモリ・メディアフォルダ）を列挙する。

    既定では **リムーバブルディスクのみ** を返す。内蔵のローカルディスク（C: など）は
    写真の枚数が膨大で走査が重くなるため対象外とし、ユーザーが明示的に
    「ローカルディスクも表示」を選んだとき（include_fixed=True）だけ加える。
    ただし、カードリーダーが固定ディスクとして認識される場合があるので、
    ドライブ直下に DCIM / PRIVATE があるものは対象に残す。
    """
    found: dict[str, Source] = {}
    system_drive = os.path.normcase((os.environ.get("SystemDrive") or "") + "\\")

    for info in _iter_storage_infos():
        path = info.rootPath()
        if not path or not info.isReady():
            continue
        if _is_pseudo_mount(info):
            continue
        removable = _is_removable(path)
        is_card = _has_card_layout(path)
        if not removable and not include_fixed and not is_card:
            continue  # 内蔵ディスクは既定では対象外
        if not removable and not include_fixed and system_drive and os.path.normcase(path) == system_drive:
            continue  # システムドライブだけは誤検出でも除外
        label = (info.displayName() or "").strip() or (info.name() or "").strip()
        if not label:
            label = path
        detail = _capacity_text(info)
        if is_card:
            card_hint = i18n.tr("source.card_layout")
            detail = f"{detail}　／　{card_hint}" if detail else card_hint
        found[os.path.normcase(path)] = Source(
            path=path,
            kind="drive",
            name=label,
            detail=detail,
            removable=removable or is_card,
            total_bytes=info.bytesTotal() or None,
            free_bytes=info.bytesAvailable() or None,
        )

    # Linux / macOS: /media/... , /Volumes/... などのメディアフォルダ
    for media_root in _media_roots():
        try:
            entries = sorted(os.scandir(media_root), key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue
            path = entry.path
            if os.path.normcase(path) in found:
                continue
            label = i18n.tr("source.media_root", root=os.path.basename(os.path.normpath(media_root)), name=entry.name)
            found[os.path.normcase(path)] = Source(
                path=path,
                kind="drive",
                name=label,
                detail=_quick_hint(path),  # 中身は走査しない（起動を軽くするため）
                removable=True,
            )

    sources = list(found.values())
    sources.sort(key=lambda s: (not s.removable, s.name.lower()))
    return sources


def _has_card_layout(path: str) -> bool:
    """ドライブ直下がカメラの SD カード構成かどうかを、走査せずに判定する。"""
    try:
        for name in ("DCIM", "PRIVATE", "MISC"):
            if os.path.isdir(os.path.join(path, name)):
                return True
    except OSError:
        pass
    return False


def card_layout_hint() -> str:
    return i18n.tr("source.card_layout")


def _is_pseudo_mount(info: QStorageInfo) -> bool:
    """tmpfs などの疑似マウントかどうか（Linux/macOS 用の除外処理）。"""
    if sys.platform.startswith("win"):
        return False
    fs_type = bytes(info.fileSystemType()).decode("utf-8", "ignore").lower()
    if fs_type in _SKIP_FS:
        return True
    root = info.rootPath() or ""
    if any(root.startswith(p) for p in _SKIP_PATHS):
        return True
    if fs_type in ("msdos", "vfat", "exfat", "ntfs"):
        return False  # SD カード（FAT32/exFAT）は残す
    if root in ("/run", "/var/run", "/dev/shm", "/sys"):
        return True
    return False


def _iter_storage_infos():
    try:
        infos = list(QStorageInfo.mountedVolumes())
    except Exception:  # noqa: BLE001
        infos = [QStorageInfo(str(d.absolutePath())) for d in QDir.drives()]
    for info in infos:
        root = info.rootPath()
        if not root:
            continue
        if sys.platform.startswith("win") and len(root) > 3 and not root.endswith("\\"):
            continue
        if not sys.platform.startswith("win") and not info.isReady():
            continue
        yield info


def _media_roots() -> list[str]:
    if sys.platform.startswith("win"):
        return []
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    roots = [
        f"/media/{user}" if user else "/media",
        f"/run/media/{user}" if user else "/run/media",
        "/mnt",
        "/Volumes",
    ]
    return [r for r in roots if r and os.path.isdir(r)]


def _is_removable(path: str) -> bool:
    """リムーバブル（SD カード / USB）かどうかを推定する。"""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            drive = os.path.splitdrive(path)[0]
            if not drive:
                return False
            DRIVE_REMOVABLE, DRIVE_CDROM, DRIVE_RAMDISK = 2, 5, 6
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\")
            return drive_type in (DRIVE_REMOVABLE, DRIVE_CDROM, DRIVE_RAMDISK)
        except Exception:  # noqa: BLE001
            return False
    lowered = path.lower()
    return any(lowered.startswith(p) for p in ("/media", "/run/media", "/volumes", "/mnt"))


def storage_info(path: str) -> Source | None:
    """1つのパスから容量情報などを取得する。"""
    info = QStorageInfo(path)
    if not info.isValid():
        return None
    return Source(
        path=path,
        kind="drive",
        name=(info.displayName() or info.name() or path).strip(),
        detail=_capacity_text(info),
        removable=_is_removable(path),
        total_bytes=info.bytesTotal() or None,
        free_bytes=info.bytesAvailable() or None,
    )


def source_from_folder(path: str) -> Source:
    path = os.path.abspath(path)
    info = storage_info(path)
    detail = _quick_hint(path)
    if info and info.total_bytes:
        detail = f"{detail}　／　空き {_gb(info.free_bytes)} / {_gb(info.total_bytes)}"
    return Source(path=path, kind="folder", name=os.path.basename(path.rstrip("\\/")) or path, detail=detail)


def _capacity_text(info: QStorageInfo) -> str:
    total = info.bytesTotal() or 0
    free = info.bytesAvailable() or 0
    if not total:
        return ""
    return i18n.tr("source.free", free=_gb(free), total=_gb(total))


def _gb(num_bytes: int | None) -> str:
    if not num_bytes:
        return "—"
    return f"{num_bytes / 1024 ** 3:.1f} GB"


def _quick_hint(path: str) -> str:
    """フォルダの種類を、中身を走査せずに判定する。

    起動時に大量のファイルを数えると重くなるため、ここでは判定だけ行い、
    実際の枚数は読み込んだあとに表示する。
    """
    if _has_card_layout(path):
        return card_layout_hint()
    for name in ("Pictures", "Photos", "写真", "画像", "DCIM"):
        if os.path.isdir(os.path.join(path, name)):
            return i18n.tr("source.photo_folder", name=name)
    return i18n.tr("source.folder")


# --------------------------------------------------------------------------
# 走査
# --------------------------------------------------------------------------


def scan_photo_files(root: str, recursive: bool = True):
    """写真ファイルを列挙する（走査対象は DCIM などを優先）。"""
    root = os.path.abspath(root)
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in ("$recycle.bin", "system volume information")]
            for name in filenames:
                if is_media(name):
                    yield os.path.join(dirpath, name)
    else:
        try:
            entries = os.scandir(root)
        except OSError:
            return
        with entries:
            for entry in entries:
                try:
                    if entry.is_file() and is_media(entry.name):
                        yield entry.path
                except OSError:
                    continue


def list_photo_folders(root: str, max_depth: int = 3) -> FolderNode:
    """写真を含むフォルダをツリー状にまとめる。"""
    root = os.path.abspath(root)
    node = FolderNode(path=root, name=os.path.basename(root.rstrip("\\/")) or root, rel="", depth=0)

    def build(current: FolderNode, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(current.path), key=lambda e: e.name.lower())
        except OSError:
            return
        for entry in entries:
            try:
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
            except OSError:
                continue
            direct = 0
            try:
                with os.scandir(entry.path) as files:
                    for f in files:
                        try:
                            if f.is_file() and is_media(f.name):
                                direct += 1
                        except OSError:
                            continue
            except OSError:
                pass
            child = FolderNode(
                path=entry.path,
                name=entry.name,
                rel=os.path.relpath(entry.path, root),
                count=direct,
                depth=depth + 1,
            )
            build(child, depth + 1)
            if child.total > 0:
                # 直下と上位フォルダ名の重複を避けるため、深い階層は末端だけ残す
                if child.count == 1 and len(child.children) == 1:
                    grand = child.children[0]
                    if grand.name.lower() in ("dcim", "photos", "picture", "pictures"):
                        child = grand
                        child.depth = depth + 1
                current.children.append(child)

    build(node, 1)
    node.count = sum(1 for _ in scan_photo_files(root, recursive=False))
    return node


def dcim_hint(root: str) -> str:
    """SD カードらしいフォルダ構成かどうかを示すヒント文字列。"""
    if _has_card_layout(root):
        return i18n.tr("source.detected", value=card_layout_hint())
    return ""


def explorer_reveal(path: str) -> None:
    """エクスプローラー / ファイラでファイルを選択表示する。"""
    import subprocess

    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])
    except Exception:  # noqa: BLE001
        pass
