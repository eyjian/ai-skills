#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用外部视觉模型自动逐批回填 review_batch_templates/batch_XXX.json，
并持续合并生成 review_results.json。

当前实现对接 OpenAI 兼容的多模态 Chat Completions 接口：
- 默认端点：<api_base>/chat/completions
- 鉴权：Authorization: Bearer <api_key>

典型用途：
1. 主流程 `main.py` 先导出 review_manifest.json / review_batch_templates/
2. 本脚本逐批读取 batch_XXX.json
3. 对每张切片调用外部视觉模型，回填 item.result
4. 每批完成后立刻合并到总表 review_results.json
5. 全部完成后，可直接调用 generate_report.py 生成正式报告
"""

import argparse
import base64
import json
import logging
import mimetypes
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib import error, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dicom-doctor.auto-review-batches")


class OpenAICompatibleVisionClient:
    """极简 OpenAI 兼容多模态调用器。"""

    def __init__(self,
                 model: str,
                 api_base: str,
                 api_key: str,
                 timeout: int = 180,
                 detail: str = "high",
                 temperature: float = 0.0):
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.detail = detail
        self.temperature = temperature

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
        content: List[Dict] = []
        prompt = (item.get("prompt") or "").strip()
        if not prompt:
            raise ValueError(f"批次条目缺少 prompt: global_index={item.get('global_index')}")

        instruction = (
            "请严格根据以下阅片要求分析这组医学影像。"
            "你将看到同一层面的多窗口图像（如有 GGO / 肺窗 / 纵隔窗，请先看 GGO，再看肺窗，再看纵隔窗）。"
            "请只返回一个 JSON 对象，不要 Markdown，不要解释，不要补充前后缀。\n\n"
            f"{prompt}\n\n"
            "补充要求：\n"
            "1. conclusion 只能是：正常 / 异常 / 无法识别\n"
            "2. 如果结论为正常，bounding_boxes 必须返回 []\n"
            "3. 如果发现异常，请尽量补全 abnormality_desc / location / size_mm / recommendation / lung_rads(如适用)\n"
            "4. 输出必须是单个 JSON 对象，字段名保持英文原样\n"
        )
        content.append({"type": "text", "text": instruction})

        image_specs = [
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

    @staticmethod
    def _extract_text_from_response(payload: Dict) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError(f"模型返回缺少 choices: {payload}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = []
            for part in content:
                if isinstance(part, dict):
                    if isinstance(part.get("text"), str):
                        texts.append(part["text"])
                    elif part.get("type") == "text" and isinstance(part.get("value"), str):
                        texts.append(part["value"])
            if texts:
                return "\n".join(texts).strip()
        raise ValueError(f"无法从模型响应中提取文本内容: {payload}")

    def review_item(self, item: Dict) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": "你是资深放射科医生助理。请只输出单个 JSON 对象，不要输出 Markdown 代码块。",
                },
                {
                    "role": "user",
                    "content": self._build_content(item),
                },
            ],
        }
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
        return self._extract_text_from_response(response_json)


def parse_args():
    parser = argparse.ArgumentParser(description="使用外部视觉模型自动逐批回填 review_batch_templates 并合并总表")
    parser.add_argument("--manifest", required=True, help="review_manifest.json 路径")
    parser.add_argument("--batch-json", default=None, help="可选：只处理单个 batch_XXX.json；不传则自动处理全部批次")
    parser.add_argument("--results", default=None, help="当前总表 JSON 路径；默认优先使用现有 review_results.json，其次使用 stub_results_json")
    parser.add_argument("--output", default=None, help="合并后的 review_results.json 输出路径；默认写到 manifest 同目录下的 review_results.json")
    parser.add_argument("--filled-batch-dir", default=None, help="自动回填后的批次 JSON 输出目录；默认 <输出目录>/review_batch_filled")
    parser.add_argument("--model", required=True, help="外部视觉模型名称")
    parser.add_argument("--api-base", default="https://api.openai.com/v1", help="OpenAI 兼容接口基地址，默认 https://api.openai.com/v1")
    parser.add_argument("--api-key", default=None, help="API Key；不传则尝试从 --api-key-env 对应环境变量读取")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="API Key 环境变量名，默认 OPENAI_API_KEY")
    parser.add_argument("--detail", choices=["low", "high", "auto"], default="high", help="图片细节级别")
    parser.add_argument("--temperature", type=float, default=0.0, help="采样温度，默认 0")
    parser.add_argument("--timeout", type=int, default=180, help="单次请求超时秒数，默认 180")
    parser.add_argument("--sleep-seconds", type=float, default=0.0, help="每个条目请求后的额外等待秒数，默认 0")
    parser.add_argument("--overwrite", action="store_true", default=False, help="即使已存在明确结论，也重新请求并覆盖结果")
    return parser.parse_args()


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(payload, path: str) -> str:
    path = str(Path(path).resolve())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _resolve_api_key(api_key: Optional[str], api_key_env: str) -> str:
    resolved = api_key or os.environ.get(api_key_env, "")
    if not resolved:
        raise ValueError(
            f"未提供 API Key。请传 --api-key，或先设置环境变量 {api_key_env}。"
        )
    return resolved


def _normalize_batch_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("批次 JSON 必须是对象，且包含 items 数组")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("批次 JSON 缺少 items 数组或 items 为空")
    return payload, items


def _is_reviewed_result(result_payload: Optional[Dict]) -> bool:
    if not isinstance(result_payload, dict):
        return False
    return result_payload.get("conclusion") in {"正常", "异常"}


def _default_results_path(manifest_path: Path, manifest: Dict) -> Path:
    preferred = manifest_path.parent / "review_results.json"
    if preferred.exists():
        return preferred
    stub = manifest.get("stub_results_json")
    if stub:
        return Path(stub).resolve()
    return manifest_path.parent / "review_results_stub.json"


def _resolve_batch_paths(manifest_path: Path, manifest: Dict, batch_json: Optional[str]) -> List[Path]:
    if batch_json:
        batch_path = Path(batch_json).resolve()
        if not batch_path.exists():
            raise FileNotFoundError(f"批次 JSON 不存在: {batch_path}")
        return [batch_path]

    batch_dir = manifest.get("batch_template_dir")
    batch_dir_path = Path(batch_dir).resolve() if batch_dir else (manifest_path.parent / "review_batch_templates")
    if not batch_dir_path.exists():
        raise FileNotFoundError(f"批次模板目录不存在: {batch_dir_path}")

    batch_paths = sorted(batch_dir_path.glob("batch_*.json"))
    if not batch_paths:
        raise FileNotFoundError(f"批次模板目录中没有 batch_*.json: {batch_dir_path}")
    return batch_paths


def _validate_manifest_requests(manifest: Dict) -> List[Dict]:
    requests_payload = manifest.get("requests")
    if not isinstance(requests_payload, list) or not requests_payload:
        raise ValueError("manifest 缺少 requests 数组")
    return requests_payload


def _merge_batch_payload_into_results(review_results: List["ReviewResult"],
                                      manifest_requests: List[Dict],
                                      batch_payload: Dict) -> List["ReviewResult"]:
    from reviewer import ReviewResult, validate_review_results

    request_by_index = {}
    for req in manifest_requests:
        try:
            request_by_index[int(req["global_index"])] = req
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("manifest 中存在非法的 global_index") from exc

    _, batch_items = _normalize_batch_payload(batch_payload)
    for item in batch_items:
        if not isinstance(item, dict):
            raise ValueError("批次 JSON items 中存在非对象条目")
        try:
            global_index = int(item.get("global_index"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"批次条目缺少合法的 global_index: {item}") from exc

        expected = request_by_index.get(global_index)
        if not expected:
            raise ValueError(f"global_index={global_index} 不在 manifest 范围内")

        result_payload = dict(item.get("result") or {})
        for key in ("png_name", "dicom_name"):
            actual = result_payload.get(key) or item.get(key)
            expected_value = expected.get(key)
            if actual and expected_value and actual != expected_value:
                raise ValueError(
                    f"global_index={global_index} 的 {key} 与 manifest 不一致: {actual} != {expected_value}"
                )

        for key in ("png_name", "dicom_name", "png_path", "slice_index", "slice_location"):
            if not result_payload.get(key):
                result_payload[key] = item.get(key) or expected.get(key, "")

        result_obj = ReviewResult.from_dict(result_payload)
        if global_index < 1 or global_index > len(review_results):
            raise ValueError(f"global_index={global_index} 超出当前总表范围 1..{len(review_results)}")
        review_results[global_index - 1] = result_obj

    validation = validate_review_results(
        review_results,
        expected_conversion_results=manifest_requests,
        require_complete=False,
    )
    if not validation["ok"]:
        errors = "；".join(validation["errors"])
        raise ValueError(f"合并后的结果校验失败：{errors}")
    return review_results


def run_auto_review_pipeline(manifest_path: str,
                             model: str,
                             api_base: str = "https://api.openai.com/v1",
                             api_key: Optional[str] = None,
                             api_key_env: str = "OPENAI_API_KEY",
                             batch_json: Optional[str] = None,
                             results_path: Optional[str] = None,
                             output_path: Optional[str] = None,
                             filled_batch_dir: Optional[str] = None,
                             detail: str = "high",
                             temperature: float = 0.0,
                             timeout: int = 180,
                             sleep_seconds: float = 0.0,
                             overwrite: bool = False,
                             reviewer: Optional["AIReviewer"] = None) -> Dict[str, object]:
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
    manifest_requests = _validate_manifest_requests(manifest)
    resolved_api_key = _resolve_api_key(api_key, api_key_env)
    resolved_results_path = Path(results_path).resolve() if results_path else _default_results_path(manifest_file, manifest)
    if not resolved_results_path.exists():
        raise FileNotFoundError(f"总表 JSON 不存在: {resolved_results_path}")

    resolved_output_path = Path(output_path).resolve() if output_path else (manifest_file.parent / "review_results.json")
    resolved_filled_batch_dir = Path(filled_batch_dir).resolve() if filled_batch_dir else (manifest_file.parent / "review_batch_filled")
    resolved_filled_batch_dir.mkdir(parents=True, exist_ok=True)

    batch_paths = _resolve_batch_paths(manifest_file, manifest, batch_json)
    reviewer = reviewer or AIReviewer()
    client = OpenAICompatibleVisionClient(
        model=model,
        api_base=api_base,
        api_key=resolved_api_key,
        timeout=timeout,
        detail=detail,
        temperature=temperature,
    )

    review_results = load_review_results_json(str(resolved_results_path))
    processed_batches: List[Dict[str, object]] = []
    total_batches = len(batch_paths)

    logger.info("开始自动逐批阅片：共 %s 个批次，模型=%s", total_batches, model)
    logger.info("当前总表输入: %s", resolved_results_path)
    logger.info("合并输出路径: %s", resolved_output_path)
    logger.info("自动回填批次目录: %s", resolved_filled_batch_dir)

    for ordinal, original_batch_path in enumerate(batch_paths, start=1):
        original_batch_path = original_batch_path.resolve()
        filled_batch_path = resolved_filled_batch_dir / f"{original_batch_path.stem}.filled.json"
        source_batch_path = filled_batch_path if (filled_batch_path.exists() and not overwrite) else original_batch_path
        batch_payload = _load_json(str(source_batch_path))
        batch_payload, items = _normalize_batch_payload(batch_payload)

        batch_index = batch_payload.get("batch_index", ordinal)
        logger.info(
            "处理批次 %s/%s：batch_index=%s，来源=%s",
            ordinal,
            total_batches,
            batch_index,
            source_batch_path,
        )

        reviewed_in_batch = 0
        skipped_in_batch = 0
        failed_in_batch = 0

        for item_pos, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"批次 {batch_index} 中存在非对象条目")

            if _is_reviewed_result(item.get("result")) and not overwrite:
                skipped_in_batch += 1
                logger.info(
                    "批次 %s 第 %s/%s 条已存在明确结论，跳过：%s",
                    batch_index,
                    item_pos,
                    len(items),
                    item.get("png_name", "<unknown>"),
                )
                continue

            logger.info(
                "批次 %s 第 %s/%s 条：请求外部视觉模型 -> %s",
                batch_index,
                item_pos,
                len(items),
                item.get("png_name", "<unknown>"),
            )

            try:
                response_text = client.review_item(item)
                result = reviewer.parse_ai_response(
                    response=response_text,
                    png_name=item.get("png_name", ""),
                    dicom_name=item.get("dicom_name", ""),
                    png_path=item.get("png_path", ""),
                )
                result.slice_index = item.get("slice_index", "") or result.slice_index
                result.slice_location = item.get("slice_location", "") or result.slice_location
                item["result"] = result.to_dict()
                reviewed_in_batch += 1
            except Exception as exc:
                logger.error(
                    "批次 %s 第 %s/%s 条自动阅片失败：%s",
                    batch_index,
                    item_pos,
                    len(items),
                    exc,
                )
                fallback = ReviewResult(
                    png_name=item.get("png_name", ""),
                    dicom_name=item.get("dicom_name", ""),
                    png_path=item.get("png_path", ""),
                    conclusion=ReviewConclusion.UNRECOGNIZABLE,
                    confidence="低",
                    details=f"外部视觉模型自动阅片失败：{exc}",
                    slice_index=item.get("slice_index", ""),
                    slice_location=item.get("slice_location", ""),
                )
                item["result"] = fallback.to_dict()
                failed_in_batch += 1

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        batch_payload["auto_review"] = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "model": model,
            "api_base": api_base,
            "detail": detail,
            "temperature": temperature,
            "reviewed_in_batch": reviewed_in_batch,
            "skipped_in_batch": skipped_in_batch,
            "failed_in_batch": failed_in_batch,
        }
        _save_json(batch_payload, str(filled_batch_path))

        review_results = _merge_batch_payload_into_results(review_results, manifest_requests, batch_payload)
        save_review_results_json(review_results, str(resolved_output_path))
        validation = validate_review_results(
            review_results,
            expected_conversion_results=manifest_requests,
            require_complete=False,
        )
        stats = validation["stats"]
        logger.info(
            "批次 %s 合并完成：本批新增 %s 条、跳过 %s 条、失败 %s 条；当前总进度 %s/%s，待检视 %s",
            batch_index,
            reviewed_in_batch,
            skipped_in_batch,
            failed_in_batch,
            stats["reviewed"],
            stats["total"],
            stats["unrecognizable"],
        )
        processed_batches.append({
            "batch_index": batch_index,
            "filled_batch_path": str(filled_batch_path),
            "reviewed_in_batch": reviewed_in_batch,
            "skipped_in_batch": skipped_in_batch,
            "failed_in_batch": failed_in_batch,
        })

    final_validation = validate_review_results(
        review_results,
        expected_conversion_results=manifest_requests,
        require_complete=False,
    )
    stats = final_validation["stats"]
    logger.info(
        "自动逐批阅片完成：共 %s 张，已阅片 %s 张，正常 %s 张，异常 %s 张，待检视 %s 张",
        stats["total"],
        stats["reviewed"],
        stats["normal"],
        stats["abnormal"],
        stats["unrecognizable"],
    )
    logger.info("最新总表 JSON：%s", resolved_output_path)

    return {
        "results_path": str(resolved_output_path),
        "filled_batch_dir": str(resolved_filled_batch_dir),
        "processed_batches": processed_batches,
        "stats": stats,
        "completed": stats["unrecognizable"] == 0,
    }


def main():
    args = parse_args()
    try:
        result = run_auto_review_pipeline(
            manifest_path=args.manifest,
            batch_json=args.batch_json,
            results_path=args.results,
            output_path=args.output,
            filled_batch_dir=args.filled_batch_dir,
            model=args.model,
            api_base=args.api_base,
            api_key=args.api_key,
            api_key_env=args.api_key_env,
            detail=args.detail,
            temperature=args.temperature,
            timeout=args.timeout,
            sleep_seconds=args.sleep_seconds,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        logger.error(f"自动逐批阅片失败: {exc}")
        sys.exit(2)

    stats = result["stats"]
    print("\n自动逐批阅片完成！")
    print(f"  总表 JSON: {result['results_path']}")
    print(f"  回填批次目录: {result['filled_batch_dir']}")
    print(
        "  统计: 共 {total} 张，已阅片 {reviewed} 张，正常 {normal} 张，异常 {abnormal} 张，待检视 {unrecognizable} 张".format(
            **stats
        )
    )
    if result["completed"]:
        print("  全部批次已完成，可直接生成正式报告。")
    else:
        print("  仍有待检视条目，请检查失败批次或继续补跑。")


if __name__ == "__main__":
    main()
