---
name: article-team
description: 自定义 Agent 文章编写团队（方式 B）。当用户要写文章（AI、健康、跑步或通用领域）、重审现有 Markdown 文章、回炉旧稿、直接润色终稿、降低 AI 味、优化开篇 / 引言、重构章节结构时触发。本方案通过 CodeBuddy 的 team_create / task（异步团队模式，使用自定义注册 Subagent）/ send_message / team_delete 工具链，真正创建多个独立自定义 Agent 实例以网状拓扑协作。与方式 A 的核心区别：每个角色在 .codebuddy/agents/ 中注册为自定义 Subagent，拥有精确的工具集声明，subagent_name 直接引用注册名而非内置 coder。
---

# 文章编写 Agent Team（自定义 Subagent 模式 — 方式 B）

这是一个**真正的自定义 Agent Team**——每个角色（scout / architect / writer / reviewer / polisher）在 CodeBuddy 中注册为独立的自定义 Subagent，拥有各自精确的工具集声明。协调者通过 `task(subagent_name: "article-scout")` 等方式直接引用已注册的自定义 Agent。

## 与方式 A（real-agent-team-writing-skill）的核心区别

| 维度 | 本方案（方式 B：自定义 Subagent） | 方式 A（借用内置 coder） |
|------|-------------------------------|------------------------|
| Agent 注册 | 每个角色在 `.codebuddy/agents/` 中注册为自定义 Subagent | 统一使用内置 `"coder"`，角色差异全靠 prompt 注入 |
| subagent_name | `"article-scout"` / `"article-writer"` 等自定义注册名 | 统一用 `"coder"` |
| 工具集 | 每个角色在 frontmatter 中精确声明 tools 列表 | 所有角色共享 coder 的完整工具集 |
| System Prompt | 由平台自动加载（frontmatter 下方的正文） | 协调者需 `read_file` 读取 agents/*.md 注入到 prompt |
| 安装步骤 | 两步：注册 agents + 安装 skill | 一步：只需安装 skill |

## 前置条件

使用本方案前，必须先完成 Subagent 注册：

```bash
# 步骤 1：注册自定义 Subagent（必须先执行）
cp custom-agent-article-team/agents/*.md .codebuddy/agents/

# 步骤 2：安装 Skill
cp -r custom-agent-article-team/article-team .codebuddy/skills/
```

如果只执行步骤 2 而跳过步骤 1，`task(subagent_name: "article-scout")` 等调用将因找不到已注册的 Subagent 而失败。

## 使用方式

输入 `/article-team` 加上选题方向，或现有文章文件路径 / 改稿需求，即可启动团队。

示例：
```
/article-team Agent 编排模式对比
/article-team 最近 AI 编程有啥值得写的
/article-team 写一篇关于久坐人群恢复活动量的健康类文章
/article-team 重审 docs/agent-orchestration.md
/article-team 请润色 article.md，重点降低 AI 味
/article-team 重构 docs/agent-orchestration.md 的章节顺序
```

## 共享领域画像

启动前先读取 `./shared-writing-resources/domain-profiles/domain-profiles.json`，解析领域画像。

当前首批画像：

| 画像 | mode | 用途 |
|------|------|------|
| `ai` | `AI 专用模式` | AI / LLM / Agent / AI 编程 / RAG / AI 工程化等 |
| `generic` | `通用模式` | 默认通用画像 |
| `health` | `通用模式` | 继承 `generic`，额外强调风险提示和求助边界 |
| `running` | `通用模式` | 继承 `generic`，额外强调训练安排和调整条件 |

## 三类入口场景（所有模式都创建团队、都派发多个 Agent）

| 场景 | 典型输入 | 参与 Agent | 多 Agent 协作流程 |
|------|---------|-----------|------------------|
| 新稿创作 | 主题方向、选题想法，且不涉及已有文件 | scout → architect → writer → reviewer → polisher | 全流程 5 Agent |
| 旧稿重审 / 回炉 | 文件路径 + 修改/改/调整/优化/重写/重构/检查/审查/重审/回炉/改稿/改写/编辑/更新/完善/补充/删减/精简/扩充 | reviewer → writer → polisher | reviewer 审查 → writer 改稿 → polisher 润色 |
| 旧稿直接润色 | 文件路径 + 只润色/去 AI 味/发布前打磨 | reviewer（快审）→ polisher | reviewer 先快审 → polisher 润色 |

**兜底规则**：提到已有文件但未明确说"只润色"时，一律按旧稿重审 / 回炉模式处理。

## 团队成员（自定义注册 Subagent）

| 成员 | 代号 | 注册名 | 工具集 | 职责 |
|------|------|--------|-------|------|
| 选题侦察员 | scout | article-scout | read_file, web_search, send_message, list_dir | 搜索热点，提供选题建议 |
| 大纲架构师 | architect | article-architect | read_file, web_search, send_message | 设计文章结构和大纲 |
| 初稿写手 | writer | article-writer | read_file, write_to_file, replace_in_file, search_content, send_message, web_search | 按大纲撰写 Markdown 初稿 |
| 技术审稿人 | reviewer | article-reviewer | read_file, web_search, search_content, send_message | 审查准确性和完整性，**自主决定退回** |
| 终稿润色师 | polisher | article-polisher | read_file, replace_in_file, search_content, send_message | 最终打磨和格式规范化 |

## 工具链调用流程

```
team_create("article-team-{timestamp}")
  → task(subagent_name:"article-scout", name:"scout", team_name:..., prompt:...)
  → task(subagent_name:"article-architect", name:"architect", team_name:..., prompt:...)
  → task(subagent_name:"article-writer", name:"writer", team_name:..., prompt:...)
  → task(subagent_name:"article-reviewer", name:"reviewer", team_name:..., prompt:...)
  → task(subagent_name:"article-polisher", name:"polisher", team_name:..., prompt:...)
  → send_message(type:"shutdown_request", recipient:...) × 5
  → team_delete()
```
