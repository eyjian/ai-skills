"""
WebSocketHub — WebSocket 连接管理 + 事件推送（实时模式 & 回放模式）
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

from fastapi import WebSocket

from server.event_timeline import EventTimeline

logger = logging.getLogger(__name__)


class WebSocketHub:
    """管理 WebSocket 连接，支持实时推送和回放推送"""

    def __init__(self, timeline: EventTimeline):
        self._timeline = timeline
        # 实时模式连接
        self._live_clients: Set[WebSocket] = set()
        # 回放会话: {websocket: ReplaySession}
        self._replay_sessions: Dict[WebSocket, "_ReplaySession"] = {}

    # ─── 实时模式 ───

    async def connect_live(self, ws: WebSocket):
        """接受实时模式连接"""
        await ws.accept()
        self._live_clients.add(ws)

        # 发送初始快照
        events = self._timeline.get_all()
        await ws.send_json(
            {"type": "connected", "mode": "live", "event_count": len(events)}
        )
        if events:
            await ws.send_json({"type": "snapshot", "events": events})

        logger.info("实时客户端已连接 (总数: %d)", len(self._live_clients))

    async def disconnect_live(self, ws: WebSocket):
        """断开实时连接"""
        self._live_clients.discard(ws)
        logger.info("实时客户端已断开 (剩余: %d)", len(self._live_clients))

    async def broadcast_event(self, event: dict):
        """向所有实时客户端广播事件"""
        if not self._live_clients:
            return
        message = json.dumps({"type": "event", "event": event}, ensure_ascii=False)
        disconnected = set()
        for ws in self._live_clients:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.add(ws)
        self._live_clients -= disconnected

    # ─── 回放模式 ───

    async def connect_replay(self, ws: WebSocket):
        """接受回放模式连接"""
        await ws.accept()
        session = _ReplaySession(ws, self._timeline)
        self._replay_sessions[ws] = session

        events = self._timeline.get_all()
        await ws.send_json(
            {
                "type": "connected",
                "mode": "replay",
                "event_count": len(events),
            }
        )
        logger.info("回放客户端已连接")

    async def disconnect_replay(self, ws: WebSocket):
        """断开回放连接"""
        session = self._replay_sessions.pop(ws, None)
        if session:
            session.stop()
        logger.info("回放客户端已断开")

    async def handle_replay_command(self, ws: WebSocket, data: dict):
        """处理回放控制命令"""
        session = self._replay_sessions.get(ws)
        if not session:
            return

        action = data.get("action", "")
        if action == "play":
            speed = data.get("speed", 1)
            await session.play(speed)
        elif action == "pause":
            session.pause()
        elif action == "resume":
            await session.resume()
        elif action == "speed":
            speed = data.get("speed", 1)
            session.set_speed(speed)
        elif action == "seek":
            timestamp = data.get("timestamp", "")
            await session.seek(timestamp)
        elif action == "step_forward":
            await session.step_forward()
        elif action == "step_backward":
            await session.step_backward()


class _ReplaySession:
    """单个回放会话"""

    def __init__(self, ws: WebSocket, timeline: EventTimeline):
        self._ws = ws
        self._timeline = timeline
        self._current_index = 0
        self._speed = 1.0
        self._playing = False
        self._task: Optional[asyncio.Task] = None

    async def play(self, speed: float = 1.0):
        """开始回放"""
        self._speed = max(0.5, min(speed, 16.0))
        self._playing = True
        self._current_index = 0

        # 取消之前的回放任务
        if self._task and not self._task.done():
            self._task.cancel()

        self._task = asyncio.create_task(self._replay_loop())

    def pause(self):
        """暂停回放"""
        self._playing = False

    async def resume(self):
        """继续回放"""
        self._playing = True
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._replay_loop())

    def set_speed(self, speed: float):
        """设置回放速度"""
        self._speed = max(0.5, min(speed, 16.0))

    async def seek(self, timestamp: str):
        """跳转到指定时间点"""
        self._playing = False
        if self._task and not self._task.done():
            self._task.cancel()

        # 发送该时间点之前的所有事件作为快照
        snapshot_events = self._timeline.get_snapshot_at(timestamp)
        self._current_index = len(snapshot_events)

        try:
            await self._ws.send_json(
                {"type": "snapshot", "events": snapshot_events}
            )
            await self._ws.send_json(
                {
                    "type": "seek_complete",
                    "index": self._current_index,
                    "total": self._timeline.length,
                }
            )
        except Exception:
            pass

    async def step_forward(self):
        """前进一个事件"""
        event = self._timeline.get_at(self._current_index)
        if event:
            try:
                await self._ws.send_json({"type": "event", "event": event})
                self._current_index += 1
                await self._send_progress()
            except Exception:
                pass

    async def step_backward(self):
        """后退一个事件"""
        if self._current_index > 0:
            self._current_index -= 1
            # 重放从头到当前位置
            snapshot = self._timeline.get_since(0)[:self._current_index]
            try:
                await self._ws.send_json({"type": "snapshot", "events": snapshot})
                await self._send_progress()
            except Exception:
                pass

    def stop(self):
        """停止回放"""
        self._playing = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _replay_loop(self):
        """回放主循环"""
        try:
            while self._playing and self._current_index < self._timeline.length:
                event = self._timeline.get_at(self._current_index)
                if not event:
                    break

                # 计算与下一个事件的间隔
                next_event = self._timeline.get_at(self._current_index + 1)
                delay = 0.5  # 默认间隔
                if next_event:
                    try:
                        t1 = datetime.fromisoformat(
                            event["timestamp"].replace("Z", "+00:00")
                        )
                        t2 = datetime.fromisoformat(
                            next_event["timestamp"].replace("Z", "+00:00")
                        )
                        delay = max(
                            0.1, (t2 - t1).total_seconds() / self._speed
                        )
                        # 限制最大延迟
                        delay = min(delay, 5.0 / self._speed)
                    except (ValueError, KeyError):
                        delay = 0.5 / self._speed

                try:
                    await self._ws.send_json({"type": "event", "event": event})
                    self._current_index += 1
                    await self._send_progress()
                except Exception:
                    break

                # 等待间隔
                await asyncio.sleep(delay)

            # 回放结束
            if self._playing and self._current_index >= self._timeline.length:
                try:
                    await self._ws.send_json({"type": "replay_complete"})
                except Exception:
                    pass
                self._playing = False

        except asyncio.CancelledError:
            pass

    async def _send_progress(self):
        """发送回放进度"""
        try:
            await self._ws.send_json(
                {
                    "type": "progress",
                    "index": self._current_index,
                    "total": self._timeline.length,
                    "speed": self._speed,
                    "playing": self._playing,
                }
            )
        except Exception:
            pass
