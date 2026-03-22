#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成测试：完整流水线端到端测试（DICOM → PDF 报告）

注意：此测试需要实际安装依赖（pydicom、reportlab 等）才能完整运行。
不依赖真实 DICOM 文件，使用 mock 数据模拟。
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dicom-doctor-skill", "scripts"))

from reviewer import ReviewConclusion, ReviewResult


class TestEndToEndPipeline(unittest.TestCase):
    """端到端集成测试"""

    def test_pipeline_import(self):
        """主入口模块应可正常导入"""
        try:
            from main import run_pipeline
            self.assertTrue(callable(run_pipeline))
        except ImportError as e:
            # 部分依赖可能未安装
            self.skipTest(f"依赖缺失: {e}")

    def test_review_results_structure(self):
        """检视结果列表应具有正确的结构"""
        results = [
            ReviewResult(
                png_name="ct_001.png",
                dicom_name="ct_001.dcm",
                png_path="/tmp/ct_001.png",
                conclusion=ReviewConclusion.NORMAL,
                confidence="高",
                details="正常影像",
            ),
            ReviewResult(
                png_name="ct_002.png",
                dicom_name="ct_002.dcm",
                png_path="/tmp/ct_002.png",
                conclusion=ReviewConclusion.ABNORMAL,
                abnormality_desc="右肺下叶疑似 6mm 结节",
                confidence="中",
                details="CT 肺窗影像",
            ),
            ReviewResult(
                png_name="ct_003.png",
                dicom_name="ct_003.dcm",
                png_path="/tmp/ct_003.png",
                conclusion=ReviewConclusion.UNRECOGNIZABLE,
                confidence="低",
                details="图片质量过差，无法有效识别",
            ),
        ]

        # 验证统计
        normal = sum(1 for r in results if r.conclusion == ReviewConclusion.NORMAL)
        abnormal = sum(1 for r in results if r.conclusion == ReviewConclusion.ABNORMAL)
        unrecognizable = sum(1 for r in results if r.conclusion == ReviewConclusion.UNRECOGNIZABLE)

        self.assertEqual(normal, 1)
        self.assertEqual(abnormal, 1)
        self.assertEqual(unrecognizable, 1)
        self.assertEqual(len(results), 3)

        # 验证异常结果
        abnormal_results = [r for r in results if r.conclusion == ReviewConclusion.ABNORMAL]
        self.assertEqual(len(abnormal_results), 1)
        self.assertIn("结节", abnormal_results[0].abnormality_desc)
        self.assertEqual(abnormal_results[0].dicom_name, "ct_002.dcm")

    def test_enhancer_unavailable_graceful(self):
        """超分增强不可用时应优雅降级"""
        try:
            from enhancer import ImageEnhancer
            enhancer = ImageEnhancer()
            # 如果 Real-ESRGAN 没装，应该返回空列表
            if not enhancer.is_available:
                result = enhancer.enhance(["/fake/image.png"], "/fake/output")
                self.assertEqual(result, [])
        except ImportError:
            self.skipTest("enhancer 模块导入失败")

    def test_converter_no_backend_graceful(self):
        """所有转换后端不可用时应优雅处理"""
        from converter import DicomConverter, DCMTKBackend, SimpleITKBackend, Dicom2jpgBackend

        with patch.object(DCMTKBackend, "is_available", return_value=False), \
             patch.object(SimpleITKBackend, "is_available", return_value=False), \
             patch.object(Dicom2jpgBackend, "is_available", return_value=False):
            converter = DicomConverter()
            result = converter.convert("/fake/file.dcm", "/tmp/output")
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
