## ADDED Requirements

### Requirement: 监听 teams 目录变化

FileWatcher 模块 SHALL 使用 watchdog 库监听指定的 `.codebuddy/teams/` 目录（或其子目录）下的文件变化事件，包括文件创建（created）、修改（modified）和删除（deleted）。

#### Scenario: 监听单个团队目录

- **WHEN** 用户通过启动参数指定一个团队目录路径（如 `/path/to/.codebuddy/teams/article-team-20260413/`）
- **THEN** FileWatcher SHALL 递归监听该目录下所有文件的变化事件

#### Scenario: 监听 teams 根目录

- **WHEN** 用户通过启动参数指定 teams 根目录路径（如 `/path/to/.codebuddy/teams/`）
- **THEN** FileWatcher SHALL 监听该目录下所有子目录（即所有团队）的文件变化事件

### Requirement: 过滤有效文件类型

FileWatcher SHALL 只关注以下文件的变化：
- `config.json`（团队配置文件）
- `inboxes/*.json`（成员收件箱文件）

其他文件的变化 SHALL 被忽略。

#### Scenario: config.json 变化

- **WHEN** 某个团队目录下的 `config.json` 被创建或修改
- **THEN** FileWatcher SHALL 触发一个 `config_changed` 事件，附带团队名称和文件路径

#### Scenario: inbox 文件变化

- **WHEN** 某个团队目录下的 `inboxes/{name}.json` 被创建或修改
- **THEN** FileWatcher SHALL 触发一个 `inbox_changed` 事件，附带团队名称、成员名称和文件路径

#### Scenario: 忽略无关文件

- **WHEN** 目录下有 `.log`、`.tmp` 或其他非 JSON 文件变化
- **THEN** FileWatcher SHALL 不触发任何事件

### Requirement: 支持 fallback 轮询模式

当文件系统事件通知不可靠时（如 NFS、Docker bind mount），FileWatcher SHALL 支持通过启动参数 `--poll` 切换为轮询模式。

#### Scenario: 轮询模式启动

- **WHEN** 服务启动时带有 `--poll` 参数
- **THEN** FileWatcher SHALL 使用 watchdog 的 `PollingObserver`（默认间隔 2 秒）代替原生文件系统事件监听

#### Scenario: 默认使用原生事件

- **WHEN** 服务启动时未指定 `--poll` 参数
- **THEN** FileWatcher SHALL 使用 watchdog 的 `Observer`（基于 inotify 等原生机制）

### Requirement: 事件回调注册

FileWatcher SHALL 提供回调注册接口，允许 StateEngine 注册 `config_changed` 和 `inbox_changed` 事件的处理函数。

#### Scenario: 注册事件处理器

- **WHEN** StateEngine 注册了 `inbox_changed` 事件的处理函数
- **THEN** 每当有 inbox 文件变化时，FileWatcher SHALL 调用该处理函数并传入事件数据（团队名、成员名、文件路径）
