## ADDED Requirements

### Requirement: 虚拟办公室场景布局

办公室渲染器 SHALL 在页面上方区域（占视口高度约 60%）渲染一个等距伪 3D 视角的开放式办公室场景。

#### Scenario: 初始渲染

- **WHEN** 页面加载并收到 `snapshot` 或 `team_created` 事件
- **THEN** SHALL 渲染包含办公室背景（地板、墙壁、装饰）和 6 个工位的场景布局

#### Scenario: 响应式布局

- **WHEN** 浏览器窗口大小变化
- **THEN** 办公室场景 SHALL 按比例缩放，保持工位相对位置不变，最小宽度 800px

### Requirement: 工位布局规则

6 个工位（main/scout/architect/writer/reviewer/polisher）SHALL 按以下规则布局：
- main（协调者）居中偏上
- scout 和 architect 在上排左右
- writer 和 reviewer 在中排左右
- polisher 在下方居中

#### Scenario: 工位位置

- **WHEN** 办公室场景渲染完成
- **THEN** 每个工位 SHALL 包含：桌面（SVG 矩形）、椅子、Agent 角色形象、名牌（显示角色名）、状态灯（显示当前状态颜色）

### Requirement: 工位状态视觉反馈

每个工位 SHALL 根据对应 Agent 的当前状态改变视觉表现。

#### Scenario: Agent 激活时工位变化

- **WHEN** 收到 `agent_activated` 事件
- **THEN** 该 Agent 的工位 SHALL：桌面灯亮起、状态灯变为绿色、桌面出现"工作中"的视觉提示

#### Scenario: Agent 完成时工位变化

- **WHEN** 收到 `agent_completed` 事件
- **THEN** 该 Agent 的工位 SHALL：显示绿色对勾标记、角色做放松姿势、状态灯变为蓝色

#### Scenario: Agent 空闲时工位表现

- **WHEN** Agent 处于 `idle` 状态
- **THEN** 该 Agent 的工位 SHALL：桌面灯熄灭、状态灯为灰色、角色有轻微的空闲动画（如小幅晃动）

### Requirement: 办公室背景

办公室场景 SHALL 包含 SVG 背景元素，营造办公室氛围。

#### Scenario: 背景元素

- **WHEN** 场景初始渲染
- **THEN** SHALL 包含：淡色地板网格、窗户装饰、植物/时钟等办公室装饰物、整体暖色调照明效果
