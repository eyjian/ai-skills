## ADDED Requirements

### Requirement: Seven review dimensions
code-reviewer SHALL 按 7 个维度检视代码：功能正确性、代码质量、安全性、性能、测试覆盖、架构一致性（含 Kratos 分层）、接口契约符合度（Proto vs 实现）。

#### Scenario: Review report format
- **WHEN** code-reviewer 完成检视
- **THEN** 输出 review-N.md 包含阻断项表（🔴）、建议改进表（🟡）、优点（🟢）、维度评分、结论

### Requirement: Autonomous rejection authority
code-reviewer SHALL 拥有自主决策权：有阻断项（🔴）直接 `send_message` 退回对应开发者，不经协调者中转。

#### Scenario: Blocking issue found
- **WHEN** 检视发现 biz 层 import 了 GORM（违反 Kratos 分层）
- **THEN** code-reviewer 直接 `send_message` 给 backend-dev 退回修改，同时通知协调者

### Requirement: Kratos-specific review focus
在 go-kratos 画像下，code-reviewer SHALL 重点检查：biz 层是否依赖 data 实现、Proto 定义质量、Wire 注入合理性、GORM 用法是否在 data 层。

#### Scenario: Kratos layering violation
- **WHEN** backend-dev 代码中 biz 层直接使用 `*gorm.DB`
- **THEN** code-reviewer 标记为 🔴 阻断项
