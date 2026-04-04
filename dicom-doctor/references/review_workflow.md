# 全量阅片详细流程

## 分批持久化机制（强制使用，不可跳过）

`run.py` 执行完成后，已在输出目录自动生成以下文件：
- `review_batch_templates/batch_001.json` ~ `batch_NNN.json`：按每批 15 张预拆好的阅片模板，每个 item 含完整 prompt + 多窗位图片路径
- `review_manifest.json`：总清单
- `review_results_stub.json`：占位总表（全部初始化为"待检视"）

**宿主 AI 必须基于这些批次模板进行全量阅片，每完成一批立即持久化到磁盘。** 这确保：
1. **断点续跑**：即使上下文耗尽或会话中断，已完成的批次不会丢失，下次会话可从断点继续
2. **全量可验证**：`apply_review_batch.py` 会校验每批结果与 manifest 的一致性，杜绝遗漏
3. **跨模型通用**：任何模型都使用相同的持久化流程，不依赖单次会话的上下文容量

## 阅片流程（逐批循环，持久化驱动）

1. **读取批次模板**：从 `review_batch_templates/` 目录加载当前批次的 `batch_XXX.json`
2. **逐张检视该批次的全部图片**：
   a. 读取该 item 的多窗位图片（按优先级：narrow_ggo → ggo → lung → mediastinum）
   b. 根据 item 中的 prompt 完成阅片分析
   c. 将分析结论填入该 item 的 `result` 字段（JSON 格式，含 conclusion/abnormality_desc/confidence/details/location 等）
3. **持久化该批次**：将回填好的批次 JSON 保存到 `review_batch_filled/batch_XXX.filled.json`
4. **合并到总表**：运行 `apply_review_batch.py` 将该批结果并入 `review_results.json`
   ```bash
   python3 <skill_path>/scripts/apply_review_batch.py \
     --manifest <输出目录>/<时间戳>/review_manifest.json \
     --results <输出目录>/<时间戳>/review_results.json \
     --batch-json <输出目录>/<时间戳>/review_batch_filled/batch_XXX.filled.json
   ```
   > 首次合并时，`--results` 传 `review_results_stub.json`（占位总表）；后续传已生成的 `review_results.json`
5. **报告进度**："已完成第 M/N 批，累计检视 X/Y 张，已持久化到磁盘"
6. **循环回到步骤 1**，直到全部批次完成

## 会话中断时的续跑机制

如果上下文即将耗尽或会话因任何原因中断：
- **已完成的批次**已持久化在 `review_batch_filled/` 目录和 `review_results.json` 中，**不会丢失**
- **下次会话**加载 skill 后，宿主 AI 应：
  1. 检查 `review_batch_filled/` 中已有哪些 `.filled.json`
  2. 对比 `review_batch_templates/` 中的总批次数，确定剩余未完成的批次
  3. 从第一个未完成的批次继续，重复上述流程
- **禁止从头重跑已完成的批次**，除非用户明确要求

## 阅片红线（违反即严重医疗失误，任务判定失败）

- ❌ **严禁抽样**：禁止只看几张代表性切片
- ❌ **严禁拼图**：禁止将多张切片缩小拼接成一张（Collage）
- ❌ **严禁跳层**：禁止以"层面正常""已到达腹部区域"等理由跳过剩余层面
- ❌ 禁止中途停下来问"需要我继续检视剩余图片吗？"
- ❌ **严禁方案选择式暂停**：禁止在阅片过程中向用户提供"方案A/方案B"或"两个选项"让用户决策。遇到任何技术问题（窗位质量差、数据量大、图片过曝等），AI 必须自行按降级策略处理并继续，不得暂停
- ❌ **严禁以数据量为由降级**：无论切片数量是 100 还是 1000+、窗位组合产生多少张图片，都必须按流程全量跑完。担心"会话太长""token 不够"不是停下来的理由——**已有分批持久化机制保障断点续跑**
- ❌ **严禁模板填充**：禁止不读取图片就批量生成阅片结论。每张切片的 conclusion 必须基于实际读取并检视该图片后得出，禁止按解剖位置套模板、禁止用 Python 脚本批量填充正常结论
- ❌ **严禁绕过持久化机制**：禁止跳过 `batch_templates` 和 `apply_review_batch.py`，自行构建 `review_results.json`。必须使用 skill 提供的分批持久化工具链
- ✅ 必须使用 `review_batch_templates/` 中的批次模板逐批推进
- ✅ 每完成一批必须调用 `apply_review_batch.py` 持久化到磁盘
- ✅ 每张图片都要实际读取并输出明确结论（正常/异常/无法识别）
- ✅ 遇到窗位质量问题时，自行降级处理并在报告中注明
- ✅ 会话中断后，从断点续跑而非从头开始

## 上下文优化说明（v2.4.7）

`main.py` 的 `review_manifest.json` 中，每层的 prompt 和 CAD hint 已自动优化：
- **📌重点层**（CAD 候选 ±5 层范围）：使用完整版 prompt + 仅本层附近的 CAD 候选提示
- **⚡快扫层**（远离 CAD 候选）：使用精简版 prompt（约 600 字 vs 完整版 5000 字）
- 这使得 prompt 总 token 消耗降低约 50-70%，大幅缓解上下文窗口耗尽问题
- **宿主 AI 仍需逐张检视全部图片**，快扫层只是 prompt 更简洁，检视精度要求不变

## 阅片结果 JSON 格式

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

## 为什么不能抽样

一个 3mm 肺结节在 800 层 CT（1mm 层距）中仅出现在约 3 层上。如果每隔 40 层看一张（共 20 张），漏诊概率超过 **96%**。这不是效率问题，是患者安全问题。

> **绝对禁令**：无论出于何种原因（Token 限制、时间限制、上下文窗口限制），都**不得以抽样代替全量阅片**。如果模型能力不足以一次完成，则必须分多个会话完成，而不是降级为抽样。

## 高效全量阅片策略

1. **分批执行**：每批 15-20 张原始分辨率切片
2. **三窗联合**：GGO窗（优先）→ 肺窗 → 纵隔窗
3. **双侧强制扫查**：每张图片检查左右两侧
4. **反保守偏见**（见铁律第 10 条）：≥2mm 的圆形高密度影优先报告为疑似结节，禁止轻易归为"血管断面"。可疑/不确定的发现**必须标"异常"**（见铁律第 9 条）
5. **扫及区域不遗漏**：甲状腺、肝脏上段、肾上腺

## 宿主 AI 阅片产物要求

阅片完成后，宿主 AI 应在输出目录中生成：
- 结构化的阅片发现 Markdown 文件（汇总所有异常）
- 关键异常影像截图展示
- 所有产物必须在 `<output_dir>/<时间戳>/` 目录内，禁止散落到工作区根目录
