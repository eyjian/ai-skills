# 文章编写 Skills 总览

本目录包含两套 Agent 方案，用于辅助**领域画像驱动**的文章创作流程，而不再只是一套“AI 技术文章写作 prompt”。

当前首批画像包括：`ai`、`generic`、`health`、`running`。
两套 skill 包遵循同一套领域画像 schema，但为了**分别发布、分别安装、分别使用**，各自在自己的目录里内置配置和架构文档，运行时互不依赖。

## 架构文档

- **Sub-Agent 包**：[ARCHITECTURE.md](/data/workspace/github/eyjian/ai-skills/ai-writing-skills/subagent-writing-skills/ARCHITECTURE.md)
- **Agent Team 包**：[ARCHITECTURE.md](/data/workspace/github/eyjian/ai-skills/ai-writing-skills/agent-team-writing-skill/ARCHITECTURE.md)

后续如果需要增加新领域，优先扩展各包内置的领域画像配置，而不是在每个角色里重复追加硬编码规则。

---

## 方案一览

| 方案 | 类型 | 触发方式 | 适用场景 |
|------|------|---------|---------|
| **5 个独立 Skill** | Sub-Agent（你手动驱动） | 分别触发 `/topic-scout`、`/outline-architect` 等 | 既可从零开始写新稿，也可按需处理已有文章的某个环节；执行前先读取**本包内置**的领域画像配置 |
| **article-team** | Agent Team（自动协作） | `/article-team {选题方向 / 文章路径 / 改稿需求}` | 新稿从选题写到发布，或让团队接管已有文章的重审 / 改稿 / 润色；执行前先解析**本包内置**的领域画像 |

---

## 方案一：5 个独立 Skill（Sub-Agent 模式）

由你充当"协调者"，按需手动调用每个角色。角色之间不互相通信，你控制每一步。
这套模式既适合从 0 到 1 写新稿，也适合对现有 Markdown 文章做定点处理：例如只重做标题、只重构结构、只改某几章、只审稿或只润色。

## 领域画像架构（各包分别内置）

两套方案遵循同一套领域画像协议，但**不共享运行时文件**，而是在各自包内分别内置一份配置：
- `subagent-writing-skills/shared-writing-resources/domain-profiles/domain-profiles.json`
- `agent-team-writing-skill/article-team/shared-writing-resources/domain-profiles/domain-profiles.json`

对应的架构说明也分别放在各自目录下：
- [ARCHITECTURE.md](/data/workspace/github/eyjian/ai-skills/ai-writing-skills/subagent-writing-skills/ARCHITECTURE.md)
- [ARCHITECTURE.md](/data/workspace/github/eyjian/ai-skills/ai-writing-skills/agent-team-writing-skill/ARCHITECTURE.md)

配置会统一给出：
- `topic_domain`
- `effective_profile`
- `resolved_mode`
- `secondary_domains`
- `default_reader`
- `article_type_candidates`
- `role_focus`

设计原则：
- `topic_domain` 表示主题真实所属领域
- `effective_profile` 表示当前实际采用的画像；当用户明确要求“按通用文章写”时，可与 `topic_domain` 不同
- 子画像通过 `inherits_from` 继承父画像；角色消费时先合并父画像，再叠加子画像
- 高风险或强边界领域（如 `health`、`running`）通过画像补充风险提示、停止条件和适用人群要求
- `shared-writing-resources` 表示**包内共享**，不是跨包共享
- 两个包在运行时互不依赖；如果希望两边行为保持一致，需要分别同步各自目录下的配置与文档

### 1. 选题侦察员（topic-scout）

| 属性 | 说明 |
|------|------|
| **触发词** | "选题"、"写什么"、"最近有啥好写的"、"热点"、"选个主题"，以及“换个标题”“重估定位”“想几个副标题” |
| **输入** | 模糊方向 / 具体方向 / 无方向 / 现有文章文件 |
| **输出** | 3-5 个选题方案，或 2-3 个标题 / 副标题 / 定位优化方向 |
| **工具** | `web_search`、`read_file` |
| **下一步** | 新稿场景 → `/outline-architect`；旧稿场景 → `/outline-architect` / `/tech-reviewer` / `/final-polisher` |

### 2. 大纲架构师（outline-architect）

| 属性 | 说明 |
|------|------|
| **触发词** | "大纲"、"文章结构"、"怎么组织"、"列个提纲"，以及“重构结构”“调整章节顺序”“给个改稿方案” |
| **输入** | 确认后的选题 + 补充意见，或现有文章 + 结构问题 |
| **输出** | 结构化大纲，或现有文章的结构重构方案 |
| **工具** | `web_search`、`read_file` |
| **规则** | 结构规则由当前 `effective_profile` 决定：`ai` 画像优先对比表、类比和工程结构件；`generic` / `health` / `running` 画像优先步骤清单、误区表、决策表、FAQ 与风险边界。默认仍建议控制在 3-5 章、每章不超 3 小节 |
| **下一步** | 新稿场景 → `/draft-writer`；旧稿场景 → `/draft-writer` |

### 3. 初稿写手（draft-writer）

| 属性 | 说明 |
|------|------|
| **触发词** | "写初稿"、"开始写"、"按大纲写"、"撰写正文"，以及“按审稿意见改稿”“重写这几段”“按新结构改一版” |
| **输入** | 审批通过的大纲，或现有文章 + 审稿意见 / 重构方案 |
| **输出** | 完整 Markdown 初稿，或基于原文的局部 / 整体改写结果 |
| **工具** | `read_file`、`web_search`、`write_to_file` / `replace_in_file` |
| **风格铁律** | 自然但克制、短句（≤30字）、每段≤5行、禁止学术腔；结构件由当前 `effective_profile` 决定：`ai` 画像优先对比表 / 类比，通用画像优先 FAQ / 清单 / 决策表 / 误区表 / 风险边界 |
| **下一步** | 新稿完成后 → `/tech-reviewer`；旧稿改完后 → `/tech-reviewer` 或 `/final-polisher` |

### 4. 技术审稿人（tech-reviewer）

| 属性 | 说明 |
|------|------|
| **触发词** | "审稿"、"review"、"检查文章"、"技术审查"、"帮我看看这篇"，以及“重审”“复审”“回炉检查” |
| **输入** | 待审稿的 Markdown 文章（可为新稿、旧稿或改稿版） |
| **输出** | 审稿报告（🔴 必须修改 / 🟡 建议改进 / 🟢 优点） |
| **工具** | `read_file`、`web_search` |
| **审查维度** | ①事实准确性 ②逻辑完整性 ③概念辨析 ④类比恰当性 ⑤代码质量 ⑥风格一致性 ⑦配图检查 ⑧引用出处 ⑨读者获得感 ⑩传播与收藏价值 ⑪AI 味和对话腔 |
| **原则** | 只标问题+给建议，不直接改文字 |
| **下一步** | 无🔴项 → `/final-polisher`；有🔴项 → `/draft-writer` 或 `/outline-architect` 后重新 `/tech-reviewer` |

### 5. 终稿润色师（final-polisher）

| 属性 | 说明 |
|------|------|
| **触发词** | "润色"、"打磨"、"终稿"、"最后检查"、"发布前检查"，以及“去 AI 味”“统一术语”“直接打磨现有文章” |
| **输入** | 审稿通过的文章，或现有文章 |
| **输出** | 润色报告 + 实际修改后的终稿 |
| **工具** | `read_file`、`replace_in_file` |
| **润色维度** | ①标题/引言优化 ②术语统一 ③Markdown格式 ④文字打磨 ⑤前后文一致性 ⑥结尾检查 ⑦扫读友好性 ⑧传播与收藏价值 |
| **原则** | 保持作者口吻，不改成另一个人的风格；发现技术问题时先回到审稿 |

### Sub-Agent 模式流程图

#### 新稿创作

```
你（协调者）
  │
  ├──► /topic-scout       → 3-5 个选题方案 → 你确认
  │
  ├──► /outline-architect → 结构化大纲     → 你确认
  │
  ├──► /draft-writer      → 逐章初稿       → 你审阅
  │
  ├──► /tech-reviewer     → 审稿报告       → 你决定是否退回
  │
  └──► /final-polisher    → 终稿           → 你终审发布
```

#### 旧稿回炉

```
你（协调者）
  │
  ├──► /topic-scout       → 标题 / 定位优化（可选）
  │
  ├──► /outline-architect → 结构重构方案（按需）
  │
  ├──► /draft-writer      → 按意见改稿（按需）
  │
  ├──► /tech-reviewer     → 重审 / 复审（推荐）
  │
  └──► /final-polisher    → 终稿打磨 / 去 AI 味
```

> 不必每次全走一遍——可以从任意环节开始，按需跳步。无论是新稿还是旧稿，都可以只调用某一个角色。

---

## 方案二：article-team（Agent Team 模式）

一条命令启动整个团队，5 个 Agent 以网状拓扑自动协作。
执行前会先解析**本包内置**的领域画像，再决定当前该采用哪种写法与协作路径。
- **新稿创作**：从选题 → 大纲 → 初稿 → 审稿 → 润色
- **旧稿重审 / 回炉**：对现有 Markdown 文章做重审、改稿、结构级大改和终稿打磨
- **旧稿直接润色**：对基本成型的文章直接做去 AI 味、统一术语和发布前收尾

### 触发方式

```
/article-team Agent 编排模式对比
/article-team 最近 AI 编程有啥值得写的
/article-team 重审 docs/agent-orchestration.md
/article-team 请润色 article.md，重点降低 AI 味
/article-team 重构 docs/agent-orchestration.md 的章节顺序，先给结构级改稿方案
```

### 旧稿入口优先级速查

| 用户输入特征 | 默认起点 | 团队处理方式 |
|-------------|---------|-------------|
| **重审 / 复审 / 检查这篇 / 回炉改一版** | `reviewer` | 先审查，再决定是否联动 `architect` / `writer` / `polisher` |
| **只润色 / 发布前打磨 / 降 AI 味 / 终稿处理** 且文件明确 | `polisher` | 直接收尾；如发现技术或结构问题，再回退给 `reviewer` |
| **重构结构 / 调整章节顺序 / 先给结构方案 / 大改章节** | `reviewer` | 视为结构优先任务，优先联动 `architect` 给出重构方案 |

### 团队成员

| 成员 | 代号 | 职责 | 自主能力 |
|------|------|------|---------|
| 选题侦察员 | `scout` | 搜索热点，提供选题建议；旧稿时协助重估标题和定位 | 可主动找 architect 讨论可行性，也可给旧稿提供标题方向 |
| 大纲架构师 | `architect` | 设计文章结构和大纲；旧稿时输出重构方案 | 可直接找 scout 调整选题、通知 writer 提前开工 |
| 初稿写手 | `writer` | 按大纲撰写 Markdown 初稿；或根据审稿意见改写旧稿 | 可找 architect 调整大纲、找 scout 确认细节 |
| 技术审稿人 | `reviewer` | 审查准确性和完整性；旧稿模式下可直接作为首个入口 | **自主决定退回**，直接找 writer 要求修改 |
| 终稿润色师 | `polisher` | 最终打磨和格式规范化；也可直接接手旧稿润色 | 发现技术问题直接反馈给 reviewer |

### 与 Sub-Agent 模式的核心区别

| 维度 | Sub-Agent（5 个独立 Skill） | Agent Team（article-team） |
|------|---------------------------|--------------------------|
| **Agent 间通信** | 无，各自独立 | 任意成员可直接 `send_message` |
| **决策权** | 你控制每一步 | Agent 自主决策（reviewer 自己退回） |
| **流程** | 手动触发，灵活跳步 | 自动推进，动态调整 |
| **并行** | 串行（一次一个） | 可并行（大纲确定后 writer 可提前开工） |
| **协调者角色** | 你是老板，做所有决策 | 你只在 3 个节点确认 |

### 需要你确认的节点（仅 3 个）

#### 新稿创作模式

1. **选题确认** — scout 给出方案后
2. **大纲确认** — architect 设计完后
3. **终稿确认** — polisher 润色完后

#### 旧稿回炉模式

1. **终稿确认** — polisher 润色完后
2. **结构级改稿确认（按需）** — 只有在 reviewer / architect 判断需要较大结构重构时，main 才会找你确认

其余环节（reviewer 退回修改、architect 找 scout 讨论、polisher 发现技术问题回退 reviewer 等）Agent 之间自行处理。

### Agent Team 通信拓扑

```
          scout ◄────► architect
            ▲              ▲
            │              │
            ▼              ▼
        reviewer ◄────► writer
            ▲              ▲
            │              │
            ▼              ▼
          polisher ◄───► main(你)
            
  所有成员均可互相直接通信
  main 只负责传话（用户确认）和启动新成员
```

---

## 旧稿回炉指令模板（可直接复制）

把下面模板里的 Markdown 文件路径替换成你的实际文章路径即可。

### 推荐写法

尽量把 4 个信息写清楚：
- **动作**：重审 / 改稿 / 润色 / 去 AI 味 / 重构结构
- **文件路径**：明确到具体 `.md` 文件
- **重点目标**：例如技术准确性、标题优化、统一术语、降低 AI 味
- **约束**：例如只审稿不改文、不要大改结构、保留原观点

推荐句式：

```text
/命令 动作 + 文件路径 + 重点目标 + 约束
```

### 用 `article-team` 一次接管旧稿

适合：**希望团队自动判断是否需要审稿、重构、改写和润色**。

```text
/article-team 重审 docs/agent-orchestration.md
/article-team 重审 docs/agent-orchestration.md，重点检查技术准确性和逻辑完整性，只审稿不改文
/article-team 重审 docs/agent-orchestration.md，如有必要先重构结构，再完成改稿和终稿润色
/article-team 润色 docs/agent-orchestration.md，重点降低 AI 味，保留原观点，不要大改结构
/article-team 处理 docs/agent-orchestration.md：统一术语、优化标题和引言，做发布前打磨
```

### 用独立 Skill 手动回炉旧稿

适合：**只想动某一个环节，或希望自己控制每一步**。

#### 1. 只重做标题 / 定位

```text
/topic-scout 给 docs/agent-orchestration.md 想 3 个更稳的标题，并重估文章定位
/topic-scout 读取 docs/agent-orchestration.md，给我 2 个更克制的副标题方案，降低标题的喊话感
```

#### 2. 只重构结构

```text
/outline-architect 读取 docs/agent-orchestration.md，给出结构重构方案，说明哪些段落保留、哪些需要重排
/outline-architect 重做 docs/agent-orchestration.md 的章节结构，重点解决信息重复和结尾收束偏弱的问题
```

#### 3. 按意见改稿

```text
/draft-writer 按审稿意见改 docs/agent-orchestration.md，重点重写第 2、3 章，保留原观点
/draft-writer 按新的结构方案改 docs/agent-orchestration.md，不要另起新文件，重点降低“我/你”密度
```

#### 4. 只做审稿 / 复审

```text
/tech-reviewer 重审 docs/agent-orchestration.md，重点检查技术准确性、逻辑完整性和 AI 味
/tech-reviewer 复审 docs/agent-orchestration.md，重点看改稿后结构是否更顺、是否还残留明显对话腔
```

#### 5. 只做终稿润色

```text
/final-polisher 打磨 docs/agent-orchestration.md，统一术语，降低 AI 味，不要大改结构
/final-polisher 直接处理 docs/agent-orchestration.md，优化标题、引言和结尾，做发布前最后润色
```

### 怎么选更合适？

- **想省事**：优先用 `article-team`
- **只想处理一个环节**：优先用单个独立 Skill
- **旧稿问题还不清楚**：先用 `article-team` 或 `/tech-reviewer`
- **已经明确只是标题、结构或润色问题**：直接用对应角色

---

## 目录结构

```
subagent-writing-skills/                    ← Sub-Agent 模式：5 个独立 Skill
├── ARCHITECTURE.md                        ← 架构说明（Sub-Agent 包，独立发布）
├── topic-scout/SKILL.md                    ← 选题侦察员
├── outline-architect/SKILL.md              ← 大纲架构师
├── draft-writer/SKILL.md                   ← 初稿写手
├── tech-reviewer/SKILL.md                  ← 技术审稿人
└── final-polisher/SKILL.md                 ← 终稿润色师

agent-team-writing-skill/                   ← Agent Team 模式：1 个完整团队
├── ARCHITECTURE.md                        ← 架构说明（Agent Team 包，独立发布）
└── article-team/
    ├── SKILL.md                            ← 入口（触发描述）
    ├── shared-writing-resources/
    │   └── domain-profiles/
    │       └── domain-profiles.json       ← article-team 内共享画像配置
    ├── commands/article-team.md            ← 编排命令（协调者 prompt）
    └── agents/
        ├── scout.md                        ← 选题侦察员（团队版）
        ├── architect.md                    ← 大纲架构师（团队版）
        ├── writer.md                       ← 初稿写手（团队版）
        ├── reviewer.md                     ← 技术审稿人（团队版）
        └── polisher.md                     ← 终稿润色师（团队版）
```

### 安装方式

将对应目录下的 Skill 文件复制到你项目的 `.codebuddy/skills/` 目录下即可使用：

```bash
# 安装 Sub-Agent 模式（5 个独立 Skill）
cp -r subagent-writing-skills/* .codebuddy/skills/

# 安装 Agent Team 模式
cp -r agent-team-writing-skill/article-team .codebuddy/skills/
```

---

## 如何选择？

| 场景 | 推荐方案 |
|------|---------|
| 只想审稿 / 只想润色 / 只想要个选题 | 独立 Skill（按需触发单个角色） |
| 完整写一篇文章，从选题到发布 | article-team（一条命令搞定） |
| 已有旧稿，但想手动控制每一步如何回炉 | 独立 Skill |
| 已有旧稿，想让团队自动重审、改稿、重润色 | article-team |
| 想最大程度控制每一步 | 独立 Skill |
| 想省事，让 Agent 自己协商解决 | article-team |

---

## 作者写作风格速查

所有 Skill 和 Agent 共享以下风格约束：

其中语气、句长、段长、克制度属于全局基础风格；对比表、清单、FAQ、误区表、图示等结构件，优先由当前 `effective_profile` 决定。

| 规则 | 说明 |
|------|------|
| 自然但克制 | 允许少量口语，但不写成聊天记录或口播脚本 |
| 陈述式为主 | 少用“我带你看”“你可以”“别急着”这类面对面带读句式 |
| 控制人称密度 | 正文尽量少用“我”“你”，必要时优先用“本文”“实践中”“建议”“可”“需”“应” |
| 短句 | 每句 ≤ 30 字 |
| 短段 | 每段 ≤ 5 行 |
| 结构件选择 | 由当前 `effective_profile` 决定：`ai` 画像优先对比表；通用画像优先 FAQ / 清单 / 决策表 / 误区表 / 适合谁&不适合谁 |
| 善用类比 | 把抽象概念映射到更易理解的场景；AI 文章偏工程类比，通用文章偏生活或行动类比 |
| 尽量配图 | 按画像选择：AI 文章更适合流程图、架构图、对比图；通用文章更适合步骤图、判断图、训练表或清单截图 |
| 标注引用 | 关键信息标注来源（官方文档、GitHub、论文、指南、机构资料等） |
| 有明确收获 | 读完后要能带走判断、方法、步骤、边界或避坑建议 |
| 有可复用资产 | 每篇至少产出 1 个 FAQ / 决策表 / 排错表 / 误区清单 / 步骤清单 / 一页总结 |
| 有传播亮点 | 至少有 1 处适合截图传播的表格、总结块或判断 |
| 禁止学术腔 | 不用“本文旨在”、“综上所述”、“笔者认为” |
| 不保留固定 AI 结尾 | 不用 `本文由 AI 原生生成...` 这类自曝式结尾 |
