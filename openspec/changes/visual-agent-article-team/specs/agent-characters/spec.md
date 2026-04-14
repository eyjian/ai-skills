## ADDED Requirements

### Requirement: 独特的 SVG 角色形象

每个 Agent SHALL 有一个独特的 SVG 卡通形象，包含可辨识的外观特征和专属配色。

#### Scenario: 6 个角色的形象定义

- **WHEN** 渲染 Agent 角色时
- **THEN** 每个角色 SHALL 具有以下独特视觉特征：

| 角色 | 形象特征 | 主配色 | 桌面物品 |
|------|---------|--------|---------|
| main（协调者） | 戴耳麦、手持平板 | 蓝色系 #3B82F6 | 多屏显示器、看板 |
| scout（侦察员） | 戴贝雷帽、手持放大镜 | 绿色系 #10B981 | 望远镜、地图 |
| architect（架构师） | 戴眼镜、手持三角尺 | 紫色系 #8B5CF6 | 蓝图、画板 |
| writer（写手） | 戴鸭舌帽、手持笔 | 橙色系 #F59E0B | 稿纸堆、咖啡杯 |
| reviewer（审稿人） | 戴红色围巾、手持红笔 | 红色系 #EF4444 | 打了红叉的文件 |
| polisher（润色师） | 戴围裙、手持喷壶 | 黄色系 #EAB308 | 抛光布、闪光特效 |

### Requirement: 角色 SVG 结构

每个角色的 SVG SHALL 采用分层结构，以便独立控制各部分动画。

#### Scenario: SVG 分层

- **WHEN** 生成角色 SVG 时
- **THEN** SHALL 包含以下可独立寻址的分组（`<g>` 元素）：
  - `body`：身体轮廓
  - `head`：头部（含发型/帽子）
  - `face`：面部表情
  - `left-arm` / `right-arm`：左右手臂（用于打字/挥手动画）
  - `accessory`：标志性物品（放大镜/三角尺/笔等）
  - `desk-items`：桌面物品

### Requirement: 角色状态形象切换

每个角色 SHALL 支持至少 4 种状态形象：idle（空闲）、active（工作中）、talking（通信中）、completed（已完成）。

#### Scenario: 从空闲切换到工作中

- **WHEN** 角色状态从 `idle` 变为 `active`
- **THEN** 角色形象 SHALL 变化：面部表情从放松变为专注、手臂移至打字/工作姿势、桌面物品出现工作相关物品

#### Scenario: 通信状态

- **WHEN** 角色处于 `talking` 状态（正在发送或接收消息）
- **THEN** 角色形象 SHALL 变化：头部微转向通信对象方向、出现对话气泡图标
