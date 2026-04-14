"""
FileWatcher — 监听 .codebuddy/teams/ 目录下的文件变化
"""

import os
import fnmatch
import logging
from typing import Callable, Optional

from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import (
    FileSystemEventHandler,
    FileModifiedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
)

logger = logging.getLogger(__name__)


class _TeamsEventHandler(FileSystemEventHandler):
    """只关注 config.json 和 inboxes/*.json 的变化"""

    def __init__(
        self,
        on_config_changed: Optional[Callable] = None,
        on_inbox_changed: Optional[Callable] = None,
    ):
        super().__init__()
        self._on_config_changed = on_config_changed
        self._on_inbox_changed = on_inbox_changed

    def _extract_team_name(self, path: str) -> Optional[str]:
        """从路径中提取团队名"""
        parts = path.replace("\\", "/").split("/")
        for i, part in enumerate(parts):
            if part == "inboxes" and i > 0:
                return parts[i - 1]
            if part == "config.json" and i > 0:
                return parts[i - 1]
        # fallback: 如果 teams 目录就是某个团队目录
        for i, part in enumerate(parts):
            if part == "teams" and i + 1 < len(parts):
                return parts[i + 1]
        return None

    def _extract_member_name(self, path: str) -> Optional[str]:
        """从 inboxes/xxx.json 路径中提取成员名"""
        basename = os.path.basename(path)
        if basename.endswith(".json"):
            return basename[:-5]
        return None

    def _handle(self, event):
        if event.is_directory:
            return

        path = event.src_path
        basename = os.path.basename(path)

        # 只关注 .json 文件
        if not basename.endswith(".json"):
            return

        team_name = self._extract_team_name(path)

        if basename == "config.json":
            if self._on_config_changed:
                logger.debug("config_changed: team=%s path=%s", team_name, path)
                self._on_config_changed(team_name=team_name, path=path)
        elif "/inboxes/" in path.replace("\\", "/"):
            member_name = self._extract_member_name(path)
            if self._on_inbox_changed and member_name:
                logger.debug(
                    "inbox_changed: team=%s member=%s path=%s",
                    team_name, member_name, path,
                )
                self._on_inbox_changed(
                    team_name=team_name, member_name=member_name, path=path
                )

    def on_created(self, event):
        self._handle(event)

    def on_modified(self, event):
        self._handle(event)

    def on_deleted(self, event):
        """监听文件删除事件 — 检测 config.json 被删除（团队被删除）"""
        if event.is_directory:
            return
        path = event.src_path
        basename = os.path.basename(path)
        if basename == "config.json" and self._on_config_deleted:
            team_name = self._extract_team_name(path)
            if team_name:
                logger.debug("config_deleted: team=%s path=%s", team_name, path)
                self._on_config_deleted(team_name=team_name, path=path)


class FileWatcher:
    """监听 teams 目录变化，支持原生事件和 fallback 轮询模式"""

    def __init__(self, teams_dir: str, use_polling: bool = False):
        self._teams_dir = os.path.abspath(teams_dir)
        self._use_polling = use_polling
        self._observer: Optional[Observer] = None
        self._on_config_changed: Optional[Callable] = None
        self._on_inbox_changed: Optional[Callable] = None
        self._on_config_deleted: Optional[Callable] = None

    def on_config_changed(self, callback: Callable):
        """注册 config_changed 事件回调"""
        self._on_config_changed = callback

    def on_inbox_changed(self, callback: Callable):
        """注册 inbox_changed 事件回调"""
        self._on_inbox_changed = callback

    def on_config_deleted(self, callback: Callable):
        """注册 config_deleted 事件回调（团队被删除）"""
        self._on_config_deleted = callback

    def start(self):
        """启动文件监听"""
        handler = _TeamsEventHandler(
            on_config_changed=self._on_config_changed,
            on_inbox_changed=self._on_inbox_changed,
            on_config_deleted=self._on_config_deleted,
        )

        if self._use_polling:
            logger.info("使用轮询模式监听 (间隔 2s): %s", self._teams_dir)
            self._observer = PollingObserver(timeout=2)
        else:
            logger.info("使用原生事件监听: %s", self._teams_dir)
            self._observer = Observer()

        # 确保目录存在
        os.makedirs(self._teams_dir, exist_ok=True)

        self._observer.schedule(handler, self._teams_dir, recursive=True)
        self._observer.start()

    def stop(self):
        """停止文件监听"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
