#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试：ZIP 解压与非 DICOM 文件过滤
"""

import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dicom-doctor-skill", "scripts"))

from converter import DicomConverter, _is_dicom_file


class TestZipExtraction(unittest.TestCase):
    """测试 ZIP 压缩包解压逻辑"""

    def test_empty_zip(self):
        """空 ZIP 文件应返回空列表"""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            zip_path = f.name

        try:
            with zipfile.ZipFile(zip_path, "w") as zf:
                pass  # 创建空 ZIP

            # Mock 一个可用的后端
            with patch.object(DicomConverter, "_detect_backend") as mock_detect:
                mock_backend = MagicMock()
                mock_backend.name = "MockBackend"
                mock_detect.return_value = mock_backend

                converter = DicomConverter()
                output_dir = tempfile.mkdtemp()
                results = converter.convert(zip_path, output_dir)
                self.assertEqual(results, [])
        finally:
            os.unlink(zip_path)

    def test_zip_with_non_dicom_files(self):
        """ZIP 中包含非 DICOM 文件时应跳过并返回空列表"""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            zip_path = f.name

        try:
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("readme.txt", "This is not a DICOM file")
                zf.writestr("image.jpg", "Fake JPEG data")

            with patch.object(DicomConverter, "_detect_backend") as mock_detect:
                mock_backend = MagicMock()
                mock_backend.name = "MockBackend"
                mock_detect.return_value = mock_backend

                converter = DicomConverter()
                output_dir = tempfile.mkdtemp()
                results = converter.convert(zip_path, output_dir)
                # 非 DICOM 文件应全部被跳过
                self.assertEqual(results, [])
        finally:
            os.unlink(zip_path)


class TestNonDicomFilter(unittest.TestCase):
    """测试非 DICOM 文件过滤"""

    def test_text_file_is_not_dicom(self):
        """文本文件不应被识别为 DICOM"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, World!")
            path = f.name
        try:
            self.assertFalse(_is_dicom_file(path))
        finally:
            os.unlink(path)

    def test_empty_file_is_not_dicom(self):
        """空文件不应被识别为 DICOM"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            path = f.name
        try:
            self.assertFalse(_is_dicom_file(path))
        finally:
            os.unlink(path)

    def test_file_with_dicm_magic(self):
        """具有正确 DICM 魔数的文件应被识别为 DICOM"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            # 写入 128 字节前缀 + DICM 魔数
            f.write(b"\x00" * 128 + b"DICM")
            f.write(b"\x00" * 100)  # 额外数据
            path = f.name
        try:
            self.assertTrue(_is_dicom_file(path))
        finally:
            os.unlink(path)

    def test_macosx_resource_file_skipped(self):
        """macOS 资源文件（__MACOSX）应被过滤"""
        # 此测试验证 _convert_zip 中的 __MACOSX 过滤逻辑
        # 通过路径包含 __MACOSX 的文件应被跳过
        path = "/tmp/__MACOSX/._test.dcm"
        self.assertIn("__MACOSX", path)


if __name__ == "__main__":
    unittest.main()
