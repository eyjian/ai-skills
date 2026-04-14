## ADDED Requirements

### Requirement: 聊天气泡式消息展示

chat-panel SHALL 在页面下方区域（占视口高度约 40%）以聊天气泡形式展示 Agent 之间的所有消息。

#### Scenario: 消息气泡渲染

- **WHEN** 收到 `message_sent` 事件
- **THEN** SHALL 在消息面板底部追加一条消息气泡，包含：
  - 发送者头像（SVG 缩略图，取自角色形象）
  - 发送者名称（带配色标签）
  - 接收者名称（"→ {to}"）
  - 消息内容（Markdown 渲染后的 HTML）
  - 时间戳（相对时间，如"2 分钟前"）

#### Scenario: 自动滚动

- **WHEN** 新消息追加到面板时，用户未手动上滚
- **THEN** 面板 SHALL 自动滚动到底部显示最新消息

#### Scenario: 手动浏览历史

- **WHEN** 用户向上滚动查看历史消息
- **THEN** 面板 SHALL 停止自动滚动，直到用户点击"回到最新"按钮或滚动到底部

### Requirement: 消息类型视觉区分

不同类型的消息 SHALL 有视觉区分。

#### Scenario: 普通消息

- **WHEN** 消息 `type` 为 `message`
- **THEN** SHALL 使用标准气泡样式，背景色取发送者配色的浅色变体

#### Scenario: 广播消息

- **WHEN** 消息 `type` 为 `broadcast`
- **THEN** SHALL 使用全宽气泡样式，带"📢 广播"标签，背景色为淡蓝色

#### Scenario: 系统消息

- **WHEN** 事件类型为 `team_created`、`agent_joined`、`agent_completed` 等系统事件
- **THEN** SHALL 以居中的小字灰色文本显示（类似微信群的系统提示），如"🏢 团队已创建"、"🔎 scout 加入团队"

### Requirement: 消息过滤

chat-panel SHALL 支持按 Agent 过滤消息。

#### Scenario: 过滤特定 Agent 的消息

- **WHEN** 用户点击某个 Agent 的头像进行过滤
- **THEN** 面板 SHALL 只显示该 Agent 发送或接收的消息，其他消息隐藏

#### Scenario: 清除过滤

- **WHEN** 用户再次点击已过滤的 Agent 头像，或点击"显示全部"按钮
- **THEN** 面板 SHALL 恢复显示所有消息

### Requirement: 消息内容展开/折叠

chat-panel SHALL 支持长消息的展开/折叠。

#### Scenario: 长消息折叠

- **WHEN** 消息内容超过 200 字符
- **THEN** 气泡 SHALL 默认折叠显示前 200 字符，末尾显示"展开"按钮

#### Scenario: 展开消息

- **WHEN** 用户点击"展开"按钮
- **THEN** 气泡 SHALL 展开显示完整内容，按钮变为"折叠"
