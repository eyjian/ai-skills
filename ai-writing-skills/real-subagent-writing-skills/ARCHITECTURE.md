## `real-subagent-writing-skills` 架构说明

本文描述 `real-subagent-writing-skills` 这个安装包——一个**真正的 SubAgent**写作流水线。

## 与现有 `subagent-writing-skills` 的核心区别

| 维度 | 本方案（真正 SubAgent） | 现有方案（skill 直接执行） |
|------|----------------------|------------------------|
| **执行方式** | 每个 skill 触发后通过 `task` 同步模式 spawn 独立子 Agent | skill 自身直接执行（单 Agent 角色扮演） |
| **Agent 实例** | 真正的独立 Agent 实例，有独立上下文 | 无独立实例，共享主对话上下文 |
| **上下文隔离** | 子 Agent 的上下文与主对话隔离 | 所有角色共享同一个上下文 |
| **工具调用** | 通过 `task` Function Call 创建子 Agent | 直接在 skill prompt 中执行 |

## 底层工具

本方案使用 CodeBuddy 的 `task` 工具，并根据角色需要选择不同模式：

### 同步模式（scout、architect、writer）

```text
task(
  subagent_name: "coder",     # 内置通用类型，无需注册
  description: "选题调研",     # 任务简述
  prompt: "..."               # 完整的角色 prompt + 用户输入 + 画像配置
)
```

**关键点**：不传 `name` 和 `team_name`，`task` 自动进入同步模式——阻塞等待子 Agent 执行完毕后返回结果。

### 团队模式（tech-reviewer、final-polisher）

```text
team_create(team_name: "review-team")   # 创建团队
task(
  subagent_name: "coder",
  name: "reviewer",                      # 团队内成员名
  team_name: "review-team",              # 加入的团队
  mode: "bypassPermissions",
  prompt: "..."
)
task(                                    # 按需派发第二个 Agent
  subagent_name: "coder",
  name: "writer",
  team_name: "review-team",
  ...
)
team_delete()                            # 完成后销毁团队
```

**关键点**：tech-reviewer 和 final-polisher 涉及多个角色协作（审稿+改稿、快审+润色），因此使用 `team_create` + `task` 异步模式 + `send_message` 创建真正的多 Agent 团队。

## 设计目标

- **真正的 SubAgent / 多 Agent**：每个角色通过 `task` 工具派发为独立子 Agent 实例
- **用户驱动串行**：用户决定从哪个角色开始、是否跳步、何时回炉
- **检查和修改也是多 Agent**：tech-reviewer 和 final-polisher 自动创建团队，派发多个 Agent 协作（审稿+改稿、快审+润色）
- **上下文隔离**：每个子 Agent 有独立上下文，不污染主对话
- **画像驱动**：先解析领域画像，再进入角色工作
- **包内自包含**：安装本包即可工作

## 包内结构

```text
real-subagent-writing-skills/
├── ARCHITECTURE.md
├── shared-writing-resources/
│   └── domain-profiles/
│       └── domain-profiles.json
├── topic-scout/
│   └── SKILL.md              ← 触发后 task(同步) → 独立子 Agent
├── outline-architect/
│   └── SKILL.md              ← 触发后 task(同步) → 独立子 Agent
├── draft-writer/
│   └── SKILL.md              ← 触发后 task(同步) → 独立子 Agent
├── tech-reviewer/
│   └── SKILL.md              ← 触发后 team_create → task(异步) × 2 → reviewer + writer 团队
└── final-polisher/
    └── SKILL.md              ← 触发后 team_create → task(异步) × 2 → reviewer(快审) + polisher 团队
```

## 执行流程

```text
用户 ──→ /topic-scout ──→ task(同步) ──→ scout 子 Agent ──→ 返回选题方案
  │
  ├──→ /outline-architect ──→ task(同步) ──→ architect 子 Agent ──→ 返回大纲
  │
  ├──→ /draft-writer ──→ task(同步) ──→ writer 子 Agent ──→ 返回初稿
  │
  ├──→ /tech-reviewer ──→ team_create ──→ task(异步) × 2 ──→ reviewer + writer 团队 ──→ 返回审稿报告+改稿
  │                       └──→ send_message(reviewer ↔ writer) ──→ team_delete
  │
  └──→ /final-polisher ──→ team_create ──→ task(异步) × 2 ──→ reviewer(快审) + polisher 团队 ──→ 返回终稿
                           └──→ send_message(reviewer → polisher) ──→ team_delete
```

- scout / architect / writer：用户触发 skill → `task` 同步派发子 Agent → 返回结果 → 用户决定下一步
- tech-reviewer / final-polisher：用户触发 skill → `team_create` 创建团队 → `task` 异步派发多个 Agent → Agent 间 `send_message` 协作 → `team_delete` 清理

## 关键技术决策

### 为什么 tech-reviewer 和 final-polisher 用团队模式

审稿和润色不是简单的单步操作——审稿后往往需要改稿，润色前需要先做技术检查。为了展示真正的多 Agent 协作效果：
- tech-reviewer：创建 `review-team`，reviewer 审查后通过 `send_message` 通知 writer 改稿
- final-polisher：创建 `polish-team`，reviewer 快审后通过 `send_message` 通知 polisher 开工

这样即使用户只是检查或润色一篇文章，也能看到多个 Agent 实例在协作。

### 为什么 scout / architect / writer 保持同步模式

SubAgent 模式的核心特征是**用户驱动串行**——每一步由用户手动触发。scout、architect、writer 这三个角色各自独立完成任务即可，不需要与其他角色实时协作，因此使用 `task` 同步模式更合适。

### 为什么 `subagent_name` 用 `"coder"`

与 Agent Team 版相同：使用内置通用类型降低安装门槛，角色差异化通过 `prompt` 注入实现。

### prompt 中如何注入画像配置

每个 SKILL.md 在派发子 Agent 时，先用 `read_file` 读取 `../shared-writing-resources/domain-profiles/domain-profiles.json`，将其内容嵌入 `task` 的 `prompt` 参数中。这样子 Agent 无需自己再读取配置文件。团队模式（tech-reviewer、final-polisher）中的每个成员 Agent 也通过 prompt 注入方式获取画像配置。

## 领域画像

与现有版本和 Agent Team 版一致：

| 画像 | 模式 | 典型用途 |
|------|------|---------|
| `generic` | `通用模式` | 通用知识解释、实践指南 |
| `health` | `通用模式` | 健康、久坐恢复等 |
| `running` | `通用模式` | 跑步训练、备赛等 |
| `ai` | `AI 专用模式` | AI / LLM / Agent 等 |

## 安装方式

```bash
cp -r real-subagent-writing-skills/* .codebuddy/skills/
```

## 维护原则

- 新增领域时修改本包的 `domain-profiles.json`
- 新增角色时在对应目录下创建 `SKILL.md`
- 如果新角色涉及多 Agent 协作（如审稿后改稿），使用 `team_create` + `task` 异步模式
- 如果新角色是独立任务（如选题、大纲），使用 `task` 同步模式
- 本包与其他三套方案（现有模拟版 × 2、真正 Agent Team 版）互不依赖
