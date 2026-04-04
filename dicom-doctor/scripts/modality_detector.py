#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影像类型自动识别模块

从 DICOM 元数据自动判断影像类型（胸部CT、腹部CT、头颅MRI、腹部MRI等），
并提供 ImagingProfile 策略模型，为不同影像类型封装窗位、Prompt、报告配置。
"""

import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("dicom-doctor.modality")


class ImagingType(str, Enum):
    """影像类型枚举"""
    CHEST_CT = "chest_ct"
    ABDOMEN_CT = "abdomen_ct"
    BRAIN_MRI = "brain_mri"
    ABDOMEN_MRI = "abdomen_mri"
    GENERIC = "generic"

    @property
    def display_name(self) -> str:
        """中文显示名"""
        _names = {
            "chest_ct": "胸部CT",
            "abdomen_ct": "腹部CT",
            "brain_mri": "头颅MRI",
            "abdomen_mri": "腹部MRI",
            "generic": "通用影像",
        }
        return _names.get(self.value, self.value)


@dataclass
class ImagingProfile:
    """
    影像类型策略配置数据模型。

    为每种影像类型封装完整的处理策略，包括窗位预设、Prompt模板、
    MIP/GGO标志、分级系统和报告分区等。
    """
    imaging_type: ImagingType
    display_name: str
    window_presets: Dict[str, Tuple[int, int]]  # {窗位名: (WC, WW)}
    primary_window: str  # 主要窗位名
    use_mip: bool  # 是否启用 MIP 重建
    use_ggo_window: bool  # 是否启用 GGO 窗（仅胸部CT）
    classification_system: str  # 分级系统名称，如 "Lung-RADS" / "LI-RADS" / ""
    review_prompt_template: str  # 阅片 Prompt 模板
    summary_prompt_template: str  # 汇总 Prompt 模板
    mip_prompt_template: Optional[str]  # MIP 阅片 Prompt 模板（可选）
    report_sections: List[str]  # 报告分区列表


def detect_mri_sequence(ds) -> str:
    """
    识别 MRI 序列类型。

    从 DICOM 数据集的 SeriesDescription 和 SequenceName 字段
    识别常见 MRI 序列类型。

    Args:
        ds: pydicom Dataset 对象

    Returns:
        序列类型字符串（T1/T2/FLAIR/DWI/MRA/UNKNOWN）
    """
    series_desc = str(getattr(ds, "SeriesDescription", "")).upper()
    seq_name = str(getattr(ds, "SequenceName", "")).upper()
    combined = series_desc + " " + seq_name

    if "FLAIR" in combined:
        return "FLAIR"
    if "DWI" in combined or "DIFFUSION" in combined:
        return "DWI"
    if "MRA" in combined or "ANGIO" in combined:
        return "MRA"
    if "T2" in combined:
        return "T2"
    if "T1" in combined:
        return "T1"
    return "UNKNOWN"


def _classify_single_dicom(dicom_path: str) -> ImagingType:
    """
    对单个 DICOM 文件进行影像类型分类。

    Args:
        dicom_path: DICOM 文件路径

    Returns:
        ImagingType 枚举值
    """
    try:
        import pydicom
        ds = pydicom.dcmread(dicom_path, stop_before_pixels=True)
    except Exception as e:
        logger.debug(f"无法读取 DICOM 元数据: {dicom_path}: {e}")
        return ImagingType.GENERIC

    modality = str(getattr(ds, "Modality", "")).upper().strip()
    body_part = str(getattr(ds, "BodyPartExamined", "")).upper().strip()
    study_desc = str(getattr(ds, "StudyDescription", "")).upper()
    series_desc = str(getattr(ds, "SeriesDescription", "")).upper()
    combined_desc = study_desc + " " + series_desc

    # CT 类影像
    if modality == "CT":
        # 胸部 CT
        if body_part == "CHEST" or any(
            kw in combined_desc for kw in ["CHEST", "THORAX", "LUNG", "胸部", "肺"]
        ):
            return ImagingType.CHEST_CT
        # 腹部 CT
        if body_part == "ABDOMEN" or any(
            kw in combined_desc for kw in ["ABDOMEN", "ABDOMINAL", "腹部", "肝", "胆", "胰"]
        ):
            return ImagingType.ABDOMEN_CT
        # CT 但无法确定部位，默认胸部CT（最常见的CT检查）
        logger.debug(f"CT 影像但部位不明确 (BodyPart={body_part})，默认为胸部CT")
        return ImagingType.CHEST_CT

    # MRI 类影像
    if modality == "MR":
        # 头颅 MRI
        if body_part in ("HEAD", "BRAIN") or any(
            kw in combined_desc for kw in ["BRAIN", "HEAD", "CRANIAL", "脑", "头颅", "颅脑"]
        ):
            return ImagingType.BRAIN_MRI
        # 腹部 MRI
        if body_part in ("ABDOMEN", "LIVER") or any(
            kw in combined_desc for kw in ["ABDOMEN", "LIVER", "腹部", "肝脏", "MRCP"]
        ):
            return ImagingType.ABDOMEN_MRI
        # MRI 但无法确定部位
        logger.debug(f"MRI 影像但部位不明确 (BodyPart={body_part})，返回 GENERIC")
        return ImagingType.GENERIC

    # 其他 modality
    logger.debug(f"未知 Modality: {modality}")
    return ImagingType.GENERIC


def detect_imaging_type(dicom_dir: str) -> ImagingType:
    """
    从 DICOM 文件集合的元数据中自动判断影像类型。

    采样前 5 个 DICOM 文件进行类型识别，取出现次数最多的类型
    作为最终结果（投票法），以应对混合序列场景。

    如果 DICOM 元数据无法识别（如缺少 Modality/BodyPart），
    会从输入路径的文件名中推断影像类型。

    Args:
        dicom_dir: DICOM 文件所在目录路径（或单个 DICOM 文件路径，或 ZIP 文件路径）

    Returns:
        ImagingType 枚举值
    """
    dicom_dir_path = dicom_dir

    # 首先从文件名/路径中推断影像类型（作为兜底或优先线索）
    path_hint = _infer_type_from_path(dicom_dir_path)

    if os.path.isfile(dicom_dir_path):
        # 如果是 ZIP 文件，需要先解压采样
        if dicom_dir_path.lower().endswith(".zip"):
            result = _detect_from_zip(dicom_dir_path, path_hint)
            logger.info(
                f"影像类型识别完成：{result.display_name}（ZIP 文件模式）"
            )
            return result

        # 单个文件
        result = _classify_single_dicom(dicom_dir_path)
        if result == ImagingType.GENERIC and path_hint != ImagingType.GENERIC:
            logger.info(f"DICOM 元数据识别为 GENERIC，根据文件名推断为 {path_hint.display_name}")
            result = path_hint
        logger.info(
            f"影像类型识别完成：{result.display_name}（单文件模式）"
        )
        return result

    # 目录模式：采样前 5 个 DICOM 文件
    dicom_files = []
    for root, dirs, files in os.walk(dicom_dir_path):
        for fname in sorted(files):
            if fname.startswith(".") or "__MACOSX" in root:
                continue
            fpath = os.path.join(root, fname)
            # 简单检查文件是否可能为 DICOM
            try:
                with open(fpath, "rb") as f:
                    f.seek(128)
                    if f.read(4) == b"DICM":
                        dicom_files.append(fpath)
            except Exception:
                continue
            if len(dicom_files) >= 5:
                break
        if len(dicom_files) >= 5:
            break

    if not dicom_files:
        if path_hint != ImagingType.GENERIC:
            logger.warning(f"未找到有效的 DICOM 文件，根据文件名推断为 {path_hint.display_name}")
            return path_hint
        logger.warning("未找到有效的 DICOM 文件，返回 GENERIC 类型")
        return ImagingType.GENERIC

    # 投票法
    votes = [_classify_single_dicom(f) for f in dicom_files]
    counter = Counter(votes)
    winner, count = counter.most_common(1)[0]

    # 如果投票结果为 GENERIC 但路径有线索，使用路径线索
    if winner == ImagingType.GENERIC and path_hint != ImagingType.GENERIC:
        logger.info(f"DICOM 元数据投票为 GENERIC，根据文件名推断为 {path_hint.display_name}")
        winner = path_hint

    logger.info(
        f"影像类型识别完成：{winner.display_name}"
        f"（采样 {len(dicom_files)} 个文件，{count}/{len(votes)} 票）"
    )
    return winner


def _infer_type_from_path(file_path: str) -> ImagingType:
    """
    从文件路径/文件名推断影像类型。

    常见文件名模式：
    - "岚天-胸部CT-20260110.zip" → 胸部CT
    - "张三_腹部CT_2025.zip" → 腹部CT
    - "李四-头颅MRI.zip" → 头颅MRI

    Args:
        file_path: 文件路径

    Returns:
        推断的 ImagingType，无法推断时返回 GENERIC
    """
    fname = os.path.basename(file_path).upper()
    # 同时检查目录名（ZIP 解压后的目录可能含线索）
    dir_name = os.path.basename(os.path.dirname(file_path)).upper()
    combined = fname + " " + dir_name

    # 胸部CT关键词
    chest_keywords = ["胸部CT", "胸部", "CHEST", "THORAX", "LUNG", "肺", "肺部CT", "胸CT"]
    for kw in chest_keywords:
        if kw.upper() in combined:
            return ImagingType.CHEST_CT

    # 腹部CT关键词
    abdomen_ct_keywords = ["腹部CT", "腹部", "ABDOMEN", "ABDOMINAL", "肝", "胆", "胰", "腹CT"]
    for kw in abdomen_ct_keywords:
        if kw.upper() in combined:
            return ImagingType.ABDOMEN_CT

    # 头颅MRI关键词
    brain_keywords = ["头颅MRI", "头颅", "脑", "BRAIN", "HEAD", "颅脑", "头MRI", "脑MRI"]
    for kw in brain_keywords:
        if kw.upper() in combined:
            return ImagingType.BRAIN_MRI

    # 腹部MRI关键词
    abdomen_mri_keywords = ["腹部MRI", "肝脏MRI", "MRCP"]
    for kw in abdomen_mri_keywords:
        if kw.upper() in combined:
            return ImagingType.ABDOMEN_MRI

    return ImagingType.GENERIC


def _detect_from_zip(zip_path: str, path_hint: ImagingType) -> ImagingType:
    """
    从 ZIP 文件中采样 DICOM 文件进行影像类型识别。

    Args:
        zip_path: ZIP 文件路径
        path_hint: 从文件名推断的类型线索

    Returns:
        ImagingType 枚举值
    """
    import tempfile
    import zipfile

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # 采样最多 5 个可能的 DICOM 文件
            candidates = [
                name for name in zf.namelist()
                if not name.startswith("__MACOSX")
                and not os.path.basename(name).startswith(".")
                and not name.endswith("/")
            ]

            if not candidates:
                if path_hint != ImagingType.GENERIC:
                    return path_hint
                return ImagingType.GENERIC

            # 创建临时目录，解压采样文件
            temp_dir = tempfile.mkdtemp(prefix="dicom_detect_")
            try:
                sample_files = candidates[:5]
                for name in sample_files:
                    zf.extract(name, temp_dir)

                votes = []
                for name in sample_files:
                    fpath = os.path.join(temp_dir, name)
                    if os.path.isfile(fpath):
                        # 检查是否为 DICOM
                        try:
                            with open(fpath, "rb") as f:
                                f.seek(128)
                                if f.read(4) == b"DICM":
                                    votes.append(_classify_single_dicom(fpath))
                        except Exception:
                            continue

                if not votes:
                    if path_hint != ImagingType.GENERIC:
                        return path_hint
                    return ImagingType.GENERIC

                counter = Counter(votes)
                winner, count = counter.most_common(1)[0]

                if winner == ImagingType.GENERIC and path_hint != ImagingType.GENERIC:
                    logger.info(f"ZIP 内 DICOM 投票为 GENERIC，根据文件名推断为 {path_hint.display_name}")
                    return path_hint

                return winner
            finally:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

    except Exception as e:
        logger.warning(f"ZIP 文件影像类型识别失败: {e}")
        if path_hint != ImagingType.GENERIC:
            return path_hint
        return ImagingType.GENERIC


def get_imaging_profile(imaging_type: ImagingType) -> ImagingProfile:
    """
    工厂函数：为指定影像类型返回预定义的 ImagingProfile 实例。

    Args:
        imaging_type: 影像类型枚举值

    Returns:
        ImagingProfile 实例
    """
    from prompt_templates import (
        chest_ct, abdomen_ct, brain_mri, abdomen_mri, generic
    )

    _PROFILES = {
        ImagingType.CHEST_CT: ImagingProfile(
            imaging_type=ImagingType.CHEST_CT,
            display_name="胸部CT",
            window_presets={
                "lung": (-600, 1500),
                "mediastinum": (40, 400),
                "bone": (400, 1800),
                "soft_tissue": (50, 350),
                "ggo": (-600, 600),
                "narrow_ggo": (-550, 400),
            },
            primary_window="lung",
            use_mip=True,
            use_ggo_window=True,
            classification_system="Lung-RADS",
            review_prompt_template=chest_ct.REVIEW_PROMPT,
            summary_prompt_template=chest_ct.SUMMARY_PROMPT,
            mip_prompt_template=chest_ct.MIP_PROMPT,
            report_sections=["肺野", "纵隔", "骨骼", "扫及区域"],
        ),
        ImagingType.ABDOMEN_CT: ImagingProfile(
            imaging_type=ImagingType.ABDOMEN_CT,
            display_name="腹部CT",
            window_presets={
                "abdomen": (40, 350),
                "liver": (70, 150),
                "bone": (400, 1800),
            },
            primary_window="abdomen",
            use_mip=False,
            use_ggo_window=False,
            classification_system="LI-RADS",
            review_prompt_template=abdomen_ct.REVIEW_PROMPT,
            summary_prompt_template=abdomen_ct.SUMMARY_PROMPT,
            mip_prompt_template=None,
            report_sections=["肝脏", "胆囊", "胰腺", "脾脏", "双肾", "肾上腺", "腹主动脉", "淋巴结", "扫及区域"],
        ),
        ImagingType.BRAIN_MRI: ImagingProfile(
            imaging_type=ImagingType.BRAIN_MRI,
            display_name="头颅MRI",
            window_presets={},  # MRI 优先使用 DICOM 自带窗位
            primary_window="default",
            use_mip=False,
            use_ggo_window=False,
            classification_system="Fazekas",
            review_prompt_template=brain_mri.REVIEW_PROMPT,
            summary_prompt_template=brain_mri.SUMMARY_PROMPT,
            mip_prompt_template=None,
            report_sections=["脑实质", "基底节及丘脑", "脑室系统", "中线结构", "鞍区", "小脑及脑干", "颅骨及软组织", "扫及区域"],
        ),
        ImagingType.ABDOMEN_MRI: ImagingProfile(
            imaging_type=ImagingType.ABDOMEN_MRI,
            display_name="腹部MRI",
            window_presets={},  # MRI 优先使用 DICOM 自带窗位
            primary_window="default",
            use_mip=False,
            use_ggo_window=False,
            classification_system="LI-RADS",
            review_prompt_template=abdomen_mri.REVIEW_PROMPT,
            summary_prompt_template=abdomen_mri.SUMMARY_PROMPT,
            mip_prompt_template=None,
            report_sections=["肝脏", "胆道系统", "胰腺", "脾脏", "双肾", "腹腔", "扫及区域"],
        ),
        ImagingType.GENERIC: ImagingProfile(
            imaging_type=ImagingType.GENERIC,
            display_name="通用影像",
            window_presets={},  # 自适应窗位
            primary_window="default",
            use_mip=False,
            use_ggo_window=False,
            classification_system="",
            review_prompt_template=generic.REVIEW_PROMPT,
            summary_prompt_template=generic.SUMMARY_PROMPT,
            mip_prompt_template=None,
            report_sections=["影像所见"],
        ),
    }

    return _PROFILES[imaging_type]
