#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片超分辨率增强模块

可选功能，使用 Real-ESRGAN 提升 PNG 图片清晰度。
当 Real-ESRGAN 不可用时，自动跳过并输出警告。
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("dicom-doctor.enhancer")


def _has_gpu() -> bool:
    """检测是否有可用的 GPU（NVIDIA）。"""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False


def _try_install_realesrgan(timeout: int = 120) -> bool:
    """
    尝试通过 pip 安装 Real-ESRGAN。

    安装失败不会阻断流程，仅输出警告。

    Returns:
        是否安装成功
    """
    logger.info("[自修复] 检测到 GPU，尝试自动安装 Real-ESRGAN ...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "realesrgan", "--quiet"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            logger.info("[自修复] Real-ESRGAN 安装成功")
            return True
        else:
            logger.warning(
                f"[自修复] Real-ESRGAN 安装失败，降级为原始 PNG\n"
                f"  stderr: {result.stderr.strip()[:200]}"
            )
            return False
    except subprocess.TimeoutExpired:
        logger.warning("[自修复] Real-ESRGAN 安装超时，降级为原始 PNG")
        return False
    except Exception as e:
        logger.warning(f"[自修复] Real-ESRGAN 安装异常，降级为原始 PNG: {e}")
        return False


class ImageEnhancer:
    """
    图片超分辨率增强器。

    支持两种 Real-ESRGAN 调用方式：
      1. 命令行工具：realesrgan-ncnn-vulkan
      2. Python 包：realesrgan
    """

    def __init__(self):
        self._method = self._detect_method()
        # 如果未检测到 Real-ESRGAN 但有 GPU，尝试自动安装
        if self._method is None and _has_gpu():
            if _try_install_realesrgan(timeout=120):
                self._method = self._detect_method()
            # 安装失败时 _method 仍为 None，is_available 返回 False，流程继续

    def _detect_method(self) -> Optional[str]:
        """检测可用的 Real-ESRGAN 方法"""
        # 优先检查命令行工具
        if shutil.which("realesrgan-ncnn-vulkan") is not None:
            logger.info("Real-ESRGAN: 使用 realesrgan-ncnn-vulkan 命令行工具")
            return "cli"

        # 其次检查 Python 包
        try:
            import realesrgan
            logger.info("Real-ESRGAN: 使用 Python realesrgan 包")
            return "python"
        except ImportError:
            pass

        logger.info("Real-ESRGAN: 未检测到可用的超分增强工具")
        return None

    @property
    def is_available(self) -> bool:
        """是否可用"""
        return self._method is not None

    def enhance(self, png_paths: List[str], output_dir: str,
                scale: int = 2) -> List[Optional[str]]:
        """
        对 PNG 图片列表执行超分增强。

        Args:
            png_paths: PNG 图片路径列表
            output_dir: 增强后图片的输出目录
            scale: 放大倍数（2 或 4，默认 2）

        Returns:
            增强后的图片路径列表（失败的位置为 None）
        """
        if not self.is_available:
            logger.warning(
                "Real-ESRGAN 不可用，跳过超分增强。"
                "如需启用，请安装：\n"
                "  命令行工具: realesrgan-ncnn-vulkan\n"
                "  或 Python 包: pip install realesrgan basicsr facexlib gfpgan"
            )
            return []

        os.makedirs(output_dir, exist_ok=True)
        results = []
        total = len(png_paths)

        for i, png_path in enumerate(png_paths, 1):
            filename = os.path.basename(png_path)
            output_path = os.path.join(output_dir, filename)

            logger.info(f"超分增强 ({i}/{total}): {filename}")

            success = False
            if self._method == "cli":
                success = self._enhance_cli(png_path, output_path, scale)
            elif self._method == "python":
                success = self._enhance_python(png_path, output_path, scale)

            if success:
                results.append(output_path)
                logger.info(f"增强成功 ({i}/{total}): {filename}")
            else:
                results.append(None)
                logger.warning(f"增强失败 ({i}/{total}): {filename}，将使用原始图片")

        return results

    def _enhance_cli(self, input_path: str, output_path: str, scale: int) -> bool:
        """通过命令行工具增强"""
        try:
            result = subprocess.run(
                [
                    "realesrgan-ncnn-vulkan",
                    "-i", input_path,
                    "-o", output_path,
                    "-s", str(scale),
                    "-n", "realesrgan-x4plus",  # 使用通用模型
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result.returncode == 0 and os.path.exists(output_path)
        except subprocess.TimeoutExpired:
            logger.warning(f"超分增强超时: {input_path}")
            return False
        except Exception as e:
            logger.warning(f"超分增强异常: {e}")
            return False

    def _enhance_python(self, input_path: str, output_path: str, scale: int) -> bool:
        """通过 Python 包增强"""
        try:
            import cv2
            import numpy as np
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer

            # 初始化模型（使用通用的 RealESRGAN_x4plus 模型）
            model = RRDBNet(
                num_in_ch=3, num_out_ch=3, num_feat=64,
                num_block=23, num_grow_ch=32, scale=4,
            )
            upsampler = RealESRGANer(
                scale=4,
                model_path=None,  # 使用默认模型路径
                model=model,
                half=False,
            )

            # 读取图片
            img = cv2.imread(input_path, cv2.IMREAD_UNCHANGED)
            if img is None:
                return False

            # 执行超分
            output, _ = upsampler.enhance(img, outscale=scale)

            # 保存结果
            cv2.imwrite(output_path, output)
            return os.path.exists(output_path)
        except Exception as e:
            logger.warning(f"Python Real-ESRGAN 增强失败: {e}")
            return False
