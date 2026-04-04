---
name: dicom-doctor
description: "Use this skill whenever the user mentions DICOM files, medical imaging, CT scans, MRI scans, or anything related to medical image conversion or chest CT analysis. This includes: converting any DICOM files (CT, MRI, PET, etc.) to PNG images, analyzing chest CT for lung nodules/masses/calcifications, generating PDF radiology review reports for chest CT, or any mention of 医学影像, 阅片, DICOM, 胸部CT, CT扫描, MRI, 核磁, 核磁共振, 肺结节, 影像报告, dcm文件, DICOM转PNG, 影像转换. Even if the user just says 'convert this DICOM to PNG' or 'look at this chest CT' or mentions a .dcm file path, activate this skill. Also trigger for requests about Lung-RADS classification, MIP reconstruction, super-resolution enhancement, or window settings (lung/mediastinum/GGO). Note: AI-assisted review (阅片) currently only supports chest CT; DICOM-to-PNG conversion supports all modalities including MRI, abdominal CT, brain MRI, etc."
---

# DICOM Doctor — AI 辅助医学影像阅片 Skill

**当前版本：v2.11.2**

## 🚨 铁律摘要（违反任何一条即为严重失败）

> 以下为铁律的核心要点。**完整的铁律详细说明见 `references/iron_rules.md`，宿主 AI 必须在首次阅片前阅读。**

1. **逐层确认式全量阅片，零遗漏**：逐张检视全部 PNG 切片，每层输出明确结论，严禁抽样/跳过/拼图。必须使用分批持久化机制（`review_batch_templates/` + `apply_review_batch.py`）。
2. **PNG 必须保存到 png/ 子目录**：验证 `<output_dir>/<时间戳>/png/` 存在且包含文件。
3. **必须生成 PDF 报告**：对标 `references/AI_chest_CT_report_template.pdf` 模板，无 PDF = 任务失败。
4. **立即执行，不得确认或中途停止**：收到指令直接干活，禁止任何形式的确认/暂停/方案选择。唯一例外：输入路径不存在。
5. **GGO 窗优先**：检视顺序 narrow_ggo → ggo → lung → mediastinum。narrow_ggo 过曝时自动降级到 ggo。
6. **双侧扫查**：每张图片同时检查左右肺。
7. **CAD 候选必须验证，结论三选一**：确认结节(异常) / 可疑不确定(异常) / 明确排除(正常)。CAD score≥0.8 默认标异常。
8. **报告两维度数据缺一不可**：结节聚合汇总 + 逐层异常明细，都必须完整输出。
9. **可疑发现必须标"异常"**：描述中出现"可疑/疑似/不确定"等措辞，conclusion 必须填"异常"。
10. **反保守偏见**：≥2mm 圆形高密度影优先报告为疑似结节，禁止轻易归为"血管断面"。
11. **禁止因能力检测结果放弃阅片**：v2.10.0「先试后判」——直接尝试读取图片，确实不行再降级。

DICOM Doctor 是一个 AI 辅助医学影像处理 skill，提供两项核心能力：

- **DICOM 转 PNG**：支持所有影像类型（胸部CT、腹部CT、头颅MRI、腹部MRI、核磁等），自动选择合适的窗位策略
- **AI 辅助阅片**：**当前版本仅支持胸部CT**，逐张检视全部切片并生成 PDF 检查报告

工作流程：接收 DICOM 文件或 ZIP 压缩包 → 自动识别影像类型 → 转换为 PNG → （胸部CT）AI 逐张检视全部影像 → 生成 PDF 检查报告

### DICOM 转 PNG 支持的影像类型

| 影像类型 | 自动识别 | 窗位策略 | MIP | GGO窗 |
|----------|---------|---------|-----|-------|
| **胸部CT** | ✅ Modality=CT + BodyPart=CHEST | 肺窗/纵隔窗/GGO窗/骨窗 | ✅ | ✅ |
| **腹部CT** | ✅ Modality=CT + BodyPart=ABDOMEN | 软组织窗/肝脏窗/骨窗 | ❌ | ❌ |
| **头颅MRI** | ✅ Modality=MR + BodyPart=HEAD/BRAIN | T1/T2/FLAIR/DWI 自适应 | ❌ | ❌ |
| **腹部MRI** | ✅ Modality=MR + BodyPart=ABDOMEN | T1/T2/DWI 自适应 | ❌ | ❌ |
| **通用** | 🔄 兜底 | 自动推断 | ❌ | ❌ |

### AI 阅片支持的影像类型

| 影像类型 | 检测重点 | 分级系统 | 状态 |
|----------|---------|---------|------|
| **胸部CT** | 肺结节/肿块/钙化 | Lung-RADS | ✅ 已支持 |
| 腹部CT | 肝胆胰脾肾占位 | LI-RADS | 🔜 后续版本 |
| 头颅MRI | 脑实质异常信号/占位/白质病变 | Fazekas | 🔜 后续版本 |
| 腹部MRI | 肝脏信号异常/胆道/T1T2DWI对比 | LI-RADS | 🔜 后续版本 |

> **前置条件**：AI 阅片要求多模态视觉模型。非视觉模型将自动跳过阅片步骤，但 DICOM 转 PNG 功能不受影响。

## ⚡ 强制执行流程（宿主 AI 必须按此步骤执行）

**收到用户指令后，立即从第 1 步开始执行，一口气执行到第 7 步。绝对禁止在执行前插入任何确认步骤。**

> **🖥️ 跨平台自动适配**：v2.3.0 起 `run.py` 已集成完整的环境自检能力。**宿主 AI 只需要一条 `python run.py` 命令，macOS / Linux / Windows 通用。**

### 第 0 步：确保 Python 可用（仅在需要时执行）

> 检测 `python --version` 或 `python3 --version`，>= 3.8 则跳过。不可用时参见 `references/python_setup.md` 自动安装。

### 第 0.5 步：确认模型身份（任务开始时自动执行）

> **v2.10.0 新增**：宿主 AI 必须先确认自己的实际模型名称，并通过 `--model-name` 参数传入，避免环境变量误判。

```bash
python <skill_path>/scripts/run.py --input <DICOM路径> --workspace <工作区> --model-name <当前模型名称> --strict-review
```

### 第 1 步：运行 run.py（自动创建输出目录并启动 main.py）

```
python <skill_path>/scripts/run.py --input <用户提供的DICOM路径> --workspace <用户工作区> --model-name <当前模型名称> --strict-review
```

> `run.py` 会自动在 `<workspace>` 下创建 `dicom_output_<时间戳>/` 输出目录，并将参数透传给 `main.py`。交付/正式阅片场景必须启用 `--strict-review`。可选直连外部视觉模型：追加 `--auto-review-model --auto-review-api-base --auto-review-api-key`。

### 第 2 步：验证 PNG 输出

列出 `<输出目录>/<时间戳>/png/` 下的子目录和文件数量。胸部CT应有 `lung/`、`mediastinum/`、`ggo/`、`narrow_ggo/` 四个子目录。PNG 文件数为 0 说明转换失败。

### 第 3 步：全量阅片（核心步骤，耗时最长）

**必须逐层确认式全量阅片——逐张检视全部 PNG 图片，一张不落。**

> 📖 **详细的分批持久化机制、阅片流程、续跑机制、阅片红线和 JSON 格式，参见 `references/review_workflow.md`**
> 📖 **三阶段阅片策略和禁止行为清单，参见 `references/review_strategy.md`**

**核心流程简述**：
1. 读取 `review_batch_templates/batch_XXX.json` 批次模板
2. 逐张检视该批次全部图片（narrow_ggo → ggo → lung → mediastinum）
3. 持久化到 `review_batch_filled/batch_XXX.filled.json`
4. 运行 `apply_review_batch.py` 合并到 `review_results.json`
5. 报告进度，循环直到全部批次完成

### 第 4 步：汇总全部阅片发现

全部切片检视完毕后：
- 统计正常/异常/无法识别的层面数
- 对重复出现的结节进行**跨层面去重合并**
- 为每个结节/病灶给出分级：Lung-RADS（胸部CT）/ LI-RADS（腹部CT/MRI）/ Fazekas（头颅MRI白质病变）

**🚨 报告必须同时包含两个维度（缺一不可）：**

1. **结节维度（聚合汇总）**：位置、类型、大小、出现层面范围、层面数、分级、置信度
2. **层面维度（逐层明细）**：层面序号、位置描述、异常描述、大小、分级

### 第 5 步：确认阅片结果完整性

检查 `review_results.json` 中是否还有 `conclusion` 为"无法识别"或空的条目。如有，返回第 3 步继续。

> **文件说明**（由 `run.py` / `main.py` 自动生成）：
> - `review_manifest.json`：结构化请求清单
> - `review_results_stub.json`：占位总表（初始状态）
> - `review_batch_templates/`：按批拆好的回填模板
> - `review_batch_filled/`：已回填的批次结果目录
> - `review_results.json`：最终总表

### 第 6 步：生成 PDF 报告

```bash
python3 <skill_path>/scripts/generate_report.py \
  --results "$REVIEW_RESULTS_JSON" \
  --manifest "$OUTPUT_DIR/<时间戳>/review_manifest.json" \
  --output "$OUTPUT_DIR/<时间戳>" \
  --input-path <原始DICOM路径> \
  --imaging-type chest_ct \
  --model-name <当前模型名称>
```

验证报告已生成：`find "$OUTPUT_DIR" -name "*.pdf" -type f`。**无 PDF = 任务失败。**

### 第 7 步：向用户呈现结果

1. 输出目录路径
2. PNG 文件总数和目录结构
3. **全量阅片完成确认**："共 N 张切片，已全部逐张检视完毕"
4. 每个异常结节的详细信息
5. **PDF 报告路径**
6. 关键异常的影像截图

**完成后询问用户**：是否需要对某个异常进行重点复核或详细说明。

## 输入参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --input | string | 是 | - | DICOM 文件路径或 ZIP 压缩包路径 |
| --output / --workspace | string | 否 | 输入文件同级目录 | 输出目录 |
| --enhance | boolean | 否 | false | 启用 Real-ESRGAN 超分辨率增强 |
| --enhance-scale | integer | 否 | 2 | 超分增强放大倍数（2 或 4） |
| --window | string | 否 | lung | 窗口类型：`lung`/`mediastinum`/`bone`/`soft_tissue`/`ggo`/`all` |
| --mip | boolean | 否 | false | 启用 MIP 重建 |
| --mip-slabs | integer | 否 | 5 | MIP slab 厚度（层数），范围 2-20 |
| --imaging-type | string | 否 | 自动检测 | `chest_ct`/`abdomen_ct`/`brain_mri`/`abdomen_mri`/`generic` |
| --model-name | string | 否 | 无 | 宿主 AI 模型名称，避免环境变量误判 |
| --strict-review | boolean | 否 | false | 启用后拒绝生成含"待检视"条目的报告 |
| --auto-review-model | string | 否 | 无 | 外部视觉模型名称（OpenAI 兼容接口） |
| --auto-review-api-base | string | 否 | `https://api.openai.com/v1` | 外部视觉模型接口基地址 |
| --auto-review-api-key | string | 否 | 环境变量 | 外部视觉模型 API Key |
| --host-ai-review | boolean | 否 | false | 强制启用宿主 AI 分批处理模式 |

## 输出

分目录模式（默认）下的输出结构：
```
<output_dir>/<时间戳>/
├── png/
│   ├── lung/           # 肺窗
│   ├── mediastinum/    # 纵隔窗
│   ├── ggo/            # GGO 专用窗（⚠️ 必须优先检视）
│   ├── narrow_ggo/     # 高灵敏度 GGO 窗
│   ├── bone/           # 骨窗（--window all）
│   ├── soft_tissue/    # 软组织窗（--window all）
│   └── mip/            # MIP（--mip）
├── review_manifest.json
├── review_batch_templates/
├── review_batch_filled/
├── review_results.json
├── dicom_report_<时间戳>.pdf
└── dicom_report_<时间戳>.md
```

## 脚本说明

### 常用命令示例

```bash
# 基本用法（推荐通过 run.py 启动）
python3 scripts/run.py --input /path/to/chest.zip --workspace /path/to/workspace --model-name claude-4.6-opus --strict-review

# 启用 MIP + 超分增强 + 全窗口
python3 scripts/main.py --input /path/to/chest.zip --output /path/to/output --mip --enhance --enhance-scale 4 --window all

# 外部视觉模型自动回填
python3 scripts/auto_review_batches.py --manifest /path/to/output/<时间戳>/review_manifest.json --model gpt-4.1 --api-base https://api.openai.com/v1 --api-key "$OPENAI_API_KEY"

# 批次结果合并
python3 scripts/apply_review_batch.py --manifest <manifest> --results <results> --batch-json <batch_filled>

# 独立生成报告
python3 scripts/generate_report.py --results <review_results.json> --manifest <manifest> --output <output_dir> --input-path <dicom_path> --imaging-type chest_ct --model-name <model>

# 宿主 AI 分批处理模式
python3 scripts/main.py --input /path/to/chest.zip --output /path/to/output --host-ai-review
```

### 脚本列表

| 脚本 | 说明 |
|------|------|
| `scripts/run.py` | **跨平台启动器（推荐入口）**：自动生成时间戳、创建输出目录、查找 Python 解释器 |
| `scripts/pip_utils.py` | pip 镜像感知安装模块，国内用户自动切换镜像 |
| `scripts/main.py` | 主入口，编排流水线（含影像类型识别） |
| `scripts/modality_detector.py` | 影像类型自动识别与 ImagingProfile 策略模型 |
| `scripts/converter.py` | DICOM → PNG 转换 |
| `scripts/enhancer.py` | Real-ESRGAN 超分辨率增强 |
| `scripts/reviewer.py` | AI 阅片检视（Prompt 模板 + 分级系统 + 批次接力包） |
| `scripts/report_generator.py` | PDF 报告生成 |
| `scripts/auto_review_batches.py` | 外部视觉模型自动回填工具（Harness 增强） |
| `scripts/review_harness.py` | Review Harness 阅片评估框架（单条级别，含重试+截断检测） |
| `scripts/apply_review_batch.py` | 批次结果合并工具 |
| `scripts/generate_report.py` | 独立报告生成入口 |
| `scripts/full_auto_review.py` | 宿主 AI 全自动化阅片 |
| `scripts/host_ai_review.py` | 宿主 AI 分批处理模式（「先试后判」视觉探测） |
| `scripts/model_capability_detector.py` | 模型能力检测模块 |
| `scripts/cad_detector.py` | CAD 自动预检（7维评分排序） |
| `scripts/prompt_templates/` | 各影像类型的 Prompt 模板目录 |

## 宿主 AI 分批处理模式（v2.7.0+）

当没有 OpenAI API Key 时，自动切换到宿主 AI 分批处理模式。触发条件：未设置 `OPENAI_API_KEY` 或显式指定 `--host-ai-review`。

> 📖 详细的工作流程、使用示例、输出结构和注意事项，参见 `references/host_ai_mode.md`

**关键提醒**：模型能力检测可能不准确，v2.10.0 新增「先试后判」机制。宿主 AI 必须传入 `--model-name` 参数。

## 内置资源

| 资源 | 说明 |
|------|------|
| `assets/fonts/NotoSansSC-Regular.ttf` | Google Noto Sans SC 中文字体（SIL OFL），PDF 中文渲染 |
| `references/AI_chest_CT_report_template.pdf` | 胸部 CT 报告模板参考 |
| `references/iron_rules.md` | **铁律详细说明**（11 条铁律的完整规则和示例） |
| `references/review_workflow.md` | **全量阅片详细流程**（分批持久化、续跑机制、阅片红线、JSON 格式） |
| `references/review_strategy.md` | 三阶段阅片策略指南 |
| `references/host_ai_mode.md` | 宿主 AI 分批处理模式详细说明 |
| `references/python_setup.md` | Python 环境安装指南（各平台） |
| `references/changelog.md` | 完整版本历史 |

## 自修复能力

| 场景 | 自修复行为 |
|------|-----------| 
| Python 依赖缺失 | 自动 pip 安装 |
| DICOM 转换后端不可用 | 自动安装 SimpleITK 或 dicom2jpg |
| Real-ESRGAN 不可用 | 自动安装，失败则降级使用原始图片 |
| reportlab 不可用 | 自动安装，失败则降级输出纯文本报告 |
| 输入路径不存在 | 搜索同目录下相似文件并提示 |

## 环境要求

- Python 3.8+
- DICOM 转换后端（至少一种）：DCMTK（推荐）/ SimpleITK / dicom2jpg
- Real-ESRGAN（可选，超分增强）

```bash
pip install -r requirements.txt
```

## JSON Schema 统一字段（v2.4.0+）

| 字段 | 说明 |
|------|------|
| `classification_system` | 分级系统名称（Lung-RADS / LI-RADS / Fazekas 等） |
| `classification_value` | 分级值（如 "2类"、"LR-3"、"2级"） |
| `bounding_boxes` | 异常区域归一化坐标 `[{x, y, width, height}]` |
| `lung_rads` | Lung-RADS 分类值（胸部CT专用，向后兼容） |

## Changelog

> 📖 完整版本历史见 `references/changelog.md`

**最近版本摘要：**
- **v2.11.2** — Skill 结构规范化（SKILL.md 瘦身、fonts→assets/fonts、evals expectations→assertions）
- **v2.11.1** — Lung-RADS v1.1 完整分级校验（修复结节分级错误）
- **v2.11.0** — Review Harness 阅片评估框架 + `auto_review_batches.py` Harness 增强
- **v2.10.0** — 「先试后判」视觉探测 + 移除环境变量误判 + 模型身份确认
- **v2.9.0** — 模型能力检测乐观策略优化
- **v2.8.0** — 模型能力自动检测 + 智能分流
- **v2.7.0** — 宿主 AI 分批处理模式
- **v2.6.0** — 宿主 AI 全自动化全量阅片
- **v2.5.0** — CAD v2.8 假阳性深度优化

## ⚠️ 免责声明

本 skill 生成的报告由 AI 辅助生成，**仅供参考，不构成医学诊断**。如有疑问，请及时咨询专业医生。
