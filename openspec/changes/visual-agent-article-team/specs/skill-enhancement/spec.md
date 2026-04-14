## ADDED Requirements

### Requirement: 复用 custom-agent-article-team 的 Subagent

visual-agent-article-team 的 Skill 变体 SHALL 完整复用 `custom-agent-article-team` 的所有 Subagent 定义（scout、architect、writer、reviewer、polisher）和 shared-writing-resources。

#### Scenario: Subagent 文件复用

- **WHEN** 创建 visual-agent-article-team 的 agents/ 目录
- **THEN** SHALL 包含与 custom-agent-article-team 相同的 5 个 Subagent 注册文件，内容一致（名称、agentMode、tools 等不变）

### Requirement: 协调者 prompt 心跳格式增强

visual-agent-article-team 的协调者 prompt（`commands/article-team.md`）SHALL 在保持原有协作流程不变的前提下，增强心跳消息的结构化格式。

#### Scenario: 结构化心跳消息

- **WHEN** 协调者发送心跳/状态更新消息给 Agent
- **THEN** 消息内容 SHALL 包含可解析的状态标记，格式为：
  ```
  [STATUS: {agent_name} = {active|waiting|completed}]
  ```
  附加在正常消息内容之后

#### Scenario: 不改变协作流程

- **WHEN** 对比 visual-agent-article-team 和 custom-agent-article-team 的协调者 prompt
- **THEN** 二者的核心协作流程（选题→大纲→初稿→审稿→润色→定稿）SHALL 完全一致，仅心跳格式有差异

### Requirement: Skill 元数据

visual-agent-article-team 的 SKILL.md SHALL 包含正确的 Skill 元数据。

#### Scenario: SKILL.md 内容

- **WHEN** CodeBuddy 加载此 Skill
- **THEN** SKILL.md SHALL 声明：
  - `name`: visual-agent-article-team
  - `description`: 包含"可视化"关键词的描述
  - `version`: 1.0.0
  - 正确的 commands 和 agents 路径引用
