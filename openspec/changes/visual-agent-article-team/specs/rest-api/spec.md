## ADDED Requirements

### Requirement: 团队列表查询

REST API SHALL 提供 `GET /api/teams` 端点，返回所有已加载团队的列表。

#### Scenario: 查询所有团队

- **WHEN** 客户端请求 `GET /api/teams`
- **THEN** SHALL 返回 JSON 数组，每项包含 `{ name, created_at, member_count, status }`，按创建时间降序排列

### Requirement: 团队详情查询

REST API SHALL 提供 `GET /api/teams/{name}` 端点，返回指定团队的详细信息。

#### Scenario: 查询团队详情

- **WHEN** 客户端请求 `GET /api/teams/article-team-20260413`
- **THEN** SHALL 返回该团队的 `config.json` 内容 + 当前各 Agent 状态 + 事件统计信息

#### Scenario: 团队不存在

- **WHEN** 客户端请求的团队名不存在
- **THEN** SHALL 返回 HTTP 404，body 为 `{ "error": "Team not found" }`

### Requirement: 事件时间线查询

REST API SHALL 提供 `GET /api/teams/{name}/timeline` 端点，返回该团队的完整事件时间线。

#### Scenario: 获取时间线

- **WHEN** 客户端请求 `GET /api/teams/{name}/timeline`
- **THEN** SHALL 返回该团队所有事件的 JSON 数组，按 timestamp 升序排列

#### Scenario: 时间范围过滤

- **WHEN** 客户端请求 `GET /api/teams/{name}/timeline?start=T1&end=T2`
- **THEN** SHALL 只返回 T1 到 T2 时间范围内的事件

### Requirement: 静态文件服务

REST API SHALL 提供对 `web/` 目录下前端静态文件的服务能力。

#### Scenario: 访问主页

- **WHEN** 客户端请求 `GET /`
- **THEN** SHALL 返回 `web/index.html` 内容
