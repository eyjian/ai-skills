"""
Main — FastAPI 入口、REST API、WebSocket 端点、静态文件服务
"""

import argparse
import asyncio
import json
import logging
import os
import sys

# 确保可以作为脚本直接运行
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_DIR = os.path.dirname(_SERVER_DIR)  # article-team/ (skill 根目录)
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.file_watcher import FileWatcher
from server.state_engine import StateEngine
from server.event_timeline import EventTimeline
from server.websocket_hub import WebSocketHub

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── 全局实例 ───
state_engine = StateEngine()
timeline = EventTimeline()
hub = WebSocketHub(timeline)
file_watcher: FileWatcher = None

app = FastAPI(title="Agent Team Visualizer", version="1.0.0")

# ─── 事件处理回调 ───

_loop: asyncio.AbstractEventLoop = None


def _on_event(event: dict):
    """StateEngine 事件回调 → 追加到 timeline + 推送给 WebSocket 客户端"""
    timeline.append(event)
    if _loop:
        asyncio.run_coroutine_threadsafe(hub.broadcast_event(event), _loop)


def _on_config_changed(team_name: str, path: str):
    state_engine.handle_config_changed(team_name, path)


def _on_inbox_changed(team_name: str, member_name: str, path: str):
    state_engine.handle_inbox_changed(team_name, member_name, path)


def _on_config_deleted(team_name: str, path: str):
    """config.json 被删除 → 团队被删除，补偿标记所有未完成 agent"""
    state_engine.handle_team_deleted(team_name)


# ─── REST API ───


@app.get("/api/teams")
async def list_teams():
    """列出所有团队"""
    teams = state_engine.get_all_teams()
    return JSONResponse(teams)


@app.get("/api/teams/{name}")
async def get_team(name: str):
    """获取团队详情"""
    detail = state_engine.get_team_detail(name)
    if detail is None:
        return JSONResponse({"error": "Team not found"}, status_code=404)
    return JSONResponse(detail)


@app.get("/api/teams/{name}/timeline")
async def get_timeline(name: str, start: str = None, end: str = None):
    """获取事件时间线"""
    if start and end:
        events = timeline.get_range(start, end)
    else:
        events = [e for e in timeline.get_all() if e.get("team") == name]
    return JSONResponse(events)


# ─── WebSocket 端点 ───


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    """实时模式 WebSocket"""
    await hub.connect_live(ws)
    try:
        while True:
            # 保持连接活跃，接收心跳
            data = await ws.receive_text()
            # 客户端心跳 ping
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        await hub.disconnect_live(ws)
    except Exception:
        await hub.disconnect_live(ws)


@app.websocket("/ws/replay")
async def ws_replay(ws: WebSocket):
    """回放模式 WebSocket"""
    await hub.connect_replay(ws)
    try:
        while True:
            data = await ws.receive_text()
            try:
                cmd = json.loads(data)
                await hub.handle_replay_command(ws, cmd)
            except json.JSONDecodeError:
                if data == "ping":
                    await ws.send_text("pong")
    except WebSocketDisconnect:
        await hub.disconnect_replay(ws)
    except Exception:
        await hub.disconnect_replay(ws)


# ─── 静态文件服务 ───

WEB_DIR = os.path.join(os.path.dirname(_SERVER_DIR), "web")


@app.get("/")
async def index():
    """主页"""
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return JSONResponse({"error": "index.html not found"}, status_code=404)


# 挂载静态文件（css/js/svg 等）
if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


# ─── 启动入口 ───


def main():
    global file_watcher, _loop

    parser = argparse.ArgumentParser(description="Agent Team Visualizer")
    parser.add_argument(
        "--teams-dir", required=True, help="teams 目录路径"
    )
    parser.add_argument("--port", type=int, default=8765, help="服务端口")
    parser.add_argument(
        "--poll", action="store_true", help="使用轮询模式监听文件变化"
    )
    args = parser.parse_args()

    teams_dir = os.path.abspath(args.teams_dir)

    # 注册事件回调
    state_engine.on_event(_on_event)

    # 加载初始快照
    logger.info("加载初始数据: %s", teams_dir)
    initial_events = state_engine.load_snapshot(teams_dir)
    timeline.load(initial_events)
    logger.info("加载了 %d 个历史事件", len(initial_events))

    # 启动文件监听
    file_watcher = FileWatcher(teams_dir, use_polling=args.poll)
    file_watcher.on_config_changed(_on_config_changed)
    file_watcher.on_inbox_changed(_on_inbox_changed)
    file_watcher.on_config_deleted(_on_config_deleted)
    file_watcher.start()
    logger.info("文件监听已启动")

    # 启动 Web 服务
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=args.port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    # 保存 event loop 引用
    loop = asyncio.new_event_loop()
    _loop = loop

    try:
        loop.run_until_complete(server.serve())
    except KeyboardInterrupt:
        pass
    finally:
        file_watcher.stop()
        loop.close()


if __name__ == "__main__":
    main()
