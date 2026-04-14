## ADDED Requirements

### Requirement: 解析 config.json 变化为团队事件

StateEngine SHALL 解析 `config.json` 文件内容，通过对比前后快照提取结构化事件。

#### Scenario: 团队首次创建

- **WHEN** 检测到一个新的 `config.json` 文件创建
- **THEN** StateEngine SHALL 生成 `team_created` 事件，包含 `{ team_name, created_at, members[] }`

#### Scenario: 新成员加入

- **WHEN** `config.json` 的 `members` 数组新增了成员条目
- **THEN** StateEngine SHALL 为每个新成员生成 `agent_joined` 事件，包含 `{ agent_name, role }`

### Requirement: 解析 inbox 变化为消息事件

StateEngine SHALL 解析 `inboxes/{name}.json` 文件内容，通过对比前后消息列表提取新增消息。

#### Scenario: 新消息到达

- **WHEN** 某个 inbox 文件新增了消息条目（通过 `id` 字段去重）
- **THEN** StateEngine SHALL 为每条新消息生成 `message_sent` 事件，包含 `{ id, from, to, type, content, timestamp }`

#### Scenario: 消息被读取

- **WHEN** 某条已存在的消息的 `read` 字段从 `false` 变为 `true`
- **THEN** StateEngine SHALL 生成 `message_read` 事件，包含 `{ id, agent_name, timestamp }`

### Requirement: 维护 Agent 状态机

StateEngine SHALL 维护每个 Agent 的当前状态，状态包括：`idle`（待启动）、`active`（已激活/工作中）、`completed`（已完成）、`error`（异常）。

#### Scenario: Agent 激活

- **WHEN** 首次收到某个 Agent 发送的 `message_sent` 事件（作为 `from`）
- **THEN** StateEngine SHALL 将该 Agent 状态更新为 `active`，并生成 `agent_activated` 事件

#### Scenario: Agent 完成

- **WHEN** 收到 `shutdown_request` 类型的消息，或协调者发送的消息中包含该 Agent 已完成任务的指示
- **THEN** StateEngine SHALL 将该 Agent 状态更新为 `completed`，并生成 `agent_completed` 事件

### Requirement: 初始快照加载

StateEngine SHALL 支持在服务启动时加载已有的团队数据（历史数据），构建初始状态快照。

#### Scenario: 加载已有团队

- **WHEN** 服务启动时指定的 teams 目录下已有团队数据
- **THEN** StateEngine SHALL 扫描所有 `config.json` 和 `inboxes/*.json`，按时间线构建完整的事件序列和当前状态快照

### Requirement: 标准化事件格式

所有 StateEngine 生成的事件 SHALL 遵循统一的 JSON 格式：

```json
{
  "event": "<event_type>",
  "timestamp": "<ISO 8601>",
  "team": "<team_name>",
  "data": { ... }
}
```

#### Scenario: 事件格式一致性

- **WHEN** StateEngine 生成任何事件（team_created、agent_joined、message_sent 等）
- **THEN** 该事件 SHALL 包含 `event`（事件类型字符串）、`timestamp`（ISO 8601 格式）、`team`（团队名称）、`data`（事件特有数据对象）四个顶层字段
