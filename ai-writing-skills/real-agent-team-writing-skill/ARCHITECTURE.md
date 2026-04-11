## `real-agent-team-writing-skill` 架构说明

本文描述 `real-agent-team-writing-skill` 这个安装包——一个**真正的多 Agent 协作**文章编写团队。

## 与现有 `agent-team-writing-skill` 的核心区别

| 维度 | 本方案（真正多 Agent） | 现有方案（skill 模拟） |
|------|----------------------|----------------------|
| **Agent 实例** | 每个角色通过 `task` 异步派发为独立 Agent 实例 | 单个 AI 对话角色扮演 |
| **通信机制** | 通过 `send_message` Function Call 实现真正消息传递 | prompt 文字描述通信，实际未调用 |
| **团队生命周期** | `team_create` → `task` × N → `send_message` → `team_delete` | 无团队容器，无生命周期 |
| **并行能力** | Agent 在后台异步运行，真正并行 | 严格串行 |
| **自主决策** | reviewer 直接 `send_message` 给 writer 退回 | 协调者代为决策 |

## 底层工具链

本方案完全基于 CodeBuddy 的四个标准工具函数：

1. **`team_create`**：创建团队容器，给 Agent 提供协作空间
2. **`task`**（异步团队模式）：同时传入 `name` + `team_name`，将角色派发为独立 Agent 实例在后台运行
3. **`send_message`**：Agent 间的唯一通信通道，支持点对点消息、广播和关闭请求
4. **`team_delete`**：销毁团队，释放所有资源

这四个工具和 `read_file`、`execute_command` 属于同一类——都是标准的 Function Call，没有特殊协议。

## 设计目标

- **真正的多 Agent**：每个角色是独立的 Agent 实例，不是单 Agent 角色扮演
- **网状通信**：任意成员可通过 `send_message` 直接对话，不必经过协调者中转
- **自主决策**：reviewer 可自主退回 writer，polisher 可自主回退 reviewer
- **包内自包含**：安装本包即可工作，不依赖其他包
- **画像驱动**：写法、边界、审稿标准由包内画像配置决定

## 包内结构

```text
real-agent-team-writing-skill/
├── ARCHITECTURE.md
└── article-team/
    ├── SKILL.md
    ├── shared-writing-resources/
    │   └── domain-profiles/
    │       └── domain-profiles.json
    ├── commands/
    │   └── article-team.md          ← 协调者 prompt（真正调用 team_create / task / send_message / team_delete）
    └── agents/
        ├── scout.md                 ← 选题侦察员（独立 Agent 实例）
        ├── architect.md             ← 大纲架构师（独立 Agent 实例）
        ├── writer.md                ← 初稿写手（独立 Agent 实例）
        ├── reviewer.md              ← 技术审稿人（独立 Agent 实例，自主退回）
        └── polisher.md              ← 终稿润色师（独立 Agent 实例）
```

## 工具链调用流程

```text
# 第 1 步：创建团队
team_create(team_name: "article-team")

# 第 2 步：派发首个 Agent（以新稿模式为例）
task(
  subagent_name: "coder",        # 内置通用类型，无需注册
  name: "scout",                  # 团队内成员名
  team_name: "article-team",      # 加入的团队
  mode: "bypassPermissions",
  prompt: "{scout.md 内容 + 运行时上下文}"
)

# 第 3 步：按需派发后续 Agent
task(subagent_name: "coder", name: "architect", team_name: "article-team", ...)
task(subagent_name: "coder", name: "writer", team_name: "article-team", ...)
task(subagent_name: "coder", name: "reviewer", team_name: "article-team", ...)
task(subagent_name: "coder", name: "polisher", team_name: "article-team", ...)

# 第 4 步：Agent 间通信（通过 send_message，由各 Agent 自主调用）
# reviewer ──→ writer：退回修改
# polisher ──→ reviewer：技术问题回退
# architect ──→ scout：讨论选题
# 任意 Agent ──→ main：需要用户确认时

# 第 5 步：关闭所有 Agent
send_message(type: "shutdown_request", recipient: "scout")
send_message(type: "shutdown_request", recipient: "architect")
send_message(type: "shutdown_request", recipient: "writer")
send_message(type: "shutdown_request", recipient: "reviewer")
send_message(type: "shutdown_request", recipient: "polisher")

# 第 6 步：销毁团队
team_delete()
```

## 关键技术决策

### 为什么 `subagent_name` 用 `"coder"` 而不是自定义名称

CodeBuddy 的 `task` 工具要求 `subagent_name` 匹配已注册的 Agent 类型。自定义 Agent 需要在目标项目的 `plugin.json` 中注册才能被识别。

为了降低安装门槛（用户只需复制文件到 `.codebuddy/skills/` 即可使用），本方案统一使用内置的 `"coder"` 作为 `subagent_name`，通过 `prompt` 参数注入完整的角色定义来实现角色差异化。效果等价于使用自定义 Agent 类型。

如果用户在 `plugin.json` 中注册了自定义 Agent 类型（如 `"scout"`、`"reviewer"` 等），可以在 `commands/article-team.md` 中将 `subagent_name` 替换为对应的自定义名称。

### Agent prompt 的来源和注入方式

协调者在派发每个 Agent 时：
1. 先用 `read_file` 读取 `agents/{name}.md` 的完整内容
2. 将其作为 `task` 的 `prompt` 参数的主体
3. 在末尾追加运行时上下文：领域画像解析结果、任务模式、团队成员列表、前序产出等

### 通信拓扑

```
          scout ◄────► architect
            ▲              ▲
            │              │
            ▼              ▼
        reviewer ◄────► writer
            ▲              ▲
            │              │
            ▼              ▼
          polisher ◄───► main(协调者)
            
  所有成员均可通过 send_message 直接通信
  main 只在需要用户确认时介入
```

## 三种任务模式（所有模式都创建团队、都派发多个 Agent）

| 模式 | 参与 Agent | 典型输入 | 多 Agent 协作流程 |
|------|-----------|---------|------------------|
| 新稿创作 | scout → architect → writer → reviewer → polisher | 只有方向、主题或选题想法，不涉及已有文件 | 全流程 5 Agent |
| 旧稿重审 / 回炉 | reviewer → writer → polisher | 文件路径 + 修改/改/调整/优化/重写/重构/检查/审查/重审/回炉/改稿/改写/编辑/更新/完善/补充/删减/精简/扩充 | reviewer 审查 → writer 改稿 → polisher 润色 |
| 旧稿直接润色 | reviewer（快审）→ polisher | 文件路径 + 只润色/去 AI 味/发布前打磨 | reviewer 先快审 → polisher 润色 |

**兜底规则**：提到已有文件但未明确说"只润色"时，一律按旧稿重审 / 回炉模式处理。

**核心原则**：即使只是检查或润色已有文章，也通过 `team_create` 创建团队、通过 `task` 派发多个独立 Agent 实例协作，确保展示真正的多 Agent 效果。协调者绝不直接修改用户文章。

## 领域画像

本包内置的画像配置与现有版本一致：

| 画像 | 模式 | 典型用途 |
|------|------|---------|
| `generic` | `通用模式` | 通用知识解释、实践指南 |
| `health` | `通用模式` | 健康、久坐恢复等 |
| `running` | `通用模式` | 跑步训练、备赛等 |
| `ai` | `AI 专用模式` | AI / LLM / Agent 等 |

## 安装方式

```bash
cp -r real-agent-team-writing-skill/article-team .codebuddy/skills/
```

## 维护原则

- 新增领域时修改本包的 `domain-profiles.json`
- 新增 Agent 角色时在 `agents/` 下添加 `.md` 文件，并在 `commands/article-team.md` 中添加派发逻辑
- 本包与现有 `agent-team-writing-skill` 和 `subagent-writing-skills` 互不依赖
