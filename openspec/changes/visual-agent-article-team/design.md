## Context

### 背景

当前 `ai-skills` 仓库中有两套 Agent Team 写作方案（`custom-agent-article-team` 和 `real-agent-team-writing-skill`），均在 CodeBuddy IDE 内运行。用户触发 `/article-team` 后，5 个 Subagent（scout、architect、writer、reviewer、polisher）由协调者（team-lead）编排协作，但整个过程对用户来说是"黑盒"——只能等待最终产出。

### 现状约束

1. **Agent 编排依赖 CodeBuddy**：`team_create`、`task`、`send_message`、`team_delete` 均为 CodeBuddy 平台内置工具，无法脱离
2. **无独立 API Key**：LLM 推理完全由 CodeBuddy 承担，不可能搭建独立的 Agent 运行时
3. **数据源格式已确定**：`.codebuddy/teams/{team-name}/` 下有 `config.json`（团队元信息）和 `inboxes/{name}.json`（各成员收件箱），JSON 结构稳定且包含足够信息
4. **用户是后端开发者**：熟悉 Python，对前端精灵图/Canvas 等不熟悉

### 数据源结构

CodeBuddy 的 teams 目录结构：

```
.codebuddy/teams/{team-name}/
├── config.json                    ← 团队元信息
│   {
│     "name": "article-team-20260413",
│     "createdAt": "2026-04-13T13:09:36.223Z",
│     "members": [
│       { "name": "team-lead", "role": "..." },
│       { "name": "scout", "role": "QMD选题调研" },
│       ...
│     ]
│   }
└── inboxes/{name}.json            ← 各成员收件箱（JSON 数组）
    [
      {
        "id": "msg-1776085961087-bqt3ne",
        "from": "scout",
        "to": "team-lead",
        "type": "message",           ← message | broadcast | shutdown_request | ...
        "content": "## QMD 选题调研报告...",
        "timestamp": "2026-04-13T13:12:41.087Z",
        "read": true
      }
    ]
```

## Goals / Non-Goals

**Goals:**

1. 提供"虚拟办公室"式的 Web 可视化，让用户直观看到 Agent Team 的协作过程
2. 支持实时模式（Agent 运行时实时跟踪）和回放模式（事后按时间线重放）
3. 高度拟人化——每个 Agent 有独特的 SVG 卡通形象、状态动画和通信动画
4. 混合式界面——上方为虚拟办公室场景，下方为聊天气泡通信流
5. 一键启动，零手动配置——用户只需运行 `./launch.sh <teams-dir>`
6. 基于 `custom-agent-article-team` 创建 Skill 变体，复用已有的 Subagent 和协作流程

**Non-Goals:**

1. **不替代 CodeBuddy**：Web 可视化只做"读取和展示"，不提供 Agent 编排能力
2. **不提供 Web 控制面**：用户不能在 Web 页面上下达指令或触发任务（操作仍在 IDE 中）
3. **不支持多用户/远程部署**：仅本地 localhost 服务
4. **不实现语音/视频数字人**：角色形象是 SVG 2D 卡通，不是 3D 模型或真人视频
5. **不修改 CodeBuddy 核心**：不改 `.codebuddy/teams/` 的数据结构，只读不写

## Decisions

### Decision 1: 可视化层定位——观察窗模式

**选择**：Web 页面是纯展示层（观察窗），CodeBuddy IDE 是引擎层

**原因**：
- 无独立 API Key，无法脱离 CodeBuddy 运行 LLM 推理
- Agent 编排工具（team_create / task / send_message）是 CodeBuddy 专属
- 观察窗模式架构最简单：只需读文件 → 推事件 → 渲染动画

**替代方案**：
- 独立 Agent 平台（需 API Key + 自建编排引擎）→ 排除
- 混合控制模式（Web 既展示又操作）→ 增加复杂度且价值不高

### Decision 2: 技术栈——Python FastAPI + 原生前端

**选择**：
- 后端：Python 3 + FastAPI + watchdog + uvicorn
- 前端：原生 HTML + CSS + JavaScript + SVG（不使用 React/Vue 等框架）
- 通信：WebSocket（实时推送）+ REST API（数据查询）

**原因**：
- 用户已有 Python 环境（dicom-doctor 项目佐证）
- FastAPI 内置 WebSocket 支持，watchdog 高效监听文件变化
- 原生前端无需 Node.js 构建链，降低部署复杂度
- SVG 是代码（XML），可精确控制，不需要美术技能

**替代方案**：
- Node.js Express + ws → 需要 Node 环境，用户更熟悉 Python → 排除
- 纯静态前端 → 无法实时监听文件变化 → 排除

### Decision 3: 角色形象——CSS/SVG 动画方案

**选择**：SVG 卡通形象 + CSS Animation 驱动状态动画

**原因**：
- SVG 是纯代码，无需外部图片资源
- CSS Animation 可实现精致的 2D 动画效果
- 开发量可控（~2000 行前端代码），后续可迭代升级
- 用户不熟悉精灵图/Canvas，SVG+CSS 对后端开发者更友好

**替代方案**：
- Canvas 像素风精灵图 → 需额外图片资源、开发量翻倍 → 排除
- WebGL 3D → 过于复杂 → 排除

### Decision 4: 实时性方案——watchdog + WebSocket

**选择**：
- watchdog 监听 `.codebuddy/teams/` 目录的文件系统事件
- 文件变化时由 StateEngine 解析出状态事件
- 通过 WebSocket 推送到浏览器

**原因**：
- watchdog 使用 OS 级别的文件事件通知（inotify），延迟低（毫秒级）
- WebSocket 双向通信，支持实时推送和回放控制
- 对比轮询方案，资源消耗更低、延迟更小

### Decision 5: 回放系统——事件时间线重放

**选择**：
- 首次加载时扫描全部 `inboxes/*.json` 和 `config.json`，构建完整事件时间线
- 回放时按时间线逐条通过 WebSocket 推送事件
- 支持倍速（1x/2x/4x/8x）、暂停/继续、跳转

**原因**：
- 所有事件都有 `timestamp` 字段，可精确还原时序
- 基于事件重放（而非快照重放）更轻量，前端复用实时模式的渲染逻辑

### Decision 6: 项目结构——独立目录 + Skill 变体

**选择**：在 `ai-writing-skills/visual-agent-article-team/` 下创建独立项目

**原因**：
- 与 `custom-agent-article-team` 平行，不破坏已有方案
- Skill 包结构复用 custom 版本的 agents/ 和 shared-writing-resources/
- Web 可视化代码（server/ + web/）独立于 Skill 包

## Risks / Trade-offs

### [Risk 1] CodeBuddy teams 目录格式变化

CodeBuddy 的 `.codebuddy/teams/` 目录结构是内部实现，可能在版本更新中变化。

→ **Mitigation**: StateEngine 层做数据解析适配，前端只消费标准化事件。如格式变化只需改 StateEngine 一处。

### [Risk 2] 文件监听的边界条件

watchdog 在某些文件系统（如 NFS、Docker bind mount）上可能不可靠。

→ **Mitigation**: 提供 fallback 轮询模式（每 2 秒扫描一次），通过启动参数 `--poll` 切换。

### [Risk 3] 大量消息时的前端性能

如果 Agent Team 运行时间长、消息量大，通信流面板和办公室动画可能卡顿。

→ **Mitigation**: 通信流面板做虚拟滚动（只渲染可见区域）；动画使用 CSS transform/opacity（GPU 加速）；回放模式下限制最大事件缓冲区大小。

### [Risk 4] SVG 角色的视觉复杂度

6 个角色的 SVG 设计 + 多种状态动画，工作量可能超预期。

→ **Mitigation**: Phase 1 先用简化的 SVG 角色（几何图形 + 配色 + 图标特征），Phase 2 再打磨精致细节。确保骨架先跑通。

### [Risk 5] 心跳消息格式增强可能影响协调者 prompt

修改协调者 prompt 要求心跳格式更结构化，可能影响 LLM 的执行稳定性。

→ **Mitigation**: 心跳格式增强是可选的（nice-to-have）。StateEngine 可以从现有的消息格式中推断出大部分状态，不强依赖心跳增强。
