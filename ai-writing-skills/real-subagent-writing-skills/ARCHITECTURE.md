## `real-subagent-writing-skills` 架构说明

本文描述 `real-subagent-writing-skills` 这个安装包——一个**真正的多 SubAgent 写作系统**，包含协调者自动编排的流水线模式和手动单步触发模式。

## 与现有 `subagent-writing-skills` 的核心区别

| 维度 | 本方案（真正 SubAgent） | 现有方案（skill 直接执行） |
|------|----------------------|------------------------|
| **执行方式** | 每个角色通过 `task` 同步模式 spawn 独立子 Agent | skill 自身直接执行（单 Agent 角色扮演） |
| **协调者** | 有统一协调者（`article-pipeline`）自动编排全流程 | 无协调者，用户手动驱动每一步 |
| **Agent 实例** | 真正的独立 Agent 实例，有独立上下文 | 无独立实例，共享主对话上下文 |
| **角色 prompt** | 独立存放在 `agents/` 目录，协调者和单步 skill 共用 | 内嵌在各 SKILL.md 中 |

## 两种使用模式

### 模式 1：协调者自动编排（推荐）

通过 `/article-pipeline` 统一入口触发，协调者按流程自动派发各角色子 Agent：

```text
用户 ──→ /article-pipeline "写一篇关于..."
  │
  └──→ 协调者（article-pipeline）自动编排：
         → task(同步) → scout 子 Agent → 返回选题方案 → 用户确认
         → task(同步) → architect 子 Agent → 返回大纲
         → task(同步) → writer 子 Agent → 返回初稿
         → task(同步) → reviewer 子 Agent → 返回审稿报告
         → [如有问题] → task(同步) → writer 子 Agent → 返回改稿
         → task(同步) → polisher 子 Agent → 返回终稿
```

用户只需在关键节点（选题确认、终稿确认）参与，协调者自动传递上下文。

### 模式 2：手动单步触发

保留原有 5 个独立 skill（`/topic-scout`、`/outline-architect`、`/draft-writer`、`/tech-reviewer`、`/final-polisher`），用户手动逐步触发。其中 tech-reviewer 和 final-polisher 各自创建小型团队：

```text
用户 ──→ /topic-scout ──→ task(同步) ──→ scout 子 Agent ──→ 返回选题方案
  │
  ├──→ /outline-architect ──→ task(同步) ──→ architect 子 Agent ──→ 返回大纲
  │
  ├──→ /draft-writer ──→ task(同步) ──→ writer 子 Agent ──→ 返回初稿
  │
  ├──→ /tech-reviewer ──→ team_create → task(异步) × 2 → reviewer + writer 团队
  │
  └──→ /final-polisher ──→ team_create → task(异步) × 2 → reviewer(快审) + polisher 团队
```

## 底层工具

### 协调者模式：`task` 同步

```text
task(
  subagent_name: "coder",
  description: "选题调研",
  prompt: "{agents/scout.md 内容} + {运行时上下文}"
)
```

不传 `name` 和 `team_name`，阻塞等待子 Agent 返回。协调者在 `prompt` 中注入前序产出和画像配置。

### 单步模式中的团队协作（tech-reviewer、final-polisher）

```text
team_create(team_name: "review-team")
task(subagent_name: "coder", name: "reviewer", team_name: "review-team", ...)
task(subagent_name: "coder", name: "writer", team_name: "review-team", ...)
team_delete()
```

## 设计目标

- **有协调者**：`article-pipeline` 作为统一入口，自动编排全流程
- **真正的 SubAgent**：每个角色通过 `task` 工具派发为独立子 Agent 实例
- **角色 prompt 独立**：`agents/` 目录下 5 个独立角色 prompt，协调者和单步 skill 共用
- **目录结构对齐 Agent Team 版**：SKILL.md + commands/ + agents/ + shared-writing-resources/
- **两种模式并存**：自动编排（推荐）+ 手动单步
- **上下文隔离**：每个子 Agent 有独立上下文，不污染主对话
- **画像驱动**：先解析领域画像，再进入角色工作
- **包内自包含**：安装本包即可工作

## 包内结构

```text
real-subagent-writing-skills/
├── ARCHITECTURE.md
├── shared-writing-resources/                  ← 单步模式用（向后兼容）
│   └── domain-profiles/
│       └── domain-profiles.json
│
├── article-pipeline/                          ← ⭐ 统一入口（协调者自动编排）
│   ├── SKILL.md                              ← 入口（触发描述）
│   ├── shared-writing-resources/
│   │   └── domain-profiles/
│   │       └── domain-profiles.json          ← 画像配置
│   ├── commands/
│   │   └── article-pipeline.md               ← 协调者 prompt（自动编排全流程）
│   └── agents/
│       ├── scout.md                          ← 选题侦察员
│       ├── architect.md                      ← 大纲架构师
│       ├── writer.md                         ← 初稿写手
│       ├── reviewer.md                       ← 技术审稿人
│       └── polisher.md                       ← 终稿润色师
│
├── topic-scout/                               ← 单步触发入口（向后兼容）
│   └── SKILL.md
├── outline-architect/
│   └── SKILL.md
├── draft-writer/
│   └── SKILL.md
├── tech-reviewer/
│   └── SKILL.md
└── final-polisher/
    └── SKILL.md
```

## 与 Agent Team 版的目录结构对比

| | Agent Team 版 | SubAgent 版 |
|---|---|---|
| 统一入口 | `article-team/SKILL.md` | `article-pipeline/SKILL.md` |
| 协调者 | `article-team/commands/article-team.md` | `article-pipeline/commands/article-pipeline.md` |
| 角色 prompt | `article-team/agents/*.md` | `article-pipeline/agents/*.md` |
| 画像配置 | `article-team/shared-writing-resources/` | `article-pipeline/shared-writing-resources/` |
| 通信机制 | `team_create` + `task` 异步 + `send_message` | `task` 同步（协调者传递上下文） |
| 单步入口 | 无 | 5 个独立 SKILL.md |

## 关键技术决策

### 为什么增加协调者

原来的 SubAgent 版没有协调者，用户需要自己记住流程顺序、手动触发每一步、手动传递上下文。增加协调者后：
- 用户只需 `/article-pipeline` 一条命令
- 协调者自动传递选题 → 大纲 → 初稿 → 审稿报告 → 终稿的上下文链
- 协调者根据审稿结果自动决定是否需要改稿

### 为什么保留单步触发入口

有些场景只需要单步操作（如只想审稿不想润色、只想选题探索方向），保留独立 SKILL.md 方便按需使用。

### 为什么 `subagent_name` 用 `"coder"`

与 Agent Team 版相同：使用内置通用类型降低安装门槛，角色差异化通过 `prompt` 注入实现。

## 领域画像

与 Agent Team 版一致：

| 画像 | 模式 | 典型用途 |
|------|------|---------|
| `generic` | `通用模式` | 通用知识解释、实践指南 |
| `health` | `通用模式` | 健康、久坐恢复等 |
| `running` | `通用模式` | 跑步训练、备赛等 |
| `ai` | `AI 专用模式` | AI / LLM / Agent 等 |

## 安装方式

```bash
# 安装全部（协调者 + 单步入口）
cp -r real-subagent-writing-skills/* .codebuddy/skills/

# 只安装协调者模式
cp -r real-subagent-writing-skills/article-pipeline .codebuddy/skills/
```

## 维护原则

- 新增领域时修改 `domain-profiles.json`（两处：`shared-writing-resources/` 和 `article-pipeline/shared-writing-resources/`）
- 新增角色时在 `article-pipeline/agents/` 下添加 `.md` 文件，并在 `commands/article-pipeline.md` 中添加派发逻辑
- 如需新增单步入口，在根目录下创建对应的 `{name}/SKILL.md`
- 本包与其他三套方案互不依赖
