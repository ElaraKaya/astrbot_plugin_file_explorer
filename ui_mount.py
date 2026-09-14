"""Mount a same-origin /file-manager UI on AstrBot 4.3.x dashboards."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path

from astrbot.api import logger

PAGE_DIR = Path(__file__).resolve().parent / "pages" / "explorer"
INDEX_ENDPOINT = "astrbot_plugin_file_explorer_index"
ASSET_ENDPOINT = "astrbot_plugin_file_explorer_asset"
REDIR_ENDPOINT = "astrbot_plugin_file_explorer_redir"
ALLOWED_ASSET_EXT = {".html", ".js", ".css", ".svg", ".png", ".ico", ".woff2", ".map"}


def find_dashboard_app():
    try:
        import gc

        from astrbot.dashboard.server import AstrBotDashboard
    except Exception:
        return None
    try:
        for obj in gc.get_objects():
            if isinstance(obj, AstrBotDashboard) and getattr(obj, "app", None) is not None:
                return obj.app
    except Exception:
        return None
    return None


def mount_file_manager_ui(app) -> bool:
    if app is None:
        return False
    app.view_functions[INDEX_ENDPOINT] = serve_index
    app.view_functions[ASSET_ENDPOINT] = serve_asset
    app.view_functions[REDIR_ENDPOINT] = serve_index
    existing = {rule.endpoint for rule in app.url_map.iter_rules()}
    if INDEX_ENDPOINT not in existing:
        app.add_url_rule(
            "/file-manager/",
            endpoint=INDEX_ENDPOINT,
            view_func=serve_index,
            methods=["GET"],
        )
    if REDIR_ENDPOINT not in existing:
        app.add_url_rule(
            "/file-manager",
            endpoint=REDIR_ENDPOINT,
            view_func=serve_index,
            methods=["GET"],
        )
    if ASSET_ENDPOINT not in existing:
        app.add_url_rule(
            "/file-manager/<path:asset>",
            endpoint=ASSET_ENDPOINT,
            view_func=serve_asset,
            methods=["GET"],
        )
    return True


async def serve_index(*_args, **_kwargs):
    from quart import send_file

    index = PAGE_DIR / "index.html"
    if not index.exists():
        return "file manager page missing", 404
    return await send_file(index)


async def serve_asset(asset: str):
    from quart import abort, send_file

    target = (PAGE_DIR / asset).resolve()
    try:
        target.relative_to(PAGE_DIR.resolve())
    except ValueError:
        abort(404)
    if not target.is_file() or target.suffix.lower() not in ALLOWED_ASSET_EXT:
        abort(404)
    mime = mimetypes.guess_type(target.name)[0]
    return await send_file(target, mimetype=mime)


async def wait_and_mount(stop_event: asyncio.Event | None = None) -> bool:
    for _ in range(40):
        if stop_event is not None and stop_event.is_set():
            return False
        app = find_dashboard_app()
        if app is not None:
            try:
                if mount_file_manager_ui(app):
                    logger.info("文件管理器已挂载到 WebUI: /file-manager/")
                    return True
            except Exception as exc:
                logger.warning(f"挂载文件管理器页面失败: {exc}", exc_info=True)
                return False
        await asyncio.sleep(0.25)
    logger.warning("未找到 Dashboard，文件管理器页面未挂载。新版 AstrBot 请使用插件 Pages。")
    return False
