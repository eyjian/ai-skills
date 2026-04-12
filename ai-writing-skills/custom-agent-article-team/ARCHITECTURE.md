## `custom-agent-article-team` 架构说明

本文描述 `custom-agent-article-team` 这个安装包——一个**真正的自定义 Agent 注册**的文章编写团队（方式 B）。

## 与方式 A（real-agent-team-writing-skill）的核心区别

| 维度 | 本方案（方式 B：自定义 Subagent） | 方式 A（借用内置 coder） |
|------|-------------------------------|------------------------|
| **Agent 注册** | 每个角色在 `.codebuddy/agents/` 中注册为自定义 Subagent，frontmatter 声明 name / description / agentMode / tools | 统一使用内置 `"coder"`，无注册 |
| **subagent_name** | 各角色的注册名：`"article-scout"` / `"article-architect"` / `"article-writer"` / `"article-reviewer"` / `"article-polisher"` | 统一 `"coder"` |
| **工具集控制** | 每个角色 frontmatter 精确声明 `tools` 列表（scout 不能写文件，reviewer 不能改文字） | 所有角色共享 coder 的完整工具集 |
| **System Prompt 来源** | 平台自动加载（agents/*.md 的 frontmatter 下方正文） | 协调者需 `read_file` 读取 agents/*.md 注入到 task() prompt |
| **prompt 长度** | 协调者 prompt 更短：只注入运行时上下文 | 协调者 prompt 更长：需注入完整角色定义 |
| **安装步骤** | 两步：先注册 agents → 再安装 skill | 一步：只需安装 skill |
| **通信机制** | 相同：`send_message` 直接通信 | 相同 |
| **团队生命周期** | 相同：`team_create` → `task` → `send_message` → `team_delete` | 相同 |

## 底层工具链

本方案基于 CodeBuddy 的四个标准工具函数 + 自定义 Subagent 注册机制：

1. **自定义 Subagent 注册**（`.codebuddy/agents/*.md`）：每个角色以 Markdown 文件注册，frontmatter 声明 `name` / `description` / `agentMode` / `tools`，正文为 System Prompt
2. **`team_create`**：创建团队容器
3. **`task`**（异步团队模式）：传入 `subagent_name`（自定义注册名）+ `name` + `team_name`，派发独立 Agent 实例
4. **`send_message`**：Agent 间通信
5. **`team_delete`**：销毁团队

## 设计目标

- **精确工具集**：每个角色只能使用其职责所需的工具，遵循最小权限原则
- **平台级角色定义**：角色 System Prompt 由平台自动加载，不需要协调者手动注入
- **真正的多 Agent**：每个角色是独立的自定义 Agent 实例
- **网状通信**：任意成员可通过 `send_message` 直接对话
- **自主决策**：reviewer 可自主退回 writer，polisher 可自主回退 reviewer
- **包内自包含**：安装本包即可工作，不依赖其他包
- **画像驱动**：写法、边界、审稿标准由包内画像配置决定

## 每个角色的精确工具集

根据各角色职责最小化授权：

| 角色 | 注册名 | tools | 设计理由 |
|------|--------|-------|---------|
| 选题侦察员 | article-scout | read_file, web_search, send_message, list_dir | 需要搜索和读取，不需要写文件 |
| 大纲架构师 | article-architect | read_file, web_search, send_message | 需要搜索和读取，不需要写文件 |
| 初稿写手 | article-writer | read_file, write_to_file, replace_in_file, search_content, send_message, web_search | 需要完整的读写能力 |
| 技术审稿人 | article-reviewer | read_file, web_search, search_content, send_message | 需要搜索验证，不需要改文件（只标问题不动手） |
| 终稿润色师 | article-polisher | read_file, replace_in_file, search_content, send_message | 需要修改文件，不需要 web_search（不做事实核查） |

## 包内结构

```text
custom-agent-article-team/
├── ARCHITECTURE.md                          ← 本文件
├── agents/                                  ← Subagent 注册文件（安装时复制到 .codebuddy/agents/）
│   ├── article-scout.md                     ← 选题侦察员（自定义 Subagent）
│   ├── article-architect.md                 ← 大纲架构师（自定义 Subagent）
│   ├── article-writer.md                    ← 初稿写手（自定义 Subagent）
│   ├── article-reviewer.md                  ← 技术审稿人（自定义 Subagent，自主退回）
│   └── article-polisher.md                  ← 终稿润色师（自定义 Subagent）
└── article-team/                            ← Skill 包（安装时复制到 .codebuddy/skills/）
    ├── SKILL.md                             ← Skill 入口
    ├── commands/
    │   └── article-team.md                  ← 协调者 prompt
    └── shared-writing-resources/
        └── domain-profiles/
            └── domain-profiles.json         ← 领域画像配置
```

## 工具链调用流程

```text
# 第 0 步：前置安装（用户执行一次即可）
cp agents/*.md .codebuddy/agents/             # 注册自定义 Subagent
cp -r article-team .codebuddy/skills/          # 安装 Skill

# 第 1 步：创建团队
team_create(team_name: "article-team")

# 第 2 步：派发首个 Agent（以新稿模式为例）
task(
  subagent_name: "article-scout",    # 自定义注册名，平台自动加载其 System Prompt
  name: "scout",                      # 团队内成员名
  team_name: "article-team",
  mode: "bypassPermissions",
  prompt: "{运行时上下文：领域画像、任务模式等}"  # 不再需要注入角色定义
)

# 第 3 步：按需派发后续 Agent
task(subagent_name: "article-architect", name: "architect", team_name: "article-team", ...)
task(subagent_name: "article-writer", name: "writer", team_name: "article-team", ...)
task(subagent_name: "article-reviewer", name: "reviewer", team_name: "article-team", ...)
task(subagent_name: "article-polisher", name: "polisher", team_name: "article-team", ...)

# 第 4 步：Agent 间通信（由各 Agent 自主调用）
# reviewer ──→ writer：退回修改
# polisher ──→ reviewer：技术问题回退

# 第 5 步：关闭所有 Agent
send_message(type: "shutdown_request", recipient: "scout")
# ... 对每个活跃成员

# 第 6 步：销毁团队
team_delete()
```

## 关键技术决策

### 为什么从方式 A 升级到方式 B

方式 A 使用内置 `"coder"` 作为所有角色的 `subagent_name`，通过 prompt 注入实现角色差异化。这种方式的局限：

1. **工具集不可控**：所有角色共享 coder 的完整工具集，reviewer 理论上也能调用 `write_to_file` 改文件
2. **prompt 膨胀**：协调者需要 `read_file` 读取每个 agents/*.md 的完整内容（100-250 行）注入到 task() prompt 中
3. **角色边界模糊**：角色定义完全靠 prompt 软约束，平台层面无法区分不同角色

方式 B 通过自定义 Subagent 注册解决了这些问题：工具集精确可控、System Prompt 由平台加载、角色在平台层面有明确注册。

### 命名前缀防冲突

所有角色注册名统一加 `article-` 前缀（如 `article-scout` 而非 `scout`），避免与 rd-team 等其他 Skill 包的 Agent 名冲突。协调者 prompt 中的 team 成员 name 参数仍保持短名（`scout` / `architect` 等），`subagent_name` 使用注册全名。

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
| 旧稿重审 / 回炉 | reviewer → writer → polisher | 文件路径 + 修改类动词 | reviewer 审查 → writer 改稿 → polisher 润色 |
| 旧稿直接润色 | reviewer（快审）→ polisher | 文件路径 + 只润色/去 AI 味/发布前打磨 | reviewer 先快审 → polisher 润色 |

## 领域画像

本包内置的画像配置与方式 A 完全一致：

| 画像 | 模式 | 典型用途 |
|------|------|---------|
| `generic` | `通用模式` | 通用知识解释、实践指南 |
| `health` | `通用模式` | 健康、久坐恢复等 |
| `running` | `通用模式` | 跑步训练、备赛等 |
| `ai` | `AI 专用模式` | AI / LLM / Agent 等 |

## 安装方式

```bash
# ⚠️ 必须两步都执行

# 步骤 1：注册自定义 Subagent
cp custom-agent-article-team/agents/*.md .codebuddy/agents/

# 步骤 2：安装 Skill
cp -r custom-agent-article-team/article-team .codebuddy/skills/
```

## 向后兼容

如果用户环境不支持自定义 Subagent 注册，可以回退使用 `real-agent-team-writing-skill/`（方式 A）。两套方案在仓库中并存互不依赖。

## 维护原则

- 新增领域时修改本包的 `domain-profiles.json`
- 新增 Agent 角色时在 `agents/` 下添加带 frontmatter 的 `.md` 文件，并在 `commands/article-team.md` 中添加派发逻辑
- 修改角色工具集时更新对应 agents/*.md 的 frontmatter `tools` 字段
- 本包与 `real-agent-team-writing-skill`、`agent-team-writing-skill` 和 `subagent-writing-skills` 互不依赖
