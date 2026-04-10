---
name: final-polisher
description: 文章终稿润色师（真正的多 Agent 模式）。当用户提到"润色""打磨""终稿""最后检查""发布前检查""去 AI 味""统一术语"时触发。本 skill 通过 CodeBuddy 的 team_create + task（异步团队模式）+ send_message + team_delete 工具链，创建包含 reviewer（快审）和 polisher 的多 Agent 团队，先快审再润色。
---

# 终稿润色师（Final Polisher）— 真正的多 Agent 模式

## 与模拟版的核心区别

| 维度 | 本方案（真正多 Agent） | 模拟版（skill 直接执行） |
|------|----------------------|------------------------|
| 执行方式 | 通过 `team_create` + `task` 异步模式创建多 Agent 团队 | skill 自身直接执行（单 Agent 角色扮演） |
| Agent 实例 | reviewer（快审）+ polisher 两个独立 Agent 实例 | 无独立实例 |
| 协作能力 | reviewer 快审后通过 `send_message` 通知 polisher 开工 | 无协作，直接润色 |
| 安全机制 | reviewer 先检查技术错误，避免 polisher 润色一篇有硬伤的文章 | 无前置检查 |
| 团队生命周期 | `team_create` → `task` × 2 → `send_message` → `team_delete` | 无 |

## 执行方式

本 skill 触发后，**创建一个润色团队**，先派发 reviewer 做快速技术检查，再派发 polisher 润色：

### 第 1 步：读取领域画像配置

先用 `read_file` 读取 `../shared-writing-resources/domain-profiles/domain-profiles.json`，解析领域画像。

### 第 2 步：创建润色团队

```
team_create(team_name: "polish-team")
```

### 第 3 步：派发 reviewer Agent（快审模式）

```
task(
  subagent_name: "coder",
  name: "reviewer",
  team_name: "polish-team",
  mode: "bypassPermissions",
  description: "润色前快速审查",
  prompt: "
    你是文章审稿人，当前任务是润色前的快速技术检查。

    ## 领域画像配置协议
    先读取画像配置，解析运行时字段。
    画像配置文件内容如下：
    {domain-profiles.json 的内容}

    ## 用户输入
    {用户的原始输入（文章路径或润色要求）}

    ## 快审重点
    这是润色前的快速审查，集中精力找关键问题：
    1. 有无明显的事实错误
    2. 有无技术概念混淆
    3. AI 味整体评级
    4. 全文\"你\"字出现次数
    不需要逐条详细列出 🟡 建议项。

    ## 团队通信
    你是 polish-team 的 reviewer 成员。
    - 快审完成后通知 polisher 开工：
      send_message(type: 'message', recipient: 'polisher', content: '快审完成，{有/无}技术问题。AI 味评级：{评级}。\"你\"字出现 {N} 次。请开始润色。', summary: '快审完成')
    - 同时通知协调者：
      send_message(type: 'message', recipient: 'main', content: '快审完成。', summary: '快审完成')
    - 发现严重技术问题时通知协调者：
      send_message(type: 'message', recipient: 'main', content: '发现严重技术问题，建议先修改再润色。', summary: '发现技术问题')
  "
)
```

### 第 4 步：派发 polisher Agent

收到 reviewer 的快审结果后：
- **无严重技术问题** → 派发 polisher：

```
task(
  subagent_name: "coder",
  name: "polisher",
  team_name: "polish-team",
  mode: "bypassPermissions",
  description: "终稿润色",
  prompt: "
    你是终稿润色师。锦上添花，不推倒重来。核心原则：保持作者口吻。

    ## 领域画像配置协议
    先读取画像配置，解析运行时字段。
    画像配置文件内容如下：
    {domain-profiles.json 的内容}

    ## 用户输入
    {用户的原始输入（文章路径或润色要求）}

    ## reviewer 快审结论
    {reviewer 的快审结果}

    ## 润色维度（7 个）
    1. 标题和引言优化
    2. 术语统一
    3. Markdown 格式规范
    4. 文字打磨
    5. 前后文一致性
    6. 结尾检查
    7. 扫读友好性

    ## 去 AI 味重点
    - 高频\"我\"\"你\"改为陈述式
    - 模板化句式改为自然表述
    - 删除 AI 自述式结尾
    - 保留作者判断和节奏

    ## \"你\"字清零门禁
    润色完成后全文搜索\"你\"字，不清零不算完成。

    ## 工作流程
    1. 读取待润色文章
    2. 读取已有文章作为风格参考
    3. 逐维度润色
    4. 使用 replace_in_file 对文章进行实际修改
    5. 输出润色报告

    ## 团队通信
    你是 polish-team 的 polisher 成员。
    - 润色完成后通知协调者：
      send_message(type: 'message', recipient: 'main', content: '终稿润色完成。\\n\\n{润色报告}', summary: '终稿完成')
    - 发现技术问题时通知 reviewer：
      send_message(type: 'message', recipient: 'reviewer', content: '发现技术问题：{问题描述}', summary: '技术问题回退')

    ## 禁止事项
    - 不改变核心观点
    - 不增加新内容段落
    - 不删除整段内容
    - 不为了去 AI 味把文章改得发干
    - 发现技术错误时提醒 reviewer，不假装是润色问题
  "
)
```

- **有严重技术问题** → 向用户报告，建议先用 `/tech-reviewer` 完整审稿并修改

### 第 5 步：清理团队

```
send_message(type: "shutdown_request", recipient: "reviewer")
send_message(type: "shutdown_request", recipient: "polisher")
team_delete()
```

输出协作总结：
```
📊 润色团队协作总结
┌──────────────────────────────────────────┐
│ 参与 Agent：reviewer（快审）+ polisher     │
│ 快审结论：{无问题 / 有问题}                │
│ 润色修改：{X} 处                           │
│ Agent 间通信：{N} 次                       │
│ 底层工具链：team_create → task × 2 → team_delete │
└──────────────────────────────────────────┘
```

## 流水线位置

```
📋 Sub-Agent 写作流水线（真正的多 Agent 模式）

  ┌────────────┐    ┌────────────────┐    ┌──────────────┐    ┌────────────────┐    ┌────────────────┐
  │  🔎🟩 scout │───►│  📐🟪 architect │───►│  📝🟧 writer  │───►│  🛡️🟥 reviewer │───►│▶ ✨🟨 polisher │
  └────────────┘    └────────────────┘    └──────────────┘    └────────────────┘    └────────────────┘

  ▶ 当前位置：✨🟨 polisher（终稿润色师）
  ⚡ 模式：真正的多 Agent——team_create + task 异步 + send_message

  润色团队拓扑：
  ┌──────────┐     ┌──────────┐
  │ reviewer │────►│ polisher │
  │ 快速审查  │     │ 终稿润色  │
  └──────────┘     └──────────┘
```

## 完成

润色完毕后，提醒用户通读全文确认是否可以发布。
