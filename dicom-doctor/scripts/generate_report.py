#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立报告生成脚本

从 JSON 文件读取阅片结果，生成 PDF 和 Markdown 报告。
用于宿主 AI 完成阅片后，独立调用生成报告。

用法：
  python3 generate_report.py --results <review_results.json> --output <output_dir> [options]
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from version import __version__

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dicom-doctor.generate-report")


def parse_args():
    parser = argparse.ArgumentParser(
        description="从阅片结果 JSON 生成 PDF 报告"
    )
    parser.add_argument(
        "--results", required=True,
        help="阅片结果 JSON 文件路径"
    )
    parser.add_argument(
        "--output", required=True,
        help="报告输出目录"
    )
    parser.add_argument(
        "--input-path", default="unknown",
        help="原始 DICOM 输入路径（记录到报告中）"
    )
    parser.add_argument(
        "--imaging-type", default=None,
        choices=["chest_ct", "abdomen_ct", "brain_mri", "abdomen_mri", "generic"],
        help="影像类型"
    )
    parser.add_argument(
        "--model-name", default=None,
        help="阅片大模型名称"
    )
    parser.add_argument(
        "--window", default="lung",
        help="窗口类型"
    )
    parser.add_argument(
        "--manifest", default=None,
        help="可选的 review_manifest.json 路径；提供后会额外校验阅片结果是否与当前输出清单匹配"
    )
    parser.add_argument(
        "--allow-incomplete", action="store_true", default=False,
        help="允许使用仍含'无法识别/待检视'条目的结果生成草稿报告；默认关闭，正式报告模式下会直接拒绝"
    )
    parser.add_argument(
        "--max-pages", type=int, default=50,
        help="PDF 最大页数限制（默认 50）。超出时自动裁剪异常影像展示数量"
    )
    return parser.parse_args()


def load_review_results(json_path: str):
    """从 JSON 文件加载阅片结果，复用 reviewer 中的统一反序列化逻辑。"""
    from reviewer import load_review_results_json
    return load_review_results_json(json_path)


def main():
    args = parse_args()

    # 导入依赖模块
    try:
        from report_generator import ReportGenerator
        from modality_detector import get_imaging_profile, ImagingType
        from reviewer import validate_review_results, cross_validate_cad_vs_review
    except ImportError as e:
        logger.error(f"模块导入失败: {e}")
        logger.error("请确保在 scripts/ 目录下运行此脚本")
        sys.exit(1)

    # 加载阅片结果
    if not os.path.exists(args.results):
        logger.error(f"阅片结果文件不存在: {args.results}")
        sys.exit(1)

    logger.info(f"加载阅片结果: {args.results}")
    review_results = load_review_results(args.results)
    logger.info(f"共加载 {len(review_results)} 条阅片记录")

    manifest_requests = None
    manifest_path = args.manifest
    if not manifest_path:
        auto_manifest = Path(args.results).resolve().parent / "review_manifest.json"
        if auto_manifest.exists():
            manifest_path = str(auto_manifest)

    if manifest_path:
        manifest_path = str(Path(manifest_path).resolve())
        if not os.path.exists(manifest_path):
            logger.error(f"manifest 文件不存在: {manifest_path}")
            sys.exit(1)
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
        manifest_requests = manifest_data.get("requests")
        logger.info(f"已加载 manifest: {manifest_path}")

    validation = validate_review_results(
        review_results,
        expected_conversion_results=manifest_requests,
        require_complete=not args.allow_incomplete,
    )
    stats = validation["stats"]
    logger.info(
        "阅片结果校验: 共 %s 张，已阅片 %s 张，正常 %s 张，异常 %s 张，待检视 %s 张",
        stats["total"],
        stats["reviewed"],
        stats["normal"],
        stats["abnormal"],
        stats["unrecognizable"],
    )
    for warning in validation["warnings"]:
        logger.warning(f"阅片结果校验警告: {warning}")
    if not validation["ok"]:
        for error in validation["errors"]:
            logger.error(f"阅片结果校验失败: {error}")
        if not args.allow_incomplete:
            logger.error("当前为正式报告模式，检测到未完成或不匹配的阅片结果，已拒绝生成报告。")
        sys.exit(2)

    # 确定影像类型
    imaging_profile = None
    if args.imaging_type:
        imaging_type = ImagingType(args.imaging_type)
        imaging_profile = get_imaging_profile(imaging_type)

    # 确保输出目录存在
    os.makedirs(args.output, exist_ok=True)

    # CAD 交叉验证（尝试加载 cad_candidates.json）
    cross_validation_result = None
    cad_json_path = Path(args.output) / "cad_candidates.json"
    if not cad_json_path.exists():
        # 也尝试从阅片结果同目录加载
        cad_json_path = Path(args.results).resolve().parent / "cad_candidates.json"
    if cad_json_path.exists():
        try:
            with open(cad_json_path, "r", encoding="utf-8") as f:
                cad_results = json.load(f)
            logger.info(f"加载 CAD 候选结果: {cad_json_path}")
            cross_validation_result = cross_validate_cad_vs_review(
                review_results=review_results,
                cad_results=cad_results,
                score_threshold=0.80,
                z_tolerance=2,
            )
            logger.info(cross_validation_result["summary"])
            if cross_validation_result["alerts"]:
                for alert in cross_validation_result["alerts"]:
                    log_fn = logger.warning if alert["severity"] == "HIGH" else logger.info
                    log_fn(f"[交叉验证 {alert['severity']}] {alert['message']}")
        except Exception as e:
            logger.warning(f"CAD 交叉验证出错（不影响报告生成）: {e}")
    else:
        logger.info("未找到 cad_candidates.json，跳过 CAD 交叉验证")

    # 生成报告
    generator = ReportGenerator()
    task_start_time = datetime.now()

    report_result = generator.generate(
        review_results=review_results,
        input_path=args.input_path,
        output_dir=args.output,
        window_type=args.window,
        imaging_profile=imaging_profile,
        task_start_time=task_start_time,
        task_end_time=datetime.now(),
        model_name=args.model_name,
        version=__version__,
        max_pages=args.max_pages,
        cross_validation=cross_validation_result,
    )

    pdf_path = report_result["pdf_path"]
    md_path = report_result["md_path"]
    logger.info(f"PDF 报告已生成: {pdf_path}")
    logger.info(f"Markdown 报告已生成: {md_path}")
    print(f"\n报告生成完成！")
    print(f"  PDF: {pdf_path}")
    print(f"  Markdown: {md_path}")


if __name__ == "__main__":
    main()
