---
name: dicom-doctor
description: "Use this skill whenever the user mentions DICOM files, medical imaging, radiology, CT scans, MRI scans, or anything related to medical image analysis. This includes: analyzing .dcm files or DICOM ZIP archives, detecting nodules/masses/calcifications/tumors in CT or MRI images, converting DICOM to PNG with different window settings (lung/mediastinum/bone/GGO), generating PDF radiology review reports, checking for lung nodules or brain abnormalities, or any mention of 医学影像, 阅片, DICOM, CT扫描, MRI, 肺结节, 影像报告, dcm文件. Even if the user just says 'look at this scan' or 'check this medical image' or mentions a .dcm file path, activate this skill. Also trigger for requests about Lung-RADS classification, LI-RADS grading, MIP reconstruction, or super-resolution enhancement of medical images."
---

# DICOM Doctor — AI 辅助医学影像阅片 Skill

**当前版本：v1.9.0**

## 🚨 铁律（违反任何一条即为严重失败）

> 以下规则对阅片质量和患者安全至关重要。宿主 AI 必须逐条遵守，不得以任何理由违反。

1. **逐层确认式全量阅片，零遗漏**：必须逐张检视**全部** PNG 切片，**每一层都必须输出明确结论**（正常/异常/无法识别），不得以任何方式跳过或简化。3mm 结节仅出现在约 3 层中，跳过即漏诊。**严格禁止**：抽样、跳过、拼图（Collage）、以任何理由降级为部分阅片。
2. **PNG 必须保存到 png/ 子目录**：运行 `main.py` 后，PNG 文件输出在 `<output_dir>/<时间戳>/png/` 下。必须验证该目录存在且包含文件。
3. **必须生成 PDF 报告（对标模板，不得省略）**：最终**必须**在输出目录中生成 `.pdf` 格式的医院风格影像检查报告。报告格式**必须严格对标** `references/AI_chest_CT_report_template.pdf` 模板，包含：检查信息表、AI 检视统计、检查所见（逐条异常发现）、异常影像详情（嵌入图片+描述+分级）、诊断意见、随访建议、分级参考表、免责声明。**如果最终输出目录中不存在 .pdf 文件，则本次任务判定为失败。**
4. **立即执行，不得确认或中途停止**：收到用户指令后，**直接开始执行第 1 步（运行 main.py）**，禁止在开始前插入任何形式的确认环节。以下行为**全部禁止**：
   - "请确认以下信息""我先确认一下""没问题的话我就开始"
   - **"先补个最小确认""快速确认一下"**——这也是确认，同样禁止
   - 列出用户信息/环境信息后问"这些信息都对吗？"
   - 复述用户的输入路径、姓名、系统环境后请求用户确认
   - 中途暂停询问"是否继续""需要我继续吗"
   
   **唯一例外**：输入文件路径确实不存在（文件系统报错），才可以询问用户。其他一切情况，直接开始干活。
5. **GGO 窗优先**：胸部 CT 阅片时，每批切片必须先独立检视**高灵敏度 GGO 窗**（`narrow_ggo/` 子目录），再检视 GGO 窗（`ggo/` 子目录），然后检视肺窗和纵隔窗。极淡的纯磨玻璃结节可能**只有在高灵敏度 GGO 窗**下才能看到。
6. **双侧扫查**：每张图片都要同时检查左肺和右肺。只在单侧发现异常时，必须回头复查对侧。
7. **CAD 预检候选必须验证**：如果 `main.py` 输出了 CAD 自动预检结果（`cad_candidates.json` 和 `cad_annotations/` 标注图），阅片时**必须逐一验证这些候选区域**，确认每个候选是真结节还是血管。v1.9.0 起 CAD 使用基于5个真实结节校准的评分排序（⭐>0.9 高度可疑，0.8-0.9 中度可疑），6维评分含球形度、elongation、大小、HU、z层数、密度一致性。厚层CT(≥1mm)额外启用 binary_closing + 密度峰值提取，提升微小结节检出率。高分候选必须优先验证。CAD 同时输出全切面图和四窗位合成图，方便对照判断。

## 概述

DICOM Doctor 是一个 AI 辅助医学影像阅片 skill。接收 DICOM 文件或 ZIP 压缩包 → 自动识别影像类型 → 转换为 PNG → AI 逐张检视全部影像 → 生成 PDF 检查报告。

### 支持的影像类型

| 影像类型 | 自动识别 | 检测重点 | 分级系统 | MIP | GGO窗 |
|----------|---------|---------|---------|-----|-------|
| **胸部CT** | ✅ Modality=CT + BodyPart=CHEST | 肺结节/肿块/钙化 | Lung-RADS | ✅ | ✅ |
| **腹部CT** | ✅ Modality=CT + BodyPart=ABDOMEN | 肝胆胰脾肾占位 | LI-RADS | ❌ | ❌ |
| **头颅MRI** | ✅ Modality=MR + BodyPart=HEAD/BRAIN | 脑实质异常信号/占位/脑室扩大 | — | ❌ | ❌ |
| **腹部MRI** | ✅ Modality=MR + BodyPart=ABDOMEN | 肝脏信号异常/胆道/T1T2DWI对比 | LI-RADS | ❌ | ❌ |
| **通用** | 🔄 兜底 | AI 自行判断并分析 | — | ❌ | ❌ |

> **前置条件**：AI 阅片要求多模态视觉模型。非视觉模型将自动跳过阅片步骤。

## ⚡ 强制执行流程（宿主 AI 必须按此步骤执行）

**收到用户指令后，立即从第 1 步开始执行，一口气执行到第 7 步。**

**🚫 绝对禁止在执行前插入任何确认步骤**，包括但不限于：
- 确认用户信息（姓名、称呼、习惯）
- 确认环境参数（操作系统、Shell、工作目录）
- 确认输入路径或输出路径
- **"先补个最小确认"——这本身就是确认，同样禁止**
- 列出信息后问"这些都对吗？"

用户提供的信息已经足够，直接运行 `main.py` 开始工作。不要说废话，不要确认，不要复述，直接干。

### 第 1 步：创建输出目录并运行 main.py

```bash
# 1. 获取当前时间戳
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
# 2. 创建输出目录
OUTPUT_DIR="<用户工作区>/dicom_output_${TIMESTAMP}"
mkdir -p "$OUTPUT_DIR"
# 3. 运行 main.py（必须传入 --output 参数！）
python3 <skill_path>/scripts/main.py \
  --input <用户提供的DICOM路径> \
  --output "$OUTPUT_DIR" \
  --model-name <当前模型名称> \
  --strict-review
```

> **交付/正式阅片场景必须启用 `--strict-review`**：这样当逐张阅片结果仍有“待检视/无法识别”时，流程会直接拦截，不会误生成正式报告。
>
> **v1.3.0 起可选直连外部视觉模型自动回填**：若你手头有 OpenAI 兼容多模态接口，可在 `main.py` 追加 `--auto-review-model --auto-review-api-base --auto-review-api-key(或环境变量)`，让批次模板自动逐批回填并直接合并出 `review_results.json`。

### 第 2 步：验证 PNG 输出

运行完成后，**必须检查** PNG 文件已正确输出：

```bash
# 验证 png 目录结构
ls -la "$OUTPUT_DIR"/*/png/
# 胸部CT应有 lung/, mediastinum/, ggo/, narrow_ggo/ 四个子目录
ls "$OUTPUT_DIR"/*/png/lung/ | head -5
ls "$OUTPUT_DIR"/*/png/ggo/ | head -5
ls "$OUTPUT_DIR"/*/png/narrow_ggo/ | head -5
ls "$OUTPUT_DIR"/*/png/mediastinum/ | head -5
# 确认文件数量
find "$OUTPUT_DIR"/*/png/ -name "*.png" | wc -l
```

如果 PNG 文件数为 0，说明转换失败，需要排查日志。**不得跳过此验证直接进入阅片。**

### 第 3 步：全量阅片（核心步骤，耗时最长）

**这是最关键的步骤。必须逐层确认式全量阅片——逐张检视全部 PNG 图片，一张不落，每张都必须输出明确结论。**

阅片流程：
1. 列出所有需要检视的 PNG 文件（按 lung/ 子目录中的文件列表）
2. 计算总数 N，按每批 15-20 张分批。**必须在开始时公布总数 N 和预计批次数**
3. 对每个批次：
   a. **首先**独立检视该批次的高灵敏度 GGO 窗图片（`narrow_ggo/` 子目录中同名文件）——检测极淡的纯磨玻璃结节
   b. **然后**独立检视该批次的 GGO 窗图片（`ggo/` 子目录中同名文件）——寻找磨玻璃结节
   c. **再**检视肺窗图片（`lung/` 子目录）——寻找实性结节、肿块
   d. **同时**参考纵隔窗图片（`mediastinum/` 子目录）——验证结节密度、检查淋巴结
   e. **为每张图片输出 JSON 格式的分析结论**（结论字段不能为空）
   f. 批次完成后**报告进度**："已完成第 M/N 批，累计检视 X/Y 张"
4. **必须循环直到最后一张图片都检视完毕**，然后进入汇总

**阅片红线（违反即严重医疗失误，任务判定失败）：**
- ❌ **严禁抽样**：禁止只看几张代表性切片
- ❌ **严禁拼图**：禁止将多张切片缩小拼接成一张（Collage）
- ❌ **严禁跳层**：禁止以"层面正常""已到达腹部区域"等理由跳过剩余层面
- ❌ 禁止中途停下来问"需要我继续检视剩余图片吗？"
- ✅ 必须每批 15-20 张，循环直到最后一张
- ✅ 每张图片都要输出明确结论（正常/异常/无法识别）

> 📖 详细的三阶段阅片策略和禁止行为清单，参见 `references/review_strategy.md`

### 第 4 步：汇总全部阅片发现

全部切片检视完毕后，汇总所有发现：
- 统计正常/异常/无法识别的层面数
- 对重复出现的结节进行跨层面去重合并
- 为每个确认的结节给出 Lung-RADS 分类（胸部CT）或 LI-RADS 分级（腹部）
- 检查扫及区域（甲状腺、肝脏上段、肾上腺）是否已覆盖

### 第 5 步：保存阅片结果到 JSON 文件

全量阅片完成后，将所有阅片结果保存为 JSON 文件，格式如下：

```bash
# 在输出目录的时间戳子目录下保存
REVIEW_RESULTS_JSON="$OUTPUT_DIR/<时间戳>/review_results.json"
```

> **v1.3.0 起闭环继续升级：** `main.py` 在未提供正式阅片结果时，会自动导出：
> - `review_requests.md`：逐张阅片请求与 prompt 汇总
> - `review_manifest.json`：结构化请求清单（后续会用于结果校验）
> - `review_results_stub.json`：待回填的占位结果 JSON
> - `review_batch_templates/batch_XXX.json`：按批拆好的回填模板
> - `review_batch_filled/`：使用外部视觉模型自动回填后生成的批次结果目录（按需生成）
>
> 推荐做法：
> 1. **自动模式**：直接运行 `main.py --auto-review-model ...`，或后续运行 `auto_review_batches.py`，让外部视觉模型逐批回填并自动合并出 `review_results.json`
> 2. **手工/半自动模式**：按批填写 `review_batch_templates/batch_XXX.json` 中每个 `item.result`
> 3. 每完成一批，运行 `apply_review_batch.py` 合并到总表 JSON
> 4. 全部批次完成后，再调用 `generate_report.py` 生成正式报告

JSON 格式（数组，每个元素对应一张切片的阅片结果）：
```json
[
  {
    "png_name": "IM-0001.png",
    "dicom_name": "IM-0001.dcm",
    "png_path": "/absolute/path/to/png/lung/IM-0001.png",
    "conclusion": "正常",
    "abnormality_desc": "",
    "confidence": "高",
    "details": "该层面显示双肺纹理清晰...",
    "location": "",
    "size_mm": "",
    "lung_rads": "",
    "recommendation": "",
    "slice_index": "1/100",
    "slice_location": "-120.5",
    "bounding_boxes": []
  },
  {
    "png_name": "IM-0050.png",
    "dicom_name": "IM-0050.dcm",
    "png_path": "/absolute/path/to/png/lung/IM-0050.png",
    "conclusion": "异常",
    "abnormality_desc": "右肺中叶内段(S5)可见约3mm×2mm实性结节",
    "confidence": "中",
    "details": "...",
    "location": "右肺中叶内段(S5) (第50层)",
    "size_mm": "3x2",
    "lung_rads": "2类",
    "recommendation": "建议12个月低剂量CT随访",
    "slice_index": "50/100",
    "slice_location": "-85.3",
    "bounding_boxes": [{"x": 0.35, "y": 0.42, "width": 0.05, "height": 0.04}]
  }
]
```

### 第 6 步：生成 PDF 报告

使用独立的报告生成脚本，从阅片结果 JSON 生成医院风格的 PDF 报告：

```bash
# 生成 PDF 和 Markdown 报告（默认正式模式，会校验 manifest 且拒绝待检视条目）
python3 <skill_path>/scripts/generate_report.py \
  --results "$REVIEW_RESULTS_JSON" \
  --manifest "$OUTPUT_DIR/<时间戳>/review_manifest.json" \
  --output "$OUTPUT_DIR/<时间戳>" \
  --input-path <原始DICOM路径> \
  --imaging-type chest_ct \
  --model-name <当前模型名称>
```

报告将参照 `references/AI_chest_CT_report_template.pdf` 的格式，包含：
- 检查信息表（检查类型、日期、影像数量、窗口类型等）
- AI 检视统计（总数、正常、异常、无法识别）
- 检查所见（逐条列出异常发现）
- 异常影像详情（嵌入照片 + 异常描述 + Lung-RADS 分类）
- 诊断意见 + 随访建议
- Lung-RADS 分类参考表
- 免责声明

验证报告已生成：
```bash
find "$OUTPUT_DIR" -name "*.pdf" -type f
find "$OUTPUT_DIR" -name "*.md" -type f
```

**⚠️ 如果 PDF 文件不存在或大小为 0，必须排查原因并重试，不得跳过。没有 PDF 报告 = 任务失败。**

> 💡 **备注**：`main.py` 运行时也会尝试生成 PDF 报告（阶段 4），但因为 AI 阅片结果需要宿主 AI 回填，
> 所以推荐使用 `generate_report.py` 在阅片完成后独立生成报告，确保报告内容完整。

### 第 7 步：向用户呈现结果

将以下信息返回给用户：
1. 输出目录路径
2. PNG 文件总数和目录结构
3. **全量阅片完成确认**：明确列出"共 N 张切片，已全部逐张检视完毕"，以及正常 X 张、异常 Y 张的统计
4. 每个异常结节的详细信息（位置、大小、分级）
5. **PDF 报告路径**（必须存在，否则任务失败）
6. 关键异常的影像截图（直接展示给用户查看）

## 输入参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| input_path / --input | string | 是 | - | DICOM 文件路径或 ZIP 压缩包路径 |
| --output-dir / --output | string | 否 | 输入文件同级目录 | PNG 图片和报告的输出目录 |
| --enhance | boolean | 否 | false | 启用 Real-ESRGAN 超分辨率增强 |
| --enhance-scale | integer | 否 | 2 | 超分增强放大倍数（2 或 4） |
| --window | string | 否 | lung | 窗口类型：`lung`/`mediastinum`/`bone`/`soft_tissue`/`ggo`/`all` |
| --separate-window-dirs | boolean | 否 | true | 不同窗口类型 PNG 是否分子目录存放 |
| --mip | boolean | 否 | false | 启用 MIP（最大密度投影）重建，提高微小肺结节检出率 |
| --mip-slabs | integer | 否 | 5 | MIP slab 厚度（层数），范围 2-20 |
| --imaging-type | string | 否 | 自动检测 | 手动指定影像类型：`chest_ct`/`abdomen_ct`/`brain_mri`/`abdomen_mri`/`generic` |
| --model-name | string | 否 | 无 | 阅片大模型名称，记录到 PDF 报告。宿主 AI 应自动传入自身模型名称 |
| --review-results-json | string | 否 | 无 | 已完成逐张阅片后的 `review_results.json` 路径；提供后将直接加载正式结果生成报告 |
| --strict-review | boolean | 否 | false | 启用后，若仍存在“无法识别/待检视”条目，则拒绝生成最终报告并退出 |
| --auto-review-model | string | 否 | 无 | 外部视觉模型名称；提供后会自动调用 OpenAI 兼容多模态接口逐批回填 `review_batch_templates` |
| --auto-review-api-base | string | 否 | `https://api.openai.com/v1` | 外部视觉模型的 OpenAI 兼容接口基地址 |
| --auto-review-api-key / --auto-review-api-key-env | string | 否 | 环境变量 `OPENAI_API_KEY` | 外部视觉模型 API Key，可显式传入或通过环境变量读取 |
| --auto-review-detail | string | 否 | `high` | 自动阅片时传给外部视觉模型的图片细节级别：`low` / `high` / `auto` |
| --auto-review-timeout | integer | 否 | 180 | 自动阅片单条请求超时秒数 |

## 输出

- **PNG 图片**：默认肺窗 + 自动输出纵隔窗和 GGO 窗。`--window all` 输出全部 5 种窗口
- **MIP 重建图像**（`--mip`）：存放在 `mip/` 子目录
- **PDF 报告**：医院风格 AI 辅助影像检查报告（含检查信息表、检查所见、异常影像展示、诊断意见、免责声明）
- **Markdown 报告**：与 PDF 同名同目录，方便版本控制

分目录模式（默认）下的输出结构：
```
<output_dir>/<时间戳>/
├── png/
│   ├── lung/           # 肺窗 — 检视实性结节、肺纹理
│   ├── mediastinum/    # 纵隔窗 — 验证结节密度、检查淋巴结
│   ├── ggo/            # GGO 专用窗 — ⚠️ 必须优先检视！磨玻璃结节可能仅此窗可见
│   ├── bone/           # 骨窗（--window all）
│   ├── soft_tissue/    # 软组织窗（--window all）
│   └── mip/            # MIP（--mip）
├── review_manifest.json
├── review_results_stub.json
├── review_batch_templates/
├── review_batch_filled/       # 使用 auto_review_batches.py 或 --auto-review-model 后生成
├── review_results.json        # 合并后的正式结果总表
├── dicom_report_<时间戳>.pdf   # 医院风格 PDF 报告
└── dicom_report_<时间戳>.md    # Markdown 报告
```

## 工作流程

```
输入（DICOM/ZIP）→ 影像类型识别 → 转换 PNG → [可选]超分增强 → [可选]MIP重建 → AI 全量阅片 → PDF+MD 报告
```

1. **DICOM 转 PNG**：自动检测后端（DCMTK → SimpleITK → dicom2jpg），CT 默认肺窗（WC=-600, WW=1500）+ 自动输出纵隔窗和 GGO 窗（WC=-500, WW=800）。低分辨率图像自动 Lanczos 放大到至少 1024×1024
2. **超分增强**（可选）：Real-ESRGAN 提升清晰度
3. **MIP 重建**（可选）：连续多层最大密度投影，提高 2-6mm 肺结节检出率
4. **AI 全量阅片**：逐批（15-20 张）检视全部切片，检视顺序 GGO窗→肺窗→纵隔窗，每张标注层面序号（如"第285/832层"）
5. **报告生成**：同时输出 PDF 和 Markdown 报告（格式参考 `references/AI_chest_CT_report_template.pdf`）

## 脚本说明

### 命令行调用

```bash
# 推荐写法（必须传入 --output 参数！）
python3 scripts/main.py --input <input_path> --output <output_dir> [options]

# 常用组合示例
python3 scripts/main.py --input /path/to/chest.zip --output /path/to/dicom_output_20260319_151835
python3 scripts/main.py --input /path/to/chest.zip --output /path/to/output --enhance --enhance-scale 4
python3 scripts/main.py --input /path/to/chest.zip --output /path/to/output --mip --window all
python3 scripts/main.py --input /path/to/abdomen.dcm --output /path/to/output --imaging-type abdomen_ct
python3 scripts/main.py --input /path/to/brain.zip --output /path/to/output --imaging-type brain_mri
# 严格模式 + 纯手工/宿主 AI 回填
python3 scripts/main.py --input /path/to/chest.zip --output /path/to/output --model-name claude-4.6-opus --strict-review
# 严格模式 + 外部视觉模型自动逐批回填（OpenAI 兼容接口）
python3 scripts/main.py --input /path/to/chest.zip --output /path/to/output --strict-review --auto-review-model gpt-4.1 --auto-review-api-base https://api.openai.com/v1 --auto-review-api-key "$OPENAI_API_KEY"
# 已有接力包时，单独调用外部视觉模型自动补跑全部批次
python3 scripts/auto_review_batches.py --manifest /path/to/output/<时间戳>/review_manifest.json --model gpt-4.1 --api-base https://api.openai.com/v1 --api-key "$OPENAI_API_KEY"
# 手工/半自动模式下：每完成一批 batch_XXX.json 回填，就把结果并入总表
python3 scripts/apply_review_batch.py --manifest /path/to/output/<时间戳>/review_manifest.json --results /path/to/output/<时间戳>/review_results_stub.json --batch-json /path/to/output/<时间戳>/review_batch_templates/batch_001.json --output /path/to/output/<时间戳>/review_results_working.json
# 全部批次回填完成后，生成正式报告
python3 scripts/generate_report.py --results /path/to/output/<时间戳>/review_results.json --manifest /path/to/output/<时间戳>/review_manifest.json --output /path/to/output/<时间戳> --input-path /path/to/chest.zip --imaging-type chest_ct --model-name claude-4.6-opus
# 如确实只想生成草稿报告（例如调试），可显式允许不完整结果
python3 scripts/generate_report.py --results /path/to/output/<时间戳>/review_results_stub.json --output /path/to/output/<时间戳>/draft --input-path /path/to/chest.zip --imaging-type chest_ct --model-name claude-4.6-opus --allow-incomplete
```

### 脚本列表

| 脚本 | 说明 |
|------|------|
| `scripts/main.py` | 主入口，编排流水线（含影像类型识别） |
| `scripts/modality_detector.py` | 影像类型自动识别与 ImagingProfile 策略模型 |
| `scripts/converter.py` | DICOM → PNG 转换（根据影像类型选择窗位策略） |
| `scripts/enhancer.py` | Real-ESRGAN 超分辨率增强 |
| `scripts/reviewer.py` | AI 阅片检视（根据影像类型选择 Prompt 模板和分级系统，并导出批次接力包） |
| `scripts/report_generator.py` | PDF 报告生成（根据影像类型动态生成报告格式） |
| `scripts/auto_review_batches.py` | **外部视觉模型自动回填工具**：逐批读取 `review_batch_templates/batch_XXX.json`，调用 OpenAI 兼容多模态接口并持续合并生成 `review_results.json` |
| `scripts/apply_review_batch.py` | **批次结果合并工具**：把 `review_batch_templates/batch_XXX.json` 中回填好的结果并入总表 |
| `scripts/generate_report.py` | **独立报告生成入口**：从阅片结果 JSON 生成 PDF（默认正式模式，会校验 manifest 并拒绝待检视条目） |
| `scripts/prompt_templates/` | 各影像类型的 Prompt 模板目录 |

## 全量阅片要点（宿主 AI 必读）

### 为什么不能抽样

一个 3mm 肺结节在 800 层 CT（1mm 层距）中仅出现在约 3 层上。如果每隔 40 层看一张（共 20 张），漏诊概率超过 **96%**。这不是效率问题，是患者安全问题。

> **绝对禁令**：无论出于何种原因（Token 限制、时间限制、上下文窗口限制），都**不得以抽样代替全量阅片**。如果模型能力不足以一次完成，则必须分多个会话完成，而不是降级为抽样。

### 高效全量阅片策略

1. **分批执行**：每批 15-20 张原始分辨率切片
2. **三窗联合**：GGO窗（优先）→ 肺窗 → 纵隔窗
3. **双侧强制扫查**：每张图片检查左右两侧
4. **反保守偏见**：≥2mm 的圆形高密度影优先报告为疑似结节，禁止轻易归为"血管断面"
5. **扫及区域不遗漏**：甲状腺、肝脏上段、肾上腺

### 宿主 AI 阅片产物要求

阅片完成后，宿主 AI 应在输出目录中生成：
- 结构化的阅片发现 Markdown 文件（汇总所有异常）
- 关键异常影像截图展示
- 所有产物必须在 `<output_dir>/<时间戳>/` 目录内，禁止散落到工作区根目录

## 内置资源

| 资源 | 说明 |
|------|------|
| `fonts/NotoSansSC-Regular.ttf` | Google Noto Sans SC 中文字体（SIL OFL），PDF 中文渲染 |
| `references/AI_chest_CT_report_template.pdf` | 胸部 CT 报告模板参考（**PDF 报告必须参照此格式**） |
| `references/review_strategy.md` | 详细的全量阅片策略指南（三阶段法） |

## 自修复能力

运行时自动处理环境问题，无需手动干预：

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

## ⚠️ 免责声明

本 skill 生成的报告由 AI 辅助生成，**仅供参考，不构成医学诊断**。如有疑问，请及时咨询专业医生。
