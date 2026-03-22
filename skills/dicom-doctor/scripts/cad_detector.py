#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD 自动候选结节检测模块（Computer-Aided Detection）v2.2

直接从 DICOM 原始 HU 数据中进行 3D 连通域分析，
输出候选结节列表（含位置、大小、HU、形态等信息）。

v2.2 核心改进（v1.9.0 — 基于5个ground truth结节校准）：
  - [新] 实性mask binary_closing: 填补厚层(≥1mm)下微小结节的体素间隙
  - [新] 空间邻近碎片二次聚合: 距离<2mm的小候选自动合并
  - [新] min_diameter_mm 降至1.5mm: 捞回被过滤的1.5-2mm真结节
  - [新] 碎片降权: d<1.8mm 且 z_slices=1 的候选在评分中降权
  - 用多维度评分排序替代硬阈值过滤（避免误杀真结节）
  - 评分维度：球形度、elongation、大小、HU、z层数、密度一致性
  - 权重：球形度0.25, elongation0.25, 大小0.20, HU0.12, z层数0.13, 一致性0.05
  - 输出 Top-N 候选（默认 25 实性 + 15 GGO），附带可信度评分
  - 生成全切面图 + 四窗位合成图，方便 AI 视觉确认

校准数据集：
  - Case 1: 2023-06-02 胸部CT (0.625mm), 右肺下叶前基底段 2mm 炎性肉芽肿 → ⭐0.947
  - Case 2: 2026-01-10 胸部CT (1.25mm), 4个结节:
    GT1 左肺上叶GGO 4mm → 检出, GT2 右肺中叶3mm → 检出,
    GT3 右肺下叶2mm → 检出, GT4 左肺下叶背段2mm×1mm → v1.8.0漏检→v1.9.0修复

算法流程：
  1. 读取 DICOM volume（优先选择薄层重建 series）
  2. 2D 逐层肺分割（填充法获得完整肺轮廓）
  3. 在肺轮廓内检测高密度区域（实性候选）和中等密度区域（GGO候选）
  3.5 [新] 实性mask morphological closing（厚层≥1mm时启用）
  4. 3D 连通域标记 + 形态学特征计算
  4.5 [新] 空间邻近碎片二次聚合
  5. 多维度评分排序
  6. 空间聚类合并 + Top-N 截取
"""

import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("dicom-doctor.cad")


def _check_deps():
    """检查 CAD 所需依赖"""
    try:
        import SimpleITK
        import numpy
        from scipy import ndimage
        return True
    except ImportError as e:
        logger.warning(f"CAD 模块缺少依赖: {e}，跳过自动检测")
        return False


def detect_nodule_candidates(
    input_path: str,
    output_dir: Optional[str] = None,
    solid_hu_threshold: float = -100,
    ggo_hu_low: float = -650,
    ggo_hu_high: float = -300,
    min_diameter_mm: float = 1.5,
    max_diameter_mm: float = 35.0,
    merge_distance_mm: float = 8.0,
    top_n_solid: int = 25,
    top_n_ggo: int = 15,
) -> Dict:
    """
    自动检测候选结节（v2: 评分排序替代硬阈值过滤）。

    核心改进：
      - 不再使用硬 elongation/z_slices 阈值过滤（容易误杀真结节）
      - 改用多维度评分系统，综合球形度、elongation、大小、HU、z层数打分
      - 按评分排序，输出 Top-N 候选给 AI 视觉确认

    Args:
        input_path: DICOM 目录或 ZIP 文件路径
        output_dir: 可选，输出标注图的目录
        solid_hu_threshold: 实性候选的 HU 下限（默认 -100）
        ggo_hu_low: GGO 候选 HU 下限（默认 -650）
        ggo_hu_high: GGO 候选 HU 上限（默认 -300）
        min_diameter_mm: 最小等效直径（mm）
        max_diameter_mm: 最大等效直径（mm）
        merge_distance_mm: 聚类合并距离（mm）
        top_n_solid: 输出的实性候选数量上限
        top_n_ggo: 输出的 GGO 候选数量上限

    Returns:
        dict: {
            'solid_candidates': [...],   # 按评分排序的 Top-N 实性候选
            'ggo_candidates': [...],     # 按评分排序的 Top-N GGO 候选
            'series_info': {...},
            'annotation_images': [...],  # 标注图路径
        }
    """
    if not _check_deps():
        return {'solid_candidates': [], 'ggo_candidates': [], 'series_info': {}, 'annotation_images': []}

    import SimpleITK as sitk
    import numpy as np
    from scipy import ndimage
    from scipy.ndimage import binary_fill_holes, binary_opening

    # ===== 1. 读取 DICOM volume =====
    arr, spacing, origin, temp_cleanup = _load_dicom_volume(input_path)
    if arr is None:
        return {'solid_candidates': [], 'ggo_candidates': [], 'series_info': {}, 'annotation_images': []}

    series_info = {
        'n_slices': int(arr.shape[0]),
        'spacing': [round(s, 4) for s in spacing],
        'origin': [round(o, 2) for o in origin],
        'shape': list(arr.shape),
    }
    logger.info(f"CAD: 加载 volume {arr.shape}, spacing={spacing}, HU=[{arr.min()},{arr.max()}]")

    # ===== 2. 肺分割 =====
    lung_contour = _segment_lungs_2d(arr)
    logger.info(f"CAD: 肺分割完成，肺轮廓体素={lung_contour.sum()}")

    # ===== 3. 检测高密度区域 =====
    # 实性候选
    solid_mask = lung_contour & (arr > solid_hu_threshold) & (arr < 500)

    # v1.9.0: 对厚层(≥1mm)做 binary_closing 填补微小结节的体素间隙
    # 解决 GT4 (2mm×1mm, 1.25mm层厚) 被拆成碎片导致漏检的问题
    z_spacing = spacing[2]
    if z_spacing >= 1.0:
        from scipy.ndimage import binary_closing
        solid_mask = binary_closing(solid_mask, iterations=1)
        # closing 后重新限制在肺轮廓内
        solid_mask = solid_mask & lung_contour
        logger.info(f"CAD: 厚层({z_spacing:.2f}mm) → 实性mask binary_closing 已应用")

    labeled_s, n_s = ndimage.label(solid_mask)
    logger.info(f"CAD: 实性区域 (HU>{solid_hu_threshold}): {n_s} 个连通域")

    solid_raw = _extract_candidates(arr, labeled_s, n_s, spacing, origin, 'solid',
                                     min_diameter_mm, max_diameter_mm)

    # v1.9.0: 空间邻近碎片二次聚合 — 合并距离<2mm的碎片候选
    solid_raw = _aggregate_fragments(solid_raw, arr, spacing, origin,
                                      max_merge_dist_mm=2.0, min_diameter_mm=min_diameter_mm)

    # v1.9.0: 大连通域内部密度峰值子候选提取
    # 在厚层CT中，微小结节可能被血管吞并到大连通域里
    if z_spacing >= 1.0:
        sub_candidates = _extract_density_peaks(
            arr, solid_mask, lung_contour, spacing, origin,
            peak_hu_threshold=50, min_peak_voxels=2, max_peak_diameter=4.0
        )
        if sub_candidates:
            solid_raw.extend(sub_candidates)
            logger.info(f"CAD: 密度峰值子候选 — 新增 {len(sub_candidates)} 个")

    # GGO 候选
    ggo_mask = lung_contour & (arr > ggo_hu_low) & (arr < ggo_hu_high)
    ggo_mask = binary_opening(ggo_mask, iterations=1)
    labeled_g, n_g = ndimage.label(ggo_mask)
    logger.info(f"CAD: GGO 区域 ({ggo_hu_low}<HU<{ggo_hu_high}): {n_g} 个连通域")

    ggo_raw = _extract_candidates(arr, labeled_g, n_g, spacing, origin, 'ggo',
                                   min_diameter_mm, max_diameter_mm)

    logger.info(f"CAD: 提取候选 — 实性 {len(solid_raw)} 个, GGO {len(ggo_raw)} 个")

    # ===== 4. 评分排序（替代硬阈值过滤）=====
    for c in solid_raw:
        c['nodule_score'] = _compute_nodule_score(c, 'solid', z_spacing=z_spacing)
    for c in ggo_raw:
        c['nodule_score'] = _compute_nodule_score(c, 'ggo', z_spacing=z_spacing)

    solid_scored = sorted(solid_raw, key=lambda x: -x['nodule_score'])
    ggo_scored = sorted(ggo_raw, key=lambda x: -x['nodule_score'])

    # ===== 5. 聚类合并（评分排序后，高分候选优先保留）=====
    solid_merged = _merge_nearby(solid_scored, merge_distance_mm, spacing)
    ggo_merged = _merge_nearby(ggo_scored, merge_distance_mm, spacing)

    # 取 Top-N
    solid_top = solid_merged[:top_n_solid]
    ggo_top = ggo_merged[:top_n_ggo]

    logger.info(f"CAD: 评分+合并后 — 实性 {len(solid_merged)} → Top {len(solid_top)}, "
                f"GGO {len(ggo_merged)} → Top {len(ggo_top)}")

    # ===== 6. 生成标注图（带评分信息）=====
    annotation_images = []
    if output_dir:
        annotation_images = _generate_annotations(arr, spacing, origin,
                                                   solid_top, ggo_top, output_dir)

    # 清理临时文件
    if temp_cleanup:
        import shutil
        shutil.rmtree(temp_cleanup, ignore_errors=True)

    return {
        'solid_candidates': solid_top,
        'ggo_candidates': ggo_top,
        'series_info': series_info,
        'annotation_images': annotation_images,
    }


def _load_dicom_volume(input_path: str):
    """加载 DICOM volume，返回 (arr, spacing, origin, temp_dir_to_cleanup)"""
    import SimpleITK as sitk
    import shutil

    temp_dir = None
    dicom_dir = input_path

    # 如果是 ZIP，解压到临时目录
    if zipfile.is_zipfile(input_path):
        temp_dir = tempfile.mkdtemp(prefix="cad_dicom_")
        with zipfile.ZipFile(input_path, 'r') as zf:
            zf.extractall(temp_dir)
        dicom_dir = temp_dir

    # 遍历找到最长的 series
    reader = sitk.ImageSeriesReader()
    best_count = 0
    best_sid = best_dir = None

    for root, dirs, files in os.walk(dicom_dir):
        if '__MACOSX' in root:
            continue
        try:
            sids = reader.GetGDCMSeriesIDs(root)
        except:
            continue
        for sid in sids:
            try:
                fnames = reader.GetGDCMSeriesFileNames(root, sid)
                if len(fnames) > best_count:
                    best_count = len(fnames)
                    best_sid = sid
                    best_dir = root
            except:
                continue

    if best_count == 0:
        logger.warning("CAD: 未找到任何 DICOM series")
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None, None, None

    logger.info(f"CAD: 选择 series ({best_count} 切片)")
    fnames = reader.GetGDCMSeriesFileNames(best_dir, best_sid)
    reader.SetFileNames(fnames)
    image = reader.Execute()

    import numpy as np
    arr = sitk.GetArrayFromImage(image)
    spacing = image.GetSpacing()
    origin = image.GetOrigin()

    return arr, spacing, origin, temp_dir


def _segment_lungs_2d(arr):
    """逐层 2D 肺分割，返回包含肺内所有结构的完整肺轮廓"""
    import numpy as np
    from scipy import ndimage
    from scipy.ndimage import binary_fill_holes

    lung_contour = np.zeros(arr.shape, dtype=bool)

    for z in range(arr.shape[0]):
        slc = arr[z]
        air = slc < -300
        labeled, n = ndimage.label(air)

        # 找接触边界的连通域（体外空气）
        border = set()
        for v in labeled[0, :]:
            if v > 0: border.add(v)
        for v in labeled[-1, :]:
            if v > 0: border.add(v)
        for v in labeled[:, 0]:
            if v > 0: border.add(v)
        for v in labeled[:, -1]:
            if v > 0: border.add(v)

        lung_air = air.copy()
        for bl in border:
            lung_air[labeled == bl] = False

        # 只保留较大的空气区域
        labeled2, n2 = ndimage.label(lung_air)
        for i in range(1, n2 + 1):
            comp = labeled2 == i
            if comp.sum() < 500:
                lung_air[comp] = False

        # fill_holes 得到完整肺轮廓
        if lung_air.sum() > 0:
            lung_contour[z] = binary_fill_holes(lung_air)

    return lung_contour


def _extract_candidates(arr, labeled, n_labels, spacing, origin, ctype,
                        min_diam, max_diam):
    """从标记的连通域中提取候选"""
    import numpy as np

    candidates = []
    for i in range(1, n_labels + 1):
        comp = labeled == i
        vol = int(comp.sum())
        if vol < 2:
            continue
        vol_mm3 = vol * spacing[0] * spacing[1] * spacing[2]
        diam = (6 * vol_mm3 / 3.14159265) ** (1/3)
        if diam < min_diam or diam > max_diam:
            continue

        zs, ys, xs = np.where(comp)
        mean_hu = float(arr[comp].mean())
        max_hu = float(arr[comp].max())

        z_span = (zs.max() - zs.min() + 1) * spacing[2]
        y_span = (ys.max() - ys.min() + 1) * spacing[1]
        x_span = (xs.max() - xs.min() + 1) * spacing[0]
        elongation = max(z_span, y_span, x_span) / (min(z_span+0.01, y_span+0.01, x_span+0.01))
        z_slices = len(set(zs.tolist()))

        candidates.append({
            'type': ctype, 'voxels': vol,
            'vol_mm3': round(vol_mm3, 1), 'diameter_mm': round(diam, 1),
            'mean_hu': round(mean_hu), 'max_hu': round(max_hu),
            'cz': round(float(zs.mean()), 1),
            'cy': round(float(ys.mean()), 1),
            'cx': round(float(xs.mean()), 1),
            'cy_mm': round(float(ys.mean() * spacing[1] + origin[1]), 1),
            'cx_mm': round(float(xs.mean() * spacing[0] + origin[0]), 1),
            'cz_mm': round(float(zs.mean() * spacing[2] + origin[2]), 1),
            'elongation': round(elongation, 2),
            'z_range': f"{zs.min()}-{zs.max()}",
            'z_span_mm': round(z_span, 1),
            'z_slices': z_slices,
        })

    return candidates


def _aggregate_fragments(candidates, arr, spacing, origin, max_merge_dist_mm=2.0,
                         min_diameter_mm=1.5):
    """
    v1.9.0: 空间邻近碎片二次聚合。

    在厚层CT中，微小结节(如2mm×1mm)可能被3D连通域分析拆成多个不相连的碎片。
    本函数将空间距离 < max_merge_dist_mm 的小候选(d<3mm)合并为一个。

    逻辑:
      - 只对 d < 3mm 的小候选进行聚合（大候选不参与）
      - 两个小候选中心距离 < max_merge_dist_mm → 合并
      - 合并后重新计算体积、直径、HU 等特征
      - 合并后 d < min_diameter_mm 的仍然丢弃
    """
    import numpy as np

    if not candidates:
        return candidates

    # 分离大候选和小候选
    big = [c for c in candidates if c['diameter_mm'] >= 3.0]
    small = [c for c in candidates if c['diameter_mm'] < 3.0]

    if len(small) < 2:
        return candidates

    # 对小候选做空间聚类
    used = set()
    merged_small = []

    for i, c1 in enumerate(small):
        if i in used:
            continue
        group = [c1]
        used.add(i)

        for j, c2 in enumerate(small):
            if j in used:
                continue
            # 计算物理距离
            dx = (c1['cx'] - c2['cx']) * spacing[0]
            dy = (c1['cy'] - c2['cy']) * spacing[1]
            dz = (c1['cz'] - c2['cz']) * spacing[2]
            dist = (dx**2 + dy**2 + dz**2) ** 0.5

            if dist < max_merge_dist_mm:
                group.append(c2)
                used.add(j)

        if len(group) == 1:
            merged_small.append(c1)
            continue

        # 合并组内候选
        total_voxels = sum(c['voxels'] for c in group)
        total_vol = sum(c['vol_mm3'] for c in group)
        merged_diam = (6 * total_vol / 3.14159265) ** (1/3)

        if merged_diam < min_diameter_mm:
            # 合并后仍然太小，取最大的单个
            merged_small.append(max(group, key=lambda c: c['voxels']))
            continue

        # 加权平均位置和 HU
        w = [c['voxels'] for c in group]
        w_sum = sum(w)
        merged_cz = sum(c['cz'] * c['voxels'] for c in group) / w_sum
        merged_cy = sum(c['cy'] * c['voxels'] for c in group) / w_sum
        merged_cx = sum(c['cx'] * c['voxels'] for c in group) / w_sum
        merged_hu = sum(c['mean_hu'] * c['voxels'] for c in group) / w_sum
        merged_max_hu = max(c['max_hu'] for c in group)

        # z 范围
        all_z_min = min(int(c['z_range'].split('-')[0]) for c in group)
        all_z_max = max(int(c['z_range'].split('-')[1]) for c in group)
        z_slices = all_z_max - all_z_min + 1
        z_span = z_slices * spacing[2]
        y_span = (max(c['cy'] for c in group) - min(c['cy'] for c in group) + 1) * spacing[1]
        x_span = (max(c['cx'] for c in group) - min(c['cx'] for c in group) + 1) * spacing[0]
        elongation = max(z_span, y_span, x_span) / (min(z_span+0.01, y_span+0.01, x_span+0.01))

        merged_small.append({
            'type': group[0]['type'],
            'voxels': total_voxels,
            'vol_mm3': round(total_vol, 1),
            'diameter_mm': round(merged_diam, 1),
            'mean_hu': round(merged_hu),
            'max_hu': round(merged_max_hu),
            'cz': round(merged_cz, 1),
            'cy': round(merged_cy, 1),
            'cx': round(merged_cx, 1),
            'cy_mm': round(merged_cy * spacing[1] + origin[1], 1),
            'cx_mm': round(merged_cx * spacing[0] + origin[0], 1),
            'cz_mm': round(merged_cz * spacing[2] + origin[2], 1),
            'elongation': round(elongation, 2),
            'z_range': f"{all_z_min}-{all_z_max}",
            'z_span_mm': round(z_span, 1),
            'z_slices': z_slices,
            '_aggregated': len(group),  # 标记这是聚合候选
        })

    logger.info(f"CAD: 碎片聚合 — {len(small)} 个小候选 → {len(merged_small)} 个")
    return big + merged_small


def _extract_density_peaks(arr, solid_mask, lung_contour, spacing, origin,
                           peak_hu_threshold=50, min_peak_voxels=2,
                           max_peak_diameter=4.0):
    """
    v1.9.0: 在肺实质内检测局部密度峰值，提取被大连通域吞并的微小结节。

    问题背景:
      在厚层CT(≥1mm)中，2mm级微小结节可能与相邻血管在3D空间中连通，
      被合并到一个 d>5mm 的大连通域里。这些结节在大候选列表中"消失"了。

    策略:
      1. 对肺内实性区域做逐层 2D 高密度峰值检测
      2. 将相邻层的峰值在3D中关联
      3. 输出独立的子候选（可能与已有大候选在空间上重叠）
      4. 通过评分+合并阶段让AI决定是否保留

    限制:
      - 只提取 d < max_peak_diameter 的小峰值
      - 至少 min_peak_voxels 个体素
    """
    import numpy as np
    from scipy import ndimage

    # 使用更高的 HU 阈值检测密度峰值（区分结节与正常肺组织）
    peak_mask = lung_contour & (arr > peak_hu_threshold) & (arr < 500)

    # 用侵蚀+重建的方式提取密度峰值：
    # 侵蚀 solid_mask 去掉大结构边缘，保留核心密集区
    from scipy.ndimage import binary_erosion
    eroded = binary_erosion(solid_mask, iterations=1)

    # 密度峰值 = 高HU体素 但不在侵蚀后的大结构核心内
    # 即：它们是大连通域的"边缘"高密度点，或者独立的小高密度区
    # 更好的方法：直接对 peak_mask 做连通域分析，只取小的
    labeled_peaks, n_peaks = ndimage.label(peak_mask)

    sub_candidates = []
    for i in range(1, n_peaks + 1):
        comp = labeled_peaks == i
        voxels = int(comp.sum())

        if voxels < min_peak_voxels:
            continue

        vol_mm3 = voxels * spacing[0] * spacing[1] * spacing[2]
        diam = (6 * vol_mm3 / 3.14159265) ** (1/3)

        # 只要小候选
        if diam > max_peak_diameter or diam < 1.5:
            continue

        zs, ys, xs = np.where(comp)
        mean_hu = float(arr[comp].mean())
        max_hu = float(arr[comp].max())
        z_slices = len(set(zs.tolist()))

        # 跳过 HU 太低的（可能是噪声）
        if mean_hu < 30:
            continue

        z_span = (zs.max() - zs.min() + 1) * spacing[2]
        y_span = (ys.max() - ys.min() + 1) * spacing[1]
        x_span = (xs.max() - xs.min() + 1) * spacing[0]
        elongation = max(z_span, y_span, x_span) / (min(z_span+0.01, y_span+0.01, x_span+0.01))

        sub_candidates.append({
            'type': 'solid',
            'voxels': voxels,
            'vol_mm3': round(vol_mm3, 1),
            'diameter_mm': round(diam, 1),
            'mean_hu': round(mean_hu),
            'max_hu': round(max_hu),
            'cz': round(float(zs.mean()), 1),
            'cy': round(float(ys.mean()), 1),
            'cx': round(float(xs.mean()), 1),
            'cy_mm': round(float(ys.mean() * spacing[1] + origin[1]), 1),
            'cx_mm': round(float(xs.mean() * spacing[0] + origin[0]), 1),
            'cz_mm': round(float(zs.mean() * spacing[2] + origin[2]), 1),
            'elongation': round(elongation, 2),
            'z_range': f"{zs.min()}-{zs.max()}",
            'z_span_mm': round(z_span, 1),
            'z_slices': z_slices,
            '_density_peak': True,
        })

    logger.info(f"CAD: 密度峰值扫描 — {n_peaks} 个高密度连通域 → {len(sub_candidates)} 个子候选")
    return sub_candidates


def _compute_nodule_score(c: Dict, ctype: str = 'solid', z_spacing: float = 0.625) -> float:
    """
    计算候选的"结节可信度评分"（0~1）。

    评分维度（v1.9.0 — 基于5个ground truth结节校准）：
      1. 球形度 (z_span/diameter 比值越接近 1 越好)
      2. Elongation (越低越好，高 elongation = 血管特征)
      3. 大小 (1.5-10mm 实性 / 2-15mm GGO 为重点关注范围)
      4. HU 值 (实性 20~200，GGO -600~-400 为典型)
      5. z 层数 — 层厚感知 (考虑 z_spacing 对层数的影响)
      6. 密度一致性加分 — 实性候选 HU+形态同时优秀时提升排名

    v1.9.0 改进：
      - 新增 1.5-2mm 实性候选评分: size_score=0.55 (避免假阳性泛滥但保留真结节)
      - 碎片候选惩罚: d<1.8mm 且 z_slices=1 → 额外 0.85 衰减
      - 聚合候选加分: 通过 _aggregate_fragments 合并的候选有 _aggregated 标记

    校准依据（5个ground truth）：
      - Case 1: 2023 CT, 2mm 炎性肉芽肿, ⭐0.947 ✅
      - Case 2: 2026 CT, GT1 GGO 4mm ✅, GT2 实性 3mm ✅, GT3 实性 2mm ✅
      - Case 2: GT4 实性 2mm×1mm (v1.8.0漏检 → v1.9.0 通过 closing+聚合修复)
    """
    d = c['diameter_mm']
    e = c['elongation']
    z_span = c['z_span_mm']
    z_slices = c['z_slices']
    hu = c['mean_hu']

    ratio = z_span / d if d > 0 else 10

    # --- 球形度评分 ---
    # v1.8.0: 更宽容的球形度评分，微小结节受层厚影响
    # ratio 在 0.7~1.5 之间给高分（v1.7.0 是 0.5~2.0 全范围线性惩罚）
    if ratio < 0.3 or ratio > 4.0:
        sphericity = 0.1
    elif 0.7 <= ratio <= 1.5:
        # 核心区间：ratio 0.7-1.5 内最多扣 10%
        sphericity = 1.0 - 0.2 * abs(ratio - 1.0)
    elif 0.5 <= ratio < 0.7:
        sphericity = 0.8 - 0.5 * (0.7 - ratio)
    elif 1.5 < ratio <= 2.0:
        sphericity = 0.9 - 0.4 * (ratio - 1.5)
    else:
        sphericity = 0.5 / (1.0 + abs(ratio - 1.0))

    # --- Elongation 评分 ---
    if e <= 1.5:
        elong_score = 1.0
    elif e <= 2.5:
        elong_score = 0.7 - 0.3 * (e - 1.5)
    elif e <= 3.5:
        elong_score = 0.4 - 0.2 * (e - 2.5)
    else:
        elong_score = max(0.05, 0.2 - 0.1 * (e - 3.5))

    # --- 大小评分 ---
    # v1.9.0: 新增 1.5-2mm 段评分，降低但不丢弃微小候选
    if ctype == 'solid':
        if 3 <= d <= 10:
            size_score = 1.0
        elif 2 <= d < 3:
            # v1.7.0 was 0.6, v1.8.0 raised to 0.8（2mm 是临床真实结节的最小检出边界）
            size_score = 0.8
        elif 1.5 <= d < 2:
            # v1.9.0 新增：1.5-2mm 候选可能是被拆碎的微小真结节
            # 给较低但非零的评分，避免假阳性泛滥
            size_score = 0.55
        elif 10 < d <= 20:
            size_score = 0.7
        elif 20 < d <= 35:
            size_score = 0.5
        else:
            size_score = 0.3
    else:  # ggo
        if 2 <= d <= 15:
            size_score = 1.0
        elif 15 < d <= 25:
            size_score = 0.7
        else:
            size_score = 0.4

    # --- HU 评分 ---
    if ctype == 'solid':
        if 20 <= hu <= 200:
            hu_score = 1.0
        elif -50 <= hu < 20:
            hu_score = 0.7
        elif 200 < hu <= 400:
            hu_score = 0.5
        else:
            hu_score = 0.3
    else:
        if -600 <= hu <= -400:
            hu_score = 1.0
        elif -650 <= hu < -600 or -400 < hu <= -300:
            hu_score = 0.7
        else:
            hu_score = 0.3

    # --- z_slices 评分（层厚感知）---
    # v1.8.0: 考虑 z_spacing 对层数的影响
    # 厚层 CT (z_spacing >= 1mm) 中，z_slices=2 已覆盖 >=2mm z范围，不应惩罚
    # 薄层 CT (z_spacing < 1mm) 中，z_slices=2 仅覆盖 ~1mm，偏噪声特征
    z_coverage_mm = z_slices * z_spacing  # 实际 z 覆盖范围(mm)
    if ctype == 'solid':
        if z_coverage_mm >= 1.5 and z_slices >= 2:
            # 覆盖 >=1.5mm 且至少跨2层 → 满分
            z_score = 1.0
        elif z_slices >= 2 and z_slices <= 8:
            z_score = 1.0
        elif z_slices == 1:
            z_score = 0.3
        elif 8 < z_slices <= 12:
            z_score = 0.6
        else:
            z_score = 0.3
    else:
        if z_coverage_mm >= 1.5 and z_slices >= 2:
            z_score = 1.0
        elif 2 <= z_slices <= 10:
            z_score = 1.0
        elif z_slices == 1:
            z_score = 0.3
        else:
            z_score = 0.5

    # --- [NEW] 密度一致性加分 ---
    # v1.8.0: 奖励同时满足多项理想特征的候选，提升"完美结节"排名
    # 同时具备理想 HU + 低 elongation + 合理 z_slices → 额外加分
    consistency = 0.5  # 基础分
    ideal_count = 0
    if ctype == 'solid' and 20 <= hu <= 200:
        ideal_count += 1
    elif ctype == 'ggo' and -600 <= hu <= -400:
        ideal_count += 1
    if e <= 1.5:
        ideal_count += 1
    if 2 <= z_slices <= 8:
        ideal_count += 1
    if 0.7 <= ratio <= 1.5:
        ideal_count += 1
    # 4项全满 → 1.0, 3项 → 0.85, 2项 → 0.7, 1项 → 0.6, 0项 → 0.5
    consistency = min(1.0, 0.5 + ideal_count * 0.125)

    # --- 综合评分 (加权几何平均) ---
    # v1.8.0 权重调整：大小权重提升以更重视微小结节，加入一致性因子
    score = (
        (sphericity ** 0.25) *
        (elong_score ** 0.25) *
        (size_score ** 0.20) *
        (hu_score ** 0.12) *
        (z_score ** 0.13) *
        (consistency ** 0.05)
    )

    # v1.9.0: 碎片候选降权 — d<1.8mm 且 z_slices=1 的可疑碎片
    if d < 1.8 and z_slices == 1:
        score *= 0.85

    # v1.9.0: 聚合候选标记加分（_aggregate_fragments 合并了多个碎片的候选更可信）
    if c.get('_aggregated', 0) >= 2:
        score = min(1.0, score * 1.05)

    return round(score, 4)


def _merge_nearby(candidates, dist_thresh, spacing):
    """合并空间距离 < dist_thresh mm 的候选（保留评分最高者）"""
    if not candidates:
        return candidates

    merged = []
    used = set()
    # 输入已按评分排序（高→低），直接遍历
    for i, c in enumerate(candidates):
        if i in used:
            continue
        group = [c]
        used.add(i)
        for j, c2 in enumerate(candidates):
            if j in used:
                continue
            dx = (c['cx'] - c2['cx']) * spacing[0]
            dy = (c['cy'] - c2['cy']) * spacing[1]
            dz = (c['cz'] - c2['cz']) * spacing[2]
            dist = (dx**2 + dy**2 + dz**2) ** 0.5
            if dist < dist_thresh:
                group.append(c2)
                used.add(j)
        # 保留评分最高者
        best = max(group, key=lambda x: x.get('nodule_score', 0))
        merged.append(best)

    return merged


def _generate_annotations(arr, spacing, origin, solid_candidates, ggo_candidates,
                          output_dir):
    """生成带黄色圈注的标注图（包含四窗位合成图和全切面图）"""
    import numpy as np

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("CAD: PIL 不可用，跳过标注图生成")
        return []

    ann_dir = os.path.join(output_dir, 'cad_annotations')
    os.makedirs(ann_dir, exist_ok=True)

    def apply_window(hu_slice, wc, ww):
        low = wc - ww / 2
        high = wc + ww / 2
        return np.clip((hu_slice - low) / (high - low) * 255, 0, 255).astype(np.uint8)

    images = []
    all_candidates = (
        [(c, 'solid') for c in solid_candidates[:20]] +
        [(c, 'ggo') for c in ggo_candidates[:15]]
    )

    for idx, (c, ctype) in enumerate(all_candidates):
        z_center = int(round(c['cz']))
        cx = int(round(c['cx']))
        cy = int(round(c['cy']))
        diam_mm = c['diameter_mm']
        score = c.get('nodule_score', 0)

        slc = arr[z_center]

        # === 全切面肺窗图（带标注）===
        windowed = apply_window(slc, -600, 1500)
        rgb = np.stack([windowed]*3, axis=-1)
        pil_img = Image.fromarray(rgb)
        draw = ImageDraw.Draw(pil_img)

        r = max(int(diam_mm / spacing[0] / 2 * 2), 8)
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline='yellow', width=2)
        label = f"#{idx+1} {ctype} s={score:.2f} d={diam_mm:.1f}mm"
        draw.text((4, 4), label, fill='yellow')

        fname = f"cad_{ctype}_{idx+1:03d}_z{z_center}_d{diam_mm:.1f}mm_s{score:.2f}.png"
        fpath = os.path.join(ann_dir, fname)
        pil_img.save(fpath)
        images.append(fpath)

        # === 四窗位合成图（裁剪局部区域）===
        crop_r = 60
        y1 = max(0, cy - crop_r)
        y2 = min(slc.shape[0], cy + crop_r)
        x1 = max(0, cx - crop_r)
        x2 = min(slc.shape[1], cx + crop_r)
        crop = slc[y1:y2, x1:x2]
        local_cy = cy - y1
        local_cx = cx - x1

        windows = [('Lung', -600, 1500), ('Mediastinum', 40, 400),
                    ('GGO', -600, 600), ('NarrowGGO', -550, 400)]

        tile_h, tile_w = crop.shape
        canvas_w = tile_w * 2 + 4
        canvas_h = tile_h * 2 + 4 + 20
        canvas = Image.new('RGB', (canvas_w, canvas_h), (0, 0, 0))
        cdraw = ImageDraw.Draw(canvas)

        info = f"#{idx+1} {ctype} s={score:.2f} d={diam_mm:.1f}mm HU={c['mean_hu']}"
        cdraw.text((4, 2), info, fill='yellow')

        local_r = max(int(diam_mm / spacing[0] / 2 * 1.5), 6)
        for wi, (wname, wc, ww) in enumerate(windows):
            w_crop = apply_window(crop, wc, ww)
            w_rgb = np.stack([w_crop]*3, axis=-1)
            tile = Image.fromarray(w_rgb)
            td = ImageDraw.Draw(tile)
            td.ellipse([local_cx-local_r, local_cy-local_r,
                        local_cx+local_r, local_cy+local_r],
                       outline='yellow', width=2)
            td.text((2, 2), wname, fill='cyan')
            col = wi % 2
            row = wi // 2
            canvas.paste(tile, (col * (tile_w + 2), row * (tile_h + 2) + 20))

        qname = f"cad_quad_{ctype}_{idx+1:03d}_z{z_center}_s{score:.2f}.png"
        qpath = os.path.join(ann_dir, qname)
        canvas.save(qpath)
        images.append(qpath)

    logger.info(f"CAD: 生成 {len(images)} 张标注图到 {ann_dir}")
    return images


def format_candidates_for_prompt(solid_candidates, ggo_candidates, n_slices=0, spacing=None):
    """将候选结节格式化为可注入到阅片 prompt 中的文本。

    Args:
        solid_candidates: 实性候选列表
        ggo_candidates: GGO 候选列表
        n_slices: 总切片数
        spacing: [x, y, z] 体素间距(mm)，用于注入层厚信息帮助 AI 理解扫描参数
    """
    if not solid_candidates and not ggo_candidates:
        return ""

    lines = [
        "",
        "**⚠️ CAD 自动预检结果（请重点验证以下候选区域！）：**",
        "以下区域由 CAD 算法从 DICOM 原始 HU 数据中自动检出并按可信度评分排序，",
        "请在阅片时**优先检视高分候选**，确认是结节还是血管：",
        "",
    ]

    # v1.8.0: 注入层厚信息，帮助 AI 理解微小结节在不同层厚下的表现
    if spacing:
        z_sp = spacing[2] if len(spacing) > 2 else spacing[0]
        lines.append(f"**扫描参数**: 层厚={z_sp:.2f}mm, 面内分辨率={spacing[0]:.3f}mm")
        if z_sp >= 1.0:
            lines.append(f"  ⚠️ 注意: 层厚 {z_sp:.2f}mm 较厚，2mm结节可能仅跨2层。"
                         f"CAD 已自动调整层厚感知评分，z_slices=2 的候选也可能是真结节。")
        elif z_sp <= 0.7:
            lines.append(f"  ✅ 薄层重建 ({z_sp:.2f}mm)，微小结节跨层较多，检出率较高。")
        lines.append("")

    if solid_candidates:
        lines.append("**实性候选（按评分排序）：**")
        for i, c in enumerate(solid_candidates[:15]):
            z_pct = f"({c['cz']:.0f}/{n_slices}层)" if n_slices else ""
            score = c.get('nodule_score', 0)
            lines.append(
                f"  {i+1}. ⭐{score:.2f} z={c['z_range']} {z_pct} "
                f"pos=({c['cx']:.0f},{c['cy']:.0f}) "
                f"d={c['diameter_mm']:.1f}mm HU均值={c['mean_hu']:.0f} "
                f"elong={c['elongation']:.1f}"
            )
        lines.append("")

    if ggo_candidates:
        lines.append("**GGO 候选（按评分排序）：**")
        for i, c in enumerate(ggo_candidates[:10]):
            z_pct = f"({c['cz']:.0f}/{n_slices}层)" if n_slices else ""
            score = c.get('nodule_score', 0)
            lines.append(
                f"  {i+1}. ⭐{score:.2f} z={c['z_range']} {z_pct} "
                f"pos=({c['cx']:.0f},{c['cy']:.0f}) "
                f"d={c['diameter_mm']:.1f}mm HU均值={c['mean_hu']:.0f} "
                f"elong={c['elongation']:.1f}"
            )
        lines.append("")

    lines.append(
        "**注意**：评分越高的候选越可能是真结节（⭐>0.9 高度可疑，0.8-0.9 中度可疑）。"
        "低分候选多为血管截面，但仍需确认。"
        "CAD 可能漏检极小或极淡的结节，仍需全量阅片！"
    )

    return "\n".join(lines)
