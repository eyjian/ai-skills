## ADDED Requirements

### Requirement: Orchestrator creates real Agent team
协调者 SHALL 通过 `team_create` 创建团队容器，通过 `task`（异步团队模式，带 `name` + `team_name`）派发独立 Agent 实例。协调者绝不能自己扮演任何角色。

#### Scenario: New project full pipeline
- **WHEN** 用户输入 `/rd-team 做一个用户管理系统`
- **THEN** 协调者创建团队，按顺序派发 analyst → architect → 并行(backend-dev + frontend-dev) → code-reviewer → tester

#### Scenario: Bug fix mode
- **WHEN** 用户输入包含"修复""bug""报错"等关键词
- **THEN** 协调者仅派发 backend-dev/frontend-dev + code-reviewer + tester，跳过 analyst 和 architect

### Requirement: Four task modes
协调者 SHALL 支持 4 种任务模式：新建项目（全 6 角色）、新增功能（analyst + architect + dev + reviewer + tester）、修复 bug（dev + reviewer + tester）、代码重构（architect + dev + reviewer + tester）。

#### Scenario: Mode detection
- **WHEN** 用户输入"做一个""创建""新建"
- **THEN** 协调者判定为"新建项目"模式，派发全部 6 个角色

### Requirement: Parallel frontend-backend orchestration
当画像 `has_frontend = true` 时，协调者 SHALL 在 architect 完成后同时派发 backend-dev 和 frontend-dev，等待两者都完成后再派发 code-reviewer。

#### Scenario: Parallel development
- **WHEN** architect 完成任务分解，画像为 go-kratos-web
- **THEN** 协调者同时调用 `task` 派发 backend-dev 和 frontend-dev，两者通过 `send_message` 直接通信

### Requirement: Heartbeat and exception recovery
协调者 SHALL 每 30 秒检查邮箱，Agent 通过心跳汇报进度。150 秒无心跳判定异常，最多重启 2 次。

#### Scenario: Agent timeout recovery
- **WHEN** 某 Agent 连续 150 秒无心跳和正式消息
- **THEN** 协调者检查其 history，必要时用相同 name 重新 `task` 派发，最多重启 2 次

### Requirement: Iteration cap
迭代回退（reviewer 退回 → dev 修改 → reviewer 复审）SHALL 最多 2 轮，超过通知用户介入。

#### Scenario: Max iteration reached
- **WHEN** code-reviewer 第 3 次退回同一开发者
- **THEN** 协调者通知用户介入决策
