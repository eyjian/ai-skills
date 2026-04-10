## Context

现有 `ai-writing-skills/real-agent-team-writing-skill/article-team/` 已验证了"真正的多 Agent 异步网状协作"模式——通过 `team_create` / `task`(异步) / `send_message` / `team_delete` 工具链，5 个独立 Agent 以网状拓扑协作完成文章编写。该模式包含协调者编排、心跳监控、异常恢复、角色视觉系统等成熟机制。

本设计将该模式迁移到软件开发领域，构建 6 角色研发团队 Skill。后端技术栈确定为 Go + Kratos v2 + GORM + go-redis + sarama，前端为 Vue 3 + TypeScript + Vite + Element Plus + Pinia。

## Goals / Non-Goals

**Goals:**

- 构建一个可安装的 CodeBuddy Skill 包（`ai-rd-team/rd-team/`），一键 `cp -r` 安装即可使用
- 6 个 Agent 角色通过 `team_create` / `task` / `send_message` / `team_delete` 实现真正的多 Agent 异步协作
- 支持 4 种任务模式：新建项目（全 6 角色）、新增功能、修复 bug、代码重构
- 技术栈画像驱动（`tech-profiles.json`），第一版重点打磨 Go + Kratos 画像
- code-reviewer 和 tester 拥有自主决策权（直接退回开发者 / 直接报 bug）
- 前后端可并行开发，通过 `send_message` 直接通信
- 架构开放，新增角色只需加 `agents/*.md` + 更新协调者

**Non-Goals:**

- 不做 SubAgent 流水线版（第一版只做 Agent Team 版）
- 不更新 `install-skill.sh`（先手动安装）
- 不打磨 `python-web` / `node-web` 画像（只做骨架占位）
- 不做 CI/CD 集成（DevOps 角色留给后续迭代）
- 研发团队运行时不使用 OpenSpec 管理需求（OpenSpec 仅用于构建本 Skill）

## Decisions

### D1: Agent Team 版（异步网状拓扑）而非 SubAgent 流水线版

**选择**：使用 `team_create` + `task`(异步，带 name+team_name) + `send_message` 的 Agent Team 模式。

**理由**：软件开发有并行段（前后端同时开发）和频繁回退（reviewer 退回 dev、tester 报 bug），天然需要网状通信。流水线的串行模式不适合。

**替代方案**：SubAgent 流水线（`task` 同步模式）——适合简单项目，但无法支持并行开发和 Agent 间直接通信。留待第二版。

### D2: Kratos v2 作为后端微服务框架

**选择**：Kratos v2（B站开源，接口化设计）。

**理由**：用户已选定 GORM/go-redis/sarama，Kratos 不和这些库冲突（不自带 ORM/Cache/Queue）。Kratos 的 Registry/Config/Log/Metrics/Tracing 全部是接口，官方 contrib 有 etcd/consul/nacos/polaris 等实现，切换云厂商只需改 import。完美满足用户"架构开放性"需求。

**替代方案**：go-zero——开箱即用更快，但自带 sqlx/cache/queue 与用户选定的组件冲突，etcd 紧耦合，换云厂商成本高。纯 gRPC——太裸，需要大量胶水代码。

### D3: Vue 3 + Element Plus 作为前端框架

**选择**：Vue 3 (Composition API) + TypeScript + Vite + Element Plus + Pinia。

**理由**：用户明确选择 Vue 3。Element Plus 是 Vue 3 生态最成熟的企业级 UI 库，AI Agent 生成代码质量稳定。

### D4: tech-profiles.json 画像继承体系

**选择**：采用与写作团队 `domain-profiles.json` 一致的继承结构。`go-kratos-api` 继承 `go-kratos-web`（只覆盖 `has_frontend: false`），`python-web` 和 `node-web` 继承 `generic`。

**理由**：复用已验证的画像合并机制（scalar 覆盖、array 合并去重、object 递归深度合并），降低维护成本。

### D5: subagent_name 统一用 "coder"

**选择**：所有 Agent 的 `subagent_name` 都用内置的 `"coder"`，角色差异化通过 `prompt` 注入。

**理由**：与写作团队一致。使用内置通用类型降低安装门槛，不需要在 `plugin.json` 中注册自定义 Agent 类型。

### D6: Kratos 分层架构作为后端 Agent 核心约束

**选择**：强制 backend-dev 遵循 Kratos 标准分层：`api(proto)` → `internal/service` → `internal/biz`(纯接口) → `internal/data`(GORM/go-redis/sarama 实现)。biz 层禁止 import 任何基础设施包。

**理由**：这是 Kratos 的核心设计哲学，也是实现"开放可替换"的关键。code-reviewer 的首要检视维度就是分层是否正确。

## Risks / Trade-offs

- **[Agent 上下文窗口限制]** → 每个 Agent prompt 本身就有几千 token，加上运行时上下文，可能接近窗口上限。**缓解**：设置合理的 `max_turns`（backend-dev 最大 40），协调者在 prompt 中只注入必要上下文。

- **[前后端并行编排复杂度]** → 两个 Agent 同时运行时，协调者需要等待两者都完成才派发 reviewer。**缓解**：复用写作团队的邮箱轮询机制（30秒检查），明确"等待双方完成"的逻辑。

- **[迭代回退无限循环]** → reviewer 退回 → dev 改 → reviewer 再退回...可能无限循环。**缓解**：最多 2 轮迭代，超过通知用户介入。

- **[Kratos 学习成本]** → Kratos 的 proto 生成 + Wire 依赖注入有一定学习曲线。**缓解**：在 backend-dev 和 architect 的 prompt 中详细说明 Kratos 标准流程和目录结构。

- **[tech-profiles 维护成本]** → 每新增一种技术栈需要创建完整画像。**缓解**：第一版只打磨 Go+Kratos 画像，其他语言只做骨架占位。

- **[Agent 间通信延迟]** → `send_message` 不是实时的，依赖邮箱轮询。**缓解**：心跳机制 + 30 秒轮询间隔，与写作团队一致的已验证方案。
