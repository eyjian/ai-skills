---
name: rd-team
description: 自定义 Agent 软件研发团队（方式 B）。当用户要创建新项目、给现有项目新增功能、修复 bug 或代码重构时触发。本方案通过 CodeBuddy 的 team_create / task（异步团队模式，使用自定义注册 Subagent）/ send_message / team_delete 工具链，真正创建多个独立自定义 Agent 实例以网状拓扑协作。与方式 A 的核心区别：每个角色在 .codebuddy/agents/ 中注册为自定义 Subagent，拥有精确的工具集声明，subagent_name 直接引用注册名而非内置 coder。默认技术栈为 Go + Kratos v2 + GORM + Vue 3，支持通过 tech-profiles.json 画像适配其他技术栈。
---

# 软件研发 Agent Team（自定义 Subagent 模式 — 方式 B）

这是一个**真正的自定义 Agent Team**——每个角色（analyst / architect / backend-dev / frontend-dev / code-reviewer / tester）在 CodeBuddy 中注册为独立的自定义 Subagent，拥有各自精确的工具集声明。协调者通过 `task(subagent_name: "rd-analyst")` 等方式直接引用已注册的自定义 Agent。

## 与方式 A（rd-team）的核心区别

| 维度 | 本方案（方式 B：自定义 Subagent） | 方式 A（借用内置 coder） |
|------|-------------------------------|------------------------|
| Agent 注册 | 每个角色在 `.codebuddy/agents/` 中注册为自定义 Subagent | 统一使用内置 `"coder"`，角色差异全靠 prompt 注入 |
| subagent_name | `"rd-analyst"` / `"rd-architect"` 等自定义注册名 | 统一用 `"coder"` |
| 工具集 | 每个角色在 frontmatter 中精确声明 tools 列表 | 所有角色共享 coder 的完整工具集 |
| System Prompt | 由平台自动加载（frontmatter 下方的正文） | 协调者需 `read_file` 读取 agents/*.md 注入到 prompt |
| 安装步骤 | 两步：注册 agents + 安装 skill | 一步：只需安装 skill |

## 前置条件

使用本方案前，必须先完成 Subagent 注册：

```bash
# 步骤 1：注册自定义 Subagent（必须先执行）
cp custom-agent-rd-team/agents/*.md .codebuddy/agents/

# 步骤 2：安装 Skill
cp -r custom-agent-rd-team/rd-team .codebuddy/skills/
```

如果只执行步骤 2 而跳过步骤 1，`task(subagent_name: "rd-analyst")` 等调用将因找不到已注册的 Subagent 而失败。

## 使用方式

输入 `/rd-team` 加上需求描述，即可启动研发团队。

示例：
```
/rd-team 做一个用户管理系统，支持注册、登录、RBAC 权限
/rd-team 给现有项目加全文搜索功能
/rd-team 修复登录接口返回 500 的 bug
/rd-team 重构 internal/data 层，把原生 SQL 改成 GORM
```

## 技术栈画像

启动前先读取 `./shared-rd-resources/tech-profiles/tech-profiles.json`，解析技术栈画像。

当前首批画像：

| 画像 | has_frontend | 主要技术栈 |
|------|-------------|-----------|
| `generic` | true | 通用（根据用户指定推断） |
| `go-kratos-web` | true | Go + Kratos v2 + GORM + Vue 3 全栈 |
| `go-kratos-api` | false | Go + Kratos v2 + GORM 纯 API |
| `python-web` | true | Python + FastAPI + Vue 3（占位） |
| `node-web` | true | Node.js + NestJS + Vue 3（占位） |

## 4 种入口场景（所有模式都创建团队、都派发多个 Agent）

| 场景 | 典型输入 | 参与 Agent | 多 Agent 协作流程 |
|------|---------|-----------|------------------|
| 新建项目 | "做一个..."、"创建..." | 全部 6 个 | analyst → architect → 并行(backend-dev + frontend-dev) → code-reviewer → tester |
| 新增功能 | 已有项目 + "加一个..." | analyst + architect + dev(s) + reviewer + tester | 同上但跳过项目初始化 |
| 修复 bug | "修复..."、"bug" | dev(s) + reviewer + tester | 直接修复 → 检视 → 测试 |
| 代码重构 | "重构..."、"优化..." | architect + dev(s) + reviewer + tester | 重新设计 → 实现 → 检视 → 测试 |

## 团队成员（自定义注册 Subagent）

| 成员 | 代号 | 注册名 | 工具集 | 职责 |
|------|------|--------|-------|------|
| 需求分析师 | analyst | rd-analyst | read_file, write_to_file, web_search, send_message, list_dir | 将模糊需求拆解为结构化 PRD |
| 架构设计师 | architect | rd-architect | read_file, write_to_file, web_search, send_message, list_dir | 技术选型、架构设计、接口契约、环境规划 |
| 后端开发 | backend-dev | rd-backend-dev | read_file, write_to_file, replace_in_file, search_content, send_message, execute_command, list_dir | 按架构实现后端代码 + 单元测试 |
| 前端开发 | frontend-dev | rd-frontend-dev | read_file, write_to_file, replace_in_file, search_content, send_message, execute_command, list_dir | 按架构实现前端页面 + 组件测试（**按需启动**） |
| 代码检视 | code-reviewer | rd-code-reviewer | read_file, search_content, send_message, list_dir | 7 维度检视，**自主决定退回** |
| 测试工程师 | tester | rd-tester | read_file, write_to_file, replace_in_file, search_content, send_message, execute_command, list_dir | 测试计划 + 测试代码 + 执行 + 报告，**自主报 bug** |

## 工具链调用流程

```
team_create("rd-team-{timestamp}")
  → task(subagent_name:"rd-analyst", name:"analyst", team_name:..., prompt:...)
  → task(subagent_name:"rd-architect", name:"architect", team_name:..., prompt:...)
  → task(subagent_name:"rd-backend-dev", name:"backend-dev", team_name:..., prompt:...)   # ┐ 并行
  → task(subagent_name:"rd-frontend-dev", name:"frontend-dev", team_name:..., prompt:...)  # ┘ 并行（如需）
  → task(subagent_name:"rd-code-reviewer", name:"code-reviewer", team_name:..., prompt:...)
  → task(subagent_name:"rd-tester", name:"tester", team_name:..., prompt:...)
  → send_message(type:"shutdown_request", recipient:...) × N
  → team_delete()
```
