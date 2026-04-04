#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 阅片检视模块

驱动 AI 逐张检视 PNG 图片，重点检测结节、肿块、钙化等异常。
此模块生成提示词和结构化检视结果，实际的 AI 视觉分析由宿主 AI 工具完成。

重要设计说明：
  - review() 方法中，默认结论为"待检视"（UNRECOGNIZABLE），而非"正常"
  - 宿主 AI 工具应逐张查看图片，调用 parse_ai_response() 填充真实结论
  - 如果 review() 返回的结果全部为 UNRECOGNIZABLE，说明宿主 AI 未真正执行阅片
"""

import json
import logging
import os
from datetime import datetime
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

from version import __version__ as _SKILL_VERSION

if TYPE_CHECKING:
    from modality_detector import ImagingProfile

logger = logging.getLogger("dicom-doctor.reviewer")


def safe_print(text: str) -> None:
    """
    编码安全的 print 函数，兼容 Windows GBK 终端。

    在 Windows GBK 编码终端中，print() 输出包含 emoji 或特殊 Unicode 字符
    的文本时会抛出 UnicodeEncodeError。此函数捕获该异常并将无法编码的字符
    替换为 '?'，确保不会因终端编码问题导致程序崩溃。

    在 UTF-8 终端中，所有字符正常输出，无任何替换。
    """
    import sys
    try:
        print(text)
    except UnicodeEncodeError:
        # Windows GBK 终端无法输出 emoji 等字符，降级输出
        encoding = sys.stdout.encoding or 'utf-8'
        safe_text = text.encode(encoding, errors='replace').decode(encoding)
        print(safe_text)


class ReviewConclusion(str, Enum):
    """检视结论枚举"""
    NORMAL = "正常"
    ABNORMAL = "异常"
    UNRECOGNIZABLE = "无法识别"


@dataclass
class ReviewResult:
    """
    单张图片的检视结果数据模型。

    Attributes:
        png_name: PNG 图片文件名
        dicom_name: 对应的原始 DICOM 文件名
        png_path: PNG 图片完整路径
        conclusion: 检视结论（正常/异常/无法识别）
        abnormality_desc: 异常描述（仅在结论为异常时有内容）
        confidence: 置信度评估（如 高/中/低）
        details: 详细说明
        location: 异常位置描述（如"左肺上叶"）
        size_mm: 异常病灶尺寸（毫米），如 "4x3"
        lung_rads: Lung-RADS 分类（如适用）
        recommendation: 随访建议
    """
    png_name: str
    dicom_name: str
    png_path: str
    conclusion: ReviewConclusion = ReviewConclusion.UNRECOGNIZABLE
    abnormality_desc: str = ""
    confidence: str = ""
    details: str = ""
    location: str = ""
    size_mm: str = ""
    lung_rads: str = ""  # 向后兼容字段（胸部CT使用）
    classification_system: str = ""  # 通用分级系统名称（如 "Lung-RADS" / "LI-RADS" / ""）
    classification_value: str = ""  # 通用分级值（如 "2类" / "LR-3" / ""）
    recommendation: str = ""
    slice_index: str = ""      # 层面序号，如 "285/832"
    slice_location: str = ""   # DICOM SliceLocation（mm）
    bounding_boxes: List[Dict] = field(default_factory=list)  # 病灶边界框 [{"x": float, "y": float, "width": float, "height": float}]，相对坐标 0~1

    def to_dict(self) -> Dict:
        """转换为字典（同时包含新旧字段以向后兼容）"""
        result = asdict(self)
        result["conclusion"] = self.conclusion.value
        # 确保 lung_rads 向后兼容：如果 classification_system 为 Lung-RADS，同步到 lung_rads
        if self.classification_system == "Lung-RADS" and self.classification_value and not self.lung_rads:
            result["lung_rads"] = self.classification_value
        # 确保 bounding_boxes 包含在序列化输出中
        result["bounding_boxes"] = self.bounding_boxes
        return result

    @classmethod
    def from_dict(cls, item: Dict) -> "ReviewResult":
        """从 JSON 字典恢复 ReviewResult，供正式报告闭环复用。"""
        conclusion_str = item.get("conclusion", "无法识别")
        if isinstance(conclusion_str, ReviewConclusion):
            conclusion = conclusion_str
        elif conclusion_str == "正常":
            conclusion = ReviewConclusion.NORMAL
        elif conclusion_str == "异常":
            conclusion = ReviewConclusion.ABNORMAL
        else:
            conclusion = ReviewConclusion.UNRECOGNIZABLE

        raw_boxes = item.get("bounding_boxes", [])
        validated_boxes = []
        if isinstance(raw_boxes, list):
            for box in raw_boxes:
                if isinstance(box, dict) and all(k in box for k in ("x", "y", "width", "height")):
                    try:
                        validated_boxes.append({
                            "x": float(box["x"]),
                            "y": float(box["y"]),
                            "width": float(box["width"]),
                            "height": float(box["height"]),
                        })
                    except (ValueError, TypeError):
                        logger.warning(f"bounding_box 坐标无法解析: {box}")

        classification_system = item.get("classification_system", "")
        classification_value = item.get("classification_value", "")
        lung_rads = item.get("lung_rads", "")
        
        # [Optimization] Mandatory Lung-RADS v1.1 full validation fallback
        # Cross-validate nodule type + size against Lung-RADS v1.1 classification table:
        #   实性(Solid):     <6mm→2类, 6-8mm→3类, 8-15mm→4A类, >15mm→4B类
        #   GGO(磨玻璃):     <30mm→2类, ≥30mm→3类
        #   部分实性(混合):   按整体尺寸近似——<6mm→2类, 6-8mm→3类, ≥8mm→4A类
        # 注意: 4X类(恶性征象)无法通过尺寸判断，不做自动校正
        size_str = item.get("size_mm", "")
        desc = item.get("abnormality_desc", "")
        is_lung_rads = classification_system == "Lung-RADS" or "Lung-RADS" in lung_rads or "Lung-RADS" in classification_value

        if conclusion == ReviewConclusion.ABNORMAL and is_lung_rads and size_str:
            import re
            nums = re.findall(r"\d+\.?\d*", size_str)
            if nums:
                try:
                    max_dim = max(float(n) for n in nums)
                    expected_category = None

                    # 判断结节密度类型
                    is_ggo = ("磨玻璃" in desc or "GGO" in desc.upper() or "GGN" in desc.upper()
                              or "ground glass" in desc.lower())
                    is_part_solid = ("部分实性" in desc or "混合" in desc or "part-solid" in desc.lower()
                                     or "part solid" in desc.lower() or "混合磨玻璃" in desc)
                    is_solid = ("实性" in desc and not is_ggo and not is_part_solid)

                    if is_solid:
                        # 实性结节: <6mm→2, 6-8mm→3, 8-15mm→4A, >15mm→4B
                        if max_dim < 6.0:
                            expected_category = "2"
                        elif max_dim < 8.0:
                            expected_category = "3"
                        elif max_dim <= 15.0:
                            expected_category = "4A"
                        else:
                            expected_category = "4B"
                    elif is_part_solid:
                        # 部分实性结节: 按整体尺寸近似分类
                        # <6mm→2, 6-8mm→3, ≥8mm→4A
                        if max_dim < 6.0:
                            expected_category = "2"
                        elif max_dim < 8.0:
                            expected_category = "3"
                        else:
                            expected_category = "4A"
                    elif is_ggo:
                        # 纯GGO: <30mm→2, ≥30mm→3
                        if max_dim < 30.0:
                            expected_category = "2"
                        else:
                            expected_category = "3"

                    # 执行校正: 仅当能确定期望分类时才校正
                    if expected_category is not None:
                        # 解析当前分类值中的核心类别 (如 "4A类" → "4A", "2" → "2")
                        current_val = (classification_value or lung_rads or "").strip()
                        current_core = re.sub(r"[类型]", "", current_val).strip()

                        if current_core != expected_category:
                            # 保持原有格式风格 (纯数字 vs 带"类"后缀)
                            has_suffix = "类" in current_val or not current_val
                            corrected = f"{expected_category}类" if has_suffix else expected_category
                            logger.info(
                                f"Lung-RADS 自动校正: {desc} {size_str} "
                                f"'{current_val}' → '{corrected}'"
                            )
                            classification_value = corrected
                            lung_rads = corrected
                except Exception:
                    pass

        if classification_system == "Lung-RADS" and classification_value and not lung_rads:
            lung_rads = classification_value
        elif lung_rads and not classification_system:
            classification_system = "Lung-RADS"
            classification_value = lung_rads

        return cls(
            png_name=item.get("png_name", ""),
            dicom_name=item.get("dicom_name", ""),
            png_path=item.get("png_path", ""),
            conclusion=conclusion,
            abnormality_desc=item.get("abnormality_desc", ""),
            confidence=item.get("confidence", ""),
            details=item.get("details", ""),
            location=item.get("location", ""),
            size_mm=item.get("size_mm", ""),
            lung_rads=lung_rads,
            classification_system=classification_system,
            classification_value=classification_value,
            recommendation=item.get("recommendation", ""),
            slice_index=item.get("slice_index", ""),
            slice_location=item.get("slice_location", ""),
            bounding_boxes=validated_boxes,
        )


def save_review_results_json(review_results: List[ReviewResult], json_path: str) -> str:
    """将阅片结果落盘为 JSON，便于宿主 AI 回填后复用。"""
    json_path = str(Path(json_path).resolve())
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in review_results], f, ensure_ascii=False, indent=2)
    return json_path


def load_review_results_json(json_path: str) -> List[ReviewResult]:
    """从 JSON 文件恢复阅片结果。"""
    json_path = str(Path(json_path).resolve())
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"阅片结果 JSON 格式错误，期望数组: {json_path}")

    return [ReviewResult.from_dict(item) for item in data]


def summarize_review_results(review_results: List[ReviewResult]) -> Dict[str, int]:
    """统计阅片结果的完成度。"""
    total = len(review_results)
    normal = sum(1 for r in review_results if r.conclusion == ReviewConclusion.NORMAL)
    abnormal = sum(1 for r in review_results if r.conclusion == ReviewConclusion.ABNORMAL)
    unrecognizable = sum(1 for r in review_results if r.conclusion == ReviewConclusion.UNRECOGNIZABLE)
    reviewed = total - unrecognizable
    return {
        "total": total,
        "normal": normal,
        "abnormal": abnormal,
        "unrecognizable": unrecognizable,
        "reviewed": reviewed,
    }


def validate_review_results(review_results: List[ReviewResult],
                            expected_conversion_results: Optional[List[Dict]] = None,
                            require_complete: bool = False) -> Dict[str, object]:
    """校验阅片结果是否完整、可复用，避免误把别的病例或占位结果拿去出正式报告。"""
    errors: List[str] = []
    warnings: List[str] = []
    stats = summarize_review_results(review_results)

    if not review_results:
        errors.append("阅片结果为空，无法生成正式报告。")

    expected_by_png: Dict[str, Dict] = {}
    if expected_conversion_results:
        for item in expected_conversion_results:
            png_path = item.get("png_path", "")
            png_name = os.path.basename(png_path) if png_path else item.get("png_name", "")
            if png_name:
                expected_by_png[png_name] = item

        if expected_by_png and len(review_results) != len(expected_by_png):
            errors.append(
                f"阅片结果条数与当前影像不一致：结果 {len(review_results)} 条，当前影像 {len(expected_by_png)} 张。"
            )

    seen_png_names = set()
    for index, result in enumerate(review_results, 1):
        label = result.png_name or f"第 {index} 条"

        if not result.png_name:
            errors.append(f"第 {index} 条阅片结果缺少 png_name。")
            continue

        if result.png_name in seen_png_names:
            errors.append(f"检测到重复的 png_name：{result.png_name}")
        else:
            seen_png_names.add(result.png_name)

        if not result.dicom_name:
            warnings.append(f"{label} 缺少 dicom_name。")
        if not result.png_path:
            warnings.append(f"{label} 缺少 png_path。")

        expected = expected_by_png.get(result.png_name)
        if expected_by_png and not expected:
            errors.append(f"{label} 不在当前输出清单中，疑似引用了别的病例/别的运行结果。")
            continue

        if expected:
            expected_dicom_name = expected.get("dicom_name", "")
            if expected_dicom_name and result.dicom_name and result.dicom_name != expected_dicom_name:
                errors.append(
                    f"{label} 的 DICOM 文件名与当前输出不一致：{result.dicom_name} != {expected_dicom_name}"
                )

            expected_slice_index = str(expected.get("slice_index", "") or "")
            actual_slice_index = str(result.slice_index or "")
            if expected_slice_index and actual_slice_index and actual_slice_index != expected_slice_index:
                errors.append(
                    f"{label} 的层面序号与当前输出不一致：{actual_slice_index} != {expected_slice_index}"
                )

            expected_png_path = expected.get("png_path", "")
            if expected_png_path and result.png_path and Path(result.png_path).name != Path(expected_png_path).name:
                errors.append(
                    f"{label} 的 PNG 文件与当前输出不一致：{Path(result.png_path).name} != {Path(expected_png_path).name}"
                )

        if require_complete and result.conclusion == ReviewConclusion.UNRECOGNIZABLE:
            errors.append(f"{label} 仍为“无法识别/待检视”，不满足正式报告要求。")

        if result.conclusion == ReviewConclusion.ABNORMAL:
            if not any([result.abnormality_desc, result.location, result.size_mm, result.details]):
                warnings.append(f"{label} 标记为异常，但缺少异常描述/位置/大小/详情。")
            if not (result.classification_value or result.lung_rads):
                warnings.append(f"{label} 标记为异常，但尚未填写分级信息。")

    if expected_by_png:
        missing = sorted(set(expected_by_png.keys()) - seen_png_names)
        if missing:
            preview = "、".join(missing[:5])
            errors.append(f"缺少 {len(missing)} 张当前影像的阅片结果，例如：{preview}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
    }


# ========================
# CAD vs AI 交叉验证（v2.4.8+）
# ========================

# 描述中出现以下关键词视为"已提及可疑征象"
_SUSPICIOUS_KEYWORDS = [
    "结节", "磨玻璃", "GGO", "实性", "混合密度", "半实性",
    "肿块", "占位", "阴影", "高密度灶", "钙化灶", "索条",
    "nodule", "opacity", "mass", "lesion",
]

# 显式排除关键词——如果 AI 在描述或详情中明确给出了排除理由，则视为"已审查并排除"
_EXCLUSION_KEYWORDS = [
    "血管", "伪影", "运动伪影", "层面伪影", "呼吸伪影",
    "横截面", "支气管", "瘢痕", "骨岛", "淋巴结",
    "vessel", "artifact", "bronch",
]


def cross_validate_cad_vs_review(
    review_results: List[ReviewResult],
    cad_results: Optional[Dict] = None,
    score_threshold: float = 0.80,
    z_tolerance: int = 2,
) -> Dict[str, object]:
    """
    CAD vs AI 交叉验证（v2.4.8）。

    对比 CAD 高评分候选与 AI 阅片结论，检测以下三类问题：
    1. **遗漏高分候选**：CAD score ≥ 阈值但 AI 在对应层面全部标"正常"且未提及可疑征象
    2. **描述了但不报**：AI 在描述中提及了可疑征象关键词但结论仍为"正常"
    3. **无覆盖**：候选 z_range 内全部层面为"无法识别/待检视"

    Args:
        review_results: AI 阅片结果列表
        cad_results: CAD 检测结果 dict（含 solid_candidates / ggo_candidates / series_info）
        score_threshold: CAD 评分阈值，仅对 score ≥ 此值的候选进行交叉验证
        z_tolerance: z-index 容差（层），CAD z_range 两端各扩展此值来匹配 AI 结果

    Returns:
        {
            "ok": bool,  # True = 无遗漏告警
            "alerts": [
                {
                    "type": "missed_candidate" | "described_but_not_reported" | "no_coverage",
                    "severity": "HIGH" | "MEDIUM" | "LOW",
                    "candidate_type": "solid" | "ggo",
                    "candidate_rank": int,  # 在 CAD 排名
                    "nodule_score": float,
                    "z_range": str,
                    "position": str,  # 例如 "(189,222)"
                    "message": str,  # 人类可读的告警描述
                }
            ],
            "summary": str,  # 交叉验证摘要文本
            "verified_count": int,  # 已验证的高分候选数
            "total_high_score": int,  # 高分候选总数
        }
    """
    alerts = []

    if not cad_results:
        return {
            "ok": True,
            "alerts": [],
            "summary": "CAD 结果不可用，跳过交叉验证。",
            "verified_count": 0,
            "total_high_score": 0,
        }

    solid_candidates = cad_results.get("solid_candidates", [])
    ggo_candidates = cad_results.get("ggo_candidates", [])
    series_info = cad_results.get("series_info", {})
    n_slices = series_info.get("n_slices", 0)

    # 构建 z-index → ReviewResult 映射
    z_to_results: Dict[int, List[ReviewResult]] = {}
    for r in review_results:
        z_idx = _extract_z_index(r.slice_index, n_slices)
        if z_idx is not None:
            z_to_results.setdefault(z_idx, []).append(r)

    # 收集所有高分候选并标记类型
    high_score_candidates = []
    for rank, c in enumerate(solid_candidates, 1):
        score = c.get("nodule_score", 0)
        if score >= score_threshold:
            high_score_candidates.append(("solid", rank, c))
    for rank, c in enumerate(ggo_candidates, 1):
        score = c.get("nodule_score", 0)
        if score >= score_threshold:
            high_score_candidates.append(("ggo", rank, c))

    total_high = len(high_score_candidates)
    verified = 0

    for cand_type, rank, candidate in high_score_candidates:
        score = candidate.get("nodule_score", 0)
        z_range_str = str(candidate.get("z_range", ""))
        position = f"({candidate.get('cx', '?')},{candidate.get('cy', '?')})"

        # 解析 z_range
        z_min, z_max = _parse_z_range(z_range_str)
        if z_min is None:
            continue

        # 收集此候选覆盖区域内（含容差）的所有 AI 阅片结果
        covered_results: List[ReviewResult] = []
        for z in range(z_min - z_tolerance, z_max + z_tolerance + 1):
            covered_results.extend(z_to_results.get(z, []))

        if not covered_results:
            # 无覆盖
            alerts.append({
                "type": "no_coverage",
                "severity": "HIGH",
                "candidate_type": cand_type,
                "candidate_rank": rank,
                "nodule_score": round(score, 3),
                "z_range": z_range_str,
                "position": position,
                "message": f"CAD {cand_type.upper()}#{rank}（score={score:.3f}, z={z_range_str}）"
                           f"覆盖层面内无任何 AI 阅片结果（可能全为待检视）",
            })
            continue

        # 检查覆盖区域内是否有"异常"结论
        has_abnormal = any(r.conclusion == ReviewConclusion.ABNORMAL for r in covered_results)

        # 检查覆盖区域内是否有描述中提及可疑征象
        has_suspicious_desc = False
        suspicious_but_normal = []
        for r in covered_results:
            desc_text = f"{r.abnormality_desc} {r.details} {r.location}".lower()
            if any(kw in desc_text for kw in _SUSPICIOUS_KEYWORDS):
                has_suspicious_desc = True
                if r.conclusion == ReviewConclusion.NORMAL:
                    suspicious_but_normal.append(r)

        # 检查是否有显式排除理由
        has_exclusion = False
        for r in covered_results:
            desc_text = f"{r.abnormality_desc} {r.details}".lower()
            if any(kw in desc_text for kw in _EXCLUSION_KEYWORDS):
                has_exclusion = True
                break

        if has_abnormal:
            # AI 已标记异常，验证通过
            verified += 1
            continue

        if has_exclusion:
            # AI 审查过并给出了排除理由，视为已验证
            verified += 1
            continue

        # 到这里：覆盖区域内全部是"正常"或"待检视"，且无排除理由
        all_unrecognizable = all(
            r.conclusion == ReviewConclusion.UNRECOGNIZABLE for r in covered_results
        )

        if all_unrecognizable:
            alerts.append({
                "type": "no_coverage",
                "severity": "HIGH",
                "candidate_type": cand_type,
                "candidate_rank": rank,
                "nodule_score": round(score, 3),
                "z_range": z_range_str,
                "position": position,
                "message": f"CAD {cand_type.upper()}#{rank}（score={score:.3f}, z={z_range_str}）"
                           f"覆盖层面内 AI 结果全部为'待检视'，未被实际审阅",
            })
            continue

        if suspicious_but_normal:
            # 描述了但不报
            slice_info = suspicious_but_normal[0].slice_index or "?"
            alerts.append({
                "type": "described_but_not_reported",
                "severity": "HIGH",
                "candidate_type": cand_type,
                "candidate_rank": rank,
                "nodule_score": round(score, 3),
                "z_range": z_range_str,
                "position": position,
                "message": f"CAD {cand_type.upper()}#{rank}（score={score:.3f}, z={z_range_str}）"
                           f"覆盖层面 AI 描述中提及可疑征象但结论为'正常'（层面 {slice_info}）",
            })
            continue

        # 遗漏高分候选
        severity = "HIGH" if score >= 0.90 else "MEDIUM"
        alerts.append({
            "type": "missed_candidate",
            "severity": severity,
            "candidate_type": cand_type,
            "candidate_rank": rank,
            "nodule_score": round(score, 3),
            "z_range": z_range_str,
            "position": position,
            "message": f"CAD {cand_type.upper()}#{rank}（score={score:.3f}, z={z_range_str}）"
                       f"在覆盖层面内 AI 全部标为'正常'，且无排除理由——可能遗漏",
        })

    # 构建摘要
    n_high = len([a for a in alerts if a["severity"] == "HIGH"])
    n_med = len([a for a in alerts if a["severity"] == "MEDIUM"])
    if not alerts:
        summary = f"✅ CAD 交叉验证通过：{total_high} 个高分候选全部已被 AI 确认或排除。"
    else:
        summary = (
            f"⚠️ CAD 交叉验证发现 {len(alerts)} 个告警"
            f"（HIGH: {n_high}, MEDIUM: {n_med}）"
            f"，共 {total_high} 个高分候选中 {verified} 个已验证。"
        )

    return {
        "ok": len(alerts) == 0,
        "alerts": alerts,
        "summary": summary,
        "verified_count": verified,
        "total_high_score": total_high,
    }


def _extract_z_index(slice_index_str: str, n_slices: int = 0) -> Optional[int]:
    """
    从 slice_index 字符串（如 "285/832"）提取 z-index。

    slice_index 格式为 "instance_number/total"，z_index = total - instance_number。
    如果无法解析则返回 None。
    """
    if not slice_index_str:
        return None
    try:
        parts = str(slice_index_str).split("/")
        instance_num = int(parts[0])
        total = int(parts[1]) if len(parts) > 1 else n_slices
        if total > 0:
            return total - instance_num
        return None
    except (ValueError, IndexError):
        return None


def _parse_z_range(z_range_str: str):
    """
    解析 CAD 候选的 z_range 字符串（如 "138-140"）。

    Returns:
        (z_min, z_max) 或 (None, None) 如果无法解析
    """
    if not z_range_str:
        return None, None
    try:
        parts = str(z_range_str).split("-")
        z_min = int(parts[0])
        z_max = int(parts[-1]) if len(parts) > 1 else z_min
        return z_min, z_max
    except (ValueError, IndexError):
        return None, None


# ========================
# Prompt 模板：统一从 prompt_templates 加载，不再内联维护
# （v1.4.0 起废弃内联冗余，所有 Prompt 以 prompt_templates/ 为唯一来源）
# ========================

def deduplicate_findings(results: List[ReviewResult]) -> List[ReviewResult]:
    """
    对所有批次的阅片结果进行去重合并。

    对同一位置（位置文本相似度 >80%）和相邻层面（层面差 ≤3）的重复结节报告
    进行合并，保留置信度最高的记录。

    Args:
        results: 所有批次的异常检视结果

    Returns:
        去重后的异常结果列表
    """
    if not results:
        return results

    # 分离正常和异常结果
    normal_results = [r for r in results if r.conclusion != ReviewConclusion.ABNORMAL]
    abnormal_results = [r for r in results if r.conclusion == ReviewConclusion.ABNORMAL]

    if len(abnormal_results) <= 1:
        return results

    # 置信度权重映射
    confidence_weight = {"高": 3, "中": 2, "低": 1, "待检视": 0}

    def _text_similarity(a: str, b: str) -> float:
        """简单的文本相似度（基于共同字符比例）"""
        if not a or not b:
            return 0.0
        a_set = set(a)
        b_set = set(b)
        intersection = a_set & b_set
        union = a_set | b_set
        return len(intersection) / len(union) if union else 0.0

    def _parse_slice_index(idx_str: str) -> Optional[int]:
        """从 '285/832' 格式提取层面编号"""
        if not idx_str:
            return None
        try:
            return int(idx_str.split("/")[0])
        except (ValueError, IndexError):
            return None

    # 去重：逐个比较
    merged = []
    used = set()

    for i, r1 in enumerate(abnormal_results):
        if i in used:
            continue

        group = [r1]
        idx1 = _parse_slice_index(r1.slice_index)

        for j in range(i + 1, len(abnormal_results)):
            if j in used:
                continue
            r2 = abnormal_results[j]
            idx2 = _parse_slice_index(r2.slice_index)

            # 检查位置相似度
            loc_sim = _text_similarity(r1.location, r2.location)
            # 检查层面距离
            slice_close = False
            if idx1 is not None and idx2 is not None:
                slice_close = abs(idx1 - idx2) <= 3

            # 位置相似度 >80% 且层面相邻，认为是同一病灶
            if loc_sim > 0.8 and slice_close:
                group.append(r2)
                used.add(j)

        # 从 group 中选择置信度最高的
        best = max(group, key=lambda r: confidence_weight.get(r.confidence, 0))
        merged.append(best)
        used.add(i)

    return normal_results + merged


class BatchReviewScheduler:
    """
    分批调度阅片，确保全量覆盖。

    将全部切片按 batch_size 分成多个批次，供宿主 AI 逐批检视。
    全部批次完成后合并结果并去重。
    """

    def __init__(self, batch_size: int = 15):
        """
        Args:
            batch_size: 每批切片数量，默认 15（范围 10~20 为佳）
        """
        self.batch_size = max(1, min(batch_size, 20))

    def create_batches(self, conversion_results: List[Dict]) -> List[List[Dict]]:
        """
        将全部切片分成多个批次列表。

        Args:
            conversion_results: DICOM 转换结果列表

        Returns:
            批次列表，每个元素是一个 conversion_results 子列表
        """
        batches = []
        for i in range(0, len(conversion_results), self.batch_size):
            batch = conversion_results[i:i + self.batch_size]
            batches.append(batch)
        return batches

    def merge_results(self, all_batch_results: List[List[ReviewResult]]) -> List[ReviewResult]:
        """
        合并所有批次结果，并对异常结果去重。

        Args:
            all_batch_results: 每个批次的检视结果列表

        Returns:
            合并并去重后的完整结果列表
        """
        # 扁平化所有批次的结果
        all_results = []
        for batch_results in all_batch_results:
            all_results.extend(batch_results)

        # 对异常结果进行去重
        return deduplicate_findings(all_results)


class AIReviewer:
    """
    AI 阅片检视器。

    此模块作为 AI 阅片的调度层：
    - 在 skill 模式下：生成提示词和图片路径，由宿主 AI 工具执行实际的视觉分析
    - 在独立运行模式下：生成待检视的占位结果

    重要：review() 返回的默认结论是 UNRECOGNIZABLE（待检视），
    宿主 AI 工具应调用 parse_ai_response() 将 AI 分析结果填入。
    如果最终结果全部为 UNRECOGNIZABLE，说明 AI 未真正参与阅片。
    """

    def __init__(self, imaging_profile: 'Optional[ImagingProfile]' = None):
        self._dicom_metadata_cache = {}
        if imaging_profile is None:
            # 向后兼容：自动加载胸部CT默认 Profile（Prompt 统一从 prompt_templates 获取）
            try:
                from modality_detector import get_imaging_profile, ImagingType
                self._profile = get_imaging_profile(ImagingType.CHEST_CT)
                logger.info("[向后兼容] 未传入 imaging_profile，已自动加载胸部CT默认 Profile")
            except Exception as e:
                logger.warning(f"[向后兼容] 自动加载胸部CT Profile 失败: {e}，将直接从 prompt_templates 加载")
                # 最后手段：直接构建最小 profile
                from prompt_templates.chest_ct import REVIEW_PROMPT, SUMMARY_PROMPT, MIP_PROMPT
                from dataclasses import dataclass
                # 用一个简易 namespace 对象兜底
                class _MinimalProfile:
                    imaging_type = "chest_ct"
                    display_name = "胸部CT"
                    window_presets = {"lung": (-600, 1500), "mediastinum": (40, 400), "ggo": (-600, 600), "narrow_ggo": (-550, 400)}
                    primary_window = "lung"
                    use_mip = True
                    use_ggo_window = True
                    classification_system = "Lung-RADS"
                    review_prompt_template = REVIEW_PROMPT
                    summary_prompt_template = SUMMARY_PROMPT
                    mip_prompt_template = MIP_PROMPT
                    report_sections = ["肺野", "纵隔", "骨骼", "扫及区域"]
                self._profile = _MinimalProfile()
        else:
            self._profile = imaging_profile

    def check_model_capability(self) -> bool:
        """
        检查宿主 AI 模型是否具备图像分析（多模态视觉）能力。

        通过输出一个测试请求，要求宿主 AI 分析一张小测试图。
        此方法在 skill 模式下输出预检提示，宿主 AI 工具应根据自身
        能力返回结果。在独立运行模式下默认返回 True。

        Returns:
            是否支持图像分析。在 skill 模式下，此方法会输出预检提示。
            实际的能力判断需要宿主 AI 工具配合完成。
        """
        safe_print("\n" + "=" * 60)
        safe_print("[模型能力预检] 检查宿主 AI 是否支持图像分析（多模态视觉模型）")
        safe_print("如果宿主 AI 不支持图像分析，将自动跳过 AI 阅片步骤。")
        safe_print("=" * 60 + "\n")
        # 在 skill 模式下，默认返回 True，宿主 AI 会根据自身能力决定
        # 是否能够执行后续的图像分析任务。如果宿主 AI 不支持视觉，
        # 它会在尝试阅片时返回错误，reviewer 会优雅处理。
        logger.info("[预检] 模型视觉能力预检完成——假定模型支持图像分析，实际能力将在阅片时验证")
        return True

    def get_review_prompt(self, png_name: str, dicom_name: str,
                          slice_info: str = "", cad_hint: str = "",
                          use_lite: bool = False) -> str:
        """
        生成单张图片的阅片提示词。

        v2.4.7: 新增 use_lite 参数。远离 CAD 候选的"快扫层"使用精简版 prompt，
        减少约 70% 的 token 消耗，大幅缓解宿主 AI 上下文耗尽问题。

        Args:
            png_name: PNG 图片文件名
            dicom_name: 对应的 DICOM 文件名
            slice_info: 层面信息，如 "第285/832层, SliceLocation=-120.5mm"
            cad_hint: CAD 自动预检候选提示文本（可选）
            use_lite: 是否使用精简版 prompt（v2.4.7+）

        Returns:
            格式化的提示词字符串
        """
        # 选择模板：精简版 or 完整版
        if use_lite:
            # 尝试从 prompt_templates 获取精简版
            try:
                from prompt_templates.chest_ct import REVIEW_PROMPT_LITE
                template = REVIEW_PROMPT_LITE
            except ImportError:
                # 如果没有精简版，回退到完整版
                template = self._profile.review_prompt_template
        else:
            template = self._profile.review_prompt_template

        # 尝试格式化 cad_hint，如果模板不支持则忽略
        try:
            return template.format(
                filename=png_name,
                dicom_name=dicom_name,
                slice_info=slice_info if slice_info else "未知",
                cad_hint=cad_hint if cad_hint else "",
            )
        except KeyError:
            # 旧版模板没有 cad_hint 占位符
            return template.format(
                filename=png_name,
                dicom_name=dicom_name,
                slice_info=slice_info if slice_info else "未知",
            )

    def get_mip_review_prompt(self, png_name: str, dicom_name: str,
                              slice_info: str = "") -> str:
        """
        生成 MIP 图像的专用阅片提示词。

        MIP 图像与普通切片不同，需要专门的分析引导。

        Args:
            png_name: MIP PNG 文件名
            dicom_name: MIP 描述（如 "MIP (层 1-5/800)"）
            slice_info: 层面信息

        Returns:
            格式化的 MIP 阅片提示词
        """
        if self._profile and not self._profile.use_mip:
            logger.warning("当前影像类型不支持MIP，返回空提示词")
            return ""
        template = (self._profile.mip_prompt_template if self._profile.mip_prompt_template
                    else "")
        if not template:
            logger.warning("当前 Profile 无 MIP Prompt 模板，返回空提示词")
            return ""
        return template.format(
            filename=png_name,
            dicom_name=dicom_name,
            slice_info=slice_info if slice_info else "未知",
        )

    def get_summary_prompt(self, review_results: List[ReviewResult],
                          window_type: str = "lung",
                          enhance_method: str = "Lanczos 高质量插值放大") -> str:
        """
        生成全部图片检视完成后的汇总提示词，用于输出医院风格的报告。

        Args:
            review_results: 所有图片的检视结果
            window_type: 使用的窗口类型
            enhance_method: 图像增强方式描述

        Returns:
            汇总提示词字符串
        """
        # 窗口类型显示名称
        # 根据 Profile 动态生成窗位显示名
        if self._profile.window_presets:
            # 从 Profile 的窗位预设动态生成显示名
            window_parts = []
            for wname, (wc, ww) in self._profile.window_presets.items():
                window_parts.append(f"{wname} (WC={wc}, WW={ww})")
            window_name = " + ".join(window_parts) if window_parts else "DICOM 自带窗位"
        else:
            window_name = "DICOM 自带窗位"

        abnormal_results = [r for r in review_results if r.conclusion == ReviewConclusion.ABNORMAL]

        if abnormal_results:
            summary_lines = []
            for i, r in enumerate(abnormal_results, 1):
                line = f"  {i}. {r.dicom_name}"
                if r.location:
                    line += f" — 位置: {r.location}"
                if r.size_mm:
                    line += f", 大小: {r.size_mm}mm"
                if r.abnormality_desc:
                    line += f", 描述: {r.abnormality_desc}"
                if r.classification_system and r.classification_value:
                    line += f", {r.classification_system}: {r.classification_value}"
                elif r.lung_rads:
                    line += f", Lung-RADS: {r.lung_rads}"
                summary_lines.append(line)
            abnormal_summary = "\n".join(summary_lines)
        else:
            abnormal_summary = "  未发现明确异常。"

        template = self._profile.summary_prompt_template
        return template.format(
            total_count=len(review_results),
            abnormal_summary=abnormal_summary,
            window_type=window_name,
            enhance_method=enhance_method,
        )

    def parse_ai_response(self, response: str, png_name: str,
                          dicom_name: str, png_path: str) -> ReviewResult:
        """
        解析 AI 的回复，构建结构化检视结果。

        Args:
            response: AI 的原始回复文本
            png_name: PNG 图片文件名
            dicom_name: 对应的 DICOM 文件名
            png_path: PNG 图片完整路径

        Returns:
            ReviewResult 结构化结果
        """
        result = ReviewResult(
            png_name=png_name,
            dicom_name=dicom_name,
            png_path=png_path,
        )

        try:
            # 尝试从回复中提取 JSON
            json_str = self._extract_json(response)
            if json_str:
                data = json.loads(json_str)
                conclusion_str = data.get("conclusion", "无法识别")
                if conclusion_str == "正常":
                    result.conclusion = ReviewConclusion.NORMAL
                elif conclusion_str == "异常":
                    result.conclusion = ReviewConclusion.ABNORMAL
                else:
                    result.conclusion = ReviewConclusion.UNRECOGNIZABLE

                result.abnormality_desc = data.get("abnormality_desc", "")
                result.confidence = data.get("confidence", "低")
                result.details = data.get("details", "")
                result.location = data.get("location", "")
                result.size_mm = data.get("size_mm", "")
                result.recommendation = data.get("recommendation", "")

                # 解析 bounding_boxes 字段
                raw_boxes = data.get("bounding_boxes", [])
                if isinstance(raw_boxes, list):
                    validated_boxes = []
                    for box in raw_boxes:
                        if isinstance(box, dict) and all(k in box for k in ("x", "y", "width", "height")):
                            try:
                                validated_boxes.append({
                                    "x": float(box["x"]),
                                    "y": float(box["y"]),
                                    "width": float(box["width"]),
                                    "height": float(box["height"]),
                                })
                            except (ValueError, TypeError):
                                logger.warning(f"bounding_box 坐标无法解析: {box}")
                    result.bounding_boxes = validated_boxes

                # 根据 Profile 的 classification_system 解析分级字段
                if self._profile and self._profile.classification_system == "Lung-RADS":
                    result.lung_rads = data.get("lung_rads", "") or data.get("classification_value", "")
                    result.classification_system = "Lung-RADS"
                    result.classification_value = result.lung_rads
                elif self._profile and self._profile.classification_system == "LI-RADS":
                    li_rads = data.get("classification_value", "") or data.get("li_rads", "") or data.get("classification", "")
                    result.classification_system = "LI-RADS"
                    result.classification_value = li_rads
                elif self._profile and self._profile.classification_system:
                    result.classification_system = self._profile.classification_system
                    result.classification_value = data.get("classification_value", "") or data.get("classification", "")
                else:
                    # 无 Profile 或无分级系统：兼容旧的 lung_rads 字段
                    result.lung_rads = data.get("lung_rads", "")
                    if result.lung_rads:
                        result.classification_system = "Lung-RADS"
                        result.classification_value = result.lung_rads
                    elif data.get("classification_value"):
                        result.classification_system = data.get("classification_system", "")
                        result.classification_value = data.get("classification_value", "")
            else:
                # 无法解析 JSON，尝试从文本中推断
                response_lower = response.lower()
                if any(kw in response_lower for kw in ["结节", "异常", "肿块", "钙化", "nodule", "mass", "abnormal"]):
                    result.conclusion = ReviewConclusion.ABNORMAL
                    result.abnormality_desc = response[:500]
                    result.confidence = "中"
                    result.details = "从 AI 回复文本中推断为异常（JSON 解析失败）"
                elif any(kw in response_lower for kw in ["正常", "未见异常", "normal", "no abnormal"]):
                    result.conclusion = ReviewConclusion.NORMAL
                    result.details = response[:500]
                    result.confidence = "中"
                else:
                    result.conclusion = ReviewConclusion.UNRECOGNIZABLE
                    result.details = f"AI 回复格式无法解析: {response[:200]}"
                    result.confidence = "低"
        except Exception as e:
            logger.warning(f"解析 AI 回复失败: {e}")
            result.conclusion = ReviewConclusion.UNRECOGNIZABLE
            result.details = f"回复解析失败: {str(e)}"
            result.confidence = "低"

        return result

    def _write_review_bundle(self, review_requests: List[Dict], results: List[ReviewResult],
                             output_dir: str, batch_size: int, total_batches: int) -> Dict[str, str]:
        """把阅片请求、占位结果和清单稳定写入输出目录，方便他人接手继续跑。"""
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)

        manifest_path = output_path / "review_manifest.json"
        requests_md_path = output_path / "review_requests.md"
        stub_results_path = output_path / "review_results_stub.json"
        batch_template_dir = output_path / "review_batch_templates"

        save_review_results_json(results, str(stub_results_path))
        batch_template_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "bundle_version": _SKILL_VERSION,
            "total_images": len(review_requests),
            "batch_size": batch_size,
            "total_batches": total_batches,
            "requests": review_requests,
            "stub_results_json": str(stub_results_path),
            "batch_template_dir": str(batch_template_dir),
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        lines = [
            "# 阅片请求导出",
            "",
            f"- 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 总图片数：{len(review_requests)}",
            f"- 批次数：{total_batches}",
            f"- 每批大小：{batch_size}",
            f"- 占位结果 JSON：`{stub_results_path}`",
            f"- 结构化清单 JSON：`{manifest_path}`",
            f"- 批次模板目录：`{batch_template_dir}`",
            "",
            "## 使用方式",
            "",
            "1. 逐张查看下列图片路径，按 prompt 要求完成阅片。",
            "2. 可手工按批填写 `review_batch_templates/batch_XXX.json` 中每个 item.result；若已配置外部视觉模型，也可直接运行 `auto_review_batches.py` 自动回填。",
            "3. 手工/半自动模式下，每完成一批，运行 `apply_review_batch.py` 将该批结果并入总表。",
            "4. 若使用 `auto_review_batches.py`，脚本会自动持续合并并生成 `review_results.json`。",
            "5. 全部批次完成后，使用生成好的 `review_results.json` 调用 `generate_report.py` 生成正式报告。",
            "",
        ]

        results_by_index = {idx: result for idx, result in enumerate(results, start=1)}
        grouped_requests: Dict[int, List[Dict]] = {}
        for request in review_requests:
            grouped_requests.setdefault(request["batch_index"], []).append(request)

        for batch_index, batch_requests in grouped_requests.items():
            batch_payload = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "batch_index": batch_index,
                "total_batches": total_batches,
                "total_items": len(batch_requests),
                "items": [],
            }
            for request in batch_requests:
                batch_payload["items"].append({
                    **request,
                    "result": results_by_index[request["global_index"]].to_dict(),
                })

            batch_file = batch_template_dir / f"batch_{batch_index:03d}.json"
            with open(batch_file, "w", encoding="utf-8") as f:
                json.dump(batch_payload, f, ensure_ascii=False, indent=2)

        for request in review_requests:
            lines.extend([
                f"## 阅片请求 {request['global_index']}/{len(review_requests)}",
                "",
                f"- 批次：{request['batch_index']}/{total_batches}",
                f"- PNG（肺窗）：`{request['png_path']}`",
                f"- PNG（纵隔窗）：`{request['mediastinum_path'] or ''}`",
                f"- PNG（GGO窗）：`{request['ggo_path'] or ''}`",
                f"- PNG（高灵敏度GGO窗）：`{request.get('narrow_ggo_path', '') or ''}`",
                f"- DICOM：`{request['dicom_name']}`",
                f"- 层面序号：`{request['slice_index'] or ''}`",
                f"- SliceLocation：`{request['slice_location'] or ''}`",
                f"- MIP：`{'是' if request['is_mip'] else '否'}`",
                "",
                "```text",
                request['prompt'],
                "```",
                "",
            ])

        with open(requests_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"已导出阅片请求清单: {requests_md_path}")
        logger.info(f"已导出阅片结构化清单: {manifest_path}")
        logger.info(f"已导出占位阅片结果 JSON: {stub_results_path}")
        logger.info(f"已导出批次模板目录: {batch_template_dir}")
        logger.info(
            "后续可手工逐批填写 review_batch_templates/batch_XXX.json 并用 apply_review_batch.py 合并；"
            "若已配置外部视觉模型，也可直接运行 auto_review_batches.py 自动回填并持续合并。"
        )

        return {
            "manifest_path": str(manifest_path),
            "requests_md_path": str(requests_md_path),
            "stub_results_path": str(stub_results_path),
            "batch_template_dir": str(batch_template_dir),
        }

    def review(self, conversion_results: List[Dict[str, str]],
               export_dir: Optional[str] = None,
               cad_hint: str = "",
               cad_candidates: Optional[Dict] = None) -> List[ReviewResult]:
        """
        逐张检视图片，生成检视结果。

        使用 BatchReviewScheduler 进行分批调度。
        在 skill 模式下，为每张图片生成提示词并输出。
        宿主 AI 工具应接管实际的视觉分析，调用 parse_ai_response() 回填结果。

        注意：返回的默认结论为 UNRECOGNIZABLE（待检视），不是 NORMAL。
        如果最终报告中全部为 UNRECOGNIZABLE，说明 AI 未真正执行阅片分析。

        v2.4.7 上下文优化：
          - 新增 cad_candidates 参数（结构化 CAD 数据），支持分层 CAD hint 注入
          - 远离 CAD 候选的"快扫层"使用精简版 REVIEW_PROMPT_LITE（~600字 vs ~5000字）
          - 快扫层批次自动增大到 30 张（重点层保持 15 张）
          - 每层只注入附近 5 层范围内的 CAD 候选，不再全局注入

        Args:
            conversion_results: DICOM 转换结果列表
            export_dir: 可选输出目录。提供后会额外写出 review_requests.md / review_manifest.json / review_results_stub.json
            cad_hint: CAD 自动预检候选全局提示文本（旧模式兼容，v2.4.7 优先使用 cad_candidates）
            cad_candidates: 结构化 CAD 候选数据（v2.4.7+），包含 solid_candidates/ggo_candidates/series_info

        Returns:
            检视结果列表
        """
        results = []
        review_requests = []
        total = len(conversion_results)

        # ====== v2.4.7: 计算 CAD 重点层集合和分层 hint 函数 ======
        focus_slices = set()
        solid_cands = []
        ggo_cands = []
        n_slices_cad = 0
        spacing_cad = None
        use_per_slice_cad = False

        if cad_candidates:
            try:
                from cad_detector import get_cad_focus_slices, format_candidates_for_slice
                solid_cands = cad_candidates.get('solid_candidates', [])
                ggo_cands = cad_candidates.get('ggo_candidates', [])
                n_slices_cad = cad_candidates.get('series_info', {}).get('n_slices', 0)
                spacing_cad = cad_candidates.get('series_info', {}).get('spacing')
                focus_slices = get_cad_focus_slices(solid_cands, ggo_cands, margin=5)
                use_per_slice_cad = True
                logger.info(
                    f"[v2.4.7 上下文优化] CAD 候选: 实性{len(solid_cands)} + GGO{len(ggo_cands)}, "
                    f"重点层: {len(focus_slices)}/{total}, "
                    f"快扫层: {total - len(focus_slices)}/{total}"
                )
            except ImportError:
                logger.warning("[v2.4.7] cad_detector 模块不可用，回退到全局 CAD hint 模式")
                use_per_slice_cad = False

        # 使用 BatchReviewScheduler 分批
        scheduler = BatchReviewScheduler(batch_size=15)
        batches = scheduler.create_batches(conversion_results)
        total_batches = len(batches)

        # v2.4.7: 输出上下文优化统计
        if use_per_slice_cad and total > 50:
            n_focus = len(focus_slices)
            n_quick = total - n_focus
            est_full_tokens = total * 1400  # 完整 prompt ~5000 字 ≈ ~1400 tokens
            est_opt_tokens = n_focus * 1400 + n_quick * 400  # 精简 prompt ~600 字 ≈ ~400 tokens
            save_pct = (1 - est_opt_tokens / est_full_tokens) * 100 if est_full_tokens > 0 else 0
            safe_print(f"\n{'🔧'*20}")
            safe_print(f"[v2.4.7 上下文优化] 共 {total} 层:")
            safe_print(f"  📌 重点层（CAD候选±5层）: {n_focus} 层 → 完整版 prompt + 分层 CAD hint")
            safe_print(f"  ⚡ 快扫层: {n_quick} 层 → 精简版 prompt（无全局 CAD hint）")
            safe_print(f"  📊 预估 prompt token 节省: ~{save_pct:.0f}%")
            safe_print(f"{'🔧'*20}\n")

        # 强制全量阅片警告
        if total > 50:
            safe_print(f"\n{'!'*60}")
            safe_print(f"[重要] 共 {total} 张影像需要检视，分为 {total_batches} 个批次，必须全量阅片，不得跳过！")
            safe_print(f"[重要] 微小结节(2-6mm)可能仅出现在1-3层中，跳过即漏诊。")
            safe_print(f"[重要] 每批 {scheduler.batch_size} 张原始分辨率切片，严禁缩放或拼图。")
            safe_print(f"[重要] 每批必须先独立检视 GGO 窗（_ggo.png），再对比肺窗和纵隔窗。")
            safe_print(f"{'!'*60}\n")

        global_idx = 0  # 全局图片序号

        for batch_idx, batch in enumerate(batches, 1):
            batch_start = global_idx + 1
            batch_end = global_idx + len(batch)

            safe_print(f"\n{'#'*60}")
            safe_print(f"[批次 {batch_idx}/{total_batches}] 切片 {batch_start}-{batch_end}/{total}")
            safe_print(f"{'#'*60}\n")

            batch_abnormal_count = 0

            for item in batch:
                global_idx += 1
                png_path = item["png_path"]
                png_name = os.path.basename(png_path)
                dicom_name = item["dicom_name"]
                mediastinum_path = item.get("mediastinum_path", "")
                ggo_path = item.get("ggo_path", "")
                narrow_ggo_path = item.get("narrow_ggo_path", "")
                is_mip = item.get("is_mip", False)
                slice_index = item.get("slice_index", "")
                slice_location = item.get("slice_location", "")

                # 构建层面信息字符串
                slice_info_parts = []
                if slice_index:
                    slice_info_parts.append(f"第{slice_index}层")
                if slice_location:
                    slice_info_parts.append(f"SliceLocation={slice_location}mm")
                slice_info = ", ".join(slice_info_parts) if slice_info_parts else ""

                logger.info(f"检视图片 ({global_idx}/{total}) [批次 {batch_idx}/{total_batches}]: {png_name} (原始: {dicom_name})")

                # ====== v2.4.7: 分层 CAD hint + 精简版/完整版 prompt 选择 ======
                slice_z = self._parse_z_from_slice_index(slice_index)
                is_focus = slice_z is not None and slice_z in focus_slices if use_per_slice_cad else True

                if is_mip:
                    prompt = self.get_mip_review_prompt(png_name, dicom_name, slice_info)
                    layer_type = "MIP"
                elif use_per_slice_cad:
                    # v2.4.7: 分层模式
                    from cad_detector import format_candidates_for_slice
                    per_slice_hint = format_candidates_for_slice(
                        solid_cands, ggo_cands,
                        slice_z if slice_z is not None else 0,
                        n_slices=n_slices_cad,
                        spacing=spacing_cad,
                        proximity=5,
                    ) if slice_z is not None else ""

                    prompt = self.get_review_prompt(
                        png_name, dicom_name, slice_info,
                        cad_hint=per_slice_hint,
                        use_lite=not is_focus,
                    )
                    layer_type = "📌重点" if is_focus else "⚡快扫"
                else:
                    # 旧模式：全局 CAD hint
                    prompt = self.get_review_prompt(png_name, dicom_name, slice_info, cad_hint=cad_hint)
                    layer_type = "标准"

                # 输出提示词和图片路径，供宿主 AI 工具使用
                safe_print(f"\n{'='*60}")
                safe_print(f"[阅片请求 {global_idx}/{total}] [批次 {batch_idx}/{total_batches}] [{layer_type}]{'  ★ MIP 图像' if is_mip else ''}")
                safe_print(f"图片路径（肺窗）: {png_path}")
                if mediastinum_path:
                    safe_print(f"图片路径（纵隔窗）: {mediastinum_path}")
                if ggo_path:
                    safe_print(f"图片路径（GGO 窗 — ⚠️ 必须先独立检视此窗口）: {ggo_path}")
                if narrow_ggo_path:
                    safe_print(f"图片路径（高灵敏度 GGO 窗 — ⚠️ 极淡磨玻璃结节专用）: {narrow_ggo_path}")
                if slice_info:
                    safe_print(f"层面位置: {slice_info}")
                safe_print(f"DICOM 文件: {dicom_name}")
                safe_print(f"{'='*60}")
                safe_print(prompt)
                safe_print(f"{'='*60}\n")

                review_requests.append({
                    "global_index": global_idx,
                    "batch_index": batch_idx,
                    "png_name": png_name,
                    "dicom_name": dicom_name,
                    "png_path": png_path,
                    "mediastinum_path": mediastinum_path,
                    "ggo_path": ggo_path,
                    "narrow_ggo_path": narrow_ggo_path,
                    "is_mip": is_mip,
                    "slice_index": slice_index,
                    "slice_location": slice_location,
                    "prompt": prompt,
                    "is_focus_layer": is_focus,  # v2.4.7
                    "layer_type": layer_type,  # v2.4.7
                })

                # 创建待填充的检视结果
                result = ReviewResult(
                    png_name=png_name,
                    dicom_name=dicom_name,
                    png_path=png_path,
                    conclusion=ReviewConclusion.UNRECOGNIZABLE,
                    abnormality_desc="",
                    confidence="待检视",
                    details=f"等待 AI 检视此影像。如果此条目最终仍为'无法识别'，说明 AI 未执行阅片分析。",
                    slice_index=slice_index,
                    slice_location=slice_location,
                )
                results.append(result)

            # 批次完成后输出中间统计
            batch_results = results[batch_start - 1:batch_end]
            batch_abnormal_count = sum(1 for r in batch_results if r.conclusion == ReviewConclusion.ABNORMAL)
            safe_print(f"\n[批次 {batch_idx}/{total_batches} 完成] 本批 {len(batch)} 张，发现异常 {batch_abnormal_count} 张")

        # 输出全部汇总
        normal_count = sum(1 for r in results if r.conclusion == ReviewConclusion.NORMAL)
        abnormal_count = sum(1 for r in results if r.conclusion == ReviewConclusion.ABNORMAL)
        unrecognizable_count = sum(1 for r in results if r.conclusion == ReviewConclusion.UNRECOGNIZABLE)

        logger.info(
            f"阅片检视完成: 共 {total} 张，"
            f"正常 {normal_count} 张，异常 {abnormal_count} 张，"
            f"待检视/无法识别 {unrecognizable_count} 张"
        )

        if unrecognizable_count == total:
            logger.warning(
                f"⚠ 已阅片 0/{total} 张，缺少 {total} 张未阅片！\n"
                "所有图片均为'待检视'状态，说明 AI 尚未执行实际阅片分析。\n"
                "宿主 AI 工具需要：\n"
                "  1. 逐张读取全部 PNG 图片（可分批，每批 10-20 张）\n"
                "  2. 使用上面输出的提示词进行视觉分析\n"
                "  3. 调用 parse_ai_response() 回填每张图片的检视结果\n"
                "  ❗ 不得自行决定只看部分图片，必须全量阅片！"
            )
        elif unrecognizable_count > 0:
            reviewed = total - unrecognizable_count
            logger.warning(
                f"⚠ 已阅片 {reviewed}/{total} 张，缺少 {unrecognizable_count} 张未阅片！\n"
                "请确保宿主 AI 继续检视剩余图片，不得遗漏！"
            )
        else:
            logger.info(f"✓ 全量阅片完成：已阅片 {total}/{total} 张，无遗漏")

        if export_dir:
            self._write_review_bundle(
                review_requests=review_requests,
                results=results,
                output_dir=export_dir,
                batch_size=scheduler.batch_size,
                total_batches=total_batches,
            )

        # 输出汇总 prompt，供宿主 AI 生成医院风格的最终报告
        summary_prompt = self.get_summary_prompt(results)
        safe_print(f"\n{'='*60}")
        safe_print("[最终汇总请求]")
        safe_print(f"{'='*60}")
        safe_print(summary_prompt)
        safe_print(f"{'='*60}\n")

        return results

    @staticmethod
    def _parse_z_from_slice_index(slice_index: str) -> Optional[int]:
        """从 '285/832' 格式的 slice_index 提取整数层面编号。

        v2.4.7: 用于分层 CAD hint 的 z-index 匹配。
        注意 InstanceNumber→z-index 的映射关系因 DICOM 排序而异，
        这里取分子部分作为近似 z-index。

        Args:
            slice_index: 层面序号字符串，如 "285/832"

        Returns:
            层面编号整数，解析失败返回 None
        """
        if not slice_index:
            return None
        try:
            return int(str(slice_index).split("/")[0])
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """从文本中提取 JSON 字符串"""
        # 尝试找到 JSON 代码块
        import re
        pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 尝试找到 {...} 块
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            return text[brace_start:brace_end + 1]

        return None
