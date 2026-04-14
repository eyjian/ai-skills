## Why

当前的 Agent Team（如 `custom-agent-article-team`）在 CodeBuddy IDE 中运行时，用户无法直观感知 Agent 之间的协作过程——谁在工作、谁在跟谁通信、任务如何流转，全部隐藏在后台。用户只能等待最终产出，缺少"数字人协作"的沉浸式体验。

我们需要一个**可视化层**，以"虚拟办公室"的形式实时展示 Agent Team 的协作过程，让每个 Agent 成为一个有独立形象和动画的"数字员工"，让用户直观感受到数字人在办公。

## What Changes

- **新增 Web 可视化服务**：Python（FastAPI）轻量本地服务，监听 `.codebuddy/teams/` 目录下的 JSON 文件变化，通过 WebSocket 实时推送状态事件到浏览器
- **新增虚拟办公室前端**：HTML + CSS + JS + SVG 实现的混合式界面——上方 60% 为等距伪 3D 虚拟办公室（SVG 卡通角色 + CSS 动画），下方 40% 为聊天气泡式通信流面板
- **新增回放系统**：支持事后按时间线回放整个协作过程，可暂停、快进、调速（1x/2x/4x/8x）
- **新增一键启动脚本**：`launch.sh` 自动创建 Python 虚拟环境、安装依赖、启动服务，零手动配置
- **新增 Skill 变体**：基于 `custom-agent-article-team` 创建 `visual-agent-article-team`，Subagent prompt 和协作流程复用，仅增强心跳消息格式以便前端解析

## Capabilities

### New Capabilities

- `file-watcher`: 监听 `.codebuddy/teams/` 目录下 `config.json` 和 `inboxes/*.json` 的文件变化，检测团队创建、成员加入、消息收发等事件
- `state-engine`: 解析文件变化生成结构化状态事件（agent_activated、message_sent、agent_completed 等），维护全局 Agent 状态机
- `event-timeline`: 维护所有事件的有序时间线，支持全量快照加载和增量事件追加，为回放功能提供数据基础
- `websocket-hub`: WebSocket 连接管理与事件推送，支持实时模式（文件变化即时推送）和回放模式（按时间线逐条推送，支持倍速）
- `rest-api`: REST API 端点，提供团队列表查询、团队详情、事件时间线等 HTTP 接口
- `office-renderer`: 虚拟办公室前端渲染——等距布局的开放式办公室场景，5+1 个工位，SVG 办公室背景
- `agent-characters`: 6 个 Agent 角色的 SVG 卡通形象设计与状态切换——每个角色有独特外观、配色和桌面物品
- `agent-animation`: 角色动画系统——空闲晃动、被激活亮灯、工作中打字、发送消息纸飞机、完成任务对勾、审稿退回红色文件等 CSS 动画
- `message-visualizer`: 通信可视化——Agent 之间的纸飞机飞线动画、对话气泡弹出、通信拓扑连线
- `chat-panel`: 下方通信流面板——聊天气泡式展示所有 Agent 间的消息，带时间戳、头像、发送/接收方向
- `replay-player`: 回放控制器——播放/暂停/快进/后退、时间线进度条、倍速切换、事件列表面板
- `launch-script`: 一键启动脚本——自动检测 Python 环境、创建 venv、安装依赖、启动服务并打开浏览器
- `skill-enhancement`: 基于 `custom-agent-article-team` 的 Skill 变体，复用全部 Subagent 和协作流程，仅增强协调者心跳消息的结构化格式

### Modified Capabilities

（无——本次为全新项目，不修改已有 Capability）

## Impact

- **新增目录**：`ai-writing-skills/visual-agent-article-team/`（含 Python 后端、Web 前端、Skill 包、Subagent 注册文件）
- **Python 依赖**：fastapi、uvicorn、watchdog、websockets（通过 venv 隔离，不影响系统环境）
- **运行时依赖**：需要系统已安装 `python3`（Linux 默认具备）
- **CodeBuddy 依赖**：LLM 推理仍由 CodeBuddy 承担，Web 可视化层仅做"读取和展示"，不替代引擎
- **不影响现有项目**：`custom-agent-article-team`、`real-agent-team-writing-skill`、`ai-rd-team` 等均不受影响
