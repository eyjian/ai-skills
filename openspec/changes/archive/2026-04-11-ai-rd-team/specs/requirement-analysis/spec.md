## ADDED Requirements

### Requirement: Structured PRD output
analyst SHALL 将用户模糊需求拆解为结构化 PRD，包含功能需求（FR-xxx）、验收标准（AC）、非功能需求、数据模型概要、范围排除。

#### Scenario: Complete PRD generation
- **WHEN** 用户提供需求描述
- **THEN** analyst 输出 `docs/requirements/prd.md`，每个 FR 至少有 1 条 AC，P0 功能必须有用户故事

### Requirement: Open questions resolution
analyst SHALL 标记所有需求歧义为开放问题，通过 `send_message` 向协调者请求用户澄清。开放问题全部关闭才算完成。

#### Scenario: Ambiguous requirement
- **WHEN** 需求中存在"可能""或者""待定"等模糊表述
- **THEN** analyst 列为开放问题，通知协调者请求用户确认

### Requirement: Scope exclusion
PRD SHALL 包含"范围排除"章节，明确列出不做什么。

#### Scenario: Scope boundary
- **WHEN** analyst 完成需求分析
- **THEN** PRD 中必须有至少 1 条范围排除项
