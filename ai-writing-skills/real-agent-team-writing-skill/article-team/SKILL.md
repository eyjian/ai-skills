---
name: article-team
description: 真正的多 Agent 文章编写团队。当用户要写文章（AI、健康、跑步或通用领域）、重审现有 Markdown 文章、回炉旧稿、直接润色终稿、降低 AI 味、优化开篇 / 引言、重构章节结构时触发。本方案通过 CodeBuddy 的 team_create / task（异步团队模式）/ send_message / team_delete 工具链，真正创建多个独立 Agent 实例以网状拓扑协作——Agent 之间可直接对话、自主决策，而非单 Agent 角色扮演。
---

# 文章编写 Agent Team（真正的多 Agent 协作）

这是一个**真正的多 Agent Team**——通过 CodeBuddy 的 `team_create` / `task` / `send_message` / `team_delete` 工具链，每个角色作为独立的 Agent 实例运行，可以互相直接对话、自主决策。

## 与模拟版的核心区别

| 维度 | 本方案（真正多 Agent） | 模拟版（skill 角色扮演） |
|------|----------------------|------------------------|
| Agent 实例 | 每个角色通过 `task` 异步派发为独立 Agent 实例 | 单个 AI 对话在角色扮演 |
| 通信机制 | 通过 `send_message` Function Call 实现真正的消息传递 | prompt 文字描述通信，实际未调用 |
| 团队生命周期 | `team_create` 建团队 → `task` 派 Agent → `send_message` 通信 → `team_delete` 清理 | 无团队容器，无生命周期管理 |
| 并行能力 | Agent 可在后台异步运行，真正并行 | 严格串行，单线程 |
| 自主决策 | reviewer 可直接 `send_message` 给 writer 退回修改 | 协调者代为决策 |

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
/article-team 修改 docs/my-article.md，开篇太弱需要重写
/article-team 优化 article.md 的结构和表达
/article-team 帮我改一下 docs/ai-agent.md，去掉对话腔
/article-team 调整 docs/running-plan.md，补充风险提示
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

**核心原则**：即使只是检查或润色一篇已有文章，也会通过 `team_create` 创建团队、通过 `task` 派发多个独立 Agent 实例协作完成。每个 Agent 通过 `send_message` 直接通信。

## 团队成员

| 成员 | 代号 | 职责 |
|------|------|------|
| 选题侦察员 | scout | 搜索热点，提供选题建议 |
| 大纲架构师 | architect | 设计文章结构和大纲 |
| 初稿写手 | writer | 按大纲撰写 Markdown 初稿 |
| 技术审稿人 | reviewer | 审查准确性和完整性，**自主决定退回** |
| 终稿润色师 | polisher | 最终打磨和格式规范化 |

## 工具链调用流程

```
team_create("article-team-{timestamp}")
  → task(name:"scout", team_name:..., prompt:...)     # 独立 Agent 实例
  → task(name:"architect", team_name:..., prompt:...)  # 独立 Agent 实例
  → task(name:"writer", team_name:..., prompt:...)     # 独立 Agent 实例
  → task(name:"reviewer", team_name:..., prompt:...)   # 独立 Agent 实例
  → task(name:"polisher", team_name:..., prompt:...)   # 独立 Agent 实例
  → send_message(type:"shutdown_request", recipient:...) × 5
  → team_delete()
```
