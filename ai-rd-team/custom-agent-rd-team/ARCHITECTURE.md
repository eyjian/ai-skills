## `custom-agent-rd-team` 架构说明

本文描述 `custom-agent-rd-team` 这个安装包——一个**真正的自定义 Agent 注册**的软件研发团队（方式 B）。

## 与方式 A（rd-team）的核心区别

| 维度 | 本方案（方式 B：自定义 Subagent） | 方式 A（借用内置 coder） |
|------|-------------------------------|------------------------|
| **Agent 注册** | 每个角色在 `.codebuddy/agents/` 中注册为自定义 Subagent，frontmatter 声明 name / description / agentMode / tools | 统一使用内置 `"coder"`，无注册 |
| **subagent_name** | 各角色的注册名：`"rd-analyst"` / `"rd-architect"` / `"rd-backend-dev"` / `"rd-frontend-dev"` / `"rd-code-reviewer"` / `"rd-tester"` | 统一 `"coder"` |
| **工具集控制** | 每个角色 frontmatter 精确声明 `tools` 列表（reviewer 不能写文件，analyst 不做技术选型） | 所有角色共享 coder 的完整工具集 |
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
- **自主决策**：code-reviewer 可自主退回开发者，tester 可自主报 bug
- **包内自包含**：安装本包即可工作，不依赖其他包
- **画像驱动**：技术栈、编码规范、检视标准由包内画像配置决定

## 每个角色的精确工具集

根据各角色职责最小化授权：

| 角色 | 注册名 | tools | 设计理由 |
|------|--------|-------|---------
| 需求分析师 | rd-analyst | read_file, write_to_file, web_search, send_message, list_dir | 需要读写 PRD、搜索调研、浏览项目 |
| 架构设计师 | rd-architect | read_file, write_to_file, web_search, send_message, list_dir | 需要读写设计文档和环境配置 |
| 后端开发 | rd-backend-dev | read_file, write_to_file, replace_in_file, search_content, send_message, execute_command, list_dir | 需要完整的读写能力和命令执行 |
| 前端开发 | rd-frontend-dev | read_file, write_to_file, replace_in_file, search_content, send_message, execute_command, list_dir | 需要完整的读写能力和命令执行 |
| 代码检视 | rd-code-reviewer | read_file, search_content, send_message, list_dir | 需要读取和搜索代码，不需要写文件（只标问题不动手） |
| 测试工程师 | rd-tester | read_file, write_to_file, replace_in_file, search_content, send_message, execute_command, list_dir | 需要读写测试代码和执行测试 |

## 包内结构

```text
custom-agent-rd-team/
├── ARCHITECTURE.md                          ← 本文件
├── agents/                                  ← Subagent 注册文件（安装时复制到 .codebuddy/agents/）
│   ├── rd-analyst.md                       ← 需求分析师（自定义 Subagent）
│   ├── rd-architect.md                     ← 架构设计师（自定义 Subagent）
│   ├── rd-backend-dev.md                   ← 后端开发工程师（自定义 Subagent）
│   ├── rd-frontend-dev.md                  ← 前端开发工程师（自定义 Subagent，按需启动）
│   ├── rd-code-reviewer.md                 ← 代码检视员（自定义 Subagent，自主退回）
│   └── rd-tester.md                        ← 测试工程师（自定义 Subagent，自主报 bug）
└── rd-team/                                 ← Skill 包（安装时复制到 .codebuddy/skills/）
    ├── SKILL.md                             ← Skill 入口
    ├── commands/
    │   └── rd-team.md                       ← 协调者 prompt
    └── shared-rd-resources/
        └── tech-profiles/
            └── tech-profiles.json           ← 技术栈画像配置
```

## 工具链调用流程

```text
# 第 0 步：前置安装（用户执行一次即可）
cp agents/*.md .codebuddy/agents/             # 注册自定义 Subagent
cp -r rd-team .codebuddy/skills/              # 安装 Skill

# 第 1 步：创建团队
team_create(team_name: "rd-team")

# 第 2 步：派发首个 Agent（以新建项目模式为例）
task(
  subagent_name: "rd-analyst",       # 自定义注册名，平台自动加载其 System Prompt
  name: "analyst",                    # 团队内成员名
  team_name: "rd-team",
  mode: "bypassPermissions",
  prompt: "{运行时上下文：技术栈画像、任务模式等}"  # 不再需要注入角色定义
)

# 第 3 步：按需派发后续 Agent
task(subagent_name: "rd-architect", name: "architect", team_name: "rd-team", ...)
task(subagent_name: "rd-backend-dev", name: "backend-dev", team_name: "rd-team", ...)
task(subagent_name: "rd-frontend-dev", name: "frontend-dev", team_name: "rd-team", ...)  # 仅 has_frontend=true
task(subagent_name: "rd-code-reviewer", name: "code-reviewer", team_name: "rd-team", ...)
task(subagent_name: "rd-tester", name: "tester", team_name: "rd-team", ...)

# 第 4 步：Agent 间通信（由各 Agent 自主调用）
# code-reviewer ──→ backend-dev：退回修改
# tester ──→ backend-dev：报告 bug

# 第 5 步：关闭所有 Agent
send_message(type: "shutdown_request", recipient: "analyst")
# ... 对每个活跃成员

# 第 6 步：销毁团队
team_delete()
```

## 关键技术决策

### 为什么从方式 A 升级到方式 B

方式 A 使用内置 `"coder"` 作为所有角色的 `subagent_name`，通过 prompt 注入实现角色差异化。这种方式的局限：

1. **工具集不可控**：所有角色共享 coder 的完整工具集，reviewer 理论上也能调用 `write_to_file` 改文件
2. **prompt 膨胀**：协调者需要 `read_file` 读取每个 agents/*.md 的完整内容（100-200 行）注入到 task() prompt 中
3. **角色边界模糊**：角色定义完全靠 prompt 软约束，平台层面无法区分不同角色

方式 B 通过自定义 Subagent 注册解决了这些问题：工具集精确可控、System Prompt 由平台加载、角色在平台层面有明确注册。

### 命名前缀防冲突

所有角色注册名统一加 `rd-` 前缀（如 `rd-analyst` 而非 `analyst`），避免与 article-team 等其他 Skill 包的 Agent 名冲突。协调者 prompt 中的 team 成员 name 参数仍保持短名（`analyst` / `architect` 等），`subagent_name` 使用注册全名。

### 通信拓扑

```
     analyst ◄────► architect
       ▲               ▲
       │               │
       ▼               ▼
  backend-dev ◄───► frontend-dev
       ▲               ▲
       │               │
       ▼               ▼
 code-reviewer ◄───► tester
       ▲               ▲
       │               │
       ▼               ▼
            main(协调者)

  所有成员均可通过 send_message 直接通信
  main 只在需要用户确认时介入
```

## 4 种任务模式（所有模式都创建团队、都派发多个 Agent）

| 模式 | 参与 Agent | 典型输入 | 多 Agent 协作流程 |
|------|-----------|---------|------------------|
| 新建项目 | analyst → architect → 并行(backend-dev + frontend-dev) → code-reviewer → tester | "做一个..."、"创建..." | 全流程 6 Agent |
| 新增功能 | analyst → architect → dev(s) → code-reviewer → tester | 已有项目 + "加一个..." | 跳过项目初始化 |
| 修复 bug | dev(s) → code-reviewer → tester | "修复..."、"bug" | 直接修复 |
| 代码重构 | architect → dev(s) → code-reviewer → tester | "重构..."、"优化..." | 重新设计 |

## 技术栈画像

本包内置的画像配置与方式 A 完全一致：

| 画像 | has_frontend | 主要技术栈 |
|------|-------------|-----------|
| `generic` | true | 通用（根据用户指定推断） |
| `go-kratos-web` | true | Go + Kratos v2 + GORM + Vue 3 全栈 |
| `go-kratos-api` | false | Go + Kratos v2 + GORM 纯 API |
| `python-web` | true | Python + FastAPI + Vue 3（占位） |
| `node-web` | true | Node.js + NestJS + Vue 3（占位） |

## 安装方式

```bash
# ⚠️ 必须两步都执行

# 步骤 1：注册自定义 Subagent
cp custom-agent-rd-team/agents/*.md .codebuddy/agents/

# 步骤 2：安装 Skill
cp -r custom-agent-rd-team/rd-team .codebuddy/skills/
```

## 向后兼容

如果用户环境不支持自定义 Subagent 注册，可以回退使用 `rd-team/`（方式 A）。两套方案在仓库中并存互不依赖。

## 维护原则

- 新增技术栈时修改本包的 `tech-profiles.json`
- 新增 Agent 角色时在 `agents/` 下添加带 frontmatter 的 `.md` 文件，并在 `commands/rd-team.md` 中添加派发逻辑
- 修改角色工具集时更新对应 agents/*.md 的 frontmatter `tools` 字段
- 本包与 `rd-team`（方式 A）互不依赖
