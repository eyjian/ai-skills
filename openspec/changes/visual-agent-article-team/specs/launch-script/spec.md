## ADDED Requirements

### Requirement: 一键启动零配置

launch.sh 脚本 SHALL 实现从"零环境"到"服务运行"的全自动化，用户只需执行一条命令。

#### Scenario: 首次运行

- **WHEN** 用户在一个干净环境中执行 `./launch.sh /path/to/.codebuddy/teams/`
- **THEN** 脚本 SHALL 依次完成：
  1. 检测 `python3` 是否可用（不可用则报错退出并提示安装）
  2. 在项目目录下创建 `.venv` 虚拟环境（如不存在）
  3. 激活虚拟环境
  4. 安装 `requirements.txt` 中的依赖（如未安装）
  5. 启动 FastAPI 服务，监听 `0.0.0.0:8765`
  6. 在终端输出访问地址 `http://localhost:8765`

#### Scenario: 后续运行

- **WHEN** 用户再次执行 `./launch.sh` 且 `.venv` 已存在
- **THEN** 脚本 SHALL 跳过创建虚拟环境步骤，直接激活并启动服务

### Requirement: 命令行参数

launch.sh SHALL 支持以下命令行参数。

#### Scenario: 指定 teams 目录

- **WHEN** 执行 `./launch.sh /path/to/.codebuddy/teams/article-team-20260413/`
- **THEN** SHALL 将该路径作为 `--teams-dir` 参数传递给 Python 服务

#### Scenario: 指定端口

- **WHEN** 执行 `./launch.sh --port 9000 /path/to/teams/`
- **THEN** SHALL 使用端口 9000 启动服务（默认 8765）

#### Scenario: 启用轮询模式

- **WHEN** 执行 `./launch.sh --poll /path/to/teams/`
- **THEN** SHALL 将 `--poll` 参数传递给 Python 服务

### Requirement: 错误处理

launch.sh SHALL 对常见错误提供友好提示。

#### Scenario: Python 未安装

- **WHEN** 系统中找不到 `python3` 命令
- **THEN** SHALL 输出红色错误提示："❌ 未找到 python3，请先安装 Python 3.8+"并退出

#### Scenario: teams 目录不存在

- **WHEN** 指定的 teams 目录路径不存在
- **THEN** SHALL 输出黄色警告提示："⚠️ 指定的目录不存在: {path}，将在该路径上等待数据..."并仍然启动服务（等待目录创建）

### Requirement: 优雅停止

launch.sh SHALL 支持 Ctrl+C 优雅停止服务。

#### Scenario: Ctrl+C 停止

- **WHEN** 用户按下 Ctrl+C
- **THEN** SHALL 捕获 SIGINT 信号，优雅关闭 uvicorn 进程，输出"👋 服务已停止"
