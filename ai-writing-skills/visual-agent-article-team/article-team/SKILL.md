---
name: article-team
description: 可视化 Agent 文章编写团队。当用户要写文章时触发，与 custom-agent-article-team 功能相同，但增加了 Web 可视化支持——通过虚拟办公室界面实时展示 Agent 协作过程。本方案通过 CodeBuddy 的 team_create / task（异步团队模式，使用自定义注册 Subagent）/ send_message / team_delete 工具链，真正创建多个独立自定义 Agent 实例以网状拓扑协作。
version: 1.0.0
---

# 可视化 Agent 文章编写团队

这是 `custom-agent-article-team` 的**可视化增强版**——在保留全部多 Agent 协作能力的基础上，增加了 Web 可视化支持。

## 与 custom-agent-article-team 的区别

| 维度 | 本方案（可视化版） | custom-agent-article-team |
|------|-------------------|--------------------------|
| 协作流程 | 完全相同 | — |
| Subagent | 完全相同（article-scout/architect/writer/reviewer/polisher） | — |
| 可视化 | ✅ Web 虚拟办公室，实时展示协作过程 | ❌ 无可视化 |
| 心跳格式 | 增强的结构化格式（便于前端解析） | 标准格式 |

## 使用方式

1. 在 CodeBuddy 中使用（可视化服务会自动启动）：
   ```
   /article-team Agent 编排模式对比
   /article-team 重审 docs/my-article.md
   ```

2. 打开浏览器 `http://localhost:8765` 观看协作过程

3. 如需手动启动可视化服务：
   ```bash
   bash .codebuddy/skills/article-team/launch.sh
   ```

## 前置条件

```bash
# 步骤 1：注册自定义 Subagent
cp visual-agent-article-team/agents/*.md .codebuddy/agents/

# 步骤 2：安装 Skill（包含 server + web + launch.sh）
cp -r visual-agent-article-team/article-team .codebuddy/skills/
```

## 共享领域画像

与 custom-agent-article-team 共享同一份领域画像配置：`./shared-writing-resources/domain-profiles/domain-profiles.json`
