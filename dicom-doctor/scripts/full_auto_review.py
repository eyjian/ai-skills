#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM Doctor v2.6.0 - 全自动化全量阅片模块

使用宿主 AI 的多模态能力逐张检视全部 PNG 切片,
实现真正的零遗漏全量阅片。

作者: AI Assistant
版本: 2.6.0
日期: 2026-03-28
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import argparse

# 添加父目录到路径以导入其他模块
sys.path.insert(0, str(Path(__file__).parent))

from reviewer import ReviewResult, ReviewConclusion, save_review_results_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dicom-doctor.full-auto-review")


class FullAutoReviewer:
    """
    全自动化阅片器 - 利用宿主 AI 的多模态能力完成全量阅片
    
    此类通过生成标准化的阅片请求,由宿主 AI 逐张分析图片,
    并将结果回填到 JSON 结构中。
    """
    
    VERSION = "2.6.0"
    
    def __init__(self, manifest_path: str, output_dir: str):
        self.manifest_path = Path(manifest_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.review_results: List[ReviewResult] = []
        self.current_batch = 0
        self.total_batches = 0
        
        # 加载 manifest
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.manifest = json.load(f)
        
        self.total_images = self.manifest.get("total_images", 0)
        self.total_batches = self.manifest.get("total_batches", 0)
        
        logger.info(f"全量自动阅片器 v{self.VERSION} 初始化完成")
        logger.info(f"总影像数: {self.total_images}, 总批次数: {self.total_batches}")
    
    def generate_review_requests(self) -> List[Dict]:
        """
        生成所有阅片请求,用于宿主 AI 逐张处理
        
        Returns:
            List[Dict]: 每个元素包含一张图片的完整阅片请求信息
        """
        requests = []
        for req in self.manifest.get("requests", []):
            review_request = {
                "global_index": req["global_index"],
                "batch_index": req["batch_index"],
                "slice_index": req["slice_index"],
                "slice_location": req["slice_location"],
                "png_name": req["png_name"],
                "dicom_name": req["dicom_name"],
                "png_path": req["png_path"],
                "ggo_path": req.get("ggo_path"),
                "narrow_ggo_path": req.get("narrow_ggo_path"),
                "mediastinum_path": req.get("mediastinum_path"),
                "is_focus_layer": req.get("is_focus_layer", False),
                "layer_type": req.get("layer_type", "快扫"),
                "prompt": req.get("prompt", ""),
            }
            requests.append(review_request)
        return requests
    
    def process_single_image(self, request: Dict, ai_analysis_result: Dict) -> ReviewResult:
        """
        处理单张图片的阅片结果
        
        Args:
            request: 阅片请求信息
            ai_analysis_result: AI 分析结果字典
            
        Returns:
            ReviewResult: 标准化的阅片结果
        """
        # 解析 AI 分析结果
        conclusion_str = ai_analysis_result.get("conclusion", "无法识别")
        if conclusion_str == "正常":
            conclusion = ReviewConclusion.NORMAL
        elif conclusion_str == "异常":
            conclusion = ReviewConclusion.ABNORMAL
        else:
            conclusion = ReviewConclusion.UNRECOGNIZABLE
        
        result = ReviewResult(
            png_name=request["png_name"],
            dicom_name=request["dicom_name"],
            png_path=request["png_path"],
            conclusion=conclusion,
            abnormality_desc=ai_analysis_result.get("abnormality_desc", ""),
            confidence=ai_analysis_result.get("confidence", ""),
            details=ai_analysis_result.get("details", ""),
            location=ai_analysis_result.get("location", ""),
            size_mm=ai_analysis_result.get("size_mm", ""),
            lung_rads=ai_analysis_result.get("lung_rads", ""),
            classification_system=ai_analysis_result.get("classification_system", ""),
            classification_value=ai_analysis_result.get("classification_value", ""),
            recommendation=ai_analysis_result.get("recommendation", ""),
            slice_index=request["slice_index"],
            slice_location=request["slice_location"],
            bounding_boxes=ai_analysis_result.get("bounding_boxes", []),
        )
        return result
    
    def save_progress(self, results: List[ReviewResult], batch_index: Optional[int] = None):
        """保存当前进度"""
        output_path = self.output_dir / "review_results_auto.json"
        save_review_results_json(results, str(output_path))
        if batch_index:
            logger.info(f"批次 {batch_index} 完成,已保存进度: {output_path}")
        else:
            logger.info(f"已保存阅片结果: {output_path}")
    
    def run_full_review(self, ai_callback) -> List[ReviewResult]:
        """
        运行全量自动阅片
        
        Args:
            ai_callback: 回调函数,用于调用宿主 AI 分析图片
                        函数签名: ai_callback(request: Dict) -> Dict
                        
        Returns:
            List[ReviewResult]: 完整的阅片结果列表
        """
        requests = self.generate_review_requests()
        results = []
        
        logger.info(f"开始全量阅片,共 {len(requests)} 张")
        
        for i, request in enumerate(requests, 1):
            logger.info(f"[{i}/{len(requests)}] 处理: {request['png_name']} (层面 {request['slice_index']})")
            
            try:
                # 调用 AI 分析
                ai_result = ai_callback(request)
                
                # 处理结果
                result = self.process_single_image(request, ai_result)
                results.append(result)
                
                # 每10张保存一次进度
                if i % 10 == 0:
                    self.save_progress(results)
                    
            except Exception as e:
                logger.error(f"处理 {request['png_name']} 时出错: {e}")
                # 创建错误结果
                error_result = ReviewResult(
                    png_name=request["png_name"],
                    dicom_name=request["dicom_name"],
                    png_path=request["png_path"],
                    conclusion=ReviewConclusion.UNRECOGNIZABLE,
                    details=f"处理出错: {str(e)}",
                    slice_index=request["slice_index"],
                    slice_location=request["slice_location"],
                )
                results.append(error_result)
        
        # 最终保存
        self.save_progress(results)
        logger.info(f"全量阅片完成!共 {len(results)} 张")
        
        return results


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="DICOM Doctor v2.6.0 - 全自动化全量阅片"
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="review_manifest.json 路径",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="输出目录",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=15,
        help="每批处理的图片数量(默认15)",
    )
    
    args = parser.parse_args()
    
    # 初始化全量阅片器
    reviewer = FullAutoReviewer(args.manifest, args.output)
    
    # 生成阅片请求
    requests = reviewer.generate_review_requests()
    
    # 输出请求列表(供宿主 AI 处理)
    output_file = Path(args.output) / "full_review_requests.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(requests, f, ensure_ascii=False, indent=2)
    
    logger.info(f"阅片请求已生成: {output_file}")
    logger.info(f"请宿主 AI 逐张处理这些请求,并将结果回填到 review_results_auto.json")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
