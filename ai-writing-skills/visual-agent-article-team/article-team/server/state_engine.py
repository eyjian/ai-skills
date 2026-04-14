"""
StateEngine — 解析文件变化为结构化事件，维护 Agent 状态机
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# 事件类型常量
EVENT_TEAM_CREATED = "team_created"
EVENT_AGENT_JOINED = "agent_joined"
EVENT_AGENT_ACTIVATED = "agent_activated"
EVENT_MESSAGE_SENT = "message_sent"
EVENT_MESSAGE_READ = "message_read"
EVENT_AGENT_COMPLETED = "agent_completed"
EVENT_TEAM_DELETED = "team_deleted"

# Agent 状态
STATE_IDLE = "idle"
STATE_ACTIVE = "active"
STATE_COMPLETED = "completed"
STATE_ERROR = "error"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_read_json(path: str) -> Any:
    """安全读取 JSON 文件"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
        logger.warning("无法读取 JSON: %s — %s", path, e)
        return None


class StateEngine:
    """解析文件变化生成结构化事件，维护全局 Agent 状态机"""

    def __init__(self):
        # 团队状态: {team_name: {agent_name: state_str}}
        self._agent_states: Dict[str, Dict[str, str]] = {}
        # 团队配置快照: {team_name: config_dict}
        self._config_snapshots: Dict[str, dict] = {}
        # 已知消息 ID: {team_name: set(msg_id)}
        self._known_messages: Dict[str, Set[str]] = {}
        # 已知已读状态: {team_name: set(msg_id)}
        self._read_messages: Dict[str, Set[str]] = {}
        # 事件回调
        self._on_event: Optional[Callable] = None
        # 激活标记: {team_name: set(agent_name)}
        self._activated_agents: Dict[str, Set[str]] = {}

    def on_event(self, callback: Callable):
        """注册事件回调: callback(event_dict)"""
        self._on_event = callback

    def _emit(self, event: dict):
        """发射事件"""
        if self._on_event:
            self._on_event(event)

    def _make_event(
        self, event_type: str, team: str, data: dict, timestamp: Optional[str] = None
    ) -> dict:
        return {
            "event": event_type,
            "timestamp": timestamp or _now_iso(),
            "team": team,
            "data": data,
        }

    # ─── config.json 变化处理 ───

    def handle_config_changed(self, team_name: str, path: str):
        """处理 config.json 变化"""
        config = _safe_read_json(path)
        if config is None:
            return

        old_config = self._config_snapshots.get(team_name)
        self._config_snapshots[team_name] = config

        if old_config is None:
            # 新团队创建
            created_at = config.get("createdAt", _now_iso())
            members = config.get("members", [])
            self._agent_states.setdefault(team_name, {})
            self._activated_agents.setdefault(team_name, set())

            self._emit(
                self._make_event(
                    EVENT_TEAM_CREATED,
                    team_name,
                    {
                        "team_name": team_name,
                        "created_at": created_at,
                        "members": members,
                    },
                    timestamp=created_at,
                )
            )

            # 为每个成员发送 agent_joined 事件
            for member in members:
                name = member.get("name", "")
                role = member.get("role", "")
                self._agent_states[team_name][name] = STATE_IDLE
                self._emit(
                    self._make_event(
                        EVENT_AGENT_JOINED,
                        team_name,
                        {"agent_name": name, "role": role},
                        timestamp=created_at,
                    )
                )
        else:
            # 检查新成员
            old_names = {m.get("name") for m in old_config.get("members", [])}
            new_members = config.get("members", [])
            for member in new_members:
                name = member.get("name", "")
                if name not in old_names:
                    role = member.get("role", "")
                    self._agent_states.setdefault(team_name, {})[name] = STATE_IDLE
                    self._emit(
                        self._make_event(
                            EVENT_AGENT_JOINED,
                            team_name,
                            {"agent_name": name, "role": role},
                        )
                    )

    # ─── inboxes/*.json 变化处理 ───

    def handle_inbox_changed(self, team_name: str, member_name: str, path: str):
        """处理 inbox 文件变化"""
        messages = _safe_read_json(path)
        if not isinstance(messages, list):
            return

        self._known_messages.setdefault(team_name, set())
        self._read_messages.setdefault(team_name, set())
        self._agent_states.setdefault(team_name, {})
        self._activated_agents.setdefault(team_name, set())

        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id:
                continue

            if msg_id not in self._known_messages[team_name]:
                # 新消息
                self._known_messages[team_name].add(msg_id)

                from_agent = msg.get("from", "")
                to_agent = msg.get("to", "")
                msg_type = msg.get("type", "message")
                content = msg.get("content", "")
                timestamp = msg.get("timestamp", _now_iso())
                summary = msg.get("summary", "")

                # 检查是否需要标记 from_agent 为 activated
                if (
                    from_agent
                    and from_agent not in self._activated_agents[team_name]
                ):
                    self._activated_agents[team_name].add(from_agent)
                    self._agent_states[team_name][from_agent] = STATE_ACTIVE
                    self._emit(
                        self._make_event(
                            EVENT_AGENT_ACTIVATED,
                            team_name,
                            {
                                "agent_name": from_agent,
                                "status": STATE_ACTIVE,
                            },
                            timestamp=timestamp,
                        )
                    )

                # 发送消息事件
                self._emit(
                    self._make_event(
                        EVENT_MESSAGE_SENT,
                        team_name,
                        {
                            "id": msg_id,
                            "from": from_agent,
                            "to": to_agent,
                            "type": msg_type,
                            "content": content,
                            "summary": summary,
                        },
                        timestamp=timestamp,
                    )
                )

                # 检查是否是 shutdown_request → agent_completed
                if msg_type == "shutdown_request":
                    target = to_agent
                    if target:
                        self._agent_states[team_name][target] = STATE_COMPLETED
                        self._emit(
                            self._make_event(
                                EVENT_AGENT_COMPLETED,
                                team_name,
                                {"agent_name": target},
                                timestamp=timestamp,
                            )
                        )

            # 检查已读状态变化
            if msg.get("read") and msg_id not in self._read_messages[team_name]:
                self._read_messages[team_name].add(msg_id)
                self._emit(
                    self._make_event(
                        EVENT_MESSAGE_READ,
                        team_name,
                        {
                            "id": msg_id,
                            "agent_name": member_name,
                        },
                        timestamp=msg.get("timestamp", _now_iso()),
                    )
                )

    # ─── 初始快照加载 ───

    def load_snapshot(self, teams_dir: str) -> List[dict]:
        """扫描 teams 目录，构建初始状态快照，返回所有事件（按时间排序）"""
        events: List[dict] = []
        original_callback = self._on_event

        # 临时替换回调，收集事件
        collected: List[dict] = []
        self._on_event = lambda e: collected.append(e)

        if not os.path.isdir(teams_dir):
            self._on_event = original_callback
            return []

        # 检查是否是单个团队目录（包含 config.json）
        if os.path.isfile(os.path.join(teams_dir, "config.json")):
            team_name = os.path.basename(teams_dir)
            self._load_team(teams_dir, team_name)
        else:
            # 扫描子目录
            for entry in sorted(os.listdir(teams_dir)):
                team_path = os.path.join(teams_dir, entry)
                config_path = os.path.join(team_path, "config.json")
                if os.path.isdir(team_path) and os.path.isfile(config_path):
                    self._load_team(team_path, entry)

        # 恢复回调
        self._on_event = original_callback

        # 按时间排序
        collected.sort(key=lambda e: e.get("timestamp", ""))
        return collected

    def _load_team(self, team_path: str, team_name: str):
        """加载单个团队的数据"""
        config_path = os.path.join(team_path, "config.json")
        if os.path.isfile(config_path):
            self.handle_config_changed(team_name, config_path)

        inboxes_dir = os.path.join(team_path, "inboxes")
        if os.path.isdir(inboxes_dir):
            for fname in sorted(os.listdir(inboxes_dir)):
                if fname.endswith(".json"):
                    member_name = fname[:-5]
                    fpath = os.path.join(inboxes_dir, fname)
                    self.handle_inbox_changed(team_name, member_name, fpath)

    # ─── 状态查询 ───

    def get_agent_states(self, team_name: str) -> Dict[str, str]:
        """获取某个团队的所有 Agent 状态"""
        return dict(self._agent_states.get(team_name, {}))

    def get_all_teams(self) -> List[dict]:
        """获取所有团队信息"""
        result = []
        for team_name, config in self._config_snapshots.items():
            members = config.get("members", [])
            result.append(
                {
                    "name": team_name,
                    "created_at": config.get("createdAt", ""),
                    "member_count": len(members),
                    "status": "active",
                    "members": members,
                }
            )
        return sorted(result, key=lambda t: t.get("created_at", ""), reverse=True)

    def get_team_detail(self, team_name: str) -> Optional[dict]:
        """获取团队详情"""
        config = self._config_snapshots.get(team_name)
        if config is None:
            return None
        return {
            "config": config,
            "agent_states": self.get_agent_states(team_name),
            "message_count": len(self._known_messages.get(team_name, set())),
        }

    # ─── 团队删除处理 ───

    def handle_team_deleted(self, team_name: str):
        """处理团队删除 — 将所有未完成的 agent 补偿标记为 completed"""
        states = self._agent_states.get(team_name, {})
        timestamp = _now_iso()
        for agent_name, state in list(states.items()):
            if state != STATE_COMPLETED:
                states[agent_name] = STATE_COMPLETED
                logger.info(
                    "团队删除补偿: %s/%s %s → completed",
                    team_name, agent_name, state,
                )
                self._emit(
                    self._make_event(
                        EVENT_AGENT_COMPLETED,
                        team_name,
                        {"agent_name": agent_name},
                        timestamp=timestamp,
                    )
                )

        # 发出 team_deleted 事件
        self._emit(
            self._make_event(
                EVENT_TEAM_DELETED,
                team_name,
                {"team_name": team_name},
                timestamp=timestamp,
            )
        )
