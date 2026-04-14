# 可视化 Agent 文章编写团队

一个本地 Web 可视化层，以**虚拟办公室**的形式实时展示 CodeBuddy Agent Team 的协作过程——每个 Agent 是一个有独立形象和动画的"数字员工"，可以直观看到谁在工作、谁在跟谁说话、任务如何流转。

基于 [`custom-agent-article-team`](../custom-agent-article-team/)（方式 B）打造，协作流程和 Subagent 完全复用，仅新增 Web 可视化能力。

## 快速开始

### 前置条件

- **Python 3.8+**（Linux 默认具备）
- **CodeBuddy IDE**（用于运行 Agent Team）

### 第 0 步：安装 Skill 和 Subagent

```bash
# 进入你的文章仓库（即你写文章的工作目录）
cd /path/to/your-articles-repo

# 注册自定义 Subagent（⚠️ 必须执行，否则 Agent 派发会失败）
cp /path/to/ai-skills/ai-writing-skills/visual-agent-article-team/agents/*.md .codebuddy/agents/

# 安装 Skill（server + web + launch.sh 已内置在 skill 包中）
cp -r /path/to/ai-skills/ai-writing-skills/visual-agent-article-team/article-team .codebuddy/skills/
```

> 💡 如果之前已安装过 `custom-agent-article-team` 的 agents 和 skill，这一步会覆盖——两者 agents 完全相同，skill 仅多一行心跳格式标记，不影响功能。

也可以使用安装脚本一键安装：

```bash
bash install-skill.sh visual-article-team
```

### 第 1 步：在 CodeBuddy 中触发写作任务

在 CodeBuddy 对话框中正常使用：

```
/article-team 写一篇关于 AI Agent 编排模式的技术文章
/article-team 重审 2026/my-article.md
/article-team 请润色 article.md，重点降低 AI 味
```

**可视化服务会由协调者自动启动**——无需手动执行任何启动脚本。

### 第 2 步：打开浏览器

访问 **http://localhost:8765**，你会看到虚拟办公室界面，**实时显示**整个团队协作过程。

### 手动启动可视化服务（可选）

如果需要在协调者之外手动启动，可以在项目根目录下执行：

```bash
# 最简用法——自动检测 .codebuddy/teams/ 目录
bash .codebuddy/skills/article-team/launch.sh

# 指定 teams 目录
bash .codebuddy/skills/article-team/launch.sh /path/to/.codebuddy/teams/

# 自定义端口
bash .codebuddy/skills/article-team/launch.sh --port 9000

# Docker 环境使用轮询模式
bash .codebuddy/skills/article-team/launch.sh --poll

# 不自动打开浏览器
bash .codebuddy/skills/article-team/launch.sh --no-browser
```

脚本会自动完成：
1. ✅ 检测 Python 环境
2. ✅ 自动查找 `.codebuddy/teams/` 目录（从当前目录向上搜索）
3. ✅ 创建虚拟环境（`.venv`）
4. ✅ 安装依赖（fastapi、uvicorn、watchdog、websockets）
5. ✅ 启动本地 Web 服务
6. ✅ 自动打开浏览器

## 命令行选项

```bash
bash .codebuddy/skills/article-team/launch.sh [选项] [teams-目录路径]

选项:
  --port <端口>    指定服务端口（默认 8765）
  --poll           使用轮询模式（适用于 NFS / Docker bind mount 环境）
  --no-browser     不自动打开浏览器
  -h, --help       显示帮助信息
```

## 界面说明

页面分为三个区域：

### 🏢 虚拟办公室（上方 60%）

等距伪 3D 视角的开放式办公室，6 个工位对应 6 个角色：

| 工位 | 角色 | 配色 | 形象特征 |
|------|------|------|---------|
| 🧭 main | 协调者 | 🟦 蓝色 | 戴耳麦、手持平板 |
| 🔎 scout | 选题侦察员 | 🟩 绿色 | 戴贝雷帽、手持放大镜 |
| 📐 architect | 大纲架构师 | 🟪 紫色 | 戴眼镜、手持三角尺 |
| 📝 writer | 初稿写手 | 🟧 橙色 | 戴鸭舌帽、手持笔 |
| 🛡️ reviewer | 技术审稿人 | 🟥 红色 | 戴红围巾、手持红笔 |
| ✨ polisher | 终稿润色师 | 🟨 黄色 | 戴围裙、手持喷壶 |

**动画效果**：
- 🪑 **空闲**：角色轻微晃动，桌灯熄灭
- 💡 **激活**：任务卡从协调者飞到工位，桌灯亮起
- ⌨️ **工作中**：打字动画，桌面纸张翻动
- ✉️ **通信**：纸飞机沿弧线飞向接收者，飞线发光
- ✅ **完成**：绿色对勾弹出，角色伸懒腰

### 💬 通信面板（下方 40%）

聊天气泡式消息流，展示所有 Agent 之间的通信：

- 每条消息显示**发送者头像、名称（带配色）、接收者、时间戳和内容**
- 系统事件（团队创建、成员加入、任务完成）以居中灰色文本显示
- 广播消息以蓝色边框突出显示
- 长消息自动折叠，点击"展开"查看全文
- 支持**按 Agent 过滤**：点击顶部的角色标签只看特定 Agent 的消息

上下两个区域之间的**分隔条可以拖动**，按需调整比例。

### ⏯️ 回放控制条（底部）

| 控件 | 功能 |
|------|------|
| ◀◀ | 跳到上一个事件 |
| ▶️ / ⏸️ | 播放 / 暂停回放 |
| ▶▶ | 跳到下一个事件 |
| 进度条 | 拖动跳转到任意时间点 |
| 1x 2x 4x 8x | 回放倍速 |
| 📋 | 展开事件列表侧边栏（点击某个事件可直接跳转） |
| 🔴 实时 / ⏯️ 回放 | 切换模式 |

## 两种模式

### 🔴 实时模式（默认）

- 页面连接后自动进入实时模式
- Agent Team 运行时，文件变化会被 watchdog 实时捕获
- 新事件通过 WebSocket 推送到浏览器，**毫秒级延迟**
- 回放控制条除"模式切换"外不可用

**适合**：在 CodeBuddy 中触发 `/article-team` 后，切到浏览器观看协作过程。

### ⏯️ 回放模式

- 点击右上角"实时"按钮切换到"回放"模式
- 从时间线第一个事件开始，按原始时间间隔逐条回放
- 支持暂停、继续、快进、后退、跳转、倍速
- 事件列表侧边栏可以直观浏览并跳转到任意事件

**适合**：任务结束后，回顾整个团队协作过程，像看一段加速的"办公室监控录像"。

## 项目结构

```
visual-agent-article-team/
├── README.md                  ← 本文件
├── ARCHITECTURE.md            ← 架构说明
├── article-team/              ← Skill 包（cp 到 .codebuddy/skills/，一次性搞定）
│   ├── SKILL.md
│   ├── commands/
│   │   └── article-team.md    ← 协调者 prompt（含自动启动可视化服务逻辑）
│   ├── shared-writing-resources/
│   │   └── domain-profiles/
│   │       └── domain-profiles.json
│   ├── launch.sh              ← 一键启动脚本（自动检测 teams 目录 + 自动打开浏览器）
│   ├── requirements.txt       ← Python 依赖
│   ├── server/                ← Python 后端
│   │   ├── main.py            ← FastAPI 入口 + REST API + WebSocket 端点
│   │   ├── file_watcher.py    ← watchdog 文件监听器
│   │   ├── state_engine.py    ← 状态解析引擎（文件变化 → 结构化事件）
│   │   ├── event_timeline.py  ← 事件时间线（支持全量/增量/范围查询）
│   │   └── websocket_hub.py   ← WebSocket 管理（实时推送 + 回放推送）
│   └── web/                   ← 前端静态文件
│       ├── index.html         ← 主页面（三区域布局）
│       ├── css/
│       │   ├── office.css     ← 办公室布局、通信面板、回放控制条
│       │   ├── agents.css     ← 6 个角色的配色、状态样式
│       │   └── animations.css ← 全部关键帧动画定义
│       ├── js/
│       │   ├── websocket-client.js  ← WebSocket 连接管理
│       │   ├── office-renderer.js   ← 办公室场景渲染
│       │   ├── agent-controller.js  ← 角色状态控制
│       │   ├── message-animator.js  ← 通信动画（纸飞机、气泡、飞线）
│       │   ├── timeline-player.js   ← 回放控制器
│       │   └── app.js               ← 主逻辑
│       └── svg/
│           ├── office-bg.svg        ← 办公室背景
│           ├── agent-main.svg       ← 协调者
│           ├── agent-scout.svg      ← 侦察员
│           ├── agent-architect.svg  ← 架构师
│           ├── agent-writer.svg     ← 写手
│           ├── agent-reviewer.svg   ← 审稿人
│           └── agent-polisher.svg   ← 润色师
└── agents/                    ← Subagent 注册文件（与 custom 版本相同）
    ├── article-scout.md
    ├── article-architect.md
    ├── article-writer.md
    ├── article-reviewer.md
    └── article-polisher.md
```

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 后端 | Python 3 + FastAPI | REST API + WebSocket 服务 |
| 文件监听 | watchdog | 基于 inotify 的文件系统事件通知 |
| 前端 | 原生 HTML + CSS + JS | 无框架依赖，零构建 |
| 角色形象 | SVG | 纯代码，无需图片资源 |
| 动画 | CSS Animation | GPU 加速，transform + opacity |
| 通信 | WebSocket | 实时推送，毫秒级延迟 |

## 常见问题

### Q: 启动报错"未找到 python3"？

确保系统已安装 Python 3.8+：

```bash
# Ubuntu/Debian
sudo apt install python3 python3-venv

# 验证
python3 --version
```

### Q: 浏览器打开后是空白的？

1. 确认服务已启动（终端有 `🚀 启动 Agent Team 可视化服务...` 输出）
2. 确认访问地址正确（默认 `http://localhost:8765`）
3. 如果 teams 目录下没有数据，页面会显示空办公室——这是正常的，等 Agent Team 开始运行后会实时更新

### Q: 可以同时监听多个团队吗？

可以。指定 teams 根目录即可：

```bash
bash .codebuddy/skills/article-team/launch.sh /path/to/.codebuddy/teams/
```

所有子目录下的团队都会被监听，页面显示最新的那个团队。

### Q: Docker 环境中文件监听不工作？

Docker bind mount 下 inotify 可能不可靠，使用轮询模式：

```bash
bash .codebuddy/skills/article-team/launch.sh --poll
```

### Q: 可视化版和 custom 版的 Skill 有冲突吗？

没有冲突。两者的 Skill 包名都是 `article-team`，安装时会互相覆盖。你只需选择安装其中一个：
- 如果想要可视化：安装本目录的 `article-team/`
- 如果不需要可视化：安装 `custom-agent-article-team/article-team/`

两者唯一的区别是协调者 prompt 中多了可视化服务自动启动逻辑和心跳格式增强标记，不影响核心功能。

### Q: 后续运行还需要重新安装依赖吗？

不需要。`launch.sh` 会检测 `.venv` 是否已存在，存在则直接激活启动，跳过创建和安装步骤。只有当 `requirements.txt` 更新时才会重新安装。

### Q: 可视化服务不需要手动启动了？

是的。协调者 prompt 中已内置自动启动逻辑——在 `team_create` 成功后会自动通过 `execute_command` 后台启动 `launch.sh`。你只需要在浏览器中打开 `http://localhost:8765` 即可。

如果需要在协调者之外独立使用（比如回放历史数据），仍可手动执行 `bash .codebuddy/skills/article-team/launch.sh`。

## 相关文档

- [架构说明](ARCHITECTURE.md) — 系统架构图、数据流、模块职责
- [custom-agent-article-team](../custom-agent-article-team/) — 基础版（无可视化）
- [OpenSpec 设计文档](../../openspec/changes/visual-agent-article-team/) — 完整的 proposal / design / specs / tasks
