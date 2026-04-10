## ADDED Requirements

### Requirement: Kratos biz-data separation
backend-dev SHALL 在 go-kratos 画像下严格遵循 biz 层纯 Repository 接口 + data 层 GORM/go-redis/sarama 实现。biz 层禁止 import 任何基础设施包。

#### Scenario: Clean biz layer
- **WHEN** backend-dev 实现业务逻辑
- **THEN** `internal/biz/` 目录下的文件不包含 `import "gorm.io` / `import "github.com/redis` / `import "github.com/IBM/sarama` 等

### Requirement: TDD workflow
backend-dev SHALL 遵循 TDD 工作方法（RED-GREEN-REFACTOR）：先写失败的测试，再写最少代码通过测试，最后重构。

#### Scenario: Test before implementation
- **WHEN** backend-dev 实现一个 API 端点
- **THEN** 先编写该端点的单元测试（RED），再编写实现代码使测试通过（GREEN）

### Requirement: Unit test per API
每个 API 端点 SHALL 有对应的单元测试。

#### Scenario: Test coverage
- **WHEN** backend-dev 完成所有分配的任务
- **THEN** 完成报告中列出每个 API 的测试状态，通过率需 > 0
