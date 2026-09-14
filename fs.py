"""Local filesystem sandbox for the WebUI file explorer."""

from __future__ import annotations

import mimetypes
import os
import shutil
import stat
import string
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TEXT_EXTS = {
    "txt",
    "md",
    "markdown",
    "json",
    "yaml",
    "yml",
    "toml",
    "ini",
    "cfg",
    "conf",
    "log",
    "csv",
    "tsv",
    "xml",
    "html",
    "htm",
    "css",
    "js",
    "mjs",
    "cjs",
    "ts",
    "tsx",
    "jsx",
    "vue",
    "py",
    "pyi",
    "rb",
    "go",
    "rs",
    "java",
    "kt",
    "c",
    "cc",
    "cpp",
    "h",
    "hpp",
    "cs",
    "php",
    "sh",
    "bash",
    "zsh",
    "bat",
    "cmd",
    "ps1",
    "sql",
    "env",
    "gitignore",
    "dockerignore",
    "editorconfig",
    "lock",
    "properties",
    "gradle",
    "makefile",
    "cmake",
    "rst",
    "tex",
    "svg",
}

IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "svg", "avif"}
AUDIO_EXTS = {"mp3", "wav", "flac", "ogg", "m4a", "aac"}
VIDEO_EXTS = {"mp4", "webm", "mkv", "avi", "mov"}
ARCHIVE_EXTS = {"zip", "tar", "gz", "tgz", "bz2", "7z", "rar", "xz"}


class FSError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class RootEntry:
    id: str
    label: str
    path: str


def _norm(path: Path | str) -> Path:
    return Path(os.path.realpath(str(path)))


def is_within(path: Path | str, root: Path | str) -> bool:
    try:
        path_r = os.path.normcase(str(_norm(path)))
        root_r = os.path.normcase(str(_norm(root)))
    except OSError:
        return False
    if path_r == root_r:
        return True
    sep = os.sep
    if not root_r.endswith(sep):
        root_r += sep
    return path_r.startswith(root_r)


def safe_filename(name: str) -> str:
    raw = str(name or "").replace("\\", "/").strip()
    if not raw or raw in {".", ".."} or "/" in raw:
        raise FSError("非法文件名")
    if os.name == "nt" and any(ch in raw for ch in '<>:"|?*'):
        raise FSError("非法文件名")
    return raw


def list_windows_drives() -> list[Path]:
    drives: list[Path] = []
    for letter in string.ascii_uppercase:
        candidate = Path(f"{letter}:/")
        if candidate.exists():
            drives.append(candidate)
    return drives


class FileSandbox:
    def __init__(
        self,
        *,
        data_path: Path,
        extra_roots: Iterable[str] | None = None,
        allow_system_root: bool = False,
        show_hidden: bool = True,
        max_upload_mb: int = 128,
        max_preview_kb: int = 512,
    ):
        self.data_path = _norm(data_path)
        self.show_hidden = bool(show_hidden)
        self.max_upload_bytes = max(1, int(max_upload_mb)) * 1024 * 1024
        self.max_preview_bytes = max(16, int(max_preview_kb)) * 1024
        self.allow_system_root = bool(allow_system_root)
        self.roots = self._build_roots(extra_roots or [])

    def _build_roots(self, extra: Iterable[str]) -> list[RootEntry]:
        entries: list[RootEntry] = []
        seen: set[str] = set()

        def add(root_id: str, label: str, path: Path) -> None:
            try:
                resolved = _norm(path)
            except OSError:
                return
            if not resolved.exists() or not resolved.is_dir():
                return
            key = os.path.normcase(str(resolved))
            if key in seen:
                return
            seen.add(key)
            entries.append(RootEntry(id=root_id, label=label, path=str(resolved)))

        add("data", "数据目录", self.data_path)
        add("plugins", "插件", self.data_path / "plugins")
        add("plugin_data", "插件数据", self.data_path / "plugin_data")
        add("config", "配置", self.data_path / "config")
        add("logs", "日志", self.data_path / "logs")
        add("temp", "临时文件", self.data_path / "temp")
        add("workspaces", "工作区", self.data_path / "workspaces")

        for idx, raw in enumerate(extra):
            text = str(raw or "").strip()
            if not text:
                continue
            add(f"extra-{idx + 1}", Path(text).name or text, Path(text))

        if self.allow_system_root:
            if os.name == "nt":
                for drive in list_windows_drives():
                    letter = str(drive)[0]
                    add(f"drive-{letter}", f"{letter}: 盘", drive)
            else:
                add("system", "系统根目录", Path("/"))

        if not entries:
            add("data", "数据目录", self.data_path)
        return entries

    def allowed_paths(self) -> list[Path]:
        return [Path(item.path) for item in self.roots]

    def default_path(self) -> str:
        return self.roots[0].path

    def resolve(self, user_path: str | None, *, must_exist: bool = False) -> Path:
        raw = str(user_path or "").strip()
        if not raw:
            target = Path(self.default_path())
        else:
            target = Path(raw)
            if not target.is_absolute():
                target = Path(self.default_path()) / target
        parent = target.parent if not target.exists() else target
        try:
            resolved_parent = _norm(parent)
        except OSError as exc:
            raise FSError(f"无法解析路径: {exc}") from exc

        candidate = resolved_parent / target.name if not target.exists() else _norm(target)
        if not any(is_within(candidate, root) for root in self.allowed_paths()):
            raise FSError("路径不在允许的根目录内", 403)
        if must_exist and not candidate.exists():
            raise FSError("文件或目录不存在", 404)
        return candidate

    def parent_path(self, path: Path) -> str | None:
        parent = path.parent
        if path == parent:
            return None
        if not any(is_within(parent, root) for root in self.allowed_paths()):
            return None
        if os.path.normcase(str(path)) == os.path.normcase(str(parent)):
            return None
        return str(parent)

    def list_dir(self, user_path: str | None) -> dict:
        path = self.resolve(user_path, must_exist=True)
        if not path.is_dir():
            raise FSError("不是目录")
        items: list[dict] = []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    name = entry.name
                    if not self.show_hidden and name.startswith("."):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)
                    ext = "" if is_dir else Path(name).suffix.lstrip(".").lower()
                    items.append(
                        {
                            "name": name,
                            "path": str(path / name),
                            "is_dir": is_dir,
                            "is_symlink": entry.is_symlink(),
                            "size": 0 if is_dir else int(info.st_size),
                            "mtime": int(info.st_mtime),
                            "mtime_text": datetime.fromtimestamp(info.st_mtime).strftime(
                                "%Y-%m-%d %H:%M"
                            ),
                            "ext": ext,
                            "kind": _kind(is_dir, ext),
                            "mode": stat.filemode(info.st_mode),
                        }
                    )
        except PermissionError as exc:
            raise FSError("没有权限读取该目录", 403) from exc
        items.sort(key=lambda x: (not x["is_dir"], x["name"].casefold()))
        usage = None
        try:
            disk = shutil.disk_usage(path)
            usage = {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
            }
        except OSError:
            usage = None
        return {
            "path": str(path),
            "name": path.name or str(path),
            "parent": self.parent_path(path),
            "items": items,
            "count": len(items),
            "usage": usage,
        }

    def mkdir(self, parent: str, name: str) -> dict:
        dest = self.resolve(parent, must_exist=True) / safe_filename(name)
        if not any(is_within(dest, root) for root in self.allowed_paths()):
            raise FSError("路径不在允许的根目录内", 403)
        if dest.exists():
            raise FSError("已存在同名文件或目录")
        dest.mkdir(parents=False)
        return {"path": str(dest), "name": dest.name}

    def create_file(self, parent: str, name: str, content: str = "") -> dict:
        dest = self.resolve(parent, must_exist=True) / safe_filename(name)
        if dest.exists():
            raise FSError("已存在同名文件或目录")
        dest.write_text(content or "", encoding="utf-8")
        return {"path": str(dest), "name": dest.name}

    def rename(self, user_path: str, new_name: str) -> dict:
        src = self.resolve(user_path, must_exist=True)
        dest = src.parent / safe_filename(new_name)
        if dest.exists():
            raise FSError("目标名称已存在")
        if not any(is_within(dest, root) for root in self.allowed_paths()):
            raise FSError("路径不在允许的根目录内", 403)
        src.rename(dest)
        return {"path": str(dest), "name": dest.name}

    def delete(self, paths: list[str]) -> dict:
        deleted: list[str] = []
        for item in paths:
            target = self.resolve(item, must_exist=True)
            if any(
                os.path.normcase(str(target)) == os.path.normcase(root.path)
                for root in self.roots
            ):
                raise FSError("不能删除根目录")
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
            deleted.append(str(target))
        return {"deleted": deleted, "count": len(deleted)}

    def move(self, srcs: list[str], dest_dir: str, copy: bool = False) -> dict:
        dest = self.resolve(dest_dir, must_exist=True)
        if not dest.is_dir():
            raise FSError("目标不是目录")
        results: list[str] = []
        for item in srcs:
            src = self.resolve(item, must_exist=True)
            target = dest / src.name
            if os.path.normcase(str(src)) == os.path.normcase(str(target)):
                continue
            if is_within(target, src):
                raise FSError("不能将目录移动到自身内部")
            if target.exists():
                raise FSError(f"目标已存在: {target.name}")
            if copy:
                if src.is_dir():
                    shutil.copytree(src, target)
                else:
                    shutil.copy2(src, target)
            else:
                shutil.move(str(src), str(target))
            results.append(str(target))
        return {"paths": results, "count": len(results), "copy": copy}

    def read_text(self, user_path: str) -> dict:
        path = self.resolve(user_path, must_exist=True)
        if path.is_dir():
            raise FSError("不能预览目录")
        size = path.stat().st_size
        if size > self.max_preview_bytes:
            raise FSError("文件过大，无法在线预览，请下载后查看")
        data = path.read_bytes()
        text = _decode_text(data)
        return {
            "path": str(path),
            "name": path.name,
            "size": size,
            "content": text,
            "ext": path.suffix.lstrip(".").lower(),
        }

    def write_text(self, user_path: str, content: str) -> dict:
        path = self.resolve(user_path, must_exist=False)
        if path.exists() and path.is_dir():
            raise FSError("不能写入目录")
        data = content.encode("utf-8")
        if len(data) > self.max_upload_bytes:
            raise FSError("内容超过上传大小限制")
        path.write_bytes(data)
        return {"path": str(path), "size": len(data)}

    def prepare_upload_dest(self, dest_dir: str, filename: str) -> Path:
        dest = self.resolve(dest_dir, must_exist=True) / safe_filename(filename)
        if dest.exists() and dest.is_dir():
            raise FSError("目标已存在同名目录")
        return dest

    def save_upload(self, dest_dir: str, filename: str, data: bytes) -> dict:
        if len(data) > self.max_upload_bytes:
            raise FSError("文件超过上传大小限制")
        dest = self.prepare_upload_dest(dest_dir, filename)
        dest.write_bytes(data)
        return {"path": str(dest), "name": dest.name, "size": len(data)}

    def finish_upload(self, dest: Path) -> dict:
        size = dest.stat().st_size
        if size > self.max_upload_bytes:
            dest.unlink(missing_ok=True)
            raise FSError("文件超过上传大小限制")
        return {"path": str(dest), "name": dest.name, "size": size}

    def archive_dir_to_zip(self, user_path: str | Path, dest_zip: Path) -> Path:
        if isinstance(user_path, Path):
            path = user_path
        else:
            path = self.resolve(user_path, must_exist=True)
        if not path.is_dir():
            raise FSError("目标不是目录")

        base_dir = path
        root_name = base_dir.name or "archive"

        with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            empty_root = True
            for root, dirs, files in os.walk(base_dir):
                if not self.show_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    files = [f for f in files if not f.startswith(".")]
                current_path = Path(root)
                rel = current_path.relative_to(base_dir)
                if rel == Path("."):
                    arc_dir = root_name
                else:
                    arc_dir = f"{root_name}/{rel.as_posix()}"

                if not dirs and not files:
                    zf.writestr(f"{arc_dir}/", "")
                    empty_root = False
                else:
                    empty_root = False

                for f in files:
                    file_full = current_path / f
                    try:
                        if file_full.is_symlink() and not file_full.exists():
                            continue
                        resolved = _norm(file_full)
                        if not any(is_within(resolved, r) for r in self.allowed_paths()):
                            continue
                        arc_file = f"{arc_dir}/{f}"
                        zf.write(file_full, arcname=arc_file)
                    except OSError:
                        continue
            if empty_root:
                zf.writestr(f"{root_name}/", "")
        return dest_zip



def _kind(is_dir: bool, ext: str) -> str:
    if is_dir:
        return "dir"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in ARCHIVE_EXTS:
        return "archive"
    if ext in TEXT_EXTS:
        return "text"
    guessed, _ = mimetypes.guess_type(f"x.{ext}")
    if guessed:
        if guessed.startswith("image/"):
            return "image"
        if guessed.startswith("text/"):
            return "text"
        if guessed.startswith("audio/"):
            return "audio"
        if guessed.startswith("video/"):
            return "video"
    return "file"


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
