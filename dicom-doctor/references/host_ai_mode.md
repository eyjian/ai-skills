# 宿主 AI 分批处理模式（v2.7.0+）

> 本文件包含宿主 AI 分批处理模式的详细说明。主文档见 `SKILL.md`。

当没有 OpenAI API Key 时，dicom-doctor 自动切换到【宿主 AI 分批处理模式】：

## 自动切换条件

以下任一条件触发宿主 AI 模式：
1. 未提供 `--auto-review-api-key` 且环境变量 `OPENAI_API_KEY` 未设置
2. 显式指定 `--host-ai-review` 参数

## 工作流程

```
DICOM 转换完成 → 生成批次模板 → 检测无 API Key
                                    ↓
                        自动切换到宿主 AI 模式
                                    ↓
                        逐批输出阅片请求给宿主 AI
                                    ↓
                        宿主 AI 读取图片 → 分析 → 返回 JSON
                                    ↓
                        自动保存批次结果 → 合并到总表
                                    ↓
                        重复直到全部完成 → 生成 PDF 报告
```

## 宿主 AI 模式特点

| 特性 | 说明 |
|------|------|
| **无需 API Key** | 完全离线运行，不依赖外部服务 |
| **断点续跑** | 每批完成后自动保存，中断后可从断点继续 |
| **分批处理** | 每批 15 张（可配置），避免上下文溢出 |
| **自动合并** | 每批完成后自动调用 `apply_review_batch.py` 合并结果 |
| **进度可见** | 可随时查看已完成/待处理批次 |

## 使用示例

```bash
# 方式 1：main.py 自动检测（推荐）
# 若未设置 OPENAI_API_KEY，自动切换到宿主 AI 模式
python3 scripts/main.py --input /path/to/chest.zip --output /path/to/output --auto-review-model gpt-4o

# 方式 2：显式启用宿主 AI 模式
python3 scripts/main.py --input /path/to/chest.zip --output /path/to/output --host-ai-review

# 方式 3：查看进度
python3 scripts/host_ai_review.py \
  --manifest /path/to/output/<时间戳>/review_manifest.json \
  --output /path/to/output/<时间戳> \
  --status

# 方式 4：继续处理（从断点续跑）
python3 scripts/host_ai_review.py \
  --manifest /path/to/output/<时间戳>/review_manifest.json \
  --output /path/to/output/<时间戳>
```

## 宿主 AI 模式输出结构

```
<output_dir>/<时间戳>/
├── png/
│   ├── lung/           # 肺窗
│   ├── mediastinum/    # 纵隔窗
│   └── ggo/            # GGO 窗
├── review_manifest.json
├── review_batch_templates/     # 原始批次模板
├── review_batch_filled/        # 宿主 AI 回填后的批次结果
│   ├── batch_001.filled.json
│   ├── batch_002.filled.json
│   └── ...
├── review_results.json         # 合并后的总表（自动更新）
└── dicom_report_<时间戳>.pdf   # 最终 PDF 报告
```

## 注意事项

1. **上下文管理**：宿主 AI 每批处理 15 张图片，避免单次会话上下文溢出
2. **断点续跑**：如果会话中断，重新运行相同命令会自动从下一个未完成批次继续
3. **结果校验**：每批完成后自动校验并合并，确保数据完整性
4. **最终报告**：全部批次完成后，运行 `generate_report.py` 生成 PDF 报告
5. **🚨 模型能力检测可能不准确**：`model_capability_detector.py` 通过模型名称推断宿主 AI 是否支持视觉。v2.10.0 已移除不可靠的环境变量推断（如 `GLM_API_KEY` 残留导致误判为 GLM），并新增「先试后判」机制。**如果检测结果与实际不符（例如检测说"不支持视觉"但你实际上可以读取图片），请忽略检测结果，直接按 SKILL.md 流程逐批阅片。** 检测误判不是停止阅片的理由——先尝试读取测试图片，确实不行再降级。
6. **宿主 AI 必须传入 `--model-name`**：执行第 1 步时，宿主 AI 应将自身模型名称通过 `--model-name` 参数传入（如 `--model-name kimi-k2.5`），这能避免环境变量残留导致的误判。
