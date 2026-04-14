## ADDED Requirements

### Requirement: 通信路径可视化

message-visualizer SHALL 在办公室场景中渲染 Agent 之间的通信路径。

#### Scenario: 通信连线

- **WHEN** 收到 `message_sent` 事件
- **THEN** SHALL 在发送者和接收者的工位之间渲染一条 SVG 弧线路径，路径颜色取发送者的主配色，持续显示 2s 后以 0.5s 的时间淡出

### Requirement: 对话气泡弹出

message-visualizer SHALL 在接收者头顶弹出消息摘要气泡。

#### Scenario: 气泡显示

- **WHEN** 消息飞抵接收者工位
- **THEN** SHALL 在接收者角色头顶弹出一个圆角矩形对话气泡，内容为消息的前 30 个字符（截断加"..."），气泡持续显示 3s 后淡出

#### Scenario: 气泡排队

- **WHEN** 新气泡弹出时前一个气泡尚未消失
- **THEN** 新气泡 SHALL 在前一个气泡上方显示（向上堆叠），最多同时显示 2 个气泡

### Requirement: 通信频率热力图（可选增强）

message-visualizer SHALL 能够展示累积的通信频率信息。

#### Scenario: 常用通信路径加粗

- **WHEN** 两个 Agent 之间的消息数超过 3 条
- **THEN** 它们之间的通信路径底线 SHALL 变粗并加深颜色，表示频繁通信关系
