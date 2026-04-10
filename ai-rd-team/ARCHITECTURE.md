## `ai-rd-team` 架构说明

本文描述 `ai-rd-team` 这个安装包——一个**真正的多 Agent 软件研发团队**，通过 CodeBuddy 的 `team_create` / `task`（异步团队模式）/ `send_message` / `team_delete` 工具链，创建 6 个独立 Agent 实例以网状拓扑协作完成完整的软件开发生命周期。

## 设计目标

- **真正的多 Agent**：每个角色是独立的 Agent 实例，不是单 Agent 角色扮演
- **网状通信**：任意成员可通过 `send_message` 直接对话，不必经过协调者中转
- **自主决策**：code-reviewer 可直接退回开发者，tester 可直接报 bug 给开发者
- **画像驱动**：先解析技术栈画像，再进入角色工作
- **环境初始化**：architect 规划环境（docker-compose/Makefile/README），dev 各自搭建并验证
- **前后端并行**：backend-dev 和 frontend-dev 同时开发，通过 send_message 协调接口对接
- **可扩展**：新增角色只需加 `agents/*.md` + 更新协调者 prompt
- **包内自包含**：安装本包即可工作

## 与写作团队 skill 的核心对比

| 维度 | 研发团队（本方案） | 写作团队（article-team） |
|------|-------------------|------------------------|
| **角色数** | 6 个（analyst/architect/backend-dev/frontend-dev/code-reviewer/tester） | 5 个（scout/architect/writer/reviewer/polisher） |
| **任务模式** | 4 种（新建项目/新增功能/修复 bug/代码重构） | 3 种（新稿/重审/润色） |
| **并行能力** | 前后端并行开发 | 串行流水线 |
| **画像类型** | 技术栈画像（Go Kratos/Python/Node） | 领域画像（AI/健康/跑步/通用） |
| **产出物** | 代码 + 测试 + 文档 + 环境配置 | Markdown 文章 |
| **环境初始化** | architect 规划 + dev 执行 | 无需 |
| **通信拓扑** | 网状（同） | 网状（同） |
| **工具链** | team_create/task/send_message/team_delete（同） | 同 |

## 底层工具链

### 异步团队模式

```text
# 第 1 步：创建团队
team_create(team_name: "rd-team")

# 第 2 步：按需派发 Agent
task(subagent_name: "coder", name: "analyst", team_name: "rd-team", mode: "bypassPermissions", ...)
task(subagent_name: "coder", name: "architect", team_name: "rd-team", ...)
task(subagent_name: "coder", name: "backend-dev", team_name: "rd-team", ...)
task(subagent_name: "coder", name: "frontend-dev", team_name: "rd-team", ...)  # 按需
task(subagent_name: "coder", name: "code-reviewer", team_name: "rd-team", ...)
task(subagent_name: "coder", name: "tester", team_name: "rd-team", ...)

# 第 3 步：Agent 间通信
# code-reviewer → backend-dev：退回修改
# tester → frontend-dev：报 bug
# backend-dev ↔ frontend-dev：接口对接
# 任意 Agent → main：需要用户确认时

# 第 4 步：关闭所有 Agent
send_message(type: "shutdown_request", recipient: "analyst")
... (对每个活跃 Agent)

# 第 5 步：销毁团队
team_delete()
```

## 通信拓扑

```text
        analyst ◄────► architect
          ▲               ▲
          │               │
          │      ┌────────┼────────┐
          │      │        │        │
          ▼      ▼        ▼        ▼
        tester  backend ◄──► frontend
          ▲      ▲              ▲
          │      │              │
          ▼      ▼              ▼
        code-reviewer ◄────► main(协调者)

  ◄──► 表示通过 send_message 直接对话
  每个角色都是通过 task 工具派发的独立 Agent 实例
```

## 4 种任务模式

| 模式 | 识别信号 | 参与 Agent | 说明 |
|------|---------|-----------|------|
| 新建项目 | "做一个""创建""新建" | 全部 6 个 | 全流程 |
| 新增功能 | 已有项目 + "加一个""增加" | analyst + architect + dev(s) + reviewer + tester | 跳过项目初始化 |
| 修复 bug | "修复""bug""报错" | dev(s) + reviewer + tester | 跳过需求和设计 |
| 代码重构 | "重构""优化""重写" | architect + dev(s) + reviewer + tester | 跳过需求分析 |

## 技术栈画像

本包使用 `tech-profiles.json` 配置技术栈画像，结构对齐写作团队的 `domain-profiles.json`。

第一版画像（以 Go + Kratos 为主力）：

| 画像 | has_frontend | 主要技术栈 |
|------|-------------|-----------|
| `generic` | true | 通用基础画像 |
| `go-kratos-web` | true | Go + Kratos v2 + GORM + Vue 3 全栈 |
| `go-kratos-api` | false | Go + Kratos v2 + GORM 纯 API |
| `python-web` | true | Python + FastAPI（占位） |
| `node-web` | true | Node.js + NestJS（占位） |

## 环境初始化策略

| 角色 | 环境职责 |
|------|---------|
| architect | 输出 docker-compose.yaml（MySQL/Redis/Kafka/etcd）+ Makefile（init/proto/wire/run/test/lint）+ README.md（快速开始） |
| backend-dev | kratos new → go mod tidy → proto 生成 → Wire 生成 → migration → 验证双端口启动 |
| frontend-dev | npm create vue@latest → 依赖安装 → Vite 代理配置 → ESLint → 验证 dev server |

## 包内结构

```text
ai-rd-team/
├── ARCHITECTURE.md
└── rd-team/
    ├── SKILL.md
    ├── shared-rd-resources/
    │   └── tech-profiles/
    │       └── tech-profiles.json
    ├── commands/
    │   └── rd-team.md              ← 协调者 prompt
    └── agents/
        ├── analyst.md              ← 需求分析师
        ├── architect.md            ← 架构设计师
        ├── backend-dev.md          ← 后端开发工程师
        ├── frontend-dev.md         ← 前端开发工程师（按需）
        ├── code-reviewer.md        ← 代码检视员
        └── tester.md               ← 测试工程师
```

## 安装方式

```bash
cp -r ai-rd-team/rd-team .codebuddy/skills/
```

## 维护原则

- 新增技术栈画像时修改 `tech-profiles.json`
- 新增 Agent 角色时在 `agents/` 下添加 `.md` 文件，并在 `commands/rd-team.md` 中添加派发逻辑
- 本包与写作团队 skill 互不依赖

## 关键技术决策

### 为什么选 Kratos 而非 go-zero

Kratos 的接口化设计（Registry/Config/Log/Metrics/Tracing 全是接口）完美匹配"开放可替换"需求。用户已选定 GORM/go-redis/sarama，go-zero 的一体化优势用不上，反而被其封闭性约束。

### 为什么 `subagent_name` 用 `"coder"`

与写作团队一致：使用内置通用类型降低安装门槛，角色差异化通过 `prompt` 注入实现。

### 为什么 architect 负责环境规划

architect 最了解全局技术选型，知道需要哪些依赖服务。Docker Compose / Makefile / README 由 architect 统一输出，避免前后端各搞各的不一致。dev 各自执行自己的环境初始化。
