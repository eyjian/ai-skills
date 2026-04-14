"""
EventTimeline — 维护有序事件时间线，支持全量/增量/范围查询
"""

import threading
from typing import List, Optional


class EventTimeline:
    """有序事件时间线"""

    def __init__(self):
        self._events: List[dict] = []
        self._lock = threading.Lock()

    def load(self, events: List[dict]):
        """全量加载事件列表（已排序）"""
        with self._lock:
            self._events = list(events)

    def append(self, event: dict):
        """追加新事件到末尾"""
        with self._lock:
            self._events.append(event)

    @property
    def length(self) -> int:
        with self._lock:
            return len(self._events)

    def get_all(self) -> List[dict]:
        """获取全部事件"""
        with self._lock:
            return list(self._events)

    def get_range(self, start_time: str, end_time: str) -> List[dict]:
        """获取时间范围内的事件（含边界）"""
        with self._lock:
            return [
                e
                for e in self._events
                if start_time <= e.get("timestamp", "") <= end_time
            ]

    def get_since(self, index: int) -> List[dict]:
        """获取指定索引之后的事件"""
        with self._lock:
            if index < 0:
                index = 0
            return list(self._events[index:])

    def get_at(self, index: int) -> Optional[dict]:
        """获取指定索引的事件"""
        with self._lock:
            if 0 <= index < len(self._events):
                return self._events[index]
            return None

    def get_snapshot_at(self, timestamp: str) -> List[dict]:
        """获取指定时间点之前的所有事件（含该时间点）"""
        with self._lock:
            return [
                e for e in self._events if e.get("timestamp", "") <= timestamp
            ]

    def find_index_for_timestamp(self, timestamp: str) -> int:
        """找到给定时间戳对应的事件索引"""
        with self._lock:
            for i, e in enumerate(self._events):
                if e.get("timestamp", "") >= timestamp:
                    return i
            return len(self._events)
