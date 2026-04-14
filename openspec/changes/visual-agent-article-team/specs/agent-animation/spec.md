## ADDED Requirements

### Requirement: 空闲状态动画

处于 `idle` 状态的 Agent SHALL 播放轻微的空闲循环动画，表示"在线但未工作"。

#### Scenario: 空闲晃动

- **WHEN** Agent 处于 `idle` 状态
- **THEN** 角色 SHALL 播放缓慢的左右轻微摆动动画（`@keyframes idle-sway`，幅度 ±2°，周期 3s），并偶尔有"喝咖啡"的小动作

### Requirement: 激活动画

当 Agent 从 `idle` 转为 `active` 时，SHALL 播放一个醒目的激活过渡动画。

#### Scenario: 任务卡飞入

- **WHEN** 收到 `agent_activated` 事件
- **THEN** SHALL 播放以下动画序列（总时长约 1.5s）：
  1. 一张任务卡从协调者（main）工位飞出，沿弧线轨迹飞向目标 Agent 工位（0.8s）
  2. Agent 做"拿起"动作（手臂伸出）（0.3s）
  3. 工位桌灯亮起，发出柔和光晕（0.4s）

### Requirement: 工作中动画

处于 `active` 状态的 Agent SHALL 播放工作循环动画。

#### Scenario: 打字动画

- **WHEN** Agent 处于 `active` 状态
- **THEN** 角色 SHALL 播放手部快速交替移动的打字动画（`@keyframes typing`，周期 0.5s），桌面上有纸张翻动效果

### Requirement: 消息发送动画

当 Agent 发送消息时，SHALL 播放消息发送动画。

#### Scenario: 纸飞机飞出

- **WHEN** 收到 `message_sent` 事件
- **THEN** SHALL 从发送者工位飞出一个纸飞机 SVG 元素，沿贝塞尔曲线轨迹飞向接收者工位（`@keyframes message-fly`，时长 1.2s），飞行过程中带有轻微旋转

#### Scenario: 飞线效果

- **WHEN** 纸飞机飞行过程中
- **THEN** 发送者与接收者之间 SHALL 出现一条渐变发光连线，持续 2s 后淡出

### Requirement: 完成动画

当 Agent 完成任务时，SHALL 播放完成庆祝动画。

#### Scenario: 对勾 + 伸懒腰

- **WHEN** 收到 `agent_completed` 事件
- **THEN** SHALL 播放以下动画序列：
  1. 工位上方出现绿色对勾标记，带弹跳效果（0.5s）
  2. 角色做"伸懒腰"动画——双臂向上伸展后放下（1s）
  3. 角色回到放松的坐姿

### Requirement: 审稿退回动画

当 reviewer 退回文章时，SHALL 播放特殊的退回动画。

#### Scenario: 红色文件退回

- **WHEN** 收到 reviewer 发出的包含退回指示的 `message_sent` 事件
- **THEN** SHALL 播放：红色文件从 reviewer 工位飞向 writer 工位，文件上带有"退回"红色印章特效

### Requirement: 动画性能要求

所有动画 SHALL 使用 CSS `transform` 和 `opacity` 属性（GPU 加速），避免使用会触发重排（reflow）的属性。

#### Scenario: 流畅度要求

- **WHEN** 同时有 3 个 Agent 在播放动画
- **THEN** 页面帧率 SHALL 保持在 30fps 以上，无明显卡顿
