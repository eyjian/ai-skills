## ADDED Requirements

### Requirement: 维护有序事件时间线

EventTimeline SHALL 以 `timestamp` 为排序键维护一个有序的事件列表，所有来自 StateEngine 的事件 SHALL 按时间戳升序插入。

#### Scenario: 事件按时间排序

- **WHEN** StateEngine 连续推送了 3 个事件，时间戳分别为 T1、T3、T2
- **THEN** EventTimeline 中的事件序列 SHALL 为 T1、T2、T3（按时间升序）

### Requirement: 支持全量快照加载

EventTimeline SHALL 支持一次性加载历史事件列表（从 StateEngine 的初始快照），用于回放模式。

#### Scenario: 加载历史事件

- **WHEN** 服务启动并完成初始快照加载后
- **THEN** EventTimeline SHALL 包含所有历史事件，按 timestamp 升序排列，可供回放使用

### Requirement: 支持增量事件追加

EventTimeline SHALL 支持在运行中追加新事件（来自实时文件监听），新事件追加到时间线末尾。

#### Scenario: 实时事件追加

- **WHEN** 实时模式下 StateEngine 检测到新的文件变化并生成事件
- **THEN** 该事件 SHALL 被追加到 EventTimeline 末尾，并通知 WebSocketHub 推送给已连接的客户端

### Requirement: 提供时间线查询接口

EventTimeline SHALL 提供以下查询接口：
- `get_all()` — 获取全部事件
- `get_range(start_time, end_time)` — 获取时间范围内的事件
- `get_since(index)` — 获取指定索引之后的新增事件
- `length` — 获取事件总数

#### Scenario: 按时间范围查询

- **WHEN** 调用 `get_range("2026-04-13T13:09:00Z", "2026-04-13T13:15:00Z")`
- **THEN** SHALL 返回该时间范围内的所有事件（含边界）

#### Scenario: 增量查询

- **WHEN** 调用 `get_since(5)` 且当前时间线有 10 个事件
- **THEN** SHALL 返回索引 5 之后的 5 个事件
