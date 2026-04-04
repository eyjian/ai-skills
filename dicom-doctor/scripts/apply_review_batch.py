#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将单批阅片结果并入总表 JSON。

推荐配合 reviewer 导出的 `review_batch_templates/batch_XXX.json` 使用：
1. 在每个 item.result 中回填该张切片的正式阅片结果
2. 运行本脚本，将该批结果合并进总表
3. 全部批次完成后，用生成的 review_results.json 调用 generate_report.py
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dicom-doctor.apply-review-batch")


def parse_args():
    parser = argparse.ArgumentParser(description="将单批阅片结果并入总表 JSON")
    parser.add_argument("--manifest", required=True, help="review_manifest.json 路径")
    parser.add_argument("--results", required=True, help="当前总表 JSON 路径（可直接传 review_results_stub.json）")
    parser.add_argument("--batch-json", required=True, help="单批回填 JSON 路径")
    parser.add_argument("--output", default=None, help="输出 JSON 路径；默认覆盖 --results")
    return parser.parse_args()


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_batch_items(payload):
    if isinstance(payload, dict):
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("批次 JSON 缺少 items 数组")
        normalized = []
        batch_index = payload.get("batch_index")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("items 中存在非对象条目")
            merged = dict(item.get("result") or {})
            for key in (
                "global_index",
                "batch_index",
                "png_name",
                "dicom_name",
                "png_path",
                "slice_index",
                "slice_location",
            ):
                if key in item and key not in merged:
                    merged[key] = item[key]
            if batch_index is not None and "batch_index" not in merged:
                merged["batch_index"] = batch_index
            normalized.append(merged)
        return normalized

    if isinstance(payload, list):
        return payload

    raise ValueError("批次 JSON 必须是对象（含 items）或数组")


def main():
    args = parse_args()

    try:
        from reviewer import ReviewResult, load_review_results_json, save_review_results_json, validate_review_results
    except ImportError as e:
        logger.error(f"模块导入失败: {e}")
        logger.error("请确保在 scripts/ 目录下运行此脚本")
        sys.exit(1)

    manifest_path = str(Path(args.manifest).resolve())
    results_path = str(Path(args.results).resolve())
    batch_json_path = str(Path(args.batch_json).resolve())
    output_path = str(Path(args.output).resolve()) if args.output else results_path

    for path in (manifest_path, results_path, batch_json_path):
        if not os.path.exists(path):
            logger.error(f"文件不存在: {path}")
            sys.exit(1)

    manifest = _load_json(manifest_path)
    requests = manifest.get("requests")
    if not isinstance(requests, list) or not requests:
        logger.error(f"manifest 格式错误，缺少 requests 数组: {manifest_path}")
        sys.exit(1)

    request_by_index = {}
    for request in requests:
        try:
            global_index = int(request["global_index"])
        except (KeyError, TypeError, ValueError):
            logger.error("manifest 中存在非法的 global_index")
            sys.exit(1)
        request_by_index[global_index] = request

    review_results = load_review_results_json(results_path)
    batch_items = _normalize_batch_items(_load_json(batch_json_path))
    if not batch_items:
        logger.error(f"批次 JSON 中没有可合并的条目: {batch_json_path}")
        sys.exit(1)

    updated_count = 0
    touched_indexes = set()

    for item in batch_items:
        if not isinstance(item, dict):
            logger.error("批次 JSON 中存在非对象条目")
            sys.exit(1)

        try:
            global_index = int(item.get("global_index"))
        except (TypeError, ValueError):
            logger.error(f"批次条目缺少合法的 global_index: {item}")
            sys.exit(1)

        expected = request_by_index.get(global_index)
        if not expected:
            logger.error(f"global_index={global_index} 不在 manifest 范围内")
            sys.exit(1)

        for key in ("png_name", "dicom_name"):
            actual = item.get(key)
            expected_value = expected.get(key)
            if actual and expected_value and actual != expected_value:
                logger.error(
                    f"global_index={global_index} 的 {key} 与 manifest 不一致: {actual} != {expected_value}"
                )
                sys.exit(1)

        result_payload = dict(item)
        for key in ("png_name", "dicom_name", "png_path", "slice_index", "slice_location"):
            if not result_payload.get(key):
                result_payload[key] = expected.get(key, "")

        result_obj = ReviewResult.from_dict(result_payload)
        if global_index < 1 or global_index > len(review_results):
            logger.error(
                f"global_index={global_index} 超出当前总表范围 1..{len(review_results)}"
            )
            sys.exit(1)

        review_results[global_index - 1] = result_obj
        touched_indexes.add(global_index)
        updated_count += 1

    validation = validate_review_results(
        review_results,
        expected_conversion_results=requests,
        require_complete=False,
    )
    for warning in validation["warnings"]:
        logger.warning(f"阅片结果校验警告: {warning}")
    if not validation["ok"]:
        for error in validation["errors"]:
            logger.error(f"阅片结果校验失败: {error}")
        sys.exit(2)

    save_review_results_json(review_results, output_path)

    stats = validation["stats"]
    logger.info(f"已合并 {updated_count} 条批次结果，涉及 global_index: {min(touched_indexes)}-{max(touched_indexes)}")
    logger.info(
        "当前总进度：共 %s 张，已阅片 %s 张，正常 %s 张，异常 %s 张，待检视 %s 张",
        stats["total"],
        stats["reviewed"],
        stats["normal"],
        stats["abnormal"],
        stats["unrecognizable"],
    )
    logger.info(f"更新后的总表已写出: {output_path}")

    if stats["unrecognizable"] == 0:
        logger.info("全部条目已完成，可直接用该 JSON 生成正式报告。")
    else:
        logger.info("仍有未完成条目，请继续填写剩余批次后再次合并。")


if __name__ == "__main__":
    main()
