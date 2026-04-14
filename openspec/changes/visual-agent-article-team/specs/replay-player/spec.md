## ADDED Requirements

### Requirement: 回放控制条 UI

replay-player SHALL 在页面底部渲染一个回放控制条。

#### Scenario: 控制条元素

- **WHEN** 页面加载完成
- **THEN** 控制条 SHALL 包含以下元素：
  - 播放/暂停按钮（▶️ / ⏸️ 切换）
  - 后退按钮（◀◀ 跳转到上一个事件）
  - 前进按钮（▶▶ 跳转到下一个事件）
  - 时间线进度条（可拖动滑块，显示当前回放位置）
  - 倍速选择器（1x / 2x / 4x / 8x 按钮组）
  - 当前时间 / 总时长显示
  - 实时/回放模式切换按钮

### Requirement: 播放/暂停控制

replay-player SHALL 支持播放和暂停回放。

#### Scenario: 开始播放

- **WHEN** 用户点击播放按钮
- **THEN** SHALL 通过 WebSocket 发送 `{ "action": "play", "speed": current_speed }` 命令，按钮变为暂停图标

#### Scenario: 暂停播放

- **WHEN** 用户点击暂停按钮
- **THEN** SHALL 通过 WebSocket 发送 `{ "action": "pause" }` 命令，按钮变为播放图标，办公室场景冻结在当前状态

### Requirement: 倍速控制

replay-player SHALL 支持 1x、2x、4x、8x 四种回放速度。

#### Scenario: 切换倍速

- **WHEN** 用户点击 4x 倍速按钮
- **THEN** SHALL 通过 WebSocket 发送 `{ "action": "speed", "speed": 4 }` 命令，当前选中的倍速按钮高亮

### Requirement: 时间线拖动

replay-player SHALL 支持通过拖动进度条跳转到任意时间点。

#### Scenario: 拖动进度条

- **WHEN** 用户拖动时间线滑块到某个位置（对应时间点 T）
- **THEN** SHALL 通过 WebSocket 发送 `{ "action": "seek", "timestamp": T }` 命令，办公室场景和通信面板 SHALL 立即更新到该时间点的状态

### Requirement: 事件列表面板

replay-player SHALL 提供可展开的事件列表面板。

#### Scenario: 展开事件列表

- **WHEN** 用户点击控制条上的"📋 事件列表"按钮
- **THEN** SHALL 弹出一个侧边面板，列出所有事件（图标 + 时间 + 简要描述），当前回放位置高亮

#### Scenario: 点击事件跳转

- **WHEN** 用户在事件列表中点击某个事件
- **THEN** SHALL 跳转到该事件的时间点，等效于 seek 操作

### Requirement: 模式切换

replay-player SHALL 支持在实时模式和回放模式之间切换。

#### Scenario: 切换到回放模式

- **WHEN** 用户点击"回放"按钮
- **THEN** SHALL 断开实时 WebSocket 连接，连接到回放 WebSocket 端点，控制条切换为可用状态

#### Scenario: 切换到实时模式

- **WHEN** 用户点击"实时"按钮
- **THEN** SHALL 断开回放连接，连接到实时 WebSocket 端点，控制条除模式切换按钮外全部禁用
