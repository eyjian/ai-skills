#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试：PDF 报告生成（含中文渲染）
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dicom-doctor-skill", "scripts"))

from reviewer import ReviewConclusion, ReviewResult


class TestReviewResult(unittest.TestCase):
    """测试 ReviewResult 数据模型"""

    def test_default_values(self):
        """默认值应为正常结论"""
        result = ReviewResult(
            png_name="test.png",
            dicom_name="test.dcm",
            png_path="/tmp/test.png",
        )
        self.assertEqual(result.conclusion, ReviewConclusion.NORMAL)
        self.assertEqual(result.abnormality_desc, "")
        self.assertEqual(result.confidence, "")

    def test_to_dict(self):
        """to_dict 应正确转换枚举值"""
        result = ReviewResult(
            png_name="test.png",
            dicom_name="test.dcm",
            png_path="/tmp/test.png",
            conclusion=ReviewConclusion.ABNORMAL,
            abnormality_desc="疑似结节",
            confidence="高",
        )
        d = result.to_dict()
        self.assertEqual(d["conclusion"], "异常")
        self.assertEqual(d["abnormality_desc"], "疑似结节")

    def test_abnormal_result(self):
        """异常结果应正确存储"""
        result = ReviewResult(
            png_name="ct_001.png",
            dicom_name="ct_001.dcm",
            png_path="/tmp/ct_001.png",
            conclusion=ReviewConclusion.ABNORMAL,
            abnormality_desc="右肺上叶可见一处约 5mm 疑似结节影",
            confidence="中",
            details="CT 肺窗影像，影像质量良好",
        )
        self.assertEqual(result.conclusion, ReviewConclusion.ABNORMAL)
        self.assertIn("结节", result.abnormality_desc)


class TestReportGeneratorImport(unittest.TestCase):
    """测试 ReportGenerator 可正常导入"""

    def test_import_font_manager(self):
        """FontManager 应可正常导入"""
        try:
            from report_generator import FontManager
            self.assertTrue(True)
        except ImportError:
            # reportlab 未安装时跳过
            self.skipTest("reportlab 未安装")

    def test_import_report_generator(self):
        """ReportGenerator 应可正常导入"""
        try:
            from report_generator import ReportGenerator
            self.assertTrue(True)
        except ImportError:
            self.skipTest("reportlab 未安装")


class TestReviewConclusion(unittest.TestCase):
    """测试检视结论枚举"""

    def test_values(self):
        """枚举值应对应中文"""
        self.assertEqual(ReviewConclusion.NORMAL.value, "正常")
        self.assertEqual(ReviewConclusion.ABNORMAL.value, "异常")
        self.assertEqual(ReviewConclusion.UNRECOGNIZABLE.value, "无法识别")


if __name__ == "__main__":
    unittest.main()
