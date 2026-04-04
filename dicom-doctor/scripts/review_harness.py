#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM Doctor v2.11.0 — Review Harness（阅片评估框架）

借鉴 AI 评测领域的 Harness 理念，将阅片任务拆解为独立的、可验证的原子单元，
逐条执行并校验，从根本上解决大模型 early stopping（过早停止）问题。

核心设计：
  - 每张切片 = 1 个独立 task，单独调用模型 API
  - 每条结果经过 JSON schema 校验 + 截断检测 + 假完成检测
  - 单条失败自动重试（最多 3 次，指数退避）
  - 实时进度追踪 + 停滞检测
  - 与现有 batch_templates / review_results.json 完全兼容

典型用途：
  1. main.py 先导出 review_manifest.json / review_batch_templates/
  2. 本脚本逐条读取每张切片，独立调用外部视觉模型
  3. 每条完成后立即持久化，支持断点续跑
  4. 全部完成后合并到 review_results.json
  5. 可直接调用 generate_report.py 生成正式报告

与 auto_review_batches.py 的区别：
  - auto_review_batches.py 按批次处理，适合稳定的模型
  - review_harness.py 按单条处理，适合有 early stopping 倾向的模型
  - 两者输出格式完全兼容，可混合使用
"""

import argparse
import base64
import json
import logging
import mimetypes
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dicom-doctor.review-harness")


# ========================
# 常量定义
# ========================

# 单条最大重试次数
MAX_RETRIES = 3

# 重试基础等待秒数（指数退避：base * 2^attempt）
RETRY_BASE_SECONDS = 2.0

# 假完成检测关键词（模型提前总结的信号）
FAKE_COMPLETION_PATTERNS = [
    r"综上所述",
    r"以上是全部",
    r"总结如下",
    r"汇总报告",
    r"全部检视完成",
    r"所有切片.*分析完毕",
    r"in\s+summary",
    r"to\s+summarize",
    r"overall\s+conclusion",
]

# JSON 必需字段
REQUIRED_JSON_FIELDS = {"conclusion"}

# conclusion 合法值
VALID_CONCLUSIONS = {"正常", "异常", "无法识别"}

# 停滞检测：连续失败超过此数则告警
STALL_THRESHOLD = 5


# ========================
# 截断检测
# ========================

def detect_truncation(text: str) -> Tuple[bool, str]:
    """
    检测模型输出是否被截断。

    检测策略：
    1. JSON 括号不匹配（缺少闭合 } 或 ]）
    2. 文本在 JSON 中间突然结束
    3. 输出为空或极短

    Args:
        text: 模型原始输出文本

    Returns:
        (is_truncated, reason) — 是否截断及原因
    """
    if not text or not text.strip():
        return True, "模型输出为空"

    stripped = text.strip()

    # 极短输出（正常的 JSON 结果至少 50 字符）
    if len(stripped) < 30:
        return True, f"模型输出过短（{len(stripped)} 字符），疑似截断"

    # 检查 JSON 括号匹配
    brace_count = 0
    bracket_count = 0
    in_string = False
    escape_next = False

    for ch in stripped:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            brace_count += 1
        elif ch == '}':
            brace_count -= 1
        elif ch == '[':
            bracket_count += 1
        elif ch == ']':
            bracket_count -= 1

    if brace_count > 0:
        return True, f"JSON 大括号未闭合（缺少 {brace_count} 个 '}}' ）"
    if bracket_count > 0:
        return True, f"JSON 方括号未闭合（缺少 {bracket_count} 个 ']' ）"

    return False, ""


# ========================
# 假完成检测
# ========================

def detect_fake_completion(text: str) -> Tuple[bool, str]:
    """
    检测模型是否在单条阅片中输出了"假完成"信号。

    某些模型在处理单张切片时，会错误地输出全局总结性语句，
    表明它"认为"整个任务已完成，实际上只处理了当前这一张。

    Args:
        text: 模型原始输出文本

    Returns:
        (is_fake_completion, matched_pattern) — 是否假完成及匹配的模式
    """
    if not text:
        return False, ""

    for pattern in FAKE_COMPLETION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True, pattern

    return False, ""


# ========================
# JSON 校验
# ========================

def validate_response_json(data: Dict) -> Tuple[bool, List[str]]:
    """
    校验模型返回的 JSON 是否符合阅片结果 schema。

    Args:
        data: 解析后的 JSON 字典

    Returns:
        (is_valid, errors) — 是否合法及错误列表
    """
    errors = []

    # 检查必需字段
    for field in REQUIRED_JSON_FIELDS:
        if field not in data:
            errors.append(f"缺少必需字段: {field}")

    # 检查 conclusion 合法值
    conclusion = data.get("conclusion", "")
    if conclusion and conclusion not in VALID_CONCLUSIONS:
        errors.append(f"conclusion 值非法: '{conclusion}'，合法值: {VALID_CONCLUSIONS}")

    # 检查 bounding_boxes 格式
    boxes = data.get("bounding_boxes", [])
    if not isinstance(boxes, list):
        errors.append(f"bounding_boxes 应为数组，实际为: {type(boxes).__name__}")
    elif boxes:
        for i, box in enumerate(boxes):
            if not isinstance(box, dict):
                errors.append(f"bounding_boxes[{i}] 应为对象")
                continue
            for key in ("x", "y", "width", "height"):
                if key not in box:
                    errors.append(f"bounding_boxes[{i}] 缺少字段: {key}")
                else:
                    try:
                        val = float(box[key])
                        if not (0.0 <= val <= 1.0):
                            errors.append(f"bounding_boxes[{i}].{key} = {val}，应在 0~1 范围内")
                    except (ValueError, TypeError):
                        errors.append(f"bounding_boxes[{i}].{key} 无法转为浮点数: {box[key]}")

    return len(errors) == 0, errors


# ========================
# 单条 Harness 执行器
# ========================

class HarnessItemResult:
    """单条 harness 执行结果"""

    def __init__(self, global_index: int, png_name: str):
        self.global_index = global_index
        self.png_name = png_name
        self.success = False
        self.attempts = 0
        self.response_text = ""
        self.parsed_result = None  # Dict
        self.truncated = False
        self.fake_completion = False
        self.validation_errors = []
        self.error_message = ""
        self.duration_seconds = 0.0

    def to_dict(self) -> Dict:
        return {
            "global_index": self.global_index,
            "png_name": self.png_name,
            "success": self.success,
            "attempts": self.attempts,
            "truncated": self.truncated,
            "fake_completion": self.fake_completion,
            "validation_errors": self.validation_errors,
            "error_message": self.error_message,
            "duration_seconds": round(self.duration_seconds, 2),
        }


class ReviewHarness:
    """
    阅片 Harness 执行框架。

    将每张切片作为独立的原子任务执行，通过重试、校验、截断检测
    和假完成检测，从根本上解决 early stopping 问题。
    """

    def __init__(self,
                 model: str,
                 api_base: str,
                 api_key: str,
                 timeout: int = 180,
                 detail: str = "high",
                 temperature: float = 0.0,
                 max_retries: int = MAX_RETRIES,
                 retry_base_seconds: float = RETRY_BASE_SECONDS,
                 max_tokens: Optional[int] = None):
        """
        Args:
            model: 外部视觉模型名称
            api_base: OpenAI 兼容接口基地址
            api_key: API Key
            timeout: 单次请求超时秒数
            detail: 图片细节级别
            temperature: 采样温度
            max_retries: 单条最大重试次数
            retry_base_seconds: 重试基础等待秒数
            max_tokens: 模型最大输出 token 数（None 则不设置，由模型默认）
        """
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.detail = detail
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.max_tokens = max_tokens

        # 统计
        self.total_items = 0
        self.completed_items = 0
        self.failed_items = 0
        self.retried_items = 0
        self.truncation_count = 0
        self.fake_completion_count = 0
        self.consecutive_failures = 0

    def _endpoint(self) -> str:
        if self.api_base.endswith("/chat/completions"):
            return self.api_base
        return f"{self.api_base}/chat/completions"

    def _image_to_data_url(self, image_path: str) -> str:
        image_path = str(Path(image_path).resolve())
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片不存在: {image_path}")
        mime_type, _ = mimetypes.guess_type(image_path)
        mime_type = mime_type or "image/png"
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _build_content(self, item: Dict) -> List[Dict]:
        """构建单条阅片请求的 content 数组"""
        content: List[Dict] = []
        prompt = (item.get("prompt") or "").strip()
        if not prompt:
            raise ValueError(f"批次条目缺少 prompt: global_index={item.get('global_index')}")

        instruction = (
            "请严格根据以下阅片要求分析这组医学影像。"
            "你将看到同一层面的多窗口图像（如有 GGO / 肺窗 / 纵隔窗，请先看 GGO，再看肺窗，再看纵隔窗）。"
            "请只返回一个 JSON 对象，不要 Markdown，不要解释，不要补充前后缀。"
            "不要输出任何总结性语句（如'综上所述''以上是全部'等），只分析当前这一张切片。\n\n"
            f"{prompt}\n\n"
            "补充要求：\n"
            "1. conclusion 只能是：正常 / 异常 / 无法识别\n"
            "2. 如果结论为正常，bounding_boxes 必须返回 []\n"
            "3. 如果发现异常，请尽量补全 abnormality_desc / location / size_mm / recommendation / lung_rads(如适用)\n"
            "4. 输出必须是单个 JSON 对象，字段名保持英文原样\n"
            "5. 这是单张切片的独立分析任务，不要输出汇总或总结\n"
        )
        content.append({"type": "text", "text": instruction})

        image_specs = [
            ("高灵敏度 GGO 窗（最优先检视）", item.get("narrow_ggo_path")),
            ("GGO 窗（优先检视）", item.get("ggo_path")),
            ("肺窗", item.get("png_path")),
            ("纵隔窗", item.get("mediastinum_path")),
        ]
        for label, path in image_specs:
            if not path:
                continue
            content.append({"type": "text", "text": label})
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": self._image_to_data_url(path),
                    "detail": self.detail,
                },
            })
        return content

    def _call_model(self, item: Dict) -> str:
        """调用模型 API，返回原始文本响应"""
        from urllib import error, request

        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是资深放射科医生助理。请只输出单个 JSON 对象，不要输出 Markdown 代码块。"
                        "不要输出任何总结性语句，只分析当前这一张切片。"
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_content(item),
                },
            ],
        }

        # 自适应 max_tokens
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._endpoint(),
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                response_text = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"请求失败: {exc}") from exc

        try:
            response_json = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"模型返回非 JSON: {response_text[:500]}") from exc

        # 提取文本内容
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError(f"模型返回缺少 choices: {response_json}")
        message = choices[0].get("message") or {}
        content = message.get("content")

        # 检查 finish_reason
        finish_reason = choices[0].get("finish_reason", "")
        if finish_reason == "length":
            logger.warning("模型因 max_tokens 限制而截断输出（finish_reason=length）")

        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = []
            for part in content:
                if isinstance(part, dict):
                    if isinstance(part.get("text"), str):
                        texts.append(part["text"])
            if texts:
                return "\n".join(texts).strip()
        raise ValueError(f"无法从模型响应中提取文本内容: {response_json}")

    def _extract_json(self, text: str) -> Optional[str]:
        """从文本中提取 JSON 字符串"""
        # 尝试找到 JSON 代码块
        pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 尝试找到 {...} 块
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            return text[brace_start:brace_end + 1]

        return None

    def execute_single_item(self, item: Dict) -> HarnessItemResult:
        """
        执行单条阅片任务（含重试、校验、截断检测、假完成检测）。

        Args:
            item: 批次模板中的单个 item（含 prompt、图片路径等）

        Returns:
            HarnessItemResult 执行结果
        """
        global_index = item.get("global_index", 0)
        png_name = item.get("png_name", "<unknown>")
        harness_result = HarnessItemResult(global_index, png_name)

        for attempt in range(1, self.max_retries + 1):
            harness_result.attempts = attempt
            start_time = time.time()

            try:
                # 1. 调用模型
                response_text = self._call_model(item)
                harness_result.response_text = response_text
                elapsed = time.time() - start_time
                harness_result.duration_seconds = elapsed

                # 2. 截断检测
                is_truncated, truncation_reason = detect_truncation(response_text)
                if is_truncated:
                    harness_result.truncated = True
                    self.truncation_count += 1
                    logger.warning(
                        "[Harness] #%s %s 第 %s 次尝试：输出截断 — %s",
                        global_index, png_name, attempt, truncation_reason,
                    )
                    if attempt < self.max_retries:
                        wait = self.retry_base_seconds * (2 ** (attempt - 1))
                        logger.info("[Harness] 等待 %.1f 秒后重试...", wait)
                        time.sleep(wait)
                        continue
                    else:
                        harness_result.error_message = f"截断（{self.max_retries}次重试后仍截断）: {truncation_reason}"
                        break

                # 3. 假完成检测
                is_fake, matched_pattern = detect_fake_completion(response_text)
                if is_fake:
                    harness_result.fake_completion = True
                    self.fake_completion_count += 1
                    logger.warning(
                        "[Harness] #%s %s 第 %s 次尝试：检测到假完成信号 — 匹配模式: '%s'",
                        global_index, png_name, attempt, matched_pattern,
                    )
                    if attempt < self.max_retries:
                        wait = self.retry_base_seconds * (2 ** (attempt - 1))
                        logger.info("[Harness] 等待 %.1f 秒后重试...", wait)
                        time.sleep(wait)
                        continue
                    else:
                        # 最后一次仍有假完成信号，但如果 JSON 可解析则仍然接受
                        logger.warning("[Harness] #%s 最终仍有假完成信号，尝试解析 JSON...", global_index)

                # 4. 提取并解析 JSON
                json_str = self._extract_json(response_text)
                if not json_str:
                    logger.warning(
                        "[Harness] #%s %s 第 %s 次尝试：无法提取 JSON",
                        global_index, png_name, attempt,
                    )
                    if attempt < self.max_retries:
                        wait = self.retry_base_seconds * (2 ** (attempt - 1))
                        time.sleep(wait)
                        continue
                    else:
                        harness_result.error_message = "无法从模型输出中提取 JSON"
                        break

                try:
                    parsed = json.loads(json_str)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "[Harness] #%s %s 第 %s 次尝试：JSON 解析失败 — %s",
                        global_index, png_name, attempt, exc,
                    )
                    if attempt < self.max_retries:
                        wait = self.retry_base_seconds * (2 ** (attempt - 1))
                        time.sleep(wait)
                        continue
                    else:
                        harness_result.error_message = f"JSON 解析失败: {exc}"
                        break

                # 5. JSON schema 校验
                is_valid, validation_errors = validate_response_json(parsed)
                if not is_valid:
                    harness_result.validation_errors = validation_errors
                    logger.warning(
                        "[Harness] #%s %s 第 %s 次尝试：JSON 校验失败 — %s",
                        global_index, png_name, attempt, "; ".join(validation_errors),
                    )
                    if attempt < self.max_retries:
                        wait = self.retry_base_seconds * (2 ** (attempt - 1))
                        time.sleep(wait)
                        continue
                    else:
                        # 最后一次校验失败，但如果有 conclusion 字段则仍然接受
                        if "conclusion" in parsed:
                            logger.warning("[Harness] #%s 校验有瑕疵但 conclusion 存在，接受结果", global_index)
                            harness_result.parsed_result = parsed
                            harness_result.success = True
                        else:
                            harness_result.error_message = f"JSON 校验失败: {'; '.join(validation_errors)}"
                        break

                # 6. 全部通过！
                harness_result.parsed_result = parsed
                harness_result.success = True
                if attempt > 1:
                    self.retried_items += 1
                    logger.info("[Harness] #%s %s 第 %s 次尝试成功 ✓", global_index, png_name, attempt)
                break

            except Exception as exc:
                elapsed = time.time() - start_time
                harness_result.duration_seconds = elapsed
                logger.error(
                    "[Harness] #%s %s 第 %s 次尝试异常: %s",
                    global_index, png_name, attempt, exc,
                )
                if attempt < self.max_retries:
                    wait = self.retry_base_seconds * (2 ** (attempt - 1))
                    logger.info("[Harness] 等待 %.1f 秒后重试...", wait)
                    time.sleep(wait)
                else:
                    harness_result.error_message = f"异常（{self.max_retries}次重试后）: {exc}"

        # 更新统计
        if harness_result.success:
            self.completed_items += 1
            self.consecutive_failures = 0
        else:
            self.failed_items += 1
            self.consecutive_failures += 1
            if self.consecutive_failures >= STALL_THRESHOLD:
                logger.error(
                    "[Harness] ⚠️ 连续 %s 条失败，可能存在系统性问题（API 故障/模型不可用/网络异常）",
                    self.consecutive_failures,
                )

        return harness_result

    def run(self,
            manifest_path: str,
            results_path: Optional[str] = None,
            output_path: Optional[str] = None,
            harness_state_path: Optional[str] = None,
            sleep_seconds: float = 0.5,
            overwrite: bool = False) -> Dict:
        """
        执行完整的 harness 阅片流程。

        Args:
            manifest_path: review_manifest.json 路径
            results_path: 当前总表 JSON 路径
            output_path: 合并后的 review_results.json 输出路径
            harness_state_path: harness 状态文件路径（用于断点续跑）
            sleep_seconds: 每条请求后的等待秒数
            overwrite: 是否覆盖已有结论

        Returns:
            执行统计信息
        """
        from reviewer import (
            AIReviewer,
            ReviewConclusion,
            ReviewResult,
            load_review_results_json,
            save_review_results_json,
            validate_review_results,
        )

        manifest_file = Path(manifest_path).resolve()
        if not manifest_file.exists():
            raise FileNotFoundError(f"manifest 不存在: {manifest_file}")

        manifest = _load_json(str(manifest_file))
        manifest_requests = manifest.get("requests")
        if not isinstance(manifest_requests, list) or not manifest_requests:
            raise ValueError("manifest 缺少 requests 数组")

        # 解析总表路径
        resolved_results_path = Path(results_path).resolve() if results_path else _default_results_path(manifest_file, manifest)
        if not resolved_results_path.exists():
            raise FileNotFoundError(f"总表 JSON 不存在: {resolved_results_path}")

        resolved_output_path = Path(output_path).resolve() if output_path else (manifest_file.parent / "review_results.json")

        # 加载总表
        review_results = load_review_results_json(str(resolved_results_path))

        # 加载 harness 状态（断点续跑）
        resolved_harness_state = Path(harness_state_path).resolve() if harness_state_path else (manifest_file.parent / "harness_state.json")
        completed_indices = set()
        if resolved_harness_state.exists() and not overwrite:
            try:
                state = _load_json(str(resolved_harness_state))
                completed_indices = set(state.get("completed_indices", []))
                logger.info("[Harness] 从状态文件恢复：已完成 %s 条", len(completed_indices))
            except Exception as exc:
                logger.warning("[Harness] 状态文件加载失败，从头开始: %s", exc)

        # 收集所有待处理的 item
        all_items = self._collect_all_items(manifest_file, manifest)
        self.total_items = len(all_items)

        logger.info("=" * 60)
        logger.info("[Harness] 阅片评估框架启动")
        logger.info("[Harness] 模型: %s", self.model)
        logger.info("[Harness] 总切片数: %s", self.total_items)
        logger.info("[Harness] 已完成: %s", len(completed_indices))
        logger.info("[Harness] 待处理: %s", self.total_items - len(completed_indices))
        logger.info("[Harness] 最大重试: %s 次/条", self.max_retries)
        if self.max_tokens:
            logger.info("[Harness] max_tokens: %s", self.max_tokens)
        logger.info("=" * 60)

        reviewer = AIReviewer()
        harness_results = []
        start_time = time.time()

        for item in all_items:
            global_index = item.get("global_index", 0)

            # 跳过已完成的
            if global_index in completed_indices and not overwrite:
                continue

            # 跳过已有明确结论的
            if not overwrite and global_index >= 1 and global_index <= len(review_results):
                existing = review_results[global_index - 1]
                if existing.conclusion in (ReviewConclusion.NORMAL, ReviewConclusion.ABNORMAL):
                    logger.info("[Harness] #%s %s 已有明确结论，跳过", global_index, item.get("png_name", ""))
                    completed_indices.add(global_index)
                    continue

            # 执行单条
            logger.info(
                "[Harness] 处理 #%s/%s: %s",
                global_index, self.total_items, item.get("png_name", ""),
            )

            harness_result = self.execute_single_item(item)
            harness_results.append(harness_result)

            # 回填结果到总表
            if harness_result.success and harness_result.parsed_result:
                result = reviewer.parse_ai_response(
                    response=json.dumps(harness_result.parsed_result, ensure_ascii=False),
                    png_name=item.get("png_name", ""),
                    dicom_name=item.get("dicom_name", ""),
                    png_path=item.get("png_path", ""),
                )
                result.slice_index = item.get("slice_index", "") or result.slice_index
                result.slice_location = item.get("slice_location", "") or result.slice_location

                if global_index >= 1 and global_index <= len(review_results):
                    review_results[global_index - 1] = result
            else:
                # 失败：标记为 UNRECOGNIZABLE
                if global_index >= 1 and global_index <= len(review_results):
                    fallback = ReviewResult(
                        png_name=item.get("png_name", ""),
                        dicom_name=item.get("dicom_name", ""),
                        png_path=item.get("png_path", ""),
                        conclusion=ReviewConclusion.UNRECOGNIZABLE,
                        confidence="低",
                        details=f"Harness 执行失败（{harness_result.attempts}次尝试）: {harness_result.error_message}",
                        slice_index=item.get("slice_index", ""),
                        slice_location=item.get("slice_location", ""),
                    )
                    review_results[global_index - 1] = fallback

            # 持久化
            completed_indices.add(global_index)

            # 每 10 条保存一次状态和总表
            if len(completed_indices) % 10 == 0 or not harness_result.success:
                self._save_harness_state(resolved_harness_state, completed_indices, harness_results)
                save_review_results_json(review_results, str(resolved_output_path))
                logger.info(
                    "[Harness] 进度: %s/%s（成功 %s，失败 %s，重试 %s，截断 %s，假完成 %s）",
                    len(completed_indices), self.total_items,
                    self.completed_items, self.failed_items,
                    self.retried_items, self.truncation_count, self.fake_completion_count,
                )

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        # 最终保存
        self._save_harness_state(resolved_harness_state, completed_indices, harness_results)
        save_review_results_json(review_results, str(resolved_output_path))

        elapsed_total = time.time() - start_time

        # 最终统计
        stats = {
            "total": self.total_items,
            "completed": self.completed_items,
            "failed": self.failed_items,
            "retried": self.retried_items,
            "truncation_detected": self.truncation_count,
            "fake_completion_detected": self.fake_completion_count,
            "elapsed_seconds": round(elapsed_total, 1),
            "avg_seconds_per_item": round(elapsed_total / max(self.completed_items + self.failed_items, 1), 1),
        }

        logger.info("=" * 60)
        logger.info("[Harness] 阅片评估框架执行完成")
        logger.info("[Harness] 总计: %s 条", stats["total"])
        logger.info("[Harness] 成功: %s 条", stats["completed"])
        logger.info("[Harness] 失败: %s 条", stats["failed"])
        logger.info("[Harness] 重试成功: %s 条", stats["retried"])
        logger.info("[Harness] 截断检测: %s 次", stats["truncation_detected"])
        logger.info("[Harness] 假完成检测: %s 次", stats["fake_completion_detected"])
        logger.info("[Harness] 总耗时: %.1f 秒（平均 %.1f 秒/条）", stats["elapsed_seconds"], stats["avg_seconds_per_item"])
        logger.info("[Harness] 总表输出: %s", resolved_output_path)
        logger.info("=" * 60)

        return {
            "results_path": str(resolved_output_path),
            "harness_state_path": str(resolved_harness_state),
            "stats": stats,
            "completed": self.failed_items == 0,
        }

    def _collect_all_items(self, manifest_file: Path, manifest: Dict) -> List[Dict]:
        """从 batch_templates 中收集所有 item，按 global_index 排序"""
        batch_dir = manifest.get("batch_template_dir")
        batch_dir_path = Path(batch_dir).resolve() if batch_dir else (manifest_file.parent / "review_batch_templates")

        if not batch_dir_path.exists():
            raise FileNotFoundError(f"批次模板目录不存在: {batch_dir_path}")

        batch_paths = sorted(batch_dir_path.glob("batch_*.json"))
        if not batch_paths:
            raise FileNotFoundError(f"批次模板目录中没有 batch_*.json: {batch_dir_path}")

        all_items = []
        for bp in batch_paths:
            payload = _load_json(str(bp))
            items = payload.get("items", [])
            all_items.extend(items)

        # 按 global_index 排序
        all_items.sort(key=lambda x: x.get("global_index", 0))
        return all_items

    @staticmethod
    def _save_harness_state(state_path: Path, completed_indices: set, harness_results: List[HarnessItemResult]):
        """保存 harness 状态文件"""
        state = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "completed_indices": sorted(completed_indices),
            "total_completed": len(completed_indices),
            "item_results": [r.to_dict() for r in harness_results[-50:]],  # 只保留最近 50 条详情
        }
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


# ========================
# 工具函数
# ========================

def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _default_results_path(manifest_path: Path, manifest: Dict) -> Path:
    preferred = manifest_path.parent / "review_results.json"
    if preferred.exists():
        return preferred
    stub = manifest.get("stub_results_json")
    if stub:
        return Path(stub).resolve()
    return manifest_path.parent / "review_results_stub.json"


# ========================
# CLI 入口
# ========================

def parse_args():
    parser = argparse.ArgumentParser(
        description="DICOM Doctor Review Harness — 单条级别阅片评估框架，解决 early stopping 问题",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 基本用法
  python3 scripts/review_harness.py \\
    --manifest output/20260329/review_manifest.json \\
    --model gpt-4o \\
    --api-key sk-xxx

  # 指定 max_tokens 防止截断
  python3 scripts/review_harness.py \\
    --manifest output/20260329/review_manifest.json \\
    --model gpt-4o \\
    --api-key sk-xxx \\
    --max-tokens 2048

  # 断点续跑（自动从上次中断处继续）
  python3 scripts/review_harness.py \\
    --manifest output/20260329/review_manifest.json \\
    --model gpt-4o \\
    --api-key sk-xxx

  # 覆盖已有结论重新执行
  python3 scripts/review_harness.py \\
    --manifest output/20260329/review_manifest.json \\
    --model gpt-4o \\
    --api-key sk-xxx \\
    --overwrite
""",
    )
    parser.add_argument("--manifest", required=True, help="review_manifest.json 路径")
    parser.add_argument("--results", default=None, help="当前总表 JSON 路径")
    parser.add_argument("--output", default=None, help="合并后的 review_results.json 输出路径")
    parser.add_argument("--harness-state", default=None, help="harness 状态文件路径（断点续跑）")
    parser.add_argument("--model", required=True, help="外部视觉模型名称")
    parser.add_argument("--api-base", default="https://api.openai.com/v1", help="OpenAI 兼容接口基地址")
    parser.add_argument("--api-key", default=None, help="API Key")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="API Key 环境变量名")
    parser.add_argument("--detail", choices=["low", "high", "auto"], default="high", help="图片细节级别")
    parser.add_argument("--temperature", type=float, default=0.0, help="采样温度")
    parser.add_argument("--timeout", type=int, default=180, help="单次请求超时秒数")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES, help=f"单条最大重试次数（默认 {MAX_RETRIES}）")
    parser.add_argument("--max-tokens", type=int, default=None, help="模型最大输出 token 数（不设则由模型默认）")
    parser.add_argument("--sleep-seconds", type=float, default=0.5, help="每条请求后的等待秒数")
    parser.add_argument("--overwrite", action="store_true", default=False, help="覆盖已有结论")
    return parser.parse_args()


def main():
    args = parse_args()

    # 解析 API Key
    api_key = args.api_key or os.environ.get(args.api_key_env, "")
    if not api_key:
        logger.error("未提供 API Key。请传 --api-key，或设置环境变量 %s", args.api_key_env)
        sys.exit(1)

    harness = ReviewHarness(
        model=args.model,
        api_base=args.api_base,
        api_key=api_key,
        timeout=args.timeout,
        detail=args.detail,
        temperature=args.temperature,
        max_retries=args.max_retries,
        max_tokens=args.max_tokens,
    )

    try:
        result = harness.run(
            manifest_path=args.manifest,
            results_path=args.results,
            output_path=args.output,
            harness_state_path=args.harness_state,
            sleep_seconds=args.sleep_seconds,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        logger.error("Harness 执行失败: %s", exc)
        sys.exit(2)

    stats = result["stats"]
    print("\n" + "=" * 60)
    print("Review Harness 执行完成！")
    print("=" * 60)
    print(f"  总表 JSON: {result['results_path']}")
    print(f"  状态文件: {result['harness_state_path']}")
    print(f"  总计: {stats['total']} 条")
    print(f"  成功: {stats['completed']} 条")
    print(f"  失败: {stats['failed']} 条")
    print(f"  重试成功: {stats['retried']} 条")
    print(f"  截断检测: {stats['truncation_detected']} 次")
    print(f"  假完成检测: {stats['fake_completion_detected']} 次")
    print(f"  总耗时: {stats['elapsed_seconds']} 秒")
    print(f"  平均: {stats['avg_seconds_per_item']} 秒/条")

    if result["completed"]:
        print("\n✅ 全部切片处理成功，可直接生成正式报告。")
    else:
        print(f"\n⚠️ 仍有 {stats['failed']} 条失败，请检查日志或重新运行（自动断点续跑）。")


if __name__ == "__main__":
    main()
