#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试：DICOM 转 PNG 多后端降级逻辑
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# 将 scripts 目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dicom-doctor-skill", "scripts"))

from converter import DCMTKBackend, SimpleITKBackend, Dicom2jpgBackend, DicomConverter, _is_dicom_file


class TestBackendAvailability(unittest.TestCase):
    """测试后端可用性检测"""

    @patch("shutil.which", return_value="/usr/bin/dcm2pnm")
    def test_dcmtk_available(self, mock_which):
        """dcm2pnm 存在时 DCMTK 后端应可用"""
        self.assertTrue(DCMTKBackend.is_available())

    @patch("shutil.which", return_value=None)
    def test_dcmtk_unavailable(self, mock_which):
        """dcm2pnm 不存在时 DCMTK 后端应不可用"""
        self.assertFalse(DCMTKBackend.is_available())


class TestBackendFallback(unittest.TestCase):
    """测试多后端自动降级逻辑"""

    @patch.object(Dicom2jpgBackend, "is_available", return_value=False)
    @patch.object(SimpleITKBackend, "is_available", return_value=False)
    @patch.object(DCMTKBackend, "is_available", return_value=True)
    def test_prefer_dcmtk(self, *mocks):
        """DCMTK 可用时应优先选择 DCMTK"""
        converter = DicomConverter()
        self.assertEqual(converter.backend_name, "DCMTK")

    @patch.object(Dicom2jpgBackend, "is_available", return_value=False)
    @patch.object(SimpleITKBackend, "is_available", return_value=True)
    @patch.object(DCMTKBackend, "is_available", return_value=False)
    def test_fallback_to_simpleitk(self, *mocks):
        """DCMTK 不可用时应降级到 SimpleITK"""
        converter = DicomConverter()
        self.assertEqual(converter.backend_name, "SimpleITK")

    @patch.object(Dicom2jpgBackend, "is_available", return_value=True)
    @patch.object(SimpleITKBackend, "is_available", return_value=False)
    @patch.object(DCMTKBackend, "is_available", return_value=False)
    def test_fallback_to_dicom2jpg(self, *mocks):
        """DCMTK 和 SimpleITK 都不可用时应降级到 dicom2jpg"""
        converter = DicomConverter()
        self.assertEqual(converter.backend_name, "dicom2jpg")

    @patch.object(Dicom2jpgBackend, "is_available", return_value=False)
    @patch.object(SimpleITKBackend, "is_available", return_value=False)
    @patch.object(DCMTKBackend, "is_available", return_value=False)
    def test_no_backend_available(self, *mocks):
        """所有后端都不可用时 backend_name 应为 None"""
        converter = DicomConverter()
        self.assertIsNone(converter.backend_name)

    @patch.object(Dicom2jpgBackend, "is_available", return_value=False)
    @patch.object(SimpleITKBackend, "is_available", return_value=False)
    @patch.object(DCMTKBackend, "is_available", return_value=False)
    def test_convert_returns_empty_when_no_backend(self, *mocks):
        """没有可用后端时 convert 应返回空列表"""
        converter = DicomConverter()
        result = converter.convert("/fake/path.dcm", "/fake/output")
        self.assertEqual(result, [])


class TestDicomFileDetection(unittest.TestCase):
    """测试 DICOM 文件检测"""

    def test_non_existent_file(self):
        """不存在的文件应返回 False"""
        self.assertFalse(_is_dicom_file("/nonexistent/file.dcm"))

    def test_regular_text_file(self):
        """普通文本文件应返回 False"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("This is not a DICOM file")
            temp_path = f.name
        try:
            self.assertFalse(_is_dicom_file(temp_path))
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    unittest.main()
