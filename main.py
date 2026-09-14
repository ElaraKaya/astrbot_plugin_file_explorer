from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .fs import FileSandbox
from .ui_mount import wait_and_mount
from .web_api import FileExplorerApi

PLUGIN_NAME = "astrbot_plugin_file_explorer"


class FileExplorerPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.api = FileExplorerApi(self)
        self._stop = asyncio.Event()
        self._mount_task: asyncio.Task | None = None
        try:
            self.api.register_routes()
        except Exception as exc:
            logger.warning(f"注册文件管理器 API 失败: {exc}", exc_info=True)

    async def initialize(self):
        self._stop.clear()
        self._mount_task = asyncio.create_task(wait_and_mount(self._stop))

    def build_sandbox(self) -> FileSandbox:
        extra = self.config.get("allowed_roots", []) or []
        if isinstance(extra, str):
            extra = [line.strip() for line in extra.splitlines() if line.strip()]
        elif isinstance(extra, list):
            extra = [str(item).strip() for item in extra if str(item).strip()]
        else:
            extra = []
        return FileSandbox(
            data_path=Path(get_astrbot_data_path()),
            extra_roots=extra,
            allow_system_root=bool(self.config.get("allow_system_root", False)),
            show_hidden=bool(self.config.get("show_hidden", True)),
            max_upload_mb=int(self.config.get("max_upload_mb", 128) or 128),
            max_preview_kb=int(self.config.get("max_preview_kb", 512) or 512),
        )

    def _panel_url(self) -> str:
        dashboard = self.context.get_config().get("dashboard", {}) or {}
        port = dashboard.get("port", 6185)
        host = str(dashboard.get("host", "127.0.0.1") or "127.0.0.1")
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        return f"http://{host}:{port}/file-manager/"

    @filter.command("文件管理", alias={"filemgr", "file-manager"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def open_file_manager(self, event: AstrMessageEvent):
        """返回 WebUI 文件管理器地址（仅管理员）。"""
        url = self._panel_url()
        yield event.plain_result(
            "AstrBot 文件管理器\n"
            f"入口：{url}\n"
            "请先登录 AstrBot WebUI，再打开上述地址。\n"
            "新版 AstrBot 也可在：插件 → 文件管理器 → Pages → file-manager"
        )

    async def terminate(self):
        self._stop.set()
        if self._mount_task is not None:
            self._mount_task.cancel()
            try:
                await self._mount_task
            except (asyncio.CancelledError, Exception):
                pass
            self._mount_task = None
