# DICOM Doctor 版本历史

> 本文件包含 DICOM Doctor skill 的完整版本变更记录。主文档见 `SKILL.md`。

## v2.11.2 — Skill 结构规范化（符合 skill-creator 规范）

**核心改动**

- **[改] SKILL.md 瘦身**：从 614 行精简至 ~300 行，将铁律详细说明、全量阅片流程、Python 安装指南拆分到 `references/` 下的独立文件
  - `references/iron_rules.md`：铁律 1-11 的完整详细说明
  - `references/review_workflow.md`：全量阅片详细流程（分批持久化、续跑机制、阅片红线、JSON 格式）
  - `references/python_setup.md`：Python 环境安装指南（各平台）
- **[改] 字体目录迁移**：`fonts/` → `assets/fonts/`，符合 skill-creator 的 `assets/` 目录规范
  - 同步更新 `report_generator.py` 中的字体路径引用
- **[改] evals.json 字段名修正**：`expectations` → `assertions`，与 skill-creator schema 一致

## v2.11.1 — Lung-RADS v1.1 完整分级校验（修复结节分级错误）

**问题背景**

使用中发现部分模型输出的 Lung-RADS 分级与结节尺寸不匹配（如实性 7mm 结节被标为 2 类，应为 3 类）。原有校验逻辑仅覆盖"实性 < 6mm → 2 类"这一条规则，无法纠正其他尺寸段和其他密度类型的分级错误。

**核心改动**

- **[改] `reviewer.py` — 扩展 Lung-RADS v1.1 完整分级校验**
  - 实性结节全尺寸段覆盖：< 6mm → 2 类, 6-8mm → 3 类, 8-15mm → 4A 类, > 15mm → 4B 类
  - 纯 GGO（磨玻璃）结节：< 30mm → 2 类, ≥ 30mm → 3 类
  - 部分实性（混合）结节：< 6mm → 2 类, 6-8mm → 3 类, ≥ 8mm → 4A 类
  - 4X 类（恶性征象）无法通过尺寸判断，不做自动校正
  - 支持双向校正（降级 + 升级），解决原来只做降级的缺陷
  - 自动保持原有格式风格（纯数字 vs 带"类"后缀）
  - 每次校正通过 logger.info 记录，方便追溯

- **[改] 密度类型智能识别**
  - 实性：包含"实性"且不含 GGO/部分实性关键词
  - GGO：匹配"磨玻璃"、"GGO"、"GGN"、"ground glass"
  - 部分实性：匹配"部分实性"、"混合"、"part-solid"、"混合磨玻璃"

**修复效果**

| 场景 | v2.11.0 行为 | v2.11.1 行为 |
|------|-------------|-------------|
| 实性 7mm 被标 2 类 | 不校正 ❌ | 自动校正为 3 类 ✅ |
| 实性 10mm 被标 3 类 | 不校正 ❌ | 自动校正为 4A 类 ✅ |
| GGO 25mm 被标 3 类 | 不校正 ❌ | 自动校正为 2 类 ✅ |
| 部分实性 9mm 被标 2 类 | 不校正 ❌ | 自动校正为 4A 类 ✅ |
| 实性 4mm 被标 3 类 | 校正为 2 类 ✅ | 校正为 2 类 ✅ |

## v2.11.0 — Review Harness 阅片评估框架（解决 early stopping）

**问题背景**

某些大模型在执行全量阅片时会出现 early stopping（过早停止）：批次内只处理部分切片就停止、输出 JSON 被截断、或在中途输出"综上所述"等总结性语句后停止。这导致阅片不完整，存在漏诊风险。

**核心改动**

- **[新] `review_harness.py` — 单条级别阅片评估框架（方案 B）**
  - 借鉴 AI 评测领域的 Harness 理念，将每张切片作为独立的原子任务执行
  - 每条结果经过 JSON schema 校验 + 截断检测 + 假完成检测
  - 单条失败自动重试（最多 N 次，指数退避）
  - 实时进度追踪 + 停滞检测（连续 5 条失败告警）
  - 独立的 `harness_state.json` 状态文件，支持断点续跑
  - 与现有 batch_templates / review_results.json 完全兼容

- **[改] `auto_review_batches.py` — Harness 增强（方案 A）**
  - `OpenAICompatibleVisionClient.review_item()` 新增重试 + 截断检测 + 假完成检测
  - 新增 `--max-retries` 参数：单条最大重试次数（默认 3）
  - 新增 `--max-tokens` 参数：模型最大输出 token 数（防止截断）
  - system prompt 增加"不要输出总结性语句"的指令
  - 内部拆分为 `_single_call()` + `review_item()` 两层，便于重试控制

- **[新] 截断检测引擎 `detect_truncation()`**
  - JSON 括号不匹配检测（缺少闭合 `}` 或 `]`）
  - 输出过短检测（< 30 字符）
  - 空输出检测

- **[新] 假完成检测引擎 `detect_fake_completion()`**
  - 正则匹配"综上所述""以上是全部""总结如下""in summary"等模式
  - 检测到后自动重试，最后一次仍有信号则尝试解析 JSON

- **[新] JSON schema 校验 `validate_response_json()`**
  - 必需字段检查（conclusion）
  - conclusion 合法值检查（正常/异常/无法识别）
  - bounding_boxes 格式和坐标范围校验

**两种工具的选择指南**

| 场景 | 推荐工具 | 原因 |
|------|---------|------|
| 模型稳定，无 early stopping | `auto_review_batches.py` | 按批处理效率更高 |
| 模型有 early stopping 倾向 | `review_harness.py` | 单条级别控制，彻底解决 |
| 不确定模型是否稳定 | `auto_review_batches.py` + `--max-retries 3` | 先用增强版批处理试试 |
| 需要最高可靠性 | `review_harness.py` + `--max-retries 3` | 每条独立重试 + 校验 |

**使用示例**

```bash
# 方案 A：增强版批处理（适合大多数场景）
python3 scripts/auto_review_batches.py \
  --manifest output/review_manifest.json \
  --model gpt-4o \
  --max-retries 3 \
  --max-tokens 2048

# 方案 B：Harness 单条模式（适合 early stopping 严重的模型）
python3 scripts/review_harness.py \
  --manifest output/review_manifest.json \
  --model gpt-4o \
  --max-retries 3 \
  --max-tokens 2048

# 断点续跑（两种工具都支持，自动从上次中断处继续）
python3 scripts/review_harness.py \
  --manifest output/review_manifest.json \
  --model gpt-4o
```

## v2.10.0 — 「先试后判」视觉探测机制 + 移除环境变量误判 + 任务开始时确认模型身份

**问题背景**

实际使用中发现，Kimi-K2.5（多模态模型，支持图片）被错误检测为 GLM-5.0（不支持视觉），原因是用户环境中残留了 `ZHIPU_API_KEY` 环境变量。`_infer_from_context()` 方法从该环境变量推断出 `"glm-model"`，导致模型名称和能力判断完全错误。

**核心改动**

- **[删] 移除不可靠的环境变量推断**：`_infer_from_context()` 不再从 `GLM_API_KEY`、`ZHIPU_API_KEY` 等 API Key 类环境变量推断模型类型。这些环境变量可能是历史残留，与当前实际运行的宿主 AI 模型无关
- **[新] 「先试后判」视觉探测机制**：新增 `generate_vision_probe_prompt()` 和 `find_probe_image()` 函数。当检测结果说"不支持视觉"时，不再直接停下来，而是提示宿主 AI 先尝试读取一张测试图片——如果能读取说明检测误判，直接进入视觉模式
- **[新] 任务开始时确认模型身份**：SKILL.md 新增"第 0.5 步"，要求宿主 AI 在任务开始时先确认自己的实际模型名称，并通过 `--model-name` 参数传入，避免环境变量误判
- **[新] `_run_probe_then_decide()` 方法**：`host_ai_review.py` 新增此方法，实现"先试后判"流程——先提示尝试读图，确实不行再给替代方案
- **[新] `_print_vision_probe_hint()` 方法**：在能力检测报告之后打印视觉探测提示
- **[改] 铁律第 11 条增强**：新增"环境变量残留误判"的具体说明（如有 ZHIPU_API_KEY 但实际用的是 Kimi），明确「先试后判」策略

**行为变化**

| 场景 | v2.9.0 行为 | v2.10.0 行为 |
|------|------------|-------------|
| 有 ZHIPU_API_KEY + 实际用 Kimi | 误判为 GLM → 可能停下来 | 不再推断 API Key → 默认乐观 → 直接阅片 |
| 检测说不支持视觉 | 直接给替代方案 | 先提示尝试读图 → 能读就继续 → 不能读再给方案 |
| 未传 --model-name | 从环境变量猜测（不可靠） | 默认 unknown + 乐观策略 + 提示传入 model-name |

## v2.9.0 — 模型能力检测乐观策略优化

- `model_capability_detector.py` 默认策略从"保守"改为"乐观"（未知模型默认假定支持视觉）
- 新增 `detect_from_model_name()` 方法，支持通过 `--model-name` 参数直接检测
- 大幅扩展已知模型列表（GPT-5.x、Claude-4.x 等）
- `host_ai_review.py` 优先使用模型名称检测，ImportError 时默认支持视觉
- SKILL.md 铁律新增第 11 条：禁止因能力检测结果而放弃阅片

## v2.8.0 — 模型能力自动检测 + 智能分流处理

**新增核心功能**

- **新增 `model_capability_detector.py` 模块**：自动检测宿主 AI 是否支持图片识别
  - 支持从环境变量推断模型类型
  - 维护已知支持/不支持视觉的模型列表
  - 提供清晰的检测报告和推荐操作

- **改进 `host_ai_review.py` 智能分流**
  - 启动时自动检测宿主 AI 能力
  - **支持视觉**：进入自动连续处理模式
  - **不支持视觉**：直接给出清晰的替代方案（OpenAI/Claude/Gemini API）
  - 避免用户在不支持的情况下浪费时间尝试

- **优化用户体验**
  - 清晰的视觉化检测报告（✅/❌ 图标）
  - 按优先级排序的推荐方案
  - 包含 API Key 获取链接的完整指引

**技术改进**

- 版本号统一升级：2.7.0 → 2.8.0
- 新增 `_detect_capabilities()` 和 `_print_capability_report()` 方法
- 新增 `_run_vision_mode()` 和 `_run_text_only_mode()` 分流方法

**使用方式**

```bash
# 自动检测并处理（推荐）
python3 scripts/host_ai_review.py \
  --manifest <path>/review_manifest.json \
  --output <output_dir>

# 系统会自动检测模型能力并给出相应提示
```

## v2.7.0 — 宿主 AI 分批处理模式（无需 API Key）

- 当没有 OpenAI API Key 时，自动切换到宿主 AI 模式
- 支持断点续跑，每批完成后自动保存
- 新增 `--host-ai-review` 参数显式启用

## v2.6.0 — 宿主 AI 全自动化全量阅片（重大更新）

**新增核心功能**

- **新增 `full_auto_review.py` 模块**：利用宿主 AI 的多模态视觉能力，实现真正的零遗漏全量阅片
  - 自动生成标准化阅片请求列表（1079层 → 1079个独立请求）
  - 支持宿主 AI 逐张分析图片并回填结果
  - 每10张自动保存进度，防止中断丢失
  - 生成标准化的 `review_results_auto.json` 结果文件
  
- **版本号升级**：2.5.0 → 2.6.0
  - `version.py` 更新版本号
  - SKILL.md 文档同步更新
  - 脚本列表新增 `full_auto_review.py` 说明

**技术改进**

- 解决了手动逐批阅片耗时过长的问题（72批次 × 15张 = 1079张）
- 保持了 dicom-doctor 的铁律要求：逐层确认、零遗漏、全量阅片
- 兼容现有 `generate_report.py` 报告生成流程

**使用方式**

```bash
# 生成全量阅片请求
python3 scripts/full_auto_review.py --manifest <path>/review_manifest.json --output <output_dir>

# 宿主 AI 逐张处理请求后，生成报告
python3 scripts/generate_report.py --results <output_dir>/review_results_auto.json --manifest <path>/review_manifest.json ...
```

## v2.5.0 — CAD v2.8 假阳性深度优化（Case2 医院报告精确对照）

基于 Case2（岚天 2026-01-10 胸部CT, 1.25mm）医院报告 vs CAD 的精确对照分析——医院确认4个结节（1个GGO+3个实性），CAD输出35个候选中31个假阳性（FP率89%）。深度分析假阳性模式后实施以下优化：

**CAD v2.8 核心改动**

- **[新] 肺外缘空间惩罚**：cx距图像中心>180px→0.4, >150px→0.6, >120px→0.8。Case2有5个外缘假阳性(S#3,S#4,S#8,S#11,S#15)全在cx>370区域。保护：4个真结节cx距中心均<100px，不触发。
- **[新] 外缘+微小灶联合惩罚**：HU 80-200 + z_slices=2 + d<2.5mm + cx_dist>100 → 0.5。这是Case2中最典型的血管截面假阳性组合模式。
- **[改] GGO HU评分精细化**：-450~-380→1.0, -480~-450→0.8, -500~-480→0.5（原-500~-400全给1.0）。以-480为新分水岭。Case2真GGO HU=-409仍在最佳区间，假阳性(HU=-476~-492)显著降分。
- **[改] GGO合并距离**：15mm→20mm。Case2有3个GGO假阳性与真GGO在15mm内残留未合并。
- **[改] GGO血管排除收紧**：mean_hu惩罚阈值从-530/-510收紧到-510/-500/-480，配合HU评分形成双重降权。

**校准数据更新**
- Case2 医院报告精确匹配：GGO#21→GT1, Solid#6→GT2, Solid#17→GT3, Solid#5→GT4
- DICOM方向确认：心脏在图像左侧, cx<256=LEFT, cx>256=RIGHT

**预期效果**
- 假阳性从~31个降至~14个（FP率89%→~60%）
- 4个真结节评分保持≥0.90（0漏检）

## v2.4.8 — CAD vs AI 交叉验证（结果复核机制）

新增自动化的 **CAD vs AI 交叉验证**步骤，在 AI 阅片完成后、PDF 报告生成前自动执行：

**核心逻辑**
- 对所有 CAD 评分 ≥ 0.80 的高分候选，检查对应 z-range（±2 层容差）内的 AI 阅片结论
- 三类告警检测：
  - `missed_candidate`：CAD 高分但 AI 全标正常且无排除理由 → 可能遗漏
  - `described_but_not_reported`：AI 描述中提及可疑征象但结论为正常 → 矛盾
  - `no_coverage`：候选区域内无 AI 实际审阅结果 → 盲区
- 支持智能排除：如 AI 在描述中明确提及"血管/伪影/支气管"等排除理由，视为已审查并排除

**集成位置**
- `main.py`：阶段 3.5（阶段 3 校验之后、阶段 4 报告生成之前）
- `generate_report.py`：自动从 `cad_candidates.json` 加载 CAD 结果并执行交叉验证
- 告警结果保存为 `cross_validation.json`，并在 PDF 报告中以醒目的告警表格展示

**新增函数**
- `reviewer.cross_validate_cad_vs_review()` — 交叉验证核心逻辑
- `report_generator._build_cross_validation_section()` — PDF 报告告警章节

## v2.4.7 — 上下文窗口优化（分层 CAD hint + 精简版 prompt）

解决宿主 AI 因上下文窗口耗尽（1079 层 × 4 窗位 × ~14KB/层 prompt）导致阅片任务中断的问题：

**分层 CAD hint 注入（替代全局注入）**
- 旧方式：每层都注入全部 25 个 CAD 候选（~2.5KB），800 层 = 2MB 冗余
- 新方式：每层只注入 z-index ±5 层范围内的 CAD 候选（通常 0-3 个，~200B）
- 新增 `cad_detector.format_candidates_for_slice()` 和 `get_cad_focus_slices()` 函数

**双层 prompt 策略**
- **📌重点层**（CAD 候选 ±5 层）：使用完整版 REVIEW_PROMPT（~5000 字）+ 分层 CAD hint
- **⚡快扫层**（远离 CAD 候选）：使用新增的 REVIEW_PROMPT_LITE（~600 字），仍需逐张检视
- 精简版保留核心要素：GGO 窗优先、反保守偏见、JSON 输出格式、扫及区域
- 典型 800 层 CT：重点层 ~60-100 层，快扫层 ~700+ 层，prompt token 总量节省 ~50-70%

**结构化 CAD 数据传递**
- `main.py` 新增 `cad_candidates` 参数传递给 `reviewer.review()`
- `reviewer.py` 的 `review()` 方法新增 `cad_candidates` 参数，自动计算重点层集合
- `review_manifest.json` 中每层新增 `is_focus_layer` 和 `layer_type` 字段

**review_manifest.json 体积大幅减小**
- 旧方式：832 层 × ~14KB/层 = 11.6MB
- 新方式：100 重点层 × ~7KB + 732 快扫层 × ~1.5KB = ~1.8MB（减少 ~85%）

## v2.4.6 — 结节聚合正则修复（兼容 第N/M层 格式）

- 修复 `_normalize_location()` 正则表达式：旧正则 `[\d\-]+` 只匹配数字和连字符，无法处理 `（第344/832层）` 这种含斜杠的层面编号格式
- 新正则支持所有常见层面编号格式：
  - `(第218-221层)` — 连字符范围
  - `（第344/832层）` — 斜杠分隔（当前层/总层数）
  - `第218层` — 无括号版本
  - `，第197-199层` — 逗号连接版本
  - `(第218,219,220层)` — 逗号列举版本
- 新增尾部残留标点清理逻辑
- 修复了"不同智能体生成的 location 字段格式不一致导致结节聚合失败"的问题（如 84 个异常层面被当成 84 个独立结节）

## v2.4.5 — PDF 报告页数控制（最多 50 页）

- 新增 `MAX_PDF_PAGES = 50` 全局常量和 `max_pages` 参数
- 异常影像展示区域增加**页数预算控制**：
  - 固定区域（标题/信息/所见/诊断/分级/免责）预估 8 页
  - 剩余页数按每张异常影像 ~1.5 页估算，计算最大可展示图片数
  - **优先展示**每个聚合结节的代表层面（置信度最高的那张，带 ★ 标记）
  - 预算有余则按顺序补充非代表层面
  - 被省略的层面用 8pt 简明汇总表替代（含 DICOM 文件名/位置/描述/置信度）
  - 汇总表末尾提示"完整异常影像请查阅输出目录下的 PNG 文件"
- `generate_report.py` 新增 `--max-pages` 命令行参数（默认 50）
- `main.py` 无需修改（`max_pages` 有默认值，零侵入兼容）

## v2.4.4 — CAD v2.7 假阳性深度优化

基于 2023-06-02 胸部CT（Case 1）vs 医院报告的复核分析——AI 报了 13 个结节，医院只报了 1 个（右肺下叶前基底段 2mm 炎性肉芽肿）。深度分析 24 个实性 + 15 个 GGO 候选的假阳性模式后：

- **实性 HU 评分进一步收紧**：mean\_hu < 20 → 0.15（Case1 大量 mean\_hu=1\~11 的假阳性，真结节最低 49）
- **新增血管模式惩罚**：(max\_hu - mean\_hu) > 200 且 mean\_hu < 50 → vessel\_penalty × 0.2\~0.4（血管横截面典型模式：中心高密度+边缘低密度被平均拉低）
- **GGO HU 下限收紧**：mean\_hu < -520 → vessel\_penalty × 0.3\~0.5（接近空气-1000，真 GGO 的 HU 一般 > -500）
- **肺尖/肺底区域惩罚**：z < 5% 或 z > 95% → vessel\_penalty × 0.4（部分容积效应/胸廓入口伪影高发区）
- **GGO 合并距离扩大**：从 8mm → 15mm（Case1 有 5 个 GGO 假阳性在 20mm 内聚集，应合并为 1 个）
- **回归验证**：5 个真结节评分全部 ≥ 0.90（Case1 GT: 0.960, Case2 GT1-4: 0.907\~0.971），假阳性肺尖 Solid#1 从 0.925 → 0.498

## v2.4.3 — 可疑发现必报铁律 + 反保守偏见铁律化

基于真实漏诊案例（2023-06-02 胸部CT，CAD score=0.96 的实性结节被 AI 描述为"可疑微小结节"但 conclusion 标为"正常"，导致未进入报告——而该结节正是医院确诊的右肺下叶前基底段 2mm×2mm 炎性肉芽肿）：

- **铁律新增第 9 条**：可疑/疑似/不确定的发现**必须标记为"异常"**并进入报告。严禁"描述了但不报"——这是最危险的漏诊模式
- **铁律新增第 10 条**：反保守偏见从"阅片策略建议"提升为铁律。≥2mm 圆形高密度影必须优先报告为疑似结节，附具体判定规则
- **铁律第 7 条增强**：CAD 候选验证从二元判定（结节/血管）改为**三元判定**（确认结节✅ / 可疑待定⚠️ / 明确排除❌），可疑待定必须标异常进报告
- 核心原则：**宁可多报一个可疑发现让医生复核，也不能吞掉一个可能的结节**

## v2.4.2 — 报告两维度数据完整性铁律

- **铁律新增第 8 条**：报告必须同时包含结节维度（聚合汇总）和层面维度（逐层明细），缺一不可
- 第 4 步汇总说明详列两维度各自必须包含的字段清单
- 第 6 步报告格式明确标注两维度"缺一不可"

## v2.4.1 — CAD v2.6 假阳性评分优化

基于 2 例 5 GT 复核校准数据（含 30 实性 + 15 GGO 候选的假阳性模式分析）：

- **实性 HU 评分收紧**：80\~200→1.0, 50\~80→0.6, 20\~50→0.4, -50\~20→0.3（原 20\~200 全给 1.0）
- **GGO HU 评分收紧**：-500\~-400→1.0, -550\~-500→0.7, -600\~-550→0.5（原 -600\~-400 全给 1.0）
- **GGO elongation 惩罚**：>1.8→0.3, >1.5 且 voxels<30→0.5（真 GGO elong=1.16, 假阳性 elong=1.4\~2.0+）
- 空间聚簇惩罚暂缓（统计基础不足）
- 回归验证 4 个真结节全部通过

## v2.4.0 — 多影像类型架构统一（Phase 0）

**统一 JSON Schema**
- 所有影像类型 prompt 模板统一输出 `classification_system` + `classification_value` + `bounding_boxes` 字段
- 胸部CT 保留 `lung_rads` 字段向后兼容
- `reviewer.py` 解析逻辑支持新旧字段名双向回退

**反保守偏见铁律全模态推广**
- 腹部CT：肝脏低密度灶反保守偏见（Couinaud 8段扫查 + 易漏诊区域清单）
- 头颅MRI：FLAIR高信号灶反保守偏见（DWI真假弥散受限鉴别 + 基底节/丘脑/脑桥腔梗高发区）
- 腹部MRI：T2高信号灶+DWI弥散受限反保守偏见（多序列组合判断表）
- 通用模式：通用反保守偏见铁律

**报告分级参考表扩展**
- 新增 LI-RADS 参考表（LR-1 到 LR-TIV，含完整处理建议）
- 新增 Fazekas 白质病变分级参考表（0-3级）
- 报告生成器根据 `ImagingProfile.classification_system` 自动选择展示哪种参考表

**诊断意见随访建议**
- LI-RADS：LR-1 无需随访 → LR-5 立即治疗，7档具体建议
- Fazekas：0级正常 → 3级重度+神经内科随访，4档具体建议
- PDF 和 Markdown 报告同步支持

**Prompt 模板深度大幅提升**
- 腹部CT：4.25KB → ~14KB（+Couinaud扫查/LI-RADS完整表/易漏诊区域/CAD占位符）
- 头颅MRI：3.83KB → ~12KB（+Fazekas分级/MRI信号分析/解剖分区扩展/CAD占位符）
- 腹部MRI：3.54KB → ~10KB（+多序列组合判断表/LI-RADS完整表/CAD占位符）
- 通用模式：2.2KB → ~4KB（+反保守偏见铁律/bounding_boxes/CAD占位符）

**头颅MRI ImagingProfile 增强**
- `classification_system` 从空改为 `"Fazekas"`
- `report_sections` 新增"基底节及丘脑"和"扫及区域"

**CAD 预留接口**
- 所有非胸部CT模板新增 `{cad_hint}` 占位符，为未来 CAD 候选注入预留
