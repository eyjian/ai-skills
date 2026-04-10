## ADDED Requirements

### Requirement: Inheritable profile hierarchy
tech-profiles.json SHALL 支持画像继承：子画像通过 `inherits_from` 继承父画像，标量字段覆盖、数组字段合并去重、对象字段递归深度合并。

#### Scenario: go-kratos-api inherits go-kratos-web
- **WHEN** 项目匹配 go-kratos-api 画像
- **THEN** 继承 go-kratos-web 的全部 stack 配置，仅覆盖 `has_frontend: false`

### Requirement: Role-specific focus per profile
每个画像 SHALL 为 6 个角色分别定义 `role_focus`（priorities / must_check / avoid）。

#### Scenario: Backend-dev focus in go-kratos-web
- **WHEN** 画像为 go-kratos-web
- **THEN** backend-dev 的 role_focus.must_check 包含"biz 层不 import GORM""使用 Wire 依赖注入"

### Requirement: Signal-based profile routing
画像路由 SHALL 基于用户输入中的关键词信号（signals）自动匹配，匹配不到时回退 generic。

#### Scenario: Go project detection
- **WHEN** 用户输入包含"Go""Kratos""gRPC"等关键词
- **THEN** 自动匹配 go-kratos-web 或 go-kratos-api 画像

### Requirement: Runtime contract resolution
所有 Agent SHALL 在开始工作前解析画像的 runtime_contract，确保 project_type / effective_profile / resolved_stack / has_frontend / role_focus 全部就绪。

#### Scenario: Unresolved contract
- **WHEN** Agent 无法解析画像
- **THEN** 回退 generic 画像并通知协调者
