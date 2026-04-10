## ADDED Requirements

### Requirement: Test plan from acceptance criteria
tester SHALL 基于 PRD 的验收标准（AC）编写测试计划，每个 AC 映射到至少 1 个测试用例（TC-xxx）。

#### Scenario: Test plan completeness
- **WHEN** tester 完成测试计划
- **THEN** test-plan.md 中每个 FR 的每个 AC 至少有 1 个对应 TC

### Requirement: Autonomous bug reporting
tester SHALL 发现致命/严重 bug 时直接 `send_message` 给对应开发者，不经协调者中转。

#### Scenario: Critical bug found
- **WHEN** gRPC 接口测试发现返回数据与 Proto 定义不一致
- **THEN** tester 直接通知 backend-dev，同时通知协调者

### Requirement: Test report with acceptance checklist
tester SHALL 输出测试报告，包含执行概要、Bug 列表（BUG-xxx）、验收标准核对表。

#### Scenario: All tests pass
- **WHEN** 所有测试用例通过且无未修复 bug
- **THEN** 测试报告结论为"可以发布"，通知协调者

### Requirement: Requirement clarification channel
tester SHALL 在发现验收标准不明确时，直接 `send_message` 联系 analyst 请求细化。

#### Scenario: Ambiguous acceptance criteria
- **WHEN** TC 的预期结果无法从 AC 中明确推断
- **THEN** tester 直接联系 analyst 请求澄清
