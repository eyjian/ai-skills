## ADDED Requirements

### Requirement: WebSocket 连接管理

WebSocketHub SHALL 管理所有浏览器 WebSocket 连接，支持多个客户端同时连接。

#### Scenario: 客户端连接

- **WHEN** 浏览器通过 `ws://localhost:{port}/ws/live` 发起 WebSocket 连接
- **THEN** WebSocketHub SHALL 接受连接，将该客户端加入实时推送列表，并发送一条 `connected` 确认消息

#### Scenario: 客户端断开

- **WHEN** 某个 WebSocket 客户端断开连接
- **THEN** WebSocketHub SHALL 将其从推送列表中移除，不影响其他客户端

### Requirement: 实时模式推送

在实时模式下，WebSocketHub SHALL 将 StateEngine 产生的每个事件立即推送给所有已连接的客户端。

#### Scenario: 实时事件推送

- **WHEN** StateEngine 生成了一个 `message_sent` 事件
- **THEN** WebSocketHub SHALL 在 100ms 内将该事件以 JSON 格式推送给所有已连接的客户端

#### Scenario: 初始状态同步

- **WHEN** 新客户端连接时，EventTimeline 中已有历史事件
- **THEN** WebSocketHub SHALL 先发送一条 `snapshot` 消息（包含当前所有 Agent 状态），再开始推送增量事件

### Requirement: 回放模式推送

WebSocketHub SHALL 支持回放模式，通过 `ws://localhost:{port}/ws/replay` 端点提供时间线回放。

#### Scenario: 启动回放

- **WHEN** 客户端连接到回放端点并发送 `{ "action": "play", "speed": 2 }` 命令
- **THEN** WebSocketHub SHALL 从 EventTimeline 的第一个事件开始，按原始时间间隔 / speed 倍速逐条推送事件

#### Scenario: 暂停回放

- **WHEN** 客户端发送 `{ "action": "pause" }` 命令
- **THEN** WebSocketHub SHALL 暂停事件推送，记住当前回放位置

#### Scenario: 继续回放

- **WHEN** 客户端发送 `{ "action": "resume" }` 命令
- **THEN** WebSocketHub SHALL 从暂停位置继续推送

#### Scenario: 调整倍速

- **WHEN** 客户端发送 `{ "action": "speed", "speed": 4 }` 命令
- **THEN** WebSocketHub SHALL 立即将回放速度调整为 4 倍速（事件间隔 = 原始间隔 / 4）

#### Scenario: 跳转到指定时间

- **WHEN** 客户端发送 `{ "action": "seek", "timestamp": "2026-04-13T13:15:00Z" }` 命令
- **THEN** WebSocketHub SHALL 发送一个包含该时间点之前所有事件的 `snapshot` 消息，然后从该时间点继续回放
