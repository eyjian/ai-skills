# 架构说明

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│  CodeBuddy IDE（引擎层）                               │
│  team_create → task → send_message → team_delete      │
│       │                                               │
│       ├── 协调者自动启动可视化服务                        │
│       │   execute_command("launch.sh ... &")           │
│       │                                               │
│       ▼                                               │
│  .codebuddy/teams/{team-name}/                        │
│  ├── config.json          ← 团队元信息+成员列表         │
│  └── inboxes/{name}.json  ← 各成员收件箱               │
│                                                       │
│  .codebuddy/skills/article-team/                      │
│  ├── launch.sh            ← 一键启动脚本               │
│  ├── server/              ← Python 后端               │
│  └── web/                 ← 前端静态文件               │
└────────────────────┬─────────────────────────────────┘
                     │ watchdog 监听文件变化
                     ▼
┌──────────────────────────────────────────────────────┐
│  Python 后端（FastAPI + WebSocket）                    │
│                                                       │
│  FileWatcher → StateEngine → EventTimeline            │
│                                  │                    │
│                          WebSocketHub ← REST API      │
└────────────────────┬─────────────────────────────────┘
                     │ WebSocket / HTTP
                     ▼
┌──────────────────────────────────────────────────────┐
│  浏览器前端                                            │
│  ┌────────────────────┐ ┌──────────────────────┐     │
│  │ 虚拟办公室（上 60%） │ │ 通信面板（下 40%）     │     │
│  │ SVG 角色 + CSS 动画 │ │ 聊天气泡 + 过滤       │     │
│  └────────────────────┘ └──────────────────────┘     │
│  ┌─────────────────────────────────────────────┐     │
│  │ 回放控制条                                    │     │
│  └─────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────┘
```

## 自动启动流程

```
用户 → /article-team 写一篇...
  ↓
协调者 → team_create("article-team")
  ↓
协调者 → execute_command("nohup bash .codebuddy/skills/article-team/launch.sh --no-browser .codebuddy/teams/ &")
  ↓
launch.sh 自动：检测 Python → 创建 .venv → 安装依赖 → 启动 FastAPI 服务
  ↓
协调者 → 派发 Agent（scout / reviewer / ...）
  ↓
用户打开浏览器 http://localhost:8765 → 实时观看协作
```

## 数据流

1. **CodeBuddy** 运行 Agent Team，产生 `config.json` 和 `inboxes/*.json` 文件
2. **FileWatcher** 通过 watchdog 监听文件变化事件
3. **StateEngine** 解析文件变化，生成标准化事件（`team_created`、`message_sent` 等）
4. **EventTimeline** 维护有序事件时间线
5. **WebSocketHub** 将事件推送给浏览器（实时模式）或按时间线回放（回放模式）
6. **前端** 渲染虚拟办公室场景、播放角色动画、展示通信气泡

## 后端模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| FileWatcher | `server/file_watcher.py` | 监听 teams 目录，过滤有效文件，触发回调 |
| StateEngine | `server/state_engine.py` | 解析文件内容变化，维护 Agent 状态机，生成事件 |
| EventTimeline | `server/event_timeline.py` | 有序事件存储，支持全量/增量/范围查询 |
| WebSocketHub | `server/websocket_hub.py` | WebSocket 连接管理，实时推送与回放推送 |
| Main | `server/main.py` | FastAPI 入口，REST API，静态文件服务 |

## 前端模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| WebSocket Client | `web/js/websocket-client.js` | 连接管理，消息解析分发 |
| Office Renderer | `web/js/office-renderer.js` | 虚拟办公室场景渲染 |
| Agent Controller | `web/js/agent-controller.js` | 角色状态切换与动画控制 |
| Message Animator | `web/js/message-animator.js` | 通信动画（纸飞机、气泡） |
| Timeline Player | `web/js/timeline-player.js` | 回放控制器 |
| App | `web/js/app.js` | 主逻辑，模块协调 |

## 事件类型

| 事件 | 说明 |
|------|------|
| `team_created` | 团队创建 |
| `agent_joined` | 成员加入 |
| `agent_activated` | Agent 开始工作 |
| `message_sent` | 消息发送 |
| `message_read` | 消息已读 |
| `agent_completed` | Agent 完成任务 |
| `team_deleted` | 团队销毁 |

## Skill 包结构

安装后位于 `.codebuddy/skills/article-team/`：

```
article-team/
├── SKILL.md                   ← Skill 元数据
├── commands/
│   └── article-team.md        ← 协调者 prompt（含自动启动可视化逻辑）
├── shared-writing-resources/  ← 领域画像配置
├── launch.sh                  ← 一键启动脚本
├── requirements.txt           ← Python 依赖
├── server/                    ← Python 后端（5 个模块）
└── web/                       ← 前端静态文件（HTML + CSS + JS + SVG）
```
