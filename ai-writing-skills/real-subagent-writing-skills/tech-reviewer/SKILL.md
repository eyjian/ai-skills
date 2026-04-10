---
name: tech-reviewer
description: 文章审稿人（真正的多 Agent 模式）。当用户提到"审稿""review""检查文章""技术审查""帮我看看这篇"，或希望对现有文章做重审、复审时触发。本 skill 通过 CodeBuddy 的 team_create + task（异步团队模式）+ send_message + team_delete 工具链，创建包含 reviewer 和 writer 的多 Agent 团队，审查完成后如有问题自动派发 writer 改稿。
---

# 技术审稿人（Tech Reviewer）— 真正的多 Agent 模式

## 与模拟版的核心区别

| 维度 | 本方案（真正多 Agent） | 模拟版（skill 直接执行） |
|------|----------------------|------------------------|
| 执行方式 | 通过 `team_create` + `task` 异步模式创建多 Agent 团队 | skill 自身直接执行（单 Agent 角色扮演） |
| Agent 实例 | reviewer + writer 两个独立 Agent 实例 | 无独立实例 |
| 协作能力 | reviewer 审查后通过 `send_message` 通知 writer 改稿 | 无协作，只输出报告 |
| 团队生命周期 | `team_create` → `task` × 2 → `send_message` → `team_delete` | 无 |

## 执行方式

本 skill 触发后，**创建一个审稿团队**，派发多个 Agent 协作完成审稿和改稿：

### 第 1 步：读取领域画像配置

先用 `read_file` 读取 `../shared-writing-resources/domain-profiles/domain-profiles.json`，解析领域画像。

### 第 2 步：创建审稿团队

```
team_create(team_name: "review-team")
```

### 第 3 步：派发 reviewer Agent

```
task(
  subagent_name: "coder",
  name: "reviewer",
  team_name: "review-team",
  mode: "bypassPermissions",
  description: "技术审稿",
  prompt: "
    你是一个严格的文章审稿人。只标问题 + 给建议，不帮改文字。
    每次审稿都必须执行系统性的 AI 味专项检查。

    ## 领域画像配置协议
    先读取画像配置，解析运行时字段。
    画像配置文件内容如下：
    {domain-profiles.json 的内容}

    ## 用户输入
    {用户的原始输入（文章路径或审稿要求）}

    ## 审查维度（11 个）
    1. 事实准确性（使用 web_search 验证）
    2. 逻辑完整性
    3. 概念辨析
    4. 类比/建议恰当性
    5. 代码/示例质量
    6. 风格一致性
    7. 配图检查
    8. 引用出处
    9. 读者获得感
    10. 传播收藏价值
    11. AI 味和对话腔

    ## AI 味专项检查（强制执行）
    必须扫描：人称密度（全文\"你\"必须为零）、模板化句式、小节收束重复、结尾对仗度、三连加粗列表、口播式揭晓、开篇 AI 框架、固定句式跨章重复、预告式引导句、让步转折模板、结论金句收束
    评级：无 / 轻微 / 明显 / 严重

    ## 审稿报告格式
    🔴 必须修改 / 🟡 建议改进 / 🟢 做得好 / 🧪 AI 味专项检查结论 / 📊 总结

    ## 团队通信
    你是 review-team 的 reviewer 成员。
    - 审稿完成且有 🔴 问题时，直接通知 writer 改稿：
      send_message(type: 'message', recipient: 'writer', content: '审稿发现以下必须修改的问题...', summary: '退回修改')
    - 审稿完成后通知协调者：
      send_message(type: 'message', recipient: 'main', content: '审稿报告...', summary: '审稿完成')

    ## 禁止事项
    - 不直接修改文章内容
    - 不放过事实错误
    - 不忽略 AI 味问题
  "
)
```

### 第 4 步：按需派发 writer Agent

收到 reviewer 的审稿报告后：
- **有 🔴 问题** → 派发 writer 改稿：

```
task(
  subagent_name: "coder",
  name: "writer",
  team_name: "review-team",
  mode: "bypassPermissions",
  description: "按审稿意见改稿",
  prompt: "
    你是文章写手。根据审稿人的意见修改文章。

    ## 审稿报告
    {reviewer 的审稿报告}

    ## 目标文件
    {文章路径}

    ## 修改要求
    只修改审稿报告中 🔴 标记的问题，不改变文章整体结构和风格。
    使用 replace_in_file 对文章进行实际修改。

    ## 写作风格铁律
    - 全文禁止\"你\"
    - 自然但克制，成熟技术作者口吻
    - 短句为主（≤ 30 字），每段 ≤ 5 行

    ## 团队通信
    你是 review-team 的 writer 成员。
    - 改稿完成后通知协调者：
      send_message(type: 'message', recipient: 'main', content: '改稿完成，已修改 {N} 处。', summary: '改稿完成')
    - 改稿完成后通知 reviewer 复审：
      send_message(type: 'message', recipient: 'reviewer', content: '已按审稿意见完成修改，请复审。', summary: '改稿完成请复审')
  "
)
```

- **无 🔴 问题** → 直接展示审稿报告给用户

### 第 5 步：清理团队

```
send_message(type: "shutdown_request", recipient: "reviewer")
send_message(type: "shutdown_request", recipient: "writer")   # 如果派发了 writer
team_delete()
```

输出协作总结：
```
📊 审稿团队协作总结
┌──────────────────────────────────────────┐
│ 参与 Agent：reviewer + writer              │
│ 审稿问题：🔴 {X} 项  🟡 {Y} 项           │
│ Agent 间通信：{N} 次                       │
│ 底层工具链：team_create → task × {Z} → team_delete │
└──────────────────────────────────────────┘
```

## 流水线位置

```
📋 Sub-Agent 写作流水线（真正的多 Agent 模式）

  ┌────────────┐    ┌────────────────┐    ┌──────────────┐    ┌────────────────┐    ┌────────────────┐
  │  🔎🟩 scout │───►│  📐🟪 architect │───►│  📝🟧 writer  │───►│▶ 🛡️🟥 reviewer │───►│  ✨🟨 polisher │
  └────────────┘    └────────────────┘    └──────────────┘    └────────────────┘    └────────────────┘

  ▶ 当前位置：🛡️🟥 reviewer（技术审稿人）
  ⚡ 模式：真正的多 Agent——team_create + task 异步 + send_message

  审稿团队拓扑：
  ┌──────────┐     ┌────────┐
  │ reviewer │◄───►│ writer │
  │ 审查文章  │     │ 按意见改│
  └──────────┘     └────────┘
```

## 下一步

- 无 🔴 项 → 使用 `/final-polisher` 进入终稿润色
- 有 🔴 项 → writer 已自动改稿，可再次 `/tech-reviewer` 复审或直接 `/final-polisher`
