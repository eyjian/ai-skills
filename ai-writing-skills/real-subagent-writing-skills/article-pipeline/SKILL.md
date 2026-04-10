---
name: article-pipeline
description: 真正的多 SubAgent 文章写作流水线。当用户要写文章（AI、健康、跑步或通用领域）、重审现有 Markdown 文章、回炉旧稿、直接润色终稿、降低 AI 味、优化开篇 / 引言、重构章节结构时触发。本方案通过 CodeBuddy 的 task 工具同步派发独立子 Agent，由协调者按流水线自动编排 scout → architect → writer → reviewer → polisher 全流程，用户只需在关键节点确认。
argument-hint: "[选题方向、具体主题，或现有文章文件路径 / 改稿需求]"
---

# 文章写作流水线（真正的多 SubAgent 协作）

这是一个**由协调者主导的 SubAgent 流水线**——通过 CodeBuddy 的 `task` 工具，协调者按流程自动派发各角色子 Agent，用户只需在关键节点确认，无需手动触发每一步。

## 与 Agent Team 版的区别

| 维度 | 本方案（SubAgent 流水线） | Agent Team 版 |
|------|------------------------|---------------|
| 通信模式 | `task` 同步模式，阻塞等待返回 | `task` 异步模式 + `send_message` |
| 团队容器 | 无（不需要 `team_create`） | 需要 `team_create` / `team_delete` |
| Agent 关系 | 协调者串行调度，Agent 间不直接通信 | 网状拓扑，Agent 间可直接对话 |
| 适用场景 | 流程明确、步步递进的写作任务 | 需要 Agent 间协商、自主决策的复杂任务 |

## 使用方式

输入 `/article-pipeline` 加上选题方向，或现有文章文件路径 / 改稿需求，即可启动流水线。

示例：
```
/article-pipeline Agent 编排模式对比
/article-pipeline 最近 AI 编程有啥值得写的
/article-pipeline 重审 docs/agent-orchestration.md
/article-pipeline 请润色 article.md，重点降低 AI 味
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

## 三类入口场景

| 场景 | 典型输入 | 参与角色 | 协调者编排流程 |
|------|---------|---------|---------------|
| 新稿创作 | 主题方向、选题想法 | scout → architect → writer → reviewer → polisher | 全流程 5 步 |
| 旧稿重审 / 回炉 | `.md` 文件路径 + 重审/回炉/检查 | reviewer → writer → polisher | 3 步 |
| 旧稿直接润色 | `.md` 文件路径 + 只润色/去 AI 味 | reviewer（快审）→ polisher | 2 步 |

## 团队成员

| 成员 | 代号 | 职责 |
|------|------|------|
| 协调者 | pipeline-coordinator | 解析需求、按流程串行派发子 Agent、传递上下文 |
| 选题侦察员 | scout | 搜索热点，提供选题建议 |
| 大纲架构师 | architect | 设计文章结构和大纲 |
| 初稿写手 | writer | 按大纲撰写 Markdown 初稿 |
| 技术审稿人 | reviewer | 审查准确性和完整性 |
| 终稿润色师 | polisher | 最终打磨和格式规范化 |

## 工具链调用流程

```
协调者（main）
  → task(同步) → scout 子 Agent → 返回选题方案 → 用户确认
  → task(同步) → architect 子 Agent → 返回大纲
  → task(同步) → writer 子 Agent → 返回初稿
  → task(同步) → reviewer 子 Agent → 返回审稿报告
  → [如有 🔴/🟡≥4] → task(同步) → writer 子 Agent → 返回改稿
  → task(同步) → polisher 子 Agent → 返回终稿
```

## 仍可单步触发

保留原有 5 个独立 skill（`/topic-scout`、`/outline-architect`、`/draft-writer`、`/tech-reviewer`、`/final-polisher`），用户仍可手动触发单步。
