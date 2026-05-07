# ai-skills

面向 [CodeBuddy](https://codebuddy.ai) 的 AI Skill / Agent 合集。用斜杠命令召唤一个多 Agent 团队，让它们分工协作把活干完——写文章、做开发、读 CT 片，各有专长。

## 有什么

| Skill | 干什么的 | Agent 数量 | 安装目标 |
|-------|---------|-----------|---------|
| **文章写作团队** | 领域画像驱动的多人协作写稿，从选题到润色一条龙 | 5 | `visual-article-team`（推荐） |
| **研发团队** | 6 人软件开发团队，覆盖需求→架构→开发→测试 | 6 | `rd-team` |
| **DICOM 阅片** | AI 辅助医学影像阅片，胸部 CT 生成 PDF 报告 | 1 | `dicom-doctor` |

## 快速安装

```bash
# 一键安装（推荐）
curl -fsSL https://raw.githubusercontent.com/eyjian/ai-skills/main/install-skill.sh | bash -s -- visual-article-team

# 或者先下载脚本再装
bash install-skill.sh visual-article-team

# 从本地仓库安装（开发时用）
bash install-skill.sh visual-article-team --from-local /path/to/ai-skills

# 查看所有可安装目标
bash install-skill.sh --list
```

安装到 `.codebuddy/skills/` 后，在 CodeBuddy 里用斜杠命令触发，比如 `/article-team`。

## 文章写作团队

5 个角色各司其职：

```
选题侦察员(scout) → 大纲架构师(architect) → 初稿写手(writer) → 技术审稿人(reviewer) → 终稿润色师(polisher)
```

核心特点：
- **领域画像驱动**：根据主题自动匹配写作风格（AI/通用/健康/跑步等）
- **去 AI 味**：内置系统性 AI 味检测协议，从"你"字清零到结构打散，全链路去味
- **自主决策**：审稿人可以直接退回稿件，润色师可以主动找人讨论，不需要协调者中转
- **可视化版**：本地 Web 服务实时展示 Agent 协作过程，能看到谁在干什么、消息怎么流转

6 种变体，从简到繁：

| 安装目标 | 方案 | 说明 |
|---------|------|------|
| `subagent-writing-skills` | 模拟 SubAgent | 单 Agent 角色扮演，最简单 |
| `article-team` | 模拟 Agent Team | 同上，打包成团队 |
| `real-subagent-writing-skills` | 真正 SubAgent | `task` 派发独立子 Agent |
| `real-article-team` | 真正 Agent Team（方式 A） | 共享内置 coder 工具集，一步安装 |
| `custom-article-team` | 自定义 Agent Team（方式 B） | 每个角色独立注册，精确声明工具集，两步安装 |
| `visual-article-team` | 可视化 Agent Team | 方式 B + Web 可视化 |

方式 A 和方式 B 的区别：方式 A 所有角色共用 CodeBuddy 内置的 `coder` 工具集，装一个 Skill 就行；方式 B 每个角色单独注册为自定义 Subagent，精确声明自己需要哪些工具（最小权限），但需要把 agents 文件复制到 `.codebuddy/agents/`。

建议新手从 `visual-article-team` 开始——安装脚本会自动处理两步安装。

## 研发团队

6 个角色覆盖完整 SDLC：

```
需求分析师(analyst) → 架构设计师(architect) → 后端开发(backend-dev) / 前端开发(frontend-dev) → 代码检视(code-reviewer) → 测试工程师(tester)
```

支持 4 种任务模式：新建项目、新增功能、修复 bug、代码重构。

默认技术栈：Go + Kratos v2 后端 + Vue 3 + TypeScript 前端。也内置了 `python-web`、`node-web` 等技术栈画像。

| 安装目标 | 方案 |
|---------|------|
| `rd-team` | 方式 A，一步安装 |
| `custom-agent-rd-team` | 方式 B，自定义 Subagent |

## DICOM 阅片

独立 Skill，不用组团队。两个能力：
1. **DICOM 转 PNG**：支持所有影像类型
2. **AI 辅助阅片**：当前仅支持胸部 CT，逐张检视全部切片，生成含 Lung-RADS 分级的 PDF 报告

```bash
bash install-skill.sh dicom-doctor
```

## 项目结构

```
ai-skills/
├── ai-writing-skills/          # 文章写作（6 种 Agent 方案）
│   ├── subagent-writing-skills/       # 模拟 SubAgent
│   ├── agent-team-writing-skill/      # 模拟 Agent Team
│   ├── real-subagent-writing-skills/  # 真正 SubAgent
│   ├── real-agent-team-writing-skill/ # 真正 Agent Team（方式 A）
│   ├── custom-agent-article-team/     # 自定义 Agent Team（方式 B）
│   └── visual-agent-article-team/     # 可视化 Agent Team
├── ai-rd-team/                 # 研发团队（方式 A + 方式 B）
├── dicom-doctor/               # DICOM 阅片
├── openspec/                   # OpenSpec 设计规范与变更记录
└── install-skill.sh            # 一键安装脚本
```

## 设计方法

本项目使用 [OpenSpec](https://openspec.dev) 管理 Skill 的设计决策——从提案（proposal）到设计（design）到规格（specs）到任务（tasks），每一步有据可查。`openspec/` 目录下可以查看历史设计记录。

## 许可

Apache 2.0
