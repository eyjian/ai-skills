#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM 转 PNG 转换模块

支持三种转换后端，按优先级自动降级：
  DCMTK (dcm2pnm) → SimpleITK → dicom2jpg
"""

import importlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modality_detector import ImagingProfile

logger = logging.getLogger("dicom-doctor.converter")


def _is_dicom_file(filepath: str) -> bool:
    """
    判断文件是否为 DICOM 格式。
    通过检查文件头部的 DICM 魔数（偏移 128 字节处）或尝试用 pydicom 读取。
    """
    try:
        with open(filepath, "rb") as f:
            f.seek(128)
            magic = f.read(4)
            if magic == b"DICM":
                return True
        # 部分 DICOM 文件没有标准前缀，尝试用 pydicom
        try:
            import pydicom
            pydicom.dcmread(filepath, stop_before_pixels=True)
            return True
        except Exception:
            return False
    except Exception:
        return False


# 窗宽窗位预设（center, width）
# 各后端共享的窗口预设
WINDOW_PRESETS = {
    "lung":        (-600, 1500),   # 肺窗：检测肺结节、肺纹理
    "mediastinum":  (40, 400),     # 纵隔窗：检测纵隔结构、淋巴结
    "bone":        (400, 1800),    # 骨窗
    "soft_tissue":  (50, 350),     # 软组织窗
    "ggo":         (-600, 600),    # GGO 专用窗（优化版）：WC=-600, WW=600 → HU范围 -900~-300
                                   # 收窄窗宽从800→600，提高GGO区域对比度约33%
                                   # GGO密度范围(-700~-400 HU)现在占动态范围约50%（原25%）
    "narrow_ggo":  (-550, 400),    # 高灵敏度GGO窗：WC=-550, WW=400 → HU范围 -750~-350
                                   # 极窄窗宽，最大化磨玻璃密度的灰阶对比
                                   # 专门检测极淡的纯磨玻璃结节(pure GGN)
}

# 所有支持的 --window 参数值
SUPPORTED_WINDOWS = list(WINDOW_PRESETS.keys()) + ["all"]


class DCMTKBackend:
    """DCMTK 后端转换器（通过 subprocess 调用 dcm2pnm）"""

    name = "DCMTK"

    @staticmethod
    def is_available() -> bool:
        """检测 dcm2pnm 命令是否可用"""
        return shutil.which("dcm2pnm") is not None

    @staticmethod
    def convert(dicom_path: str, png_path: str, window_type: str = "lung") -> bool:
        """
        使用 dcm2pnm 将 DICOM 文件转换为 PNG。

        Args:
            dicom_path: DICOM 文件路径
            png_path: 输出 PNG 路径
            window_type: 窗口类型（lung/mediastinum/bone/soft_tissue/all）
        """
        def _run_dcm2pnm(dicom: str, out_png: str, wc: float, ww: float) -> bool:
            """内部辅助：用指定窗宽窗位运行 dcm2pnm"""
            try:
                result = subprocess.run(
                    [
                        "dcm2pnm",
                        "--write-png",
                        "+Wn",               # 使用指定窗宽窗位
                        str(int(wc)),         # 窗位中心
                        str(int(ww)),         # 窗宽
                        dicom,
                        out_png,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0 and os.path.exists(out_png):
                    return True
                else:
                    logger.warning(f"dcm2pnm 转换失败: {result.stderr.strip()}")
                    return False
            except subprocess.TimeoutExpired:
                logger.warning(f"dcm2pnm 转换超时: {dicom}")
                return False
            except Exception as e:
                logger.warning(f"dcm2pnm 转换异常: {e}")
                return False

        if window_type == "all":
            # 输出所有窗口版本：主文件用肺窗，其他窗口加后缀
            wc, ww = WINDOW_PRESETS["lung"]
            success = _run_dcm2pnm(dicom_path, png_path, wc, ww)
            if success:
                for wtype, (wc2, ww2) in WINDOW_PRESETS.items():
                    if wtype == "lung":
                        continue
                    extra_path = png_path.replace(".png", f"_{wtype}.png")
                    _run_dcm2pnm(dicom_path, extra_path, wc2, ww2)
            return success
        else:
            wc, ww = WINDOW_PRESETS.get(window_type, WINDOW_PRESETS["lung"])
            success = _run_dcm2pnm(dicom_path, png_path, wc, ww)
            # 额外输出纵隔窗版本，用于多窗口联合阅片
            if success and window_type == "lung":
                med_wc, med_ww = WINDOW_PRESETS["mediastinum"]
                med_path = png_path.replace(".png", "_mediastinum.png")
                _run_dcm2pnm(dicom_path, med_path, med_wc, med_ww)
                # 额外输出 GGO 窗版本，用于磨玻璃结节检测
                ggo_wc, ggo_ww = WINDOW_PRESETS["ggo"]
                ggo_path = png_path.replace(".png", "_ggo.png")
                _run_dcm2pnm(dicom_path, ggo_path, ggo_wc, ggo_ww)
                # 额外输出高灵敏度 narrow_ggo 窗版本
                if "narrow_ggo" in WINDOW_PRESETS:
                    nggo_wc, nggo_ww = WINDOW_PRESETS["narrow_ggo"]
                    nggo_path = png_path.replace(".png", "_narrow_ggo.png")
                    _run_dcm2pnm(dicom_path, nggo_path, nggo_wc, nggo_ww)
            return success


class SimpleITKBackend:
    """SimpleITK 后端转换器"""

    name = "SimpleITK"

    @staticmethod
    def is_available() -> bool:
        """检测 SimpleITK 是否可用"""
        try:
            import SimpleITK
            return True
        except ImportError:
            return False

    @staticmethod
    def convert(dicom_path: str, png_path: str, window_type: str = "lung") -> bool:
        """
        使用 SimpleITK 将 DICOM 文件转换为 PNG。

        Args:
            dicom_path: DICOM 文件路径
            png_path: 输出 PNG 路径
            window_type: 窗口类型（lung/mediastinum/bone/soft_tissue/all）
        """
        try:
            import SimpleITK as sitk
            import numpy as np
            from PIL import Image as PILImage

            # 读取 DICOM 文件
            image = sitk.ReadImage(dicom_path)
            array = sitk.GetArrayFromImage(image)

            # 处理多帧：取第一帧
            if array.ndim == 3:
                array = array[0]

            array = array.astype(np.float64)

            # 判断是否为 CT 影像（HU 值范围通常在 -1024 到 3000+）
            is_ct = array.min() < -100 or array.max() > 1000

            if is_ct:
                if window_type == "all":
                    # 输出所有窗口版本：主文件用肺窗，其他窗口加后缀
                    wc, ww = WINDOW_PRESETS["lung"]
                    windowed = SimpleITKBackend._apply_window(array, wc, ww)
                    PILImage.fromarray(windowed).save(png_path)
                    for wtype, (wc2, ww2) in WINDOW_PRESETS.items():
                        if wtype == "lung":
                            continue
                        extra_windowed = SimpleITKBackend._apply_window(array, wc2, ww2)
                        extra_path = png_path.replace(".png", f"_{wtype}.png")
                        PILImage.fromarray(extra_windowed).save(extra_path)
                        logger.debug(f"额外输出 {wtype} 窗: {extra_path}")
                else:
                    # 使用用户指定的窗口类型
                    wc, ww = WINDOW_PRESETS.get(window_type, WINDOW_PRESETS["lung"])
                    logger.debug(f"使用 {window_type} 窗: WC={wc}, WW={ww}")
                    windowed = SimpleITKBackend._apply_window(array, wc, ww)
                    PILImage.fromarray(windowed).save(png_path)
                    # 额外输出纵隔窗版本，用于多窗口联合阅片
                    if window_type == "lung":
                        med_wc, med_ww = WINDOW_PRESETS["mediastinum"]
                        med_windowed = SimpleITKBackend._apply_window(array, med_wc, med_ww)
                        med_path = png_path.replace(".png", "_mediastinum.png")
                        PILImage.fromarray(med_windowed).save(med_path)
                        logger.debug(f"额外输出纵隔窗（联合阅片）: {med_path}")
                        # 额外输出 GGO 窗版本，用于磨玻璃结节检测
                        ggo_wc, ggo_ww = WINDOW_PRESETS["ggo"]
                        ggo_windowed = SimpleITKBackend._apply_window(array, ggo_wc, ggo_ww)
                        ggo_path = png_path.replace(".png", "_ggo.png")
                        PILImage.fromarray(ggo_windowed).save(ggo_path)
                        logger.debug(f"额外输出 GGO 窗（磨玻璃结节检测）: {ggo_path}")
                        # 额外输出高灵敏度 narrow_ggo 窗版本，专门检测极淡的纯磨玻璃结节
                        if "narrow_ggo" in WINDOW_PRESETS:
                            nggo_wc, nggo_ww = WINDOW_PRESETS["narrow_ggo"]
                            nggo_windowed = SimpleITKBackend._apply_window(array, nggo_wc, nggo_ww)
                            nggo_path = png_path.replace(".png", "_narrow_ggo.png")
                            PILImage.fromarray(nggo_windowed).save(nggo_path)
                            logger.debug(f"额外输出高灵敏度 GGO 窗（纯磨玻璃结节检测）: {nggo_path}")
            else:
                # 非 CT 影像：尝试从 DICOM 元数据获取窗宽窗位
                wc, ww = None, None
                try:
                    reader = sitk.ImageFileReader()
                    reader.SetFileName(dicom_path)
                    reader.LoadPrivateTagsOn()
                    reader.ReadImageInformation()
                    wc_str = reader.GetMetaData("0028|1050") if reader.HasMetaDataKey("0028|1050") else None
                    ww_str = reader.GetMetaData("0028|1051") if reader.HasMetaDataKey("0028|1051") else None
                    if wc_str and ww_str:
                        wc = float(wc_str.split("\\")[0].strip())
                        ww = float(ww_str.split("\\")[0].strip())
                        logger.debug(f"DICOM 元数据窗位: WC={wc}, WW={ww}")
                except Exception:
                    pass

                if wc is not None and ww is not None:
                    windowed = SimpleITKBackend._apply_window(array, wc, ww)
                else:
                    min_val, max_val = array.min(), array.max()
                    if max_val > min_val:
                        windowed = ((array - min_val) / (max_val - min_val) * 255.0).astype(np.uint8)
                    else:
                        windowed = np.zeros_like(array, dtype=np.uint8)
                PILImage.fromarray(windowed).save(png_path)

            return True
        except Exception as e:
            logger.warning(f"SimpleITK 转换失败: {e}")
            return False

    @staticmethod
    def _apply_window(array, window_center: float, window_width: float):
        """
        对像素数组应用窗宽窗位变换。

        Args:
            array: numpy 数组（float64）
            window_center: 窗位中心值
            window_width: 窗宽

        Returns:
            uint8 类型的归一化数组（0-255）
        """
        import numpy as np
        lower = window_center - window_width / 2.0
        upper = window_center + window_width / 2.0
        windowed = np.clip(array, lower, upper)
        windowed = ((windowed - lower) / (upper - lower) * 255.0).astype(np.uint8)
        return windowed


class Dicom2jpgBackend:
    """dicom2jpg 后端转换器"""

    name = "dicom2jpg"

    @staticmethod
    def is_available() -> bool:
        """检测 dicom2jpg 是否可用"""
        try:
            import dicom2jpg
            return True
        except ImportError:
            return False

    @staticmethod
    def convert(dicom_path: str, png_path: str, window_type: str = "lung") -> bool:
        """
        使用 dicom2jpg 将 DICOM 文件转换为 PNG。
        注意：dicom2jpg 后端不支持自定义窗口类型，window_type 参数被忽略。
        """
        try:
            import dicom2jpg

            # dicom2jpg 输出到目录，需要重命名
            output_dir = os.path.dirname(png_path)
            result_paths = dicom2jpg.dicom2png(dicom_path, output_dir)

            if result_paths and len(result_paths) > 0:
                result_path = result_paths[0] if isinstance(result_paths, list) else result_paths
                if str(result_path) != png_path and os.path.exists(str(result_path)):
                    shutil.move(str(result_path), png_path)
                return os.path.exists(png_path)
            return False
        except Exception as e:
            logger.warning(f"dicom2jpg 转换失败: {e}")
            return False


class DicomConverter:
    """
    DICOM 转 PNG 转换器，支持多后端自动降级。

    优先级：DCMTK → SimpleITK → dicom2jpg
    支持输入：单个 DICOM 文件 或 ZIP 压缩包

    清晰度说明：
      CT DICOM 原始像素矩阵通常只有 512×512，对于 AI 检测肺小结节来说
      分辨率偏低（2-4mm 结节可能只占 2-4 个像素）。
      本转换器默认会将输出 PNG 做高质量插值放大（Lanczos），确保 AI 有
      足够的像素信息进行分析。
    """

    # 后端列表，按优先级排列
    BACKENDS = [DCMTKBackend, SimpleITKBackend, Dicom2jpgBackend]

    # 默认最小输出尺寸（宽或高的最小值）
    DEFAULT_MIN_SIZE = 2048

    def __init__(self, auto_install: bool = True, min_size: int = None,
                 window_type: str = "lung", separate_dirs: bool = True,
                 mip: bool = False, mip_slabs: int = 5,
                 imaging_profile: 'Optional[ImagingProfile]' = None):
        """
        Args:
            auto_install: 是否自动安装缺失后端
            min_size: 输出 PNG 的最小尺寸（像素），默认 1024。
                      若 DICOM 原始矩阵小于此值，将使用 Lanczos 高质量插值放大。
                      设为 0 或 None 则保持原始分辨率不做放大。
            window_type: 窗口类型，可选值：
                         lung（肺窗，默认）、mediastinum（纵隔窗）、
                         bone（骨窗）、soft_tissue（软组织窗）、
                         ggo（GGO 窗）、all（输出所有窗口版本）
            separate_dirs: 是否将不同窗口类型的 PNG 分别存放到独立子目录
            mip: 是否生成 MIP（最大密度投影）图像，用于提高微小结节检出率
            mip_slabs: MIP 的 slab 厚度（层数），默认 5 层
            imaging_profile: 影像类型策略配置（可选）。传入后将覆盖窗位预设、
                            MIP 和 GGO 窗的启用策略。未传入时默认使用胸部CT行为。
        """
        self._auto_install = auto_install
        self._min_size = min_size if min_size is not None else self.DEFAULT_MIN_SIZE
        self._imaging_profile = imaging_profile

        # 如果传入了 ImagingProfile，根据 Profile 覆盖窗位/MIP/GGO 策略
        if imaging_profile is not None:
            # 用 Profile 的窗位预设覆盖全局 WINDOW_PRESETS
            self._profile_window_presets = imaging_profile.window_presets
            self._window_type = imaging_profile.primary_window if imaging_profile.primary_window != "default" else window_type
            # MIP 和 GGO 由 Profile 控制
            self._mip = mip and imaging_profile.use_mip  # 仅当用户启用且 Profile 支持时才启用
            self._use_ggo_window = imaging_profile.use_ggo_window
        else:
            self._profile_window_presets = None
            self._window_type = window_type if window_type in SUPPORTED_WINDOWS else "lung"
            self._mip = mip
            self._use_ggo_window = True  # 默认胸部CT行为

        self._separate_dirs = separate_dirs
        self._mip_slabs = max(2, min(mip_slabs, 20))  # 限制范围 2-20
        self._backend = self._detect_backend()
        # 如果无可用后端且允许自动安装，则尝试自修复
        if self._backend is None and self._auto_install:
            self._backend = self._auto_install_backend()
        logger.info(f"窗口类型: {self._window_type}")
        logger.info(f"分目录输出: {'启用' if self._separate_dirs else '禁用'}")
        if self._mip:
            logger.info(f"MIP 重建: 启用（slab 厚度={self._mip_slabs} 层）")

    def _detect_backend(self):
        """检测可用后端，按优先级自动选择"""
        for backend_cls in self.BACKENDS:
            if backend_cls.is_available():
                logger.info(f"使用 DICOM 转换后端: {backend_cls.name}")
                return backend_cls
        return None

    def _auto_install_backend(self):
        """
        [自修复] 尝试自动安装 DICOM 转换后端（镜像感知）。
        按优先级依次尝试安装 SimpleITK 和 dicom2jpg。
        自动检测网络环境，国内用户使用清华/阿里等镜像加速。
        """
        from pip_utils import pip_install as pip_install_mirror

        install_candidates = [
            ("SimpleITK", "SimpleITK>=2.3.0", SimpleITKBackend),
            ("dicom2jpg", "dicom2jpg>=0.1.5", Dicom2jpgBackend),
        ]
        for module_name, pip_spec, backend_cls in install_candidates:
            logger.info(f"[自修复] 尝试安装 DICOM 转换后端: {module_name} ...")
            if pip_install_mirror(pip_spec):
                importlib.invalidate_caches()
                try:
                    importlib.import_module(module_name)
                    logger.info(f"[自修复] 成功安装并启用后端: {module_name}")
                    return backend_cls
                except ImportError:
                    logger.warning(f"[自修复] 安装后仍无法导入: {module_name}")
            else:
                logger.warning(f"[自修复] 安装失败: {module_name}")

        logger.error(
            "[自修复] 无法自动安装任何 DICOM 转换后端。\n"
            "请手动安装以下任一工具：\n"
            "  1. DCMTK: sudo apt install dcmtk（推荐）\n"
            "  2. SimpleITK: pip install SimpleITK -i https://pypi.tuna.tsinghua.edu.cn/simple/\n"
            "  3. dicom2jpg: pip install dicom2jpg -i https://pypi.tuna.tsinghua.edu.cn/simple/"
        )
        return None

    @property
    def backend_name(self) -> Optional[str]:
        """当前使用的后端名称"""
        return self._backend.name if self._backend else None

    def convert(self, input_path: str, output_dir: str) -> List[Dict[str, str]]:
        """
        转换 DICOM 文件为 PNG。

        Args:
            input_path: DICOM 文件路径或 ZIP 压缩包路径
            output_dir: PNG 输出目录

        Returns:
            转换结果列表，每项包含:
              - dicom_path: 原始 DICOM 文件路径
              - dicom_name: 原始 DICOM 文件名
              - png_path: 转换后 PNG 文件路径
        """
        if self._backend is None:
            logger.error(
                "未检测到可用的 DICOM 转换后端。请安装以下任一工具：\n"
                "  1. DCMTK: sudo apt install dcmtk（推荐）\n"
                "  2. SimpleITK: pip install SimpleITK\n"
                "  3. dicom2jpg: pip install dicom2jpg"
            )
            return []

        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)

        input_path = Path(input_path)
        if input_path.suffix.lower() == ".zip":
            return self._convert_zip(str(input_path), output_dir)
        else:
            return self._convert_single(str(input_path), output_dir)

    def _get_window_output_dir(self, base_output_dir: str, window_type: str) -> str:
        """
        根据分目录模式计算窗口类型对应的输出目录。

        Args:
            base_output_dir: 基础输出目录（如 png/）
            window_type: 窗口类型名称（如 lung、mediastinum）

        Returns:
            分目录模式下返回 base_output_dir/window_type/，否则返回 base_output_dir
        """
        if self._separate_dirs:
            window_dir = os.path.join(base_output_dir, window_type)
            os.makedirs(window_dir, exist_ok=True)
            return window_dir
        return base_output_dir

    def _get_window_png_name(self, base_stem: str, window_type: str) -> str:
        """
        根据分目录模式计算窗口类型对应的 PNG 文件名。

        分目录模式下：所有窗口类型的文件名统一为 base_stem.png（目录名已标明窗口类型）
        平铺模式下：非主窗口文件名加后缀（如 base_stem_mediastinum.png）

        Args:
            base_stem: 文件名基础部分（不含扩展名）
            window_type: 窗口类型名称

        Returns:
            PNG 文件名
        """
        if self._separate_dirs:
            return f"{base_stem}.png"
        elif window_type == "lung":
            return f"{base_stem}.png"
        else:
            return f"{base_stem}_{window_type}.png"

    def _convert_single(self, dicom_path: str, output_dir: str) -> List[Dict[str, str]]:
        """转换单个 DICOM 文件"""
        if not _is_dicom_file(dicom_path):
            logger.warning(f"跳过非 DICOM 文件: {dicom_path}")
            return []

        dicom_name = os.path.basename(dicom_path)
        base_stem = Path(dicom_name).stem

        if self._separate_dirs:
            # 分目录模式：先用临时路径让后端转换，然后移动到对应子目录
            tmp_png_name = base_stem + ".png"
            tmp_png_path = os.path.join(output_dir, tmp_png_name)

            success = self._backend.convert(dicom_path, tmp_png_path, window_type=self._window_type)
            if success:
                # 将文件移动到对应的窗口子目录
                result = self._relocate_to_window_dirs(output_dir, base_stem, tmp_png_path)
                if result:
                    png_path = result["png_path"]
                    mediastinum_path = result.get("mediastinum_path", "")
                    # 高质量插值放大
                    self._upscale_if_needed(png_path, mediastinum_path=mediastinum_path)
                    logger.info(f"转换成功: {dicom_name} → {os.path.relpath(png_path, output_dir)}")
                    # 提取 DICOM 层面元数据
                    slice_location, instance_number = self._extract_dicom_metadata(dicom_path)
                    ggo_path = result.get("ggo_path", "")
                    narrow_ggo_path = result.get("narrow_ggo_path", "")
                    return [{
                        "dicom_path": dicom_path,
                        "dicom_name": dicom_name,
                        "png_path": png_path,
                        "mediastinum_path": mediastinum_path,
                        "ggo_path": ggo_path,
                        "narrow_ggo_path": narrow_ggo_path,
                        "slice_location": slice_location,
                        "instance_number": instance_number,
                        "slice_index": "1/1",
                    }]
            logger.error(f"转换失败: {dicom_name}")
            return []
        else:
            # 平铺模式：保持原有行为
            png_name = base_stem + ".png"
            png_path = os.path.join(output_dir, png_name)

            success = self._backend.convert(dicom_path, png_path, window_type=self._window_type)
            if success:
                # 高质量插值放大：确保输出图片足够清晰
                self._upscale_if_needed(png_path)
                logger.info(f"转换成功: {dicom_name} → {png_name}")
                # 提取 DICOM 层面元数据
                slice_location, instance_number = self._extract_dicom_metadata(dicom_path)
                # 检查是否存在纵隔窗版本
                mediastinum_path = png_path.replace(".png", "_mediastinum.png")
                if not os.path.exists(mediastinum_path):
                    mediastinum_path = ""
                # 检查是否存在 GGO 窗版本
                ggo_path = png_path.replace(".png", "_ggo.png")
                if not os.path.exists(ggo_path):
                    ggo_path = ""
                # 检查是否存在高灵敏度 GGO 窗版本
                narrow_ggo_path = png_path.replace(".png", "_narrow_ggo.png")
                if not os.path.exists(narrow_ggo_path):
                    narrow_ggo_path = ""
                return [{
                    "dicom_path": dicom_path,
                    "dicom_name": dicom_name,
                    "png_path": png_path,
                    "mediastinum_path": mediastinum_path,
                    "ggo_path": ggo_path,
                    "narrow_ggo_path": narrow_ggo_path,
                    "slice_location": slice_location,
                    "instance_number": instance_number,
                    "slice_index": "1/1",
                }]
            else:
                logger.error(f"转换失败: {dicom_name}")
                return []

    def _relocate_to_window_dirs(self, output_dir: str, base_stem: str, tmp_png_path: str) -> Optional[Dict[str, str]]:
        """
        将后端输出的 PNG 文件重新定位到窗口类型子目录中。

        后端 convert 方法总是在同一目录下以后缀方式输出不同窗口文件（如 xxx_mediastinum.png），
        此方法将这些文件移动到对应的子目录，并统一文件名。

        Args:
            output_dir: 基础输出目录（如 png/）
            base_stem: 文件名基础部分
            tmp_png_path: 后端输出的主 PNG 文件路径

        Returns:
            包含 png_path 和 mediastinum_path 的字典，失败返回 None
        """
        if not os.path.exists(tmp_png_path):
            return None

        result = {}

        # 确定主窗口类型
        if self._window_type == "all":
            primary_window = "lung"
        else:
            primary_window = self._window_type

        # 移动主窗口文件到子目录
        primary_dir = self._get_window_output_dir(output_dir, primary_window)
        primary_dst = os.path.join(primary_dir, f"{base_stem}.png")
        shutil.move(tmp_png_path, primary_dst)
        result["png_path"] = primary_dst

        # 移动额外窗口文件到各自子目录
        mediastinum_path = ""
        ggo_path = ""
        narrow_ggo_path = ""
        for wtype in WINDOW_PRESETS:
            if wtype == primary_window:
                continue
            # 后端输出的额外窗口文件名格式
            extra_src = os.path.join(output_dir, f"{base_stem}_{wtype}.png")
            if os.path.exists(extra_src):
                extra_dir = self._get_window_output_dir(output_dir, wtype)
                extra_dst = os.path.join(extra_dir, f"{base_stem}.png")
                shutil.move(extra_src, extra_dst)
                if wtype == "mediastinum":
                    mediastinum_path = extra_dst
                elif wtype == "ggo":
                    ggo_path = extra_dst
                elif wtype == "narrow_ggo":
                    narrow_ggo_path = extra_dst
                logger.debug(f"  {wtype} 窗移入子目录: {os.path.relpath(extra_dst, output_dir)}")

        result["mediastinum_path"] = mediastinum_path
        result["ggo_path"] = ggo_path
        result["narrow_ggo_path"] = narrow_ggo_path
        return result

    def _convert_zip(self, zip_path: str, output_dir: str) -> List[Dict[str, str]]:
        """
        解压 ZIP 压缩包并批量转换。

        关键改进：按 DICOM 元数据的解剖空间顺序排列切片，而非文件名字母序。
        排序优先级：SliceLocation（Z轴物理位置）→ InstanceNumber（序列编号）→ 文件名字母序。
        正确的排序对 AI 阅片至关重要——微小结节(2-6mm)通常在连续 2-3 层中出现，
        层面打散会导致 AI 无法利用相邻切片的连续性来辅助判断。
        """
        results = []
        temp_dir = tempfile.mkdtemp(prefix="dicom_doctor_")

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(temp_dir)
                logger.info(f"已解压 ZIP 文件到临时目录: {temp_dir}")

            # 递归遍历所有文件
            all_files = []
            for root, dirs, files in os.walk(temp_dir):
                for fname in sorted(files):
                    fpath = os.path.join(root, fname)
                    # 跳过隐藏文件和 macOS 资源文件
                    if fname.startswith(".") or "__MACOSX" in fpath:
                        continue
                    all_files.append(fpath)

            # 第一遍：过滤出 DICOM 文件并预提取排序元数据
            dicom_files_with_meta = []
            skipped = 0
            for fpath in all_files:
                if not _is_dicom_file(fpath):
                    logger.warning(f"跳过非 DICOM 文件: {os.path.basename(fpath)}")
                    skipped += 1
                    continue
                # 预提取排序所需的元数据
                slice_location, instance_number = self._extract_dicom_metadata(fpath)
                dicom_files_with_meta.append((fpath, slice_location, instance_number))

            # 按解剖空间顺序排序（Decision 15）
            # 优先级：SliceLocation（Z轴物理位置）→ InstanceNumber → 文件名
            dicom_files_with_meta = self._sort_by_anatomy(dicom_files_with_meta)

            total_all = len(all_files)
            total_dicom = len(dicom_files_with_meta)
            converted = 0

            logger.info(
                f"DICOM 文件排序完成: 共 {total_dicom} 个 DICOM 文件"
                f"（跳过 {skipped} 个非 DICOM 文件）"
            )

            for i, (fpath, slice_location, instance_number) in enumerate(dicom_files_with_meta, 1):
                dicom_name = os.path.basename(fpath)
                png_name = Path(dicom_name).stem + ".png"
                png_path = os.path.join(output_dir, png_name)

                # 处理文件名冲突：覆盖并记录日志
                if os.path.exists(png_path):
                    logger.info(f"覆盖已有文件: {png_name}")

                success = self._backend.convert(fpath, png_path, window_type=self._window_type)
                if success:
                    if self._separate_dirs:
                        # 分目录模式：将文件移动到窗口子目录
                        reloc = self._relocate_to_window_dirs(output_dir, Path(dicom_name).stem, png_path)
                        if reloc:
                            actual_png_path = reloc["png_path"]
                            mediastinum_path = reloc.get("mediastinum_path", "")
                            ggo_path = reloc.get("ggo_path", "")
                            narrow_ggo_path = reloc.get("narrow_ggo_path", "")
                            # 高质量插值放大
                            self._upscale_if_needed(actual_png_path, mediastinum_path=mediastinum_path)
                        else:
                            actual_png_path = png_path
                            mediastinum_path = ""
                            ggo_path = ""
                            narrow_ggo_path = ""
                            self._upscale_if_needed(actual_png_path)
                    else:
                        # 平铺模式：保持原有行为
                        actual_png_path = png_path
                        self._upscale_if_needed(png_path)
                        mediastinum_path = png_path.replace(".png", "_mediastinum.png")
                        if not os.path.exists(mediastinum_path):
                            mediastinum_path = ""
                        ggo_path = png_path.replace(".png", "_ggo.png")
                        if not os.path.exists(ggo_path):
                            ggo_path = ""
                        narrow_ggo_path = png_path.replace(".png", "_narrow_ggo.png")
                        if not os.path.exists(narrow_ggo_path):
                            narrow_ggo_path = ""

                    converted += 1
                    logger.info(f"转换成功 ({i}/{total_dicom}): {dicom_name} → {os.path.relpath(actual_png_path, output_dir)}")
                    results.append({
                        "dicom_path": fpath,
                        "dicom_name": dicom_name,
                        "png_path": actual_png_path,
                        "mediastinum_path": mediastinum_path,
                        "ggo_path": ggo_path,
                        "narrow_ggo_path": narrow_ggo_path,
                        "slice_location": slice_location,
                        "instance_number": instance_number,
                        "slice_index": "",  # 批量转换后统一回填
                    })
                else:
                    logger.error(f"转换失败 ({i}/{total_dicom}): {dicom_name}")

            # 回填 slice_index（基于解剖空间排序后的序号/总数）
            total_results = len(results)
            for idx, r in enumerate(results, 1):
                r["slice_index"] = f"{idx}/{total_results}"

            logger.info(
                f"ZIP 批量转换完成: 共 {total_all} 个文件，"
                f"DICOM {total_dicom} 个，成功 {converted} 个，"
                f"跳过 {skipped} 个非 DICOM，"
                f"失败 {total_dicom - converted} 个"
            )

            # MIP 重建（可选）
            if self._mip and results:
                mip_generator = MIPGenerator(
                    slab_thickness=self._mip_slabs,
                    min_size=self._min_size,
                )
                # 从排序后的 DICOM 文件列表中提取路径
                sorted_dicom_paths = [r["dicom_path"] for r in results]
                mip_output_dir = os.path.join(output_dir, "mip")
                mip_results = mip_generator.generate(
                    dicom_paths=sorted_dicom_paths,
                    output_dir=mip_output_dir,
                )
                if mip_results:
                    results.extend(mip_results)
                    logger.info(f"MIP 重建完成: 生成 {len(mip_results)} 张 MIP 图")
                else:
                    logger.warning("MIP 重建未生成任何图片")

        finally:
            # 清理临时目录
            shutil.rmtree(temp_dir, ignore_errors=True)

        return results

    @staticmethod
    def _sort_by_anatomy(dicom_files_with_meta: List[tuple]) -> List[tuple]:
        """
        按解剖空间顺序对 DICOM 切片进行排序。

        排序优先级：
          1. SliceLocation（Z轴物理位置，mm）— 最准确
          2. InstanceNumber（CT设备序列编号）— 可靠的备选
          3. 文件名字母序 — 最后兜底

        ZIP 中的 DCM 文件名命名方式不统一（如 IM-0001.dcm、CT.1.dcm），
        字母序不等于解剖空间顺序。例如 IM-0010.dcm 按字母序排在
        IM-0002.dcm 前面，但实际解剖位置可能完全不同。

        Args:
            dicom_files_with_meta: [(文件路径, slice_location, instance_number), ...]

        Returns:
            排序后的列表
        """
        # 检查哪种元数据可用
        has_slice_location = any(
            meta[1] != "" for meta in dicom_files_with_meta
        )
        has_instance_number = any(
            meta[2] != "" for meta in dicom_files_with_meta
        )

        if has_slice_location:
            # 优先按 SliceLocation 排序（升序：从肺尖到肺底）
            logger.info("按 SliceLocation（Z轴物理位置）对切片进行解剖空间排序")

            def sort_key(item):
                fpath, sl, ins = item
                try:
                    return (0, float(sl))
                except (ValueError, TypeError):
                    # SliceLocation 无效的排在最后
                    try:
                        return (1, float(ins))
                    except (ValueError, TypeError):
                        return (2, os.path.basename(fpath))

            dicom_files_with_meta.sort(key=sort_key)

        elif has_instance_number:
            # 备选：按 InstanceNumber 排序
            logger.info("SliceLocation 不可用，按 InstanceNumber（序列编号）对切片排序")

            def sort_key(item):
                fpath, sl, ins = item
                try:
                    return (0, int(ins))
                except (ValueError, TypeError):
                    return (1, os.path.basename(fpath))

            dicom_files_with_meta.sort(key=sort_key)

        else:
            # 兜底：文件名字母序，并输出警告
            logger.warning(
                "⚠ DICOM 文件中未包含 SliceLocation 或 InstanceNumber 元数据，"
                "无法按解剖空间排序，将使用文件名字母序。"
                "切片顺序可能不准确，层面序号仅供参考。"
            )
            dicom_files_with_meta.sort(key=lambda item: os.path.basename(item[0]))

        return dicom_files_with_meta

    def _upscale_if_needed(self, png_path: str, mediastinum_path: str = "") -> None:
        """
        若 PNG 图片尺寸小于 min_size，使用 Lanczos 高质量插值放大。

        CT DICOM 原始矩阵通常为 512×512，对于检测 2-4mm 肺小结节来说
        分辨率偏低。通过高质量插值放大到至少 1024×1024，可以：
        1. 让 AI 有更多像素信息进行分析
        2. 保持影像的锐度和细节（Lanczos 是最佳的下采样/上采样滤波器之一）
        3. 不引入虚假细节（不同于超分 AI，Lanczos 是确定性插值）

        分目录模式下：通过 mediastinum_path 参数直接定位额外窗口文件。
        平铺模式下：通过文件名后缀查找额外窗口文件。

        Args:
            png_path: 主 PNG 文件路径
            mediastinum_path: 纵隔窗文件路径（分目录模式下直接传入）
        """
        if not self._min_size or self._min_size <= 0:
            return

        try:
            from PIL import Image as PILImage

            img = PILImage.open(png_path)
            w, h = img.size

            # 只在图片小于最小尺寸时放大
            if w >= self._min_size and h >= self._min_size:
                return

            # 计算放大倍数（保持宽高比，取较大的倍数以确保两边都 >= min_size）
            scale = max(self._min_size / w, self._min_size / h)
            new_w = int(w * scale)
            new_h = int(h * scale)

            # Lanczos 高质量插值
            img_resized = img.resize((new_w, new_h), PILImage.LANCZOS)
            img_resized.save(png_path)
            logger.info(
                f"  高质量放大: {w}×{h} → {new_w}×{new_h} "
                f"(Lanczos, {scale:.1f}x)"
            )

            if self._separate_dirs:
                # 分目录模式：通过传入的路径查找额外窗口文件
                # 主文件所在的基础目录（如 png/）
                base_dir = os.path.dirname(os.path.dirname(png_path))
                base_name = os.path.basename(png_path)
                for wtype in WINDOW_PRESETS:
                    extra_path_in_dir = os.path.join(base_dir, wtype, base_name)
                    if extra_path_in_dir != png_path and os.path.exists(extra_path_in_dir):
                        extra_img = PILImage.open(extra_path_in_dir)
                        extra_resized = extra_img.resize((new_w, new_h), PILImage.LANCZOS)
                        extra_resized.save(extra_path_in_dir)
                        logger.debug(f"  {wtype} 窗也已放大: {new_w}×{new_h}")
            else:
                # 平铺模式：通过文件名后缀查找额外窗口文件
                for wtype in WINDOW_PRESETS:
                    extra_path = png_path.replace(".png", f"_{wtype}.png")
                    if os.path.exists(extra_path):
                        extra_img = PILImage.open(extra_path)
                        extra_resized = extra_img.resize((new_w, new_h), PILImage.LANCZOS)
                        extra_resized.save(extra_path)
                        logger.debug(f"  {wtype} 窗也已放大: {new_w}×{new_h}")

        except ImportError:
            logger.warning("Pillow 未安装，无法执行图片放大")
        except Exception as e:
            logger.warning(f"图片放大失败（不影响主流程）: {e}")

    @staticmethod
    def _extract_dicom_metadata(dicom_path: str) -> tuple:
        """
        从 DICOM 文件提取层面相关元数据。

        提取 SliceLocation（切片在Z轴方向的物理位置，mm）和
        InstanceNumber（切片在序列中的编号）。

        Args:
            dicom_path: DICOM 文件路径

        Returns:
            (slice_location, instance_number) 元组，提取失败时返回空字符串
        """
        slice_location = ""
        instance_number = ""

        # 优先尝试 pydicom（更可靠地读取 DICOM 标签）
        try:
            import pydicom
            ds = pydicom.dcmread(dicom_path, stop_before_pixels=True)
            if hasattr(ds, 'SliceLocation'):
                slice_location = str(round(float(ds.SliceLocation), 2))
            if hasattr(ds, 'InstanceNumber'):
                instance_number = str(ds.InstanceNumber)
            return (slice_location, instance_number)
        except Exception:
            pass

        # 备选：尝试 SimpleITK 读取元数据
        try:
            import SimpleITK as sitk
            reader = sitk.ImageFileReader()
            reader.SetFileName(dicom_path)
            reader.LoadPrivateTagsOn()
            reader.ReadImageInformation()
            # SliceLocation: (0020,1041), InstanceNumber: (0020,0013)
            if reader.HasMetaDataKey("0020|1041"):
                slice_location = str(round(float(reader.GetMetaData("0020|1041").strip()), 2))
            if reader.HasMetaDataKey("0020|0013"):
                instance_number = reader.GetMetaData("0020|0013").strip()
        except Exception:
            pass

        return (slice_location, instance_number)


class MIPGenerator:
    """
    MIP（最大密度投影）图像生成器。

    MIP（Maximum Intensity Projection）是放射科筛查肺结节的常用技术：
    将连续多层 DICOM 切片的像素值沿 Z 轴取最大值，投影到一张 2D 图上。

    优势：
    - 将微小结节（2-6mm）"放大"为更明显的高密度亮点
    - 减少总阅片数量（如 800 层 → 160 张 MIP，slab=5）
    - 在 MIP 图上，结节呈现为圆形高密度影，而血管呈现为条状/分支状

    实现方式：Slab MIP（滑动窗口），每 N 层（默认 5 层）生成一张 MIP。
    """

    def __init__(self, slab_thickness: int = 5, min_size: int = 1024):
        """
        Args:
            slab_thickness: 每个 slab 包含的层数，默认 5
            min_size: MIP 图的最小输出尺寸（像素），默认 1024
        """
        self._slab_thickness = max(2, min(slab_thickness, 20))
        self._min_size = min_size

    def generate(self, dicom_paths: List[str], output_dir: str) -> List[Dict[str, str]]:
        """
        从一组已排序的 DICOM 文件生成 Slab MIP 图像。

        Args:
            dicom_paths: 按解剖空间排序的 DICOM 文件路径列表
            output_dir: MIP 图像输出目录

        Returns:
            MIP 结果列表，每项包含:
              - dicom_path: 空（MIP 无对应单个 DICOM）
              - dicom_name: MIP slab 描述
              - png_path: MIP PNG 路径
              - is_mip: True
              - mip_range: slab 范围描述（如 "1-5"）
        """
        if len(dicom_paths) < 2:
            logger.warning("DICOM 文件数量不足 2 个，无法生成 MIP")
            return []

        os.makedirs(output_dir, exist_ok=True)

        results = []
        total = len(dicom_paths)
        slab_count = 0

        logger.info(
            f"开始 MIP 重建: 共 {total} 层, slab 厚度={self._slab_thickness} 层, "
            f"预计生成 {(total + self._slab_thickness - 1) // self._slab_thickness} 张 MIP"
        )

        for start_idx in range(0, total, self._slab_thickness):
            end_idx = min(start_idx + self._slab_thickness, total)
            slab_paths = dicom_paths[start_idx:end_idx]

            if len(slab_paths) < 2:
                # 最后不足 2 层的 slab 跳过
                logger.debug(f"跳过不足 2 层的 slab: {start_idx + 1}-{end_idx}")
                continue

            # 生成 MIP
            slab_start = start_idx + 1  # 1-based
            slab_end = end_idx
            mip_filename = f"mip_{slab_start:03d}-{slab_end:03d}.png"
            mip_path = os.path.join(output_dir, mip_filename)

            success = self._generate_slab_mip(slab_paths, mip_path)
            if success:
                slab_count += 1
                results.append({
                    "dicom_path": "",
                    "dicom_name": f"MIP (层 {slab_start}-{slab_end}/{total})",
                    "png_path": mip_path,
                    "mediastinum_path": "",
                    "ggo_path": "",
                    "slice_location": "",
                    "instance_number": "",
                    "slice_index": f"MIP-{slab_count}",
                    "is_mip": True,
                    "mip_range": f"{slab_start}-{slab_end}",
                })
                logger.debug(f"MIP slab {slab_start}-{slab_end}: 成功")
            else:
                logger.warning(f"MIP slab {slab_start}-{slab_end}: 失败")

        logger.info(f"MIP 重建完成: 生成 {slab_count} 张 MIP 图 → {output_dir}")
        return results

    def _generate_slab_mip(self, slab_paths: List[str], output_path: str) -> bool:
        """
        对一个 slab（连续多层）生成 MIP 投影。

        在 HU 值空间（float64）计算最大值投影，然后应用肺窗窗宽窗位转换为 8-bit PNG。

        Args:
            slab_paths: 当前 slab 包含的 DICOM 文件路径列表
            output_path: 输出 PNG 路径

        Returns:
            是否成功
        """
        try:
            import numpy as np
            from PIL import Image as PILImage

            arrays = []

            # 读取每层的像素数据
            for dicom_path in slab_paths:
                array = self._read_dicom_pixels(dicom_path)
                if array is not None:
                    arrays.append(array)

            if len(arrays) < 2:
                return False

            # 确保所有数组形状一致
            shapes = set(a.shape for a in arrays)
            if len(shapes) > 1:
                # 形状不一致，取最小公共尺寸
                min_h = min(a.shape[0] for a in arrays)
                min_w = min(a.shape[1] for a in arrays)
                arrays = [a[:min_h, :min_w] for a in arrays]

            # 沿 Z 轴取最大值（MIP 核心操作）
            stacked = np.stack(arrays, axis=0)  # shape: (N, H, W)
            mip_array = np.max(stacked, axis=0)  # shape: (H, W)

            # 应用肺窗窗宽窗位
            wc, ww = WINDOW_PRESETS["lung"]
            lower = wc - ww / 2.0
            upper = wc + ww / 2.0
            mip_windowed = np.clip(mip_array, lower, upper)
            mip_windowed = ((mip_windowed - lower) / (upper - lower) * 255.0).astype(np.uint8)

            # 保存 PNG
            img = PILImage.fromarray(mip_windowed)

            # 如果需要放大
            w, h = img.size
            if self._min_size and self._min_size > 0 and (w < self._min_size or h < self._min_size):
                scale = max(self._min_size / w, self._min_size / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), PILImage.LANCZOS)

            img.save(output_path)
            return True

        except Exception as e:
            logger.warning(f"MIP 生成失败: {e}")
            return False

    @staticmethod
    def _read_dicom_pixels(dicom_path: str):
        """
        读取 DICOM 文件的原始像素数据（HU 值空间）。

        优先使用 pydicom，备选 SimpleITK。

        Args:
            dicom_path: DICOM 文件路径

        Returns:
            float64 类型的 2D numpy 数组，失败返回 None
        """
        import numpy as np

        # 优先尝试 pydicom
        try:
            import pydicom
            ds = pydicom.dcmread(dicom_path)
            array = ds.pixel_array.astype(np.float64)

            # 应用 RescaleSlope 和 RescaleIntercept 转换为 HU 值
            slope = float(getattr(ds, 'RescaleSlope', 1))
            intercept = float(getattr(ds, 'RescaleIntercept', 0))
            array = array * slope + intercept

            # 处理多帧
            if array.ndim == 3:
                array = array[0]

            return array
        except Exception:
            pass

        # 备选：SimpleITK
        try:
            import SimpleITK as sitk
            image = sitk.ReadImage(dicom_path)
            array = sitk.GetArrayFromImage(image).astype(np.float64)
            if array.ndim == 3:
                array = array[0]
            return array
        except Exception:
            pass

        return None


def extract_patient_info(dicom_dir: str) -> Dict[str, str]:
    """
    从 DICOM 目录中提取患者基本信息。

    读取目录中第一个可解析的 DICOM 文件，提取：
    - PatientName（脱敏处理：仅保留姓氏首字 + **）
    - PatientID（脱敏处理：保留前 2 位 + ***）
    - PatientSex
    - PatientBirthDate（仅保留年份）
    - StudyDate（检查日期）
    - InstitutionName（检查机构）
    - StudyDescription（检查描述）

    Args:
        dicom_dir: DICOM 文件所在目录路径

    Returns:
        字典，包含提取到的患者信息（缺失字段不包含在内）
    """
    info: Dict[str, str] = {}
    try:
        import pydicom
    except ImportError:
        logger.debug("pydicom 未安装，无法提取患者信息")
        return info

    # 找到第一个可读的 DICOM 文件
    ds = None
    dicom_path = Path(dicom_dir)
    candidates = sorted(dicom_path.glob("**/*.dcm"))
    if not candidates:
        # 尝试所有文件
        candidates = sorted(f for f in dicom_path.rglob("*") if f.is_file())

    for fpath in candidates[:10]:  # 最多尝试 10 个
        try:
            ds = pydicom.dcmread(str(fpath), stop_before_pixels=True)
            break
        except Exception:
            continue

    if ds is None:
        return info

    # 提取并脱敏患者姓名
    patient_name = str(getattr(ds, "PatientName", "")).strip()
    if patient_name:
        # 脱敏：保留首字 + **
        first_char = patient_name[0] if patient_name else ""
        info["patient_name"] = f"{first_char}**"

    # 患者 ID（脱敏）
    patient_id = str(getattr(ds, "PatientID", "")).strip()
    if patient_id:
        visible = patient_id[:2] if len(patient_id) > 2 else patient_id[0]
        info["patient_id"] = f"{visible}***"

    # 性别
    sex_raw = str(getattr(ds, "PatientSex", "")).strip().upper()
    sex_map = {"M": "男", "F": "女", "O": "其他"}
    if sex_raw in sex_map:
        info["patient_sex"] = sex_map[sex_raw]

    # 出生日期 → 仅保留年份
    birth_date = str(getattr(ds, "PatientBirthDate", "")).strip()
    if birth_date and len(birth_date) >= 4:
        info["birth_year"] = birth_date[:4]

    # 检查日期
    study_date = str(getattr(ds, "StudyDate", "")).strip()
    if study_date and len(study_date) == 8:
        info["study_date"] = f"{study_date[:4]}-{study_date[4:6]}-{study_date[6:8]}"

    # 检查机构
    institution = str(getattr(ds, "InstitutionName", "")).strip()
    if institution:
        info["institution"] = institution

    # 检查描述
    study_desc = str(getattr(ds, "StudyDescription", "")).strip()
    if study_desc:
        info["study_description"] = study_desc

    logger.info(f"已提取患者信息: {list(info.keys())}")
    return info
