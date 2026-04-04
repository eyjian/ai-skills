#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM Doctor — AI 辅助医学影像阅片工具

四阶段流水线：
  输入（DICOM/ZIP）→ 转换（PNG）→ [可选]增强（超分）→ AI 阅片 → PDF 报告

自修复能力：
  - 自动检测并安装缺失的 Python 依赖
  - 各阶段失败时优雅降级，不直接向用户报错退出
  - 自动重试关键步骤
"""

import argparse
import importlib
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dicom-doctor")

# Skill 版本号（SemVer）
from version import __version__


# ========================
# 阶段计时数据类
# ========================

@dataclass
class PipelineTimings:
    """流水线各阶段耗时统计"""
    dicom_parse_seconds: float = 0.0    # DICOM 解析耗时（秒）
    png_convert_seconds: float = 0.0    # PNG 转换耗时（秒）
    ai_review_seconds: float = 0.0      # AI 阅片耗时（秒）
    pdf_generate_seconds: float = 0.0   # PDF 生成耗时（秒）
    total_seconds: float = 0.0          # 总耗时（秒）
    dicom_file_count: int = 0           # 处理的 DICOM 文件总数
    png_file_count: int = 0             # 输出的 PNG 文件总数

# ========================
# 自修复：依赖自动检测与安装（使用镜像感知模块）
# ========================

from pip_utils import pip_install as _pip_install_with_mirror, ensure_pip, check_python_version, get_mirror_status

# 核心依赖映射：{import名: pip包名}
CORE_DEPENDENCIES = {
    "pydicom": "pydicom>=2.4.0",
    "PIL": "Pillow>=10.0.0",
    "reportlab": "reportlab>=4.0.0",
}

# 可选依赖映射（DICOM 转换后端，至少需要安装一个）
OPTIONAL_BACKENDS = {
    "SimpleITK": "SimpleITK>=2.3.0",
    "dicom2jpg": "dicom2jpg>=0.1.5",
}


def _pip_install(package_spec: str) -> bool:
    """
    通过 pip 安装指定包（自动选择最佳镜像源）。

    Args:
        package_spec: pip 包规格（如 'Pillow>=10.0.0'）

    Returns:
        是否安装成功
    """
    return _pip_install_with_mirror(package_spec)


def _check_import(module_name: str) -> bool:
    """检查模块是否可导入"""
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def _ensure_dependencies() -> bool:
    """
    检测并自动安装缺失依赖（镜像感知）。

    Returns:
        核心依赖是否全部就绪
    """
    # 0. 前置检查：Python 版本和 pip
    if not check_python_version((3, 8)):
        return False
    if not ensure_pip():
        return False

    logger.info(f"[自修复] {get_mirror_status()}")

    all_ok = True

    # 1. 检查并安装核心依赖
    for module_name, pip_spec in CORE_DEPENDENCIES.items():
        if not _check_import(module_name):
            logger.warning(f"[自修复] 缺失核心依赖: {module_name}")
            if _pip_install(pip_spec):
                # 安装后重新验证
                if _check_import(module_name):
                    logger.info(f"[自修复] 核心依赖已修复: {module_name}")
                else:
                    logger.error(f"[自修复] 安装后仍无法导入: {module_name}")
                    all_ok = False
            else:
                all_ok = False

    # 2. 检查 DICOM 转换后端（至少需要一个可用）
    import shutil
    has_dcmtk = shutil.which("dcm2pnm") is not None
    has_any_backend = has_dcmtk

    if not has_any_backend:
        for module_name, pip_spec in OPTIONAL_BACKENDS.items():
            if _check_import(module_name):
                has_any_backend = True
                break

    if not has_any_backend:
        logger.warning("[自修复] 未检测到任何 DICOM 转换后端，尝试安装 SimpleITK ...")
        # 优先安装 SimpleITK（质量较高且纯 Python）
        if _pip_install(OPTIONAL_BACKENDS["SimpleITK"]):
            if _check_import("SimpleITK"):
                logger.info("[自修复] 已自动安装 SimpleITK 作为 DICOM 转换后端")
                has_any_backend = True

    if not has_any_backend:
        logger.warning("[自修复] 尝试安装 dicom2jpg 作为备选后端 ...")
        if _pip_install(OPTIONAL_BACKENDS["dicom2jpg"]):
            if _check_import("dicom2jpg"):
                logger.info("[自修复] 已自动安装 dicom2jpg 作为 DICOM 转换后端")
                has_any_backend = True

    if not has_any_backend:
        logger.error(
            "[自修复] 无法自动安装任何 DICOM 转换后端。\n"
            "请手动执行以下任一命令：\n"
            "  pip install SimpleITK\n"
            "  pip install dicom2jpg\n"
            "  或安装 DCMTK: sudo apt install dcmtk"
        )
        all_ok = False

    return all_ok


# ========================
# 延迟导入（确保自修复运行后再导入业务模块）
# ========================

def _lazy_import_modules():
    """
    延迟导入业务模块，在依赖检查通过后调用。
    这样即使首次 import 失败，自修复安装依赖后再导入也能成功。
    """
    global DicomConverter, ImageEnhancer, AIReviewer, ReportGenerator
    global ReviewConclusion, load_review_results_json, validate_review_results
    global detect_imaging_type, get_imaging_profile, ImagingType
    global run_auto_review_pipeline
    from converter import DicomConverter
    from enhancer import ImageEnhancer
    from reviewer import (
        AIReviewer,
        ReviewConclusion,
        load_review_results_json,
        validate_review_results,
        cross_validate_cad_vs_review,
    )
    from report_generator import ReportGenerator
    from modality_detector import detect_imaging_type, get_imaging_profile, ImagingType
    from auto_review_batches import run_auto_review_pipeline


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="DICOM Doctor — AI 辅助医学影像阅片工具"
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        type=str,
        default=None,
        help="DICOM 文件路径或 ZIP 压缩包路径（位置参数，也可用 --input 替代）",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        dest="input_named",
        help="DICOM 文件路径或 ZIP 压缩包路径（与位置参数 input_path 二选一即可）",
    )
    parser.add_argument(
        "--output-dir", "--output",
        type=str,
        default=None,
        help="PNG 图片和报告的输出目录（默认为输入文件同级目录）",
    )
    parser.add_argument(
        "--enhance",
        action="store_true",
        default=False,
        help="启用 Real-ESRGAN 超分辨率增强",
    )
    parser.add_argument(
        "--enhance-scale",
        type=int,
        default=2,
        choices=[2, 4],
        help="超分增强放大倍数（默认 2）",
    )
    parser.add_argument(
        "--report-path",
        type=str,
        default=None,
        help="PDF 报告输出路径（默认自动生成）",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=2048,
        help="PNG 输出的最小尺寸（像素），小于此值的图片将用 Lanczos 高质量插值放大（默认 2048，设为 0 保持原始分辨率）",
    )
    parser.add_argument(
        "--window",
        type=str,
        default="lung",
        choices=["lung", "mediastinum", "bone", "soft_tissue", "ggo", "all"],
        help="CT 影像的窗口类型（默认 lung 肺窗）。可选：lung（肺窗）、mediastinum（纵隔窗）、bone（骨窗）、soft_tissue（软组织窗）、ggo（GGO 磨玻璃结节专用窗）、all（同时输出所有窗口版本）",
    )
    parser.add_argument(
        "--separate-window-dirs",
        action="store_true",
        default=True,
        dest="separate_window_dirs",
        help="将不同窗口类型的 PNG 文件分别存放到独立子目录（默认启用）",
    )
    parser.add_argument(
        "--no-separate-window-dirs",
        action="store_false",
        dest="separate_window_dirs",
        help="所有窗口类型的 PNG 文件平铺在同一目录（禁用分目录）",
    )
    parser.add_argument(
        "--mip",
        action="store_true",
        default=False,
        dest="mip",
        help="启用 MIP（最大密度投影）重建，显著提高微小肺结节检出率",
    )
    parser.add_argument(
        "--no-mip",
        action="store_false",
        dest="mip",
        help="禁用 MIP 重建（默认）",
    )
    parser.add_argument(
        "--mip-slabs",
        type=int,
        default=5,
        help="MIP 的 slab 厚度（层数），默认 5，范围 2-20。对 1mm 层距 CT，5 层覆盖 5mm",
    )
    parser.add_argument(
        "--imaging-type",
        type=str,
        default=None,
        choices=["chest_ct", "abdomen_ct", "brain_mri", "abdomen_mri", "generic"],
        help="手动指定影像类型以覆盖自动检测。可选值：chest_ct（胸部CT）、abdomen_ct（腹部CT）、brain_mri（头颅MRI）、abdomen_mri（腹部MRI）、generic（通用）",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
        help="阅片使用的大模型名称（如 claude-4.6-opus、GPT-5.4），记录到 PDF 报告中",
    )
    parser.add_argument(
        "--review-results-json",
        type=str,
        default=None,
        help="宿主 AI 完成逐张阅片后生成的 review_results.json；提供后将直接加载该结果并生成正式报告",
    )
    parser.add_argument(
        "--strict-review",
        action="store_true",
        default=False,
        help="要求所有切片都已有明确阅片结果；若仍存在‘无法识别/待检视’条目，则拒绝生成最终报告并以非零状态退出",
    )
    parser.add_argument(
        "--auto-review-model",
        type=str,
        default=None,
        help="可选：自动调用外部视觉模型逐批回填 review_batch_templates 并合并出 review_results.json",
    )
    parser.add_argument(
        "--auto-review-api-base",
        type=str,
        default="https://api.openai.com/v1",
        help="外部视觉模型的 OpenAI 兼容接口基地址，默认 https://api.openai.com/v1",
    )
    parser.add_argument(
        "--auto-review-api-key",
        type=str,
        default=None,
        help="外部视觉模型 API Key；不传则尝试从环境变量读取",
    )
    parser.add_argument(
        "--auto-review-api-key-env",
        type=str,
        default="OPENAI_API_KEY",
        help="外部视觉模型 API Key 对应的环境变量名，默认 OPENAI_API_KEY",
    )
    parser.add_argument(
        "--auto-review-detail",
        type=str,
        default="high",
        choices=["low", "high", "auto"],
        help="自动阅片时传给外部视觉模型的图片细节级别",
    )
    parser.add_argument(
        "--auto-review-temperature",
        type=float,
        default=0.0,
        help="自动阅片时外部视觉模型的采样温度，默认 0",
    )
    parser.add_argument(
        "--auto-review-timeout",
        type=int,
        default=180,
        help="自动阅片时单条请求超时秒数，默认 180",
    )
    parser.add_argument(
        "--auto-review-sleep-seconds",
        type=float,
        default=0.0,
        help="自动阅片时每张切片请求后的额外等待秒数，默认 0",
    )
    parser.add_argument(
        "--auto-review-overwrite",
        action="store_true",
        default=False,
        help="自动阅片时即使某些批次文件已存在明确结论，也重新请求并覆盖",
    )
    args = parser.parse_args()

    # 输入参数解析逻辑：--input 优先于位置参数，均未提供时报错退出
    if args.input_named and args.input_path:
        if args.input_named != args.input_path:
            logger.warning(
                f"同时提供了位置参数 '{args.input_path}' 和 --input '{args.input_named}'，"
                f"且值不同，以 --input 的值为准"
            )
        args.input_path = args.input_named
    elif args.input_named:
        args.input_path = args.input_named
    elif args.input_path:
        pass  # 使用位置参数的值
    else:
        parser.error("必须提供输入路径：使用位置参数或 --input 参数指定 DICOM 文件/ZIP 路径")

    return args


def run_pipeline(input_path: str, output_dir: str = None, enhance: bool = False,
                 enhance_scale: int = 2, report_path: str = None,
                 min_size: int = 1024, window_type: str = "lung",
                 separate_dirs: bool = True, mip: bool = False,
                 mip_slabs: int = 5, imaging_type: str = None,
                 model_name: str = None, review_results_json: str = None,
                 strict_review: bool = False, auto_review_model: str = None,
                 auto_review_api_base: str = "https://api.openai.com/v1",
                 auto_review_api_key: str = None,
                 auto_review_api_key_env: str = "OPENAI_API_KEY",
                 auto_review_detail: str = "high",
                 auto_review_temperature: float = 0.0,
                 auto_review_timeout: int = 180,
                 auto_review_sleep_seconds: float = 0.0,
                 auto_review_overwrite: bool = False):
    """
    执行四阶段流水线：
      1. DICOM → PNG 转换（自动高质量放大到指定尺寸）
      2. [可选] Real-ESRGAN 超分增强
      3. AI 阅片检视（由宿主 AI 工具完成，此处输出提示）
      4. PDF 报告生成

    内置自修复能力，遇到依赖缺失或可恢复错误时自动修复。
    """
    # ====== 自修复：依赖检测与自动安装 ======
    logger.info("[自修复] 正在检测运行环境和依赖 ...")

    # 记录任务开始时间
    from datetime import datetime
    task_start_time = datetime.now()
    pipeline_start = time.time()
    timings = PipelineTimings()
    effective_model_name = model_name or auto_review_model

    deps_ok = _ensure_dependencies()
    if not deps_ok:
        logger.error("[自修复] 部分核心依赖无法自动修复，流程可能失败")
        # 不直接退出，尝试继续运行，让实际出错的地方给出更精确的信息

    # 延迟导入业务模块（在依赖安装完成后）
    try:
        _lazy_import_modules()
    except ImportError as e:
        logger.error(
            f"[自修复] 业务模块导入失败: {e}\n"
            f"请手动安装依赖: pip install -r requirements.txt"
        )
        sys.exit(1)

    logger.info("[自修复] 环境检测完成，所有依赖就绪")

    input_path = Path(input_path).resolve()
    if not input_path.exists():
        logger.error(f"输入路径不存在: {input_path}")
        # 尝试模糊匹配修复路径（常见的用户输入问题）
        parent = input_path.parent
        if parent.exists():
            similar = [
                f for f in parent.iterdir()
                if f.suffix.lower() in (".dcm", ".zip", ".dicom")
                and f.name.lower().startswith(input_path.stem[:3].lower())
            ]
            if similar:
                logger.info(
                    f"[自修复] 在同目录下找到相似文件:\n"
                    + "\n".join(f"  - {f.name}" for f in similar[:5])
                )
        sys.exit(1)

    # 确定输出目录（每次运行使用时间戳子目录隔离）
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if output_dir is None:
        output_dir = input_path.parent / "dicom_output" / run_timestamp
    else:
        output_dir = Path(output_dir).resolve() / run_timestamp

    png_dir = output_dir / "png"
    png_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"本次运行时间戳: {run_timestamp}")
    logger.info(f"⚠️ 提醒：宿主 AI 额外生成的任何文件（如 CT_Report.md、collage.png 等）也必须写入此目录: {output_dir}")

    # ====== 影像类型识别 ======
    logger.info("=" * 50)
    logger.info("影像类型识别")
    logger.info("=" * 50)

    if imaging_type:
        # 用户手动指定
        user_type = ImagingType(imaging_type)
        auto_type = detect_imaging_type(str(input_path))
        logger.info(f"使用用户指定的影像类型：{user_type.display_name}（自动检测结果为：{auto_type.display_name}）")
        detected_type = user_type
    else:
        detected_type = detect_imaging_type(str(input_path))
        logger.info(f"影像类型识别完成：{detected_type.display_name}")

    imaging_profile = get_imaging_profile(detected_type)
    logger.info(f"已加载 {imaging_profile.display_name} 的阅片策略（窗位: {len(imaging_profile.window_presets)} 组, MIP: {'启用' if imaging_profile.use_mip else '禁用'}, GGO窗: {'启用' if imaging_profile.use_ggo_window else '禁用'}）")

    # ====== 阶段 1: DICOM → PNG 转换 ======
    logger.info("=" * 50)
    logger.info("阶段 1/4: DICOM → PNG 转换")
    logger.info("=" * 50)

    stage1_start = time.time()

    converter = DicomConverter(min_size=min_size, window_type=window_type,
                               separate_dirs=separate_dirs, mip=mip, mip_slabs=mip_slabs,
                               imaging_profile=imaging_profile)

    # 如果首次检测不到后端，自修复安装后重新检测
    if converter.backend_name is None:
        logger.warning("[自修复] 转换器无可用后端，尝试重新检测 ...")
        _ensure_dependencies()
        converter = DicomConverter(min_size=min_size, window_type=window_type,
                                   separate_dirs=separate_dirs, mip=mip, mip_slabs=mip_slabs,
                                   imaging_profile=imaging_profile)

    conversion_results = converter.convert(str(input_path), str(png_dir))

    if not conversion_results:
        logger.error("未能成功转换任何 DICOM 文件")
        # 不直接退出，尝试给出更有用的诊断信息
        if converter.backend_name is None:
            logger.error(
                "[自修复] 诊断: 没有可用的 DICOM 转换后端。\n"
                "建议手动安装: pip install SimpleITK 或 pip install dicom2jpg"
            )
        else:
            logger.error(
                f"[自修复] 诊断: 使用了 {converter.backend_name} 后端但转换失败。\n"
                "可能原因: 输入文件不是有效的 DICOM 文件，或文件已损坏。"
            )
        sys.exit(1)

    logger.info(f"阶段 1 完成: 成功转换 {len(conversion_results)} 个文件")

    stage1_end = time.time()
    timings.png_convert_seconds = stage1_end - stage1_start
    timings.dicom_file_count = len(conversion_results)
    timings.png_file_count = len(conversion_results)

    # ====== 阶段 1.5: CAD 自动候选结节预检 ======
    cad_results = None
    try:
        from cad_detector import detect_nodule_candidates, format_candidates_for_prompt
        logger.info("=" * 50)
        logger.info("阶段 1.5: CAD 自动候选结节预检")
        logger.info("=" * 50)
        cad_results = detect_nodule_candidates(
            str(input_path),
            output_dir=str(output_dir),
        )
        n_solid = len(cad_results.get('solid_candidates', []))
        n_ggo = len(cad_results.get('ggo_candidates', []))
        n_ann = len(cad_results.get('annotation_images', []))
        logger.info(f"CAD 预检完成: 实性候选 {n_solid}, GGO 候选 {n_ggo}, 标注图 {n_ann}")
        if n_solid > 0 or n_ggo > 0:
            # 保存 CAD 结果
            cad_json_path = output_dir / "cad_candidates.json"
            with open(cad_json_path, 'w', encoding='utf-8') as f:
                json.dump(cad_results, f, indent=2, ensure_ascii=False)
            logger.info(f"CAD 候选结果已保存: {cad_json_path}")

            # 输出 prompt 文本摘要
            cad_prompt_text = format_candidates_for_prompt(
                cad_results['solid_candidates'],
                cad_results['ggo_candidates'],
                cad_results.get('series_info', {}).get('n_slices', 0),
                spacing=cad_results.get('series_info', {}).get('spacing'),
            )
            logger.info(f"CAD prompt 注入内容:\n{cad_prompt_text}")
    except ImportError:
        logger.info("CAD 模块不可用（缺少 SimpleITK/scipy），跳过自动预检")
    except Exception as e:
        logger.warning(f"CAD 预检出错: {e}，继续后续流程")

    # ====== 阶段 2: [可选] 超分增强 ======
    png_files = conversion_results  # 默认使用原始转换结果
    if enhance:
        logger.info("=" * 50)
        logger.info("阶段 2/4: Real-ESRGAN 超分增强")
        logger.info("=" * 50)

        enhancer = ImageEnhancer()

        if not enhancer.is_available:
            # 检查是否因缺少 GPU 驱动导致
            try:
                nvidia_check = subprocess.run(
                    ["nvidia-smi"], capture_output=True, text=True, timeout=10
                )
                has_gpu = nvidia_check.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
                has_gpu = False

            if not has_gpu:
                logger.warning(
                    "[自修复] 超分因缺少 GPU 驱动降级为原始 PNG"
                )
            else:
                logger.warning(
                    "[自修复] Real-ESRGAN 不可用，尝试安装 ..."
                )
            if _pip_install("realesrgan"):
                # 重新检测
                enhancer = ImageEnhancer()

        enhanced_dir = output_dir / "enhanced"
        enhanced_dir.mkdir(parents=True, exist_ok=True)
        enhanced_files = enhancer.enhance(
            [r["png_path"] for r in conversion_results],
            str(enhanced_dir),
            scale=enhance_scale,
        )
        if enhanced_files:
            # 更新 png_files 以使用增强后的图片
            for i, result in enumerate(conversion_results):
                if i < len(enhanced_files) and enhanced_files[i]:
                    result["png_path"] = enhanced_files[i]
            png_files = conversion_results
            logger.info(f"阶段 2 完成: 增强 {len(enhanced_files)} 张图片")
        else:
            logger.warning(
                "[自修复] 超分增强未能执行，自动降级使用原始 PNG 图片继续流程"
            )
    else:
        logger.info("阶段 2/4: 超分增强（已跳过，未启用）")

    # ====== 阶段 3: AI 阅片检视 ======
    logger.info("=" * 50)
    logger.info("阶段 3/4: AI 阅片检视")
    logger.info("=" * 50)

    stage3_start = time.time()

    # 准备 CAD hint 文本
    cad_prompt_hint = ""
    if cad_results:
        try:
            from cad_detector import format_candidates_for_prompt
            cad_prompt_hint = format_candidates_for_prompt(
                cad_results.get('solid_candidates', []),
                cad_results.get('ggo_candidates', []),
                cad_results.get('series_info', {}).get('n_slices', 0),
                spacing=cad_results.get('series_info', {}).get('spacing'),
            )
        except Exception:
            pass

    reviewer = AIReviewer(imaging_profile=imaging_profile)

    if review_results_json:
        review_results_json = str(Path(review_results_json).resolve())
        logger.info(f"检测到外部阅片结果 JSON，直接加载: {review_results_json}")
        review_results = load_review_results_json(review_results_json)
        logger.info(f"阶段 3 完成: 已加载 {len(review_results)} 条外部阅片结果")

        copied_results_path = output_dir / "review_results.json"
        if Path(review_results_json) != copied_results_path:
            import shutil
            shutil.copy2(review_results_json, copied_results_path)
            logger.info(f"已复制外部阅片结果到输出目录: {copied_results_path}")
    else:
        # 模型视觉能力预检：检查宿主 AI 是否支持图像分析
        model_capable = reviewer.check_model_capability()
        if not model_capable:
            logger.warning(
                "⚠️ 当前模型不支持图像分析（需要多模态视觉模型），已跳过 AI 阅片"
            )
            review_results = []
        else:
            review_results = reviewer.review(png_files, export_dir=str(output_dir),
                                               cad_hint=cad_prompt_hint,
                                               cad_candidates=cad_results)
            logger.info(f"阶段 3 完成: 初始导出 {len(review_results)} 条待检视结果")

            # 检查是否有 API Key
            api_key_available = auto_review_api_key or os.environ.get(auto_review_api_key_env)
            
            if auto_review_model and api_key_available:
                # 使用外部 API 自动阅片
                manifest_path = output_dir / "review_manifest.json"
                stub_results_path = output_dir / "review_results_stub.json"
                merged_results_path = output_dir / "review_results.json"
                filled_batch_dir = output_dir / "review_batch_filled"
                logger.info(
                    "检测到 --auto-review-model，开始调用外部视觉模型自动逐批回填: %s",
                    auto_review_model,
                )
                auto_review_result = run_auto_review_pipeline(
                    manifest_path=str(manifest_path),
                    results_path=str(stub_results_path),
                    output_path=str(merged_results_path),
                    filled_batch_dir=str(filled_batch_dir),
                    model=auto_review_model,
                    api_base=auto_review_api_base,
                    api_key=auto_review_api_key,
                    api_key_env=auto_review_api_key_env,
                    detail=auto_review_detail,
                    temperature=auto_review_temperature,
                    timeout=auto_review_timeout,
                    sleep_seconds=auto_review_sleep_seconds,
                    overwrite=auto_review_overwrite,
                    reviewer=reviewer,
                )
                review_results = load_review_results_json(auto_review_result["results_path"])
                logger.info(
                    "外部视觉模型自动回填完成：当前已阅片 %s/%s，待检视 %s",
                    auto_review_result["stats"]["reviewed"],
                    auto_review_result["stats"]["total"],
                    auto_review_result["stats"]["unrecognizable"],
                )
            else:
                # 没有 API Key，切换到宿主 AI 模式
                manifest_path = output_dir / "review_manifest.json"
                logger.info(
                    "未检测到 OpenAI API Key，自动切换到【宿主 AI 分批处理模式】"
                )
                logger.info(
                    "宿主 AI 将逐批读取图片并完成阅片，每批完成后自动保存进度"
                )
                
                # 导入宿主 AI 审阅模块
                try:
                    from host_ai_review import HostAIReviewer
                    
                    host_reviewer = HostAIReviewer(
                        manifest_path=str(manifest_path),
                        output_dir=str(output_dir),
                        model_name=effective_model_name,
                    )
                    
                    # 输出当前进度
                    progress = host_reviewer.get_progress()
                    logger.info(
                        "宿主 AI 阅片进度: 已完成 %s/%s 批次，剩余 %s 批次",
                        progress["completed_batches"],
                        progress["total_batches"],
                        progress["remaining_batches"],
                    )
                    
                    if progress["next_batch"]:
                        logger.info(
                            "请宿主 AI 继续处理批次 %s，使用以下命令查看详情:",
                            progress["next_batch"],
                        )
                        logger.info(
                            "  python3 %s --manifest %s --output %s --status",
                            Path(__file__).parent / "host_ai_review.py",
                            manifest_path,
                            output_dir,
                        )
                        
                        # 输出下一批的提示信息
                        next_batch = host_reviewer.get_next_batch()
                        if next_batch:
                            prompt = host_reviewer.generate_host_ai_prompt(next_batch)
                            print("\n" + "="*60)
                            print("【宿主 AI 阅片提示 - 请复制给 AI 助手】")
                            print("="*60)
                            print(prompt)
                            print("="*60 + "\n")
                    else:
                        logger.info("✅ 所有批次已完成，正在合并结果...")
                        
                    # 提示用户如何继续
                    print("\n" + "="*60)
                    print("【阅片模式说明】")
                    print("="*60)
                    print("当前为【宿主 AI 分批处理模式】")
                    print("\n请按以下步骤操作:")
                    print("1. 查看上方的阅片提示")
                    print("2. 读取对应的 PNG 图片并分析")
                    print("3. 返回 JSON 格式的阅片结果")
                    print("4. 我会自动保存并合并到总表")
                    print("\n如需查看进度，运行:")
                    print(f"  python3 {Path(__file__).parent / 'host_ai_review.py'} --manifest {manifest_path} --output {output_dir} --status")
                    print("="*60 + "\n")
                    
                except ImportError as e:
                    logger.warning(
                        "宿主 AI 审阅模块加载失败: %s，将生成标准批次模板供手动填写",
                        e,
                    )

    stage3_end = time.time()
    timings.ai_review_seconds = stage3_end - stage3_start

    validation = validate_review_results(
        review_results,
        expected_conversion_results=png_files,
        require_complete=strict_review,
    )
    stats = validation["stats"]
    logger.info(
        "阶段 3 校验: 共 %s 张，已阅片 %s 张，正常 %s 张，异常 %s 张，待检视 %s 张",
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
        sys.exit(2)

    unreviewed_count = stats["unrecognizable"]
    if strict_review and review_results and unreviewed_count > 0:
        logger.error(
            "严格模式已启用：当前仍有 %s 张切片处于‘无法识别/待检视’状态，拒绝生成最终报告。\n"
            "请优先按批填写输出目录中的 review_batch_templates/batch_XXX.json，\n"
            "再运行 apply_review_batch.py 合并生成 review_results.json；\n"
            "如希望自动跑完整批次，也可在首次运行 main.py 时直接传 --auto-review-model 及对应 API 参数。\n"
            "全部完成后，再重新运行 main.py（传入 --review-results-json）或 generate_report.py。",
            unreviewed_count,
        )
        sys.exit(2)

    # ====== 阶段 3.5: CAD vs AI 交叉验证 ======
    cross_validation_result = None
    if cad_results:
        logger.info("=" * 50)
        logger.info("阶段 3.5: CAD vs AI 交叉验证")
        logger.info("=" * 50)
        try:
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
                    log_fn(
                        f"[交叉验证 {alert['severity']}] {alert['message']}"
                    )
                # 保存交叉验证结果
                cv_json_path = output_dir / "cross_validation.json"
                with open(cv_json_path, 'w', encoding='utf-8') as f:
                    json.dump(cross_validation_result, f, indent=2, ensure_ascii=False)
                logger.info(f"交叉验证结果已保存: {cv_json_path}")
            else:
                logger.info("所有 CAD 高分候选均已被 AI 确认或明确排除，无遗漏告警。")
        except Exception as e:
            logger.warning(f"CAD 交叉验证出错（不影响报告生成）: {e}")

    # ====== 阶段 4: PDF 报告生成 ======
    logger.info("=" * 50)
    logger.info("阶段 4/4: PDF 报告生成")
    logger.info("=" * 50)

    stage4_start = time.time()

    # 提取患者信息（脱敏后写入报告）
    patient_info = {}
    try:
        from converter import extract_patient_info
        patient_info = extract_patient_info(str(input_path))
        if patient_info:
            logger.info(f"已提取患者信息: {list(patient_info.keys())}")
    except Exception as e:
        logger.debug(f"患者信息提取失败（不影响报告生成）: {e}")

    try:
        generator = ReportGenerator()
        report_result = generator.generate(
            review_results=review_results,
            input_path=str(input_path),
            output_dir=str(output_dir),
            report_path=report_path,
            window_type=window_type,
            min_size=min_size,
            enhance=enhance,
            enhance_scale=enhance_scale,
            version=__version__,
            imaging_profile=imaging_profile,
            task_start_time=task_start_time,
            task_end_time=datetime.now(),
            timings=timings,
            model_name=effective_model_name,
            patient_info=patient_info,
            cross_validation=cross_validation_result,
        )
        pdf_path = report_result["pdf_path"]
        md_path = report_result["md_path"]
        logger.info(f"阶段 4 完成: PDF 报告 → {pdf_path}")
        logger.info(f"阶段 4 完成: Markdown 报告 → {md_path}")
    except Exception as e:
        logger.warning(f"[自修复] PDF 报告生成失败: {e}")
        logger.info("[自修复] 尝试重新安装 reportlab 后重试 ...")
        if _pip_install("reportlab>=4.0.0"):
            try:
                # 重新加载模块
                importlib.invalidate_caches()
                # 重新导入
                import report_generator as rg_module
                importlib.reload(rg_module)
                generator = rg_module.ReportGenerator()
                report_result = generator.generate(
                    review_results=review_results,
                    input_path=str(input_path),
                    output_dir=str(output_dir),
                    report_path=report_path,
                    window_type=window_type,
                    min_size=min_size,
                    enhance=enhance,
                    enhance_scale=enhance_scale,
                    version=__version__,
                    imaging_profile=imaging_profile,
                    task_start_time=task_start_time,
                    task_end_time=datetime.now(),
                    timings=timings,
                    model_name=effective_model_name,
                    patient_info=patient_info,
                    cross_validation=cross_validation_result,
                )
                pdf_path = report_result["pdf_path"]
                md_path = report_result["md_path"]
                logger.info(f"[自修复] 重试成功！PDF 报告 → {pdf_path}")
                logger.info(f"[自修复] 重试成功！Markdown 报告 → {md_path}")
            except Exception as retry_err:
                logger.error(f"[自修复] 重试仍失败: {retry_err}")
                # 降级：输出纯文本报告
                pdf_path = _fallback_text_report(
                    review_results, str(input_path), str(output_dir), report_path
                )
                md_path = None
        else:
            # 降级：输出纯文本报告
            pdf_path = _fallback_text_report(
                review_results, str(input_path), str(output_dir), report_path
            )
            md_path = None

    logger.info("=" * 50)
    logger.info("全部流程完成！")

    # 计算总耗时和 PDF 生成耗时
    pipeline_end = time.time()
    timings.total_seconds = pipeline_end - pipeline_start
    timings.pdf_generate_seconds = pipeline_end - stage4_start
    task_end_time = datetime.now()

    # 输出各阶段耗时统计
    logger.info(f"  总耗时: {timings.total_seconds:.1f}秒")
    logger.info(f"  DICOM/PNG 转换耗时: {timings.png_convert_seconds:.1f}秒")
    logger.info(f"  AI 阅片耗时: {timings.ai_review_seconds:.1f}秒")
    logger.info(f"  PDF 生成耗时: {timings.pdf_generate_seconds:.1f}秒")
    logger.info(f"  DICOM 文件数: {timings.dicom_file_count}")
    logger.info(f"  PNG 文件数: {timings.png_file_count}")

    logger.info(f"  PNG 图片目录: {png_dir}")
    logger.info(f"  PDF 报告: {pdf_path}")
    if md_path:
        logger.info(f"  Markdown 报告: {md_path}")
    logger.info("=" * 50)

    return {"pdf_path": pdf_path, "md_path": md_path}


def _fallback_text_report(review_results, input_path: str,
                          output_dir: str, report_path: str = None) -> str:
    """
    降级方案：当 PDF 生成失败时，输出纯文本报告。

    Args:
        review_results: 检视结果列表
        input_path: 原始输入文件路径
        output_dir: 输出目录
        report_path: 指定的报告路径

    Returns:
        文本报告文件路径
    """
    from datetime import datetime

    logger.info("[自修复] 降级为纯文本报告 ...")

    if report_path:
        txt_path = str(report_path).replace(".pdf", ".txt")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        txt_path = os.path.join(output_dir, f"dicom_report_{timestamp}.txt")

    lines = [
        "=" * 60,
        "DICOM 影像 AI 检视报告（文本版）",
        "=" * 60,
        f"检视时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"输入文件: {os.path.basename(input_path)}",
        "",
        "注: PDF 报告生成失败，已自动降级为文本报告。",
        "    请安装 reportlab 后重新运行以获取 PDF 报告: pip install reportlab",
        "",
        "-" * 60,
        f"检视图片总数: {len(review_results)}",
    ]

    for i, r in enumerate(review_results, 1):
        lines.append(f"\n--- 图片 {i}: {r.dicom_name} ---")
        lines.append(f"  结论: {r.conclusion.value}")
        lines.append(f"  置信度: {r.confidence}")
        if r.abnormality_desc:
            lines.append(f"  异常描述: {r.abnormality_desc}")
        if r.details:
            lines.append(f"  详细说明: {r.details}")

    lines.append("")
    lines.append("-" * 60)
    lines.append("⚠ 本报告由 AI 辅助生成，仅供参考，不构成医学诊断。")
    lines.append("  如有疑问，请及时咨询专业医生。")
    lines.append("=" * 60)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"[自修复] 文本报告已生成: {txt_path}")
    return txt_path


def main():
    """主入口"""
    args = parse_args()
    run_pipeline(
        input_path=args.input_path,
        output_dir=args.output_dir,
        enhance=args.enhance,
        enhance_scale=args.enhance_scale,
        report_path=args.report_path,
        min_size=args.min_size,
        window_type=args.window,
        separate_dirs=args.separate_window_dirs,
        mip=args.mip,
        mip_slabs=args.mip_slabs,
        imaging_type=args.imaging_type,
        model_name=args.model_name,
        review_results_json=args.review_results_json,
        strict_review=args.strict_review,
        auto_review_model=args.auto_review_model,
        auto_review_api_base=args.auto_review_api_base,
        auto_review_api_key=args.auto_review_api_key,
        auto_review_api_key_env=args.auto_review_api_key_env,
        auto_review_detail=args.auto_review_detail,
        auto_review_temperature=args.auto_review_temperature,
        auto_review_timeout=args.auto_review_timeout,
        auto_review_sleep_seconds=args.auto_review_sleep_seconds,
        auto_review_overwrite=args.auto_review_overwrite,
    )


if __name__ == "__main__":
    main()
