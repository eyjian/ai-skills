## Why

现有的 AI 写作团队 Skill（`real-agent-team-writing-skill`）已验证了"多 Agent 异步网状协作"的可行性。现在需要将同样的模式迁移到软件开发领域，构建一个纯 AI Agent 组成的研发团队 Skill，覆盖从需求分析到测试验证的完整软件开发生命周期。

目标是让用户输入一句需求描述（如 `/rd-team 做一个用户管理系统`），即可触发 6 个独立 Agent 实例自动协作完成：需求分析 → 架构设计 → 前后端并行开发 → 代码检视 → 测试验证。

## What Changes

- **新增 `ai-rd-team/` 目录**：包含完整的研发团队 Skill 包（Agent Team 版），结构对齐 `real-agent-team-writing-skill/article-team/`
- **新增 6 个 Agent 角色 prompt**：analyst（需求分析师）、architect（架构设计师）、backend-dev（后端开发）、frontend-dev（前端开发，按需可选）、code-reviewer（代码检视）、tester（测试工程师）
- **新增协调者 prompt**（`commands/rd-team.md`）：编排全流程，支持 4 种任务模式（新建项目/新增功能/修复 bug/代码重构）
- **新增技术栈画像配置**（`tech-profiles.json`）：5 个画像，以 Go + Kratos v2 生态为主力（`go-kratos-web` / `go-kratos-api`），Python/Node 保留占位
- **后端技术栈**：Go + Kratos v2 + GORM + go-redis + IBM/sarama(Kafka) + Google Wire + etcd + Prometheus + OpenTelemetry
- **前端技术栈**：Vue 3 (Composition API) + TypeScript + Vite + Element Plus + Pinia + Axios
- **架构开放性**：Kratos 接口化设计，服务发现/配置/可观测性全部可替换（支持腾讯云 Polaris、阿里云 Nacos 等）
- **新增 `ARCHITECTURE.md`**：包级架构说明文档

## Capabilities

### New Capabilities

- `rd-team-orchestration`: 研发团队协调者编排能力——团队创建、Agent 按需派发（含前后端并行）、心跳监控、异常恢复、迭代回退（最多 2 轮）、完成清理。支持 4 种任务模式。
- `requirement-analysis`: 需求分析能力——将用户模糊需求拆解为结构化 PRD（功能需求 FR-xxx / 验收标准 AC / 非功能需求 / 数据模型 / 范围排除）。
- `architecture-design`: 架构设计能力——基于 Kratos 分层架构（service→biz→data）输出技术选型、Protobuf API 定义、数据库设计、任务分解（含并行标注）。
- `backend-development`: 后端开发能力——基于 Kratos + GORM + go-redis + sarama 实现 API，遵循 TDD，biz 层纯接口、data 层基础设施实现。
- `frontend-development`: 前端开发能力——基于 Vue 3 + TypeScript + Element Plus 实现页面，对接后端 gRPC-Gateway HTTP API。
- `code-review`: 代码检视能力——7 维度检视（含 Kratos 分层一致性、Proto 契约符合度），拥有自主退回开发者的决策权。
- `testing`: 测试能力——基于 PRD 验收标准编写测试计划、gRPC 接口测试、Vue 组件测试、E2E 测试，拥有自主报 bug 的决策权。
- `tech-profile-system`: 技术栈画像系统——可继承的画像配置（generic → go-kratos-web/go-kratos-api），为每个角色定义 priorities/must_check/avoid。

### Modified Capabilities

（无现有 capability 需要修改）

## Impact

- **新增文件**：约 10 个文件（ARCHITECTURE.md + SKILL.md + tech-profiles.json + rd-team.md + 6 个 agents/*.md）
- **不影响现有代码**：ai-rd-team/ 是全新目录，与 ai-writing-skills/ 完全独立
- **安装方式**：`cp -r ai-rd-team/rd-team .codebuddy/skills/`
- **依赖**：CodeBuddy 的 team_create / task / send_message / team_delete 工具链（已内置）
