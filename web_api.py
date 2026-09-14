"""Dashboard web APIs for the file explorer."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from quart import request, send_file
from quart.wrappers.response import FileBody

from astrbot.api import logger

from .fs import IMAGE_EXTS, TEXT_EXTS, FileSandbox, FSError

PLUGIN_NAME = "astrbot_plugin_file_explorer"
API_PREFIX = f"/{PLUGIN_NAME}"
TICKET_TTL = 300


def ok(data: Any = None) -> dict[str, Any]:
    return {"status": "ok", "data": data if data is not None else {}}


def error(message: str, status: int = 400) -> tuple[dict[str, Any], int]:
    return {"status": "error", "message": str(message)}, status


class TempFileBody(FileBody):
    def __init__(self, file_path: str | Path, *, buffer_size: int | None = None) -> None:
        super().__init__(file_path, buffer_size=buffer_size)
        self._cleaned = False

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, tb: TracebackType | None
    ) -> None:
        try:
            await super().__aexit__(exc_type, exc_value, tb)
        finally:
            if not self._cleaned:
                self._cleaned = True
                try:
                    self.file_path.unlink(missing_ok=True)
                except OSError:
                    pass




class FileExplorerApi:
    def __init__(self, plugin) -> None:
        self.plugin = plugin
        self._tickets: dict[str, tuple[float, str]] = {}

    def sandbox(self) -> FileSandbox:
        return self.plugin.build_sandbox()

    def register_routes(self) -> None:
        register = self.plugin.context.register_web_api
        routes: list[tuple[str, Callable, list[str], str]] = [
            (f"{API_PREFIX}/info", self.info, ["GET"], "File explorer info"),
            (f"{API_PREFIX}/list", self.list_dir, ["GET"], "List directory"),
            (f"{API_PREFIX}/mkdir", self.mkdir, ["POST"], "Create directory"),
            (f"{API_PREFIX}/create", self.create_file, ["POST"], "Create text file"),
            (f"{API_PREFIX}/rename", self.rename, ["POST"], "Rename entry"),
            (f"{API_PREFIX}/delete", self.delete, ["POST"], "Delete entries"),
            (f"{API_PREFIX}/move", self.move, ["POST"], "Move or copy entries"),
            (f"{API_PREFIX}/read", self.read_text, ["GET"], "Read text file"),
            (f"{API_PREFIX}/write", self.write_text, ["POST"], "Write text file"),
            (f"{API_PREFIX}/preview", self.preview, ["GET"], "Preview file"),
            (f"{API_PREFIX}/preview-data", self.preview_data, ["GET"], "Preview as JSON"),
            (f"{API_PREFIX}/download", self.download, ["GET"], "Download file"),
            (f"{API_PREFIX}/upload", self.upload, ["POST"], "Upload file"),
            (f"{API_PREFIX}/upload-prepare", self.upload_prepare, ["POST"], "Prepare upload"),
            (
                f"{API_PREFIX}/upload/<ticket>",
                self.upload_ticket,
                ["POST"],
                "Upload by ticket",
            ),
        ]
        for route, handler, methods, desc in routes:
            register(route, handler, methods, desc)

    async def info(self):
        try:
            box = self.sandbox()
            return ok(
                {
                    "roots": [
                        {"id": r.id, "label": r.label, "path": r.path} for r in box.roots
                    ],
                    "default_path": box.default_path(),
                    "allow_system_root": box.allow_system_root,
                    "show_hidden": box.show_hidden,
                    "max_upload_mb": box.max_upload_bytes // (1024 * 1024),
                    "max_preview_kb": box.max_preview_bytes // 1024,
                    "platform": os_name(),
                    "username": _request_username(),
                }
            )
        except Exception as exc:
            logger.error(f"file explorer info failed: {exc}", exc_info=True)
            return error(str(exc), 500)

    async def list_dir(self):
        path = request.args.get("path")
        return await self._run(lambda box: box.list_dir(path))

    async def mkdir(self):
        def _op(box: FileSandbox, payload: dict):
            return box.mkdir(payload.get("path") or "", payload.get("name") or "")

        return await self._run_json(_op)

    async def create_file(self):
        def _op(box: FileSandbox, payload: dict):
            return box.create_file(
                payload.get("path") or "",
                payload.get("name") or "",
                payload.get("content") or "",
            )

        return await self._run_json(_op)

    async def rename(self):
        def _op(box: FileSandbox, payload: dict):
            return box.rename(payload.get("path") or "", payload.get("name") or "")

        return await self._run_json(_op)

    async def delete(self):
        def _op(box: FileSandbox, payload: dict):
            paths = payload.get("paths") or []
            if not isinstance(paths, list) or not paths:
                raise FSError("请选择要删除的文件")
            return box.delete([str(p) for p in paths])

        return await self._run_json(_op)

    async def move(self):
        def _op(box: FileSandbox, payload: dict):
            paths = payload.get("paths") or []
            dest = payload.get("dest") or ""
            copy = bool(payload.get("copy"))
            if not isinstance(paths, list) or not paths:
                raise FSError("请选择要移动的文件")
            return box.move([str(p) for p in paths], dest, copy=copy)

        return await self._run_json(_op)

    async def read_text(self):
        path = request.args.get("path") or ""
        return await self._run(lambda box: box.read_text(path))

    async def write_text(self):
        def _op(box: FileSandbox, payload: dict):
            return box.write_text(payload.get("path") or "", payload.get("content") or "")

        return await self._run_json(_op)

    async def preview_data(self):
        user_path = request.args.get("path") or ""

        def _op(box: FileSandbox):
            import base64

            path = box.resolve(user_path, must_exist=True)
            if path.is_dir():
                raise FSError("不能预览目录")
            ext = path.suffix.lstrip(".").lower()
            if ext in TEXT_EXTS:
                data = box.read_text(str(path))
                data["kind"] = "text"
                return data
            if ext in IMAGE_EXTS:
                raw = path.read_bytes()
                if len(raw) > max(box.max_preview_bytes, 8 * 1024 * 1024):
                    raise FSError("图片过大，请下载后查看")
                mime = mimetypes.guess_type(path.name)[0] or "image/png"
                return {
                    "kind": "image",
                    "name": path.name,
                    "path": str(path),
                    "size": len(raw),
                    "data_url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
                }
            raise FSError("该类型不支持预览")

        return await self._run(_op)

    async def preview(self):
        try:
            user_path = request.args.get("path") or ""
            box = self.sandbox()
            path = await asyncio.to_thread(box.resolve, user_path, must_exist=True)
            if path.is_dir():
                return error("不能预览目录")
            ext = path.suffix.lstrip(".").lower()
            if ext not in IMAGE_EXTS and ext not in TEXT_EXTS:
                return error("该类型不支持预览")
            if path.stat().st_size > box.max_preview_bytes and ext not in IMAGE_EXTS:
                return error("文件过大，无法预览")
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return await send_file(path, mimetype=mime)
        except FSError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:
            logger.error(f"file explorer preview failed: {exc}", exc_info=True)
            return error(str(exc), 500)

    async def download(self):
        try:
            user_path = request.args.get("path") or ""
            box = self.sandbox()
            path = await asyncio.to_thread(box.resolve, user_path, must_exist=True)
            if path.is_dir():
                archive_name = f"{(path.name or 'archive')}.zip"
                tmp_fd, tmp_str = tempfile.mkstemp(prefix="fe_dir_", suffix=".zip")
                os.close(tmp_fd)
                tmp_path = Path(tmp_str)
                try:
                    await asyncio.to_thread(box.archive_dir_to_zip, path, tmp_path)
                    try:
                        resp = await send_file(
                            tmp_path, as_attachment=True, attachment_filename=archive_name
                        )
                    except TypeError:
                        resp = await send_file(
                            tmp_path, as_attachment=True, download_name=archive_name
                        )
                    resp.response = TempFileBody(tmp_path)
                    return resp
                except Exception:
                    tmp_path.unlink(missing_ok=True)
                    raise

            try:
                return await send_file(path, as_attachment=True, attachment_filename=path.name)
            except TypeError:
                return await send_file(path, as_attachment=True, download_name=path.name)
        except FSError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:
            logger.error(f"file explorer download failed: {exc}", exc_info=True)
            return error(str(exc), 500)

    async def upload(self):
        try:
            files = await request.files
            form = await request.form
            upload = files.get("file")
            dest_dir = form.get("path") or request.args.get("path") or ""
            if upload is None:
                return error("未收到文件")
            filename = upload.filename or "upload.bin"
            box = self.sandbox()
            dest = await asyncio.to_thread(box.prepare_upload_dest, dest_dir, filename)
            await asyncio.to_thread(upload.save, str(dest))
            result = await asyncio.to_thread(box.finish_upload, dest)
            return ok(result)
        except FSError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:
            logger.error(f"file explorer upload failed: {exc}", exc_info=True)
            return error(str(exc), 500)

    async def upload_prepare(self):
        try:
            payload = await request.get_json(silent=True) or {}
            dest = str(payload.get("path") or "")
            box = self.sandbox()
            await asyncio.to_thread(box.resolve, dest, must_exist=True)
            ticket = uuid.uuid4().hex
            self._tickets[ticket] = (time.time() + TICKET_TTL, dest)
            self._purge_tickets()
            return ok({"ticket": ticket})
        except FSError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:
            return error(str(exc), 500)

    async def upload_ticket(self, ticket: str):
        rec = self._tickets.pop(ticket, None)
        if rec is None or rec[0] < time.time():
            return error("上传凭证无效或已过期", 403)
        dest = rec[1]
        try:
            files = await request.files
            upload = files.get("file")
            if upload is None:
                return error("未收到文件")
            filename = upload.filename or "upload.bin"
            box = self.sandbox()
            dest_path = await asyncio.to_thread(box.prepare_upload_dest, dest, filename)
            await asyncio.to_thread(upload.save, str(dest_path))
            result = await asyncio.to_thread(box.finish_upload, dest_path)
            return ok(result)
        except FSError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:
            logger.error(f"file explorer ticket upload failed: {exc}", exc_info=True)
            return error(str(exc), 500)

    def _purge_tickets(self) -> None:
        now = time.time()
        expired = [key for key, (exp, _) in self._tickets.items() if exp < now]
        for key in expired:
            self._tickets.pop(key, None)

    async def _run(self, fn):
        try:
            box = self.sandbox()
            data = await asyncio.to_thread(fn, box)
            return ok(data)
        except FSError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:
            logger.error(f"file explorer failed: {exc}", exc_info=True)
            return error(str(exc), 500)

    async def _run_json(self, fn):
        try:
            payload = await request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                return error("请求体必须是 JSON 对象")
            box = self.sandbox()
            data = await asyncio.to_thread(fn, box, payload)
            return ok(data)
        except FSError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:
            logger.error(f"file explorer failed: {exc}", exc_info=True)
            return error(str(exc), 500)


def os_name() -> str:
    import os

    return os.name


def _request_username() -> str | None:
    try:
        from quart import g

        return getattr(g, "username", None)
    except Exception:
        return None
