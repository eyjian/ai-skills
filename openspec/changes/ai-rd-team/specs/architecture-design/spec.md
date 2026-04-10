## ADDED Requirements

### Requirement: Kratos layered architecture enforcement
architect SHALL 在 go-kratos 画像下强制采用 Kratos 标准分层：api(proto) → internal/service → internal/biz(纯接口) → internal/data(实现)。

#### Scenario: Architecture document for Go Kratos project
- **WHEN** 画像为 go-kratos-web 或 go-kratos-api
- **THEN** architecture.md 中必须包含 Kratos 分层说明、标准目录结构、Wire 依赖注入方案

### Requirement: API contracts based on Protobuf
architect SHALL 输出基于 Protobuf 的接口契约（api-contracts.md），每个 API 包含 gRPC method + HTTP route + Request + Response + 状态码。

#### Scenario: API contract completeness
- **WHEN** architect 完成设计
- **THEN** 每个功能需求（FR-xxx）至少映射到 1 个 API 定义，每个 API 有 Request/Response JSON 示例

### Requirement: Task decomposition with parallelism
architect SHALL 将功能需求分解为开发任务（T-xxx），明确标注哪些任务可并行、分配给 backend-dev 还是 frontend-dev。

#### Scenario: Parallel task annotation
- **WHEN** 项目包含前后端
- **THEN** 任务列表中并行任务标注"可并行"，并标明分配给哪个 Agent
