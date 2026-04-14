## 1. 项目骨架与基础设施

- [x] 1.1 创建 `ai-writing-skills/visual-agent-article-team/` 目录结构（server/、web/、web/css/、web/js/、web/svg/、article-team/、agents/）
- [x] 1.2 创建 `requirements.txt`（fastapi、uvicorn、watchdog、websockets）
- [x] 1.3 创建 `launch.sh` 一键启动脚本（自动 venv 创建、依赖安装、服务启动、错误处理、Ctrl+C 优雅停止）
- [x] 1.4 创建 `README.md` 项目说明文档
- [x] 1.5 创建 `ARCHITECTURE.md` 架构说明文档

## 2. Python 后端核心

- [x] 2.1 实现 `server/file_watcher.py`（watchdog 监听 teams 目录、过滤 config.json/inboxes/*.json、回调注册、fallback 轮询模式）
- [x] 2.2 实现 `server/state_engine.py`（解析 config/inbox 变化为结构化事件、维护 Agent 状态机、初始快照加载、标准化事件格式）
- [x] 2.3 实现 `server/event_timeline.py`（有序事件时间线、全量加载、增量追加、时间范围查询/增量查询接口）
- [x] 2.4 实现 `server/websocket_hub.py`（WebSocket 连接管理、实时模式推送、回放模式推送含倍速/暂停/跳转、初始状态同步）
- [x] 2.5 实现 `server/main.py`（FastAPI 入口、REST API 端点：/api/teams、/api/teams/{name}、/api/teams/{name}/timeline、静态文件服务、启动参数解析）

## 3. 前端基础框架

- [x] 3.1 创建 `web/index.html` 主页面骨架（三区域布局：办公室区 60% + 通信面板 40% + 回放控制条）
- [x] 3.2 创建 `web/css/office.css` 办公室布局样式（等距伪 3D 视角、工位布局、响应式缩放）
- [x] 3.3 创建 `web/css/agents.css` 角色样式（6 个角色的配色方案、状态灯颜色、名牌样式）
- [x] 3.4 创建 `web/css/animations.css` 动画定义（idle-sway、typing、message-fly、card-fly、checkmark、reject-fly 等全部关键帧动画）
- [x] 3.5 创建 `web/js/websocket-client.js` WebSocket 客户端（连接管理、实时/回放端点切换、消息解析分发）

## 4. SVG 角色与办公室场景

- [x] 4.1 创建 `web/svg/office-bg.svg` 办公室背景（地板网格、墙壁、窗户、植物/时钟装饰）
- [x] 4.2 创建 `web/svg/agent-main.svg` 协调者角色（蓝色系、戴耳麦、多屏显示器）
- [x] 4.3 创建 `web/svg/agent-scout.svg` 侦察员角色（绿色系、贝雷帽、放大镜、望远镜）
- [x] 4.4 创建 `web/svg/agent-architect.svg` 架构师角色（紫色系、眼镜、三角尺、蓝图）
- [x] 4.5 创建 `web/svg/agent-writer.svg` 写手角色（橙色系、鸭舌帽、笔、稿纸堆、咖啡杯）
- [x] 4.6 创建 `web/svg/agent-reviewer.svg` 审稿人角色（红色系、红围巾、红笔、红叉文件）
- [x] 4.7 创建 `web/svg/agent-polisher.svg` 润色师角色（黄色系、围裙、喷壶、闪光特效）

## 5. 前端核心交互

- [x] 5.1 实现 `web/js/office-renderer.js` 办公室渲染器（初始渲染工位布局、SVG 加载与放置、工位状态视觉反馈、响应式调整）
- [x] 5.2 实现 `web/js/agent-controller.js` 角色状态控制器（接收事件 → 切换角色状态/形象、管理状态动画生命周期）
- [x] 5.3 实现 `web/js/message-animator.js` 通信动画（纸飞机飞线贝塞尔曲线、对话气泡弹出/排队/淡出、通信频率热力图底线）
- [x] 5.4 实现 `web/js/app.js` 主逻辑（页面初始化、WebSocket 事件分发到各模块、模式切换协调）

## 6. 通信面板与回放控制

- [x] 6.1 实现聊天气泡面板（消息气泡渲染含头像/配色/Markdown、自动滚动/手动浏览、消息类型视觉区分、长消息展开折叠）
- [x] 6.2 实现消息过滤功能（按 Agent 过滤、显示全部）
- [x] 6.3 实现 `web/js/timeline-player.js` 回放控制器（播放/暂停/前进/后退、时间线进度条拖动、倍速切换、事件列表面板、实时/回放模式切换）

## 7. Skill 变体

- [x] 7.1 创建 `article-team/SKILL.md` Skill 元数据文件
- [x] 7.2 创建 `article-team/commands/article-team.md` 协调者 prompt（基于 custom 版本，增加心跳格式结构化标记）
- [x] 7.3 复制 `agents/` 目录下的 5 个 Subagent 注册文件（article-scout/architect/writer/reviewer/polisher.md）
- [x] 7.4 复制 `article-team/shared-writing-resources/` 共享资源目录

## 8. 集成测试与文档

- [x] 8.1 端到端验证：使用历史 teams 数据（article-team-20260413）验证回放功能完整性
- [ ] 8.2 端到端验证：在 CodeBuddy 中触发 visual-agent-article-team，验证实时模式功能
- [x] 8.3 完善 README.md（使用说明、截图示意、FAQ）
- [x] 8.4 完善 ARCHITECTURE.md（系统架构图、数据流图、模块职责）
