---
name: rd-team
description: 真正的多 Agent 软件研发团队。当用户要创建新项目、给现有项目新增功能、修复 bug 或代码重构时触发。本方案通过 CodeBuddy 的 team_create / task（异步团队模式）/ send_message / team_delete 工具链，真正创建多个独立 Agent 实例以网状拓扑协作——Agent 之间可直接对话、自主决策，而非单 Agent 角色扮演。默认技术栈为 Go + Kratos v2 + GORM + Vue 3，支持通过 tech-profiles.json 画像适配其他技术栈。
argument-hint: "[需求描述、功能说明，或现有项目路径 + 修改需求]"
---

# 软件研发 Agent Team（真正的多 Agent 协作）

这是一个**真正的多 Agent Team**——通过 CodeBuddy 的 `team_create` / `task` / `send_message` / `team_delete` 工具链，每个角色作为独立的 Agent 实例运行，可以互相直接对话、自主决策。

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

## 4 种入口场景

| 场景 | 典型输入 | 参与 Agent | 协作流程 |
|------|---------|-----------|---------|
| 新建项目 | "做一个..."、"创建..." | 全部 6 个 | analyst → architect → 并行(backend-dev + frontend-dev) → code-reviewer → tester |
| 新增功能 | 已有项目 + "加一个..." | analyst + architect + dev(s) + reviewer + tester | 同上但跳过项目初始化 |
| 修复 bug | "修复..."、"bug" | dev(s) + reviewer + tester | 直接修复 → 检视 → 测试 |
| 代码重构 | "重构..."、"优化..." | architect + dev(s) + reviewer + tester | 重新设计 → 实现 → 检视 → 测试 |

## 团队成员

| 成员 | 代号 | 职责 |
|------|------|------|
| 需求分析师 | analyst | 将模糊需求拆解为结构化 PRD |
| 架构设计师 | architect | 技术选型、架构设计、接口契约、环境规划 |
| 后端开发 | backend-dev | 按架构实现后端代码 + 单元测试 |
| 前端开发 | frontend-dev | 按架构实现前端页面 + 组件测试（**按需启动**） |
| 代码检视 | code-reviewer | 7 维度检视，**自主决定退回** |
| 测试工程师 | tester | 测试计划 + 测试代码 + 执行 + 报告，**自主报 bug** |

## 工具链调用流程

```
team_create("rd-team-{timestamp}")
  → task(name:"analyst", team_name:..., prompt:...)
  → task(name:"architect", team_name:..., prompt:...)
  → task(name:"backend-dev", team_name:..., prompt:...)   # ┐ 并行
  → task(name:"frontend-dev", team_name:..., prompt:...)   # ┘ 并行（如需）
  → task(name:"code-reviewer", team_name:..., prompt:...)
  → task(name:"tester", team_name:..., prompt:...)
  → send_message(type:"shutdown_request", recipient:...) × N
  → team_delete()
```
