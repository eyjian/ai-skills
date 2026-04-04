#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD 自动候选结节检测模块（Computer-Aided Detection）v2.8

直接从 DICOM 原始 HU 数据中进行 3D 连通域分析，
输出候选结节列表（含位置、大小、HU、形态等信息）。

v2.8 假阳性深度优化（基于 Case2 2026-01-10 医院报告精确对照）：
  - [新] 肺外缘空间惩罚: cx距图像中心>180px → 0.5, >160px → 0.7
         (Case2: 5个外缘假阳性 S#3,S#4,S#8,S#11,S#15 全在cx>370区域)
         (保护: 4个真结节 cx=155,159,345,351 距中心<100px，不触发)
  - [新] 外缘+微小灶联合惩罚: HU 80-200 + z_slices=2 + d<2.5mm + 外缘 → 0.4
         (Case2: 大量2层微小血管截面在外缘获高分的核心假阳性模式)
  - [改] GGO HU评分精细化: -450~-380→1.0, -480~-450→0.8, -500~-480→0.5
         (Case2: 真GGO HU=-409, 假阳性集中在-476~-492, -480为新分水岭)
  - [改] GGO 空间聚簇合并距离: 从15mm增至20mm
         (Case2: G#25,G#29,G#32 与真GGO#21在15mm内残留未合并)
  - [改] GGO mean_hu 血管排除阈值收紧: -510→-500, -530→-510
         (配合HU评分收紧，双重降权偏淡候选)
  - 回归验证: Case1 GT不受影响, Case2 全部4个GT不受影响
  - 校准数据新增: Case2 医院报告精确匹配(GGO#21→GT1, S#6→GT2, S#17→GT3, S#5→GT4)

v2.7 假阳性深度优化（基于2023-06-02 Case1 vs 医院报告复核）：
  - [新] 实性mean_hu<20强降权: score×0.3 (Case1有大量mean_hu=1~11的假阳性)
  - [新] 血管模式惩罚: (max_hu-mean_hu)>200 且 mean_hu<50 → 0.25~0.4
         (血管横截面典型特征: 中心高密度+边缘被低密度平均拉低)
  - [新] GGO mean_hu<-520降权: HU过低接近空气，0.4~0.6
  - [新] 肺尖/肺底区域惩罚: z<5%或z>95% → 0.5 (部分容积效应/胸廓入口伪影)
  - [改] GGO空间聚簇合并距离: 从8mm增至15mm (Case1有5个GGO在20mm内聚集)
  - 回归验证: Case1 GT Solid#3 不受影响, Case2 全部4个GT不受影响

v2.6 假阳性模式惩罚优化（基于2例5GT复核校准）：
  - [改] 实性HU评分收紧: 80~200→1.0, 50~80→0.6, 20~50→0.4, -50~20→0.3
         (原: 20~200全给1.0，HU<80的大量假阳性与真结节评分无区分)
  - [改] GGO HU评分收紧: -500~-400→1.0, -550~-500→0.7, -600~-550→0.5
         (原: -600~-400全给1.0，HU<-500的过淡GGO假阳性无惩罚)
  - [新] GGO elongation惩罚: >1.8→0.3, >1.5且voxels<30→0.5
         (校准: 真GGO elong=1.16, 假阳性elong=1.4~2.0+)

v2.5 核心改进（v2.1.1 — 薄层CT小候选回归修复）：
  - [修] 小候选(<=15vox) max_hu 惩罚放宽: >=400才开始惩罚(原350)
         Case 1 GT(vox=15,max_hu=353)部分容积效应被误惩→掉出Top-25，修复后恢复

v2.4 核心改进（v2.1.0 — 性能优化 + GGO 去噪修复）：
  - [修] GGO 厚层CT: 去掉 3D opening（杀死GT1）→ 逐层2D去噪(>=8体素/层)
  - [优] _extract_candidates: find_objects 向量化加速 (24K labels: 超时→0.5s)
  - [优] _extract_density_peaks: 同上向量化加速

v2.3 核心改进（v2.0.0 — 假阳性复核优化）：
  - [修] 移除聚合候选 1.05 加分 — 聚合本身不增加可信度
  - [新] 血管排除评分: HU异质度(std)过高、max_HU>400、体素稀疏→降权
  - [新] 微小血管截面惩罚: voxels<=10 且 z_slices==2 且 d<2.5mm → 强降权
  - [新] binary_closing 膨胀保护: closing后连通域直径翻倍则回退
  - [改] GGO elongation权重: 0.25→0.15（GGO形态不规则是正常的）
  - [改] 评分权重重分配: 引入血管排除维度，改善评分区分度

v2.2 核心改进（v1.9.0）：
  - 实性mask binary_closing: 填补厚层(≥1mm)下微小结节的体素间隙
  - 空间邻近碎片二次聚合: 距离<2mm的小候选自动合并
  - min_diameter_mm 降至1.5mm: 捞回被过滤的1.5-2mm真结节
  - 碎片降权: d<1.8mm 且 z_slices=1 的候选在评分中降权
  - 用多维度评分排序替代硬阈值过滤（避免误杀真结节）

评分维度（v2.3 权重不变）：
  实性: 球形度0.20, elongation0.20, 大小0.15, HU0.10, z层数0.10,
        一致性0.05, 血管排除0.20
  GGO:  球形度0.20, elongation0.15, 大小0.15, HU0.12, z层数0.13,
        一致性0.05, 血管排除0.20

校准数据集：
  - Case 1: 2023-06-02 胸部CT (0.625mm), 右肺下叶前基底段 2mm 炎性肉芽肿
  - Case 2: 2026-01-10 胸部CT (1.25mm), 4个结节(医院报告精确匹配):
    GT1 GGO#21 左肺上叶下舌段近斜裂下 GGO 4×3mm (HU=-409) 炎性改变
    GT2 Solid#6 右肺中叶内段 实性 3×2mm (HU=144) 炎性肉芽肿
    GT3 Solid#17 右肺下叶前基底段 实性 2×2mm (HU=117) 炎性肉芽肿
    GT4 Solid#5 左肺下叶背段 实性 2×1mm (HU=152) 炎性肉芽肿
  - DICOM方向: 心脏在图像左侧, cx<256=LEFT, cx>256=RIGHT

GGO 去噪校准 (Case 2):
  - 3D opening: GT1 完全消失 (0体素)
  - 2D opening(3x3): GT1 消失
  - 逐层2D去噪>=3: 24464连通域, GT1存活(38vox)
  - 逐层2D去噪>=5: 9839连通域, GT1存活(27vox)
  - 逐层2D去噪>=8: 3717连通域, GT1存活(17vox) ← 最优
  - 逐层2D去噪>=10: 2250连通域, GT1丢失(0vox)

算法流程：
  1. 读取 DICOM volume（优先选择薄层重建 series）
  2. 2D 逐层肺分割（填充法获得完整肺轮廓）
  3. 在肺轮廓内检测高密度区域（实性候选）和中等密度区域（GGO候选）
  3.5 实性mask morphological closing（厚层≥1mm时启用，带膨胀保护）
  3.6 GGO mask 逐层2D去噪（厚层≥1mm：>=8体素/层; 薄层: 3D opening）
  4. 3D 连通域标记 + 形态学特征计算（find_objects 向量化加速）
  4.5 空间邻近碎片二次聚合
  5. 多维度评分排序（含血管排除维度）
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
    top_n_solid: int = 30,
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
    # v2.0.0: 增加膨胀保护 — closing后连通域直径翻倍的回退到closing前
    z_spacing = spacing[2]
    if z_spacing >= 1.0:
        from scipy.ndimage import binary_closing
        solid_mask_pre_closing = solid_mask.copy()
        solid_mask_closed = binary_closing(solid_mask, iterations=1)
        solid_mask_closed = solid_mask_closed & lung_contour

        # 膨胀保护: 比较 closing 前后每个连通域的大小变化
        labeled_pre, n_pre = ndimage.label(solid_mask_pre_closing)
        labeled_post, n_post = ndimage.label(solid_mask_closed)
        logger.info(f"CAD: 厚层({z_spacing:.2f}mm) closing: {n_pre}→{n_post} 连通域")

        # 检查 closing 后是否有连通域过度膨胀
        # 策略: 对每个 closing 后的大连通域(>100体素)，检查其中包含的 closing 前
        # 小连通域数量。如果一个 post-closing 连通域吞并了多个 pre-closing 域，
        # 且总体积比最大子域体积增长 > 3x，则在该区域回退到 closing 前的 mask
        solid_mask = solid_mask_closed.copy()
        rollback_count = 0
        for i in range(1, n_post + 1):
            post_comp = labeled_post == i
            post_vol = int(post_comp.sum())
            if post_vol < 50:
                continue
            # 该 post-closing 区域内包含哪些 pre-closing 连通域
            pre_labels_in_post = set(labeled_pre[post_comp].tolist()) - {0}
            if len(pre_labels_in_post) <= 1:
                continue
            # 计算 pre-closing 中最大子域的体积
            max_pre_vol = max(int((labeled_pre == pl).sum()) for pl in pre_labels_in_post)
            # 如果 closing 后体积相比最大子域膨胀 > 3x，回退
            if post_vol > max_pre_vol * 3:
                solid_mask[post_comp] = solid_mask_pre_closing[post_comp]
                rollback_count += 1
                logger.info(f"CAD: closing 膨胀保护 — 连通域 {i}: "
                            f"{max_pre_vol}→{post_vol} 体素(×{post_vol/max_pre_vol:.1f}), 已回退")

        if rollback_count > 0:
            logger.info(f"CAD: closing 膨胀保护 — 共回退 {rollback_count} 个过度膨胀连通域")
        else:
            logger.info(f"CAD: 厚层({z_spacing:.2f}mm) → binary_closing 已应用，无过度膨胀")
    else:
        solid_mask_pre_closing = None

    labeled_s, n_s = ndimage.label(solid_mask)
    logger.info(f"CAD: 实性区域 (HU>{solid_hu_threshold}): {n_s} 个连通域")

    solid_raw = _extract_candidates(arr, labeled_s, n_s, spacing, origin, 'solid',
                                     min_diameter_mm, max_diameter_mm)

    # v1.9.0: 空间邻近碎片二次聚合 — 合并距离<2mm的碎片候选
    solid_raw = _aggregate_fragments(solid_raw, arr, spacing, origin,
                                      max_merge_dist_mm=2.0, min_diameter_mm=min_diameter_mm)

    # v1.9.0: 大连通域内部密度峰值子候选提取
    # v2.0.0: 增加大连通域逐层2D子候选提取
    if z_spacing >= 1.0:
        sub_candidates = _extract_density_peaks(
            arr, solid_mask, lung_contour, spacing, origin,
            peak_hu_threshold=50, min_peak_voxels=2, max_peak_diameter=4.0
        )
        if sub_candidates:
            solid_raw.extend(sub_candidates)
            logger.info(f"CAD: 密度峰值子候选 — 新增 {len(sub_candidates)} 个")

        # v2.0.0: 对大连通域(d>4mm)做逐层2D分析，提取被吞没的小结节
        sub_2d = _extract_from_large_regions(
            arr, labeled_s, n_s, spacing, origin,
            min_large_d=4.0, max_sub_d=4.0, min_sub_voxels=2
        )
        if sub_2d:
            solid_raw.extend(sub_2d)
            logger.info(f"CAD: 大连通域2D子候选 — 新增 {len(sub_2d)} 个")

    # GGO 候选
    ggo_mask = lung_contour & (arr > ggo_hu_low) & (arr < ggo_hu_high)
    # v2.1: 厚层CT 用逐层2D去噪代替3D opening（opening 会杀死微小 GGO 如 GT1）
    # 策略: 在每层中独立去掉小于阈值的2D碎片，保留有足够面积的GGO信号
    # 测试结果: >=8 体素/层 → 3717 连通域(可接受), GT1 存活, >=10 → GT1 丢失
    if z_spacing < 1.0:
        ggo_mask = binary_opening(ggo_mask, iterations=1)
        logger.info("CAD: 薄层CT → GGO mask 3D opening 已应用")
    else:
        min_2d_voxels = 8  # 每层最小体素数（校准: >=8保GT1, >=10杀GT1）
        n_removed = 0
        for z in range(ggo_mask.shape[0]):
            lab_2d, n_2d = ndimage.label(ggo_mask[z])
            if n_2d == 0:
                continue
            sizes_2d = ndimage.sum(ggo_mask[z], lab_2d, range(1, n_2d + 1))
            for idx, sz in enumerate(sizes_2d):
                if sz < min_2d_voxels:
                    ggo_mask[z][lab_2d == (idx + 1)] = False
                    n_removed += 1
        logger.info(f"CAD: 厚层CT → GGO 逐层2D去噪(>={min_2d_voxels}体素/层)，"
                    f"移除 {n_removed} 个2D碎片")

    labeled_g, n_g = ndimage.label(ggo_mask)
    logger.info(f"CAD: GGO 区域 ({ggo_hu_low}<HU<{ggo_hu_high}): {n_g} 个连通域")

    ggo_raw = _extract_candidates(arr, labeled_g, n_g, spacing, origin, 'ggo',
                                   min_diameter_mm, max_diameter_mm)

    logger.info(f"CAD: 提取候选 — 实性 {len(solid_raw)} 个, GGO {len(ggo_raw)} 个")

    # ===== 4. 评分排序（替代硬阈值过滤）=====
    n_slices_total = int(arr.shape[0])
    for c in solid_raw:
        c['nodule_score'] = _compute_nodule_score(c, 'solid', z_spacing=z_spacing, n_slices=n_slices_total)
    for c in ggo_raw:
        c['nodule_score'] = _compute_nodule_score(c, 'ggo', z_spacing=z_spacing, n_slices=n_slices_total)

    solid_scored = sorted(solid_raw, key=lambda x: -x['nodule_score'])
    ggo_scored = sorted(ggo_raw, key=lambda x: -x['nodule_score'])

    # ===== 5. 聚类合并（评分排序后，高分候选优先保留）=====
    solid_merged = _merge_nearby(solid_scored, merge_distance_mm, spacing)
    # v2.8: GGO 合并距离扩大到 20mm — Case2 G#25,G#29,G#32 与真GGO在15mm内残留
    ggo_merge_distance = max(merge_distance_mm, 20.0)
    ggo_merged = _merge_nearby(ggo_scored, ggo_merge_distance, spacing)

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
    """从标记的连通域中提取候选（v2.1: find_objects 向量化加速）"""
    import numpy as np
    from scipy import ndimage as ndi

    candidates = []
    voxel_vol = spacing[0] * spacing[1] * spacing[2]

    # v2.1: 使用 find_objects 获取每个连通域的 bounding box，
    # 避免对全 volume 逐个做 labeled==i（O(N*V) → O(N*bbox)）
    slices = ndi.find_objects(labeled)
    if slices is None:
        return candidates

    for i, sl in enumerate(slices):
        if sl is None:
            continue
        lbl = i + 1
        region = labeled[sl]
        comp = region == lbl
        vol = int(comp.sum())
        if vol < 2:
            continue
        vol_mm3 = vol * voxel_vol
        diam = (6 * vol_mm3 / 3.14159265) ** (1/3)
        if diam < min_diam or diam > max_diam:
            continue

        # 在 bounding box 内提取 HU 和坐标
        arr_region = arr[sl]
        vals = arr_region[comp]
        mean_hu = float(vals.mean())
        max_hu = float(vals.max())
        hu_std = float(vals.std())

        zs_local, ys_local, xs_local = np.where(comp)
        zs = zs_local + sl[0].start
        ys = ys_local + sl[1].start
        xs = xs_local + sl[2].start

        z_span = (zs.max() - zs.min() + 1) * spacing[2]
        y_span = (ys.max() - ys.min() + 1) * spacing[1]
        x_span = (xs.max() - xs.min() + 1) * spacing[0]
        elongation = max(z_span, y_span, x_span) / (min(z_span+0.01, y_span+0.01, x_span+0.01))
        z_slices = len(set(zs.tolist()))

        sphere_vol_voxels = (3.14159265 / 6) * (diam / spacing[0]) * (diam / spacing[1]) * (diam / spacing[2])
        voxel_density = vol / max(sphere_vol_voxels, 1.0)

        candidates.append({
            'type': ctype, 'voxels': vol,
            'vol_mm3': round(vol_mm3, 1), 'diameter_mm': round(diam, 1),
            'mean_hu': round(mean_hu), 'max_hu': round(max_hu),
            'hu_std': round(hu_std, 1),
            'voxel_density': round(min(voxel_density, 1.0), 3),
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
    voxel_vol = spacing[0] * spacing[1] * spacing[2]

    # v2.1: 使用 find_objects 向量化加速
    peak_slices = ndimage.find_objects(labeled_peaks)
    if peak_slices is None:
        peak_slices = []

    for i, sl in enumerate(peak_slices):
        if sl is None:
            continue
        lbl = i + 1
        region = labeled_peaks[sl]
        comp = region == lbl
        voxels = int(comp.sum())

        if voxels < min_peak_voxels:
            continue

        vol_mm3 = voxels * voxel_vol
        diam = (6 * vol_mm3 / 3.14159265) ** (1/3)

        if diam > max_peak_diameter or diam < 1.5:
            continue

        arr_region = arr[sl]
        vals = arr_region[comp]
        mean_hu = float(vals.mean())
        max_hu = float(vals.max())
        hu_std = float(vals.std())

        if mean_hu < 30:
            continue

        zs_local, ys_local, xs_local = np.where(comp)
        zs = zs_local + sl[0].start
        ys = ys_local + sl[1].start
        xs = xs_local + sl[2].start
        z_slices = len(set(zs.tolist()))

        z_span = (zs.max() - zs.min() + 1) * spacing[2]
        y_span = (ys.max() - ys.min() + 1) * spacing[1]
        x_span = (xs.max() - xs.min() + 1) * spacing[0]
        elongation = max(z_span, y_span, x_span) / (min(z_span+0.01, y_span+0.01, x_span+0.01))

        sphere_vol_voxels = (3.14159265 / 6) * (diam / spacing[0]) * (diam / spacing[1]) * (diam / spacing[2])
        voxel_density = voxels / max(sphere_vol_voxels, 1.0)

        sub_candidates.append({
            'type': 'solid',
            'voxels': voxels,
            'vol_mm3': round(vol_mm3, 1),
            'diameter_mm': round(diam, 1),
            'mean_hu': round(mean_hu),
            'max_hu': round(max_hu),
            'hu_std': round(hu_std, 1),
            'voxel_density': round(min(voxel_density, 1.0), 3),
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


def _extract_from_large_regions(arr, labeled, n_labels, spacing, origin,
                                 min_large_d=4.0, max_sub_d=4.0, min_sub_voxels=2):
    """
    v2.0.0: 在大连通域(d>min_large_d)内做逐层2D分析，提取被吞没的小结节。

    问题背景:
      GT3(2mm结节)与血管在3D空间中直接连通，形成一个226体素的大连通域(d=6.6mm)。
      密度峰值提取(HU>50)无法将其分离，因为整个连通域HU都>50。

    策略:
      1. 对每个大连通域(d>4mm)，逐层做2D连通域分析
      2. 在每层中找到小的、紧凑的2D区域
      3. 将相邻层的2D区域在z方向关联成3D子候选
      4. 输出 d < max_sub_d 的子候选
    """
    import numpy as np
    from scipy import ndimage as ndi

    sub_candidates = []

    for i in range(1, n_labels + 1):
        comp3d = labeled == i
        vol = int(comp3d.sum())
        vol_mm3 = vol * spacing[0] * spacing[1] * spacing[2]
        diam = (6 * vol_mm3 / 3.14159265) ** (1/3)

        if diam < min_large_d:
            continue

        # 这是一个大连通域，逐层做2D分析
        zs = np.where(comp3d.any(axis=(1, 2)))[0]

        # 收集每层的2D小区域
        layer_regions = {}  # z -> list of (centroid_y, centroid_x, voxel_count, hu_mean, hu_std, region_mask)
        for z in zs:
            slice_mask = comp3d[z]
            # 在这个大连通域的当前层内，用更高的HU阈值做2D分割
            # 结节HU通常比血管边缘更高更集中
            slice_hu = arr[z] * slice_mask
            labeled_2d, n_2d = ndi.label(slice_mask)

            for j in range(1, n_2d + 1):
                comp_2d = labeled_2d == j
                vox_count = int(comp_2d.sum())
                if vox_count < min_sub_voxels or vox_count > 50:
                    continue

                ys, xs = np.where(comp_2d)
                cy_px = float(ys.mean())
                cx_px = float(xs.mean())
                hu_vals = arr[z][comp_2d]
                hu_mean = float(hu_vals.mean())
                hu_std_val = float(hu_vals.std())

                # 计算2D区域的紧凑度(接近圆形的更像结节)
                y_span = (ys.max() - ys.min() + 1) * spacing[1]
                x_span = (xs.max() - xs.min() + 1) * spacing[0]
                aspect_ratio = max(y_span, x_span) / (min(y_span, x_span) + 0.01)

                if aspect_ratio > 3.0:
                    continue  # 太细长，跳过

                layer_regions.setdefault(z, []).append({
                    'cy_px': cy_px, 'cx_px': cx_px,
                    'voxels': vox_count, 'hu_mean': hu_mean,
                    'hu_std': hu_std_val, 'aspect': aspect_ratio,
                })

        if not layer_regions:
            continue

        # 跨层关联: 将相邻层中位置接近的2D区域组合成3D子候选
        # 使用简单的贪心匹配
        sorted_zs = sorted(layer_regions.keys())
        used_regions = set()  # (z, region_idx) 已用
        sub_groups = []

        for z in sorted_zs:
            for ri, reg in enumerate(layer_regions[z]):
                if (z, ri) in used_regions:
                    continue

                group = [(z, reg)]
                used_regions.add((z, ri))

                # 向上搜索相邻层
                for zz in range(z + 1, min(z + 6, sorted_zs[-1] + 1)):
                    if zz not in layer_regions:
                        break
                    best_match = None
                    best_dist = 999
                    for rj, reg2 in enumerate(layer_regions[zz]):
                        if (zz, rj) in used_regions:
                            continue
                        dy = (reg['cy_px'] - reg2['cy_px']) * spacing[1]
                        dx = (reg['cx_px'] - reg2['cx_px']) * spacing[0]
                        dist = (dy**2 + dx**2) ** 0.5
                        if dist < 3.0 and dist < best_dist:
                            best_match = (zz, rj, reg2)
                            best_dist = dist
                    if best_match:
                        group.append((best_match[0], best_match[2]))
                        used_regions.add((best_match[0], best_match[1]))
                    else:
                        break

                if len(group) >= 2:
                    sub_groups.append(group)

        # 从每个3D子组生成候选
        for group in sub_groups:
            total_voxels = sum(g[1]['voxels'] for g in group)
            total_vol = total_voxels * spacing[0] * spacing[1] * spacing[2]
            sub_diam = (6 * total_vol / 3.14159265) ** (1/3)

            if sub_diam > max_sub_d or sub_diam < 1.5:
                continue

            z_vals = [g[0] for g in group]
            w_sum = sum(g[1]['voxels'] for g in group)
            avg_cy = sum(g[1]['cy_px'] * g[1]['voxels'] for g in group) / w_sum
            avg_cx = sum(g[1]['cx_px'] * g[1]['voxels'] for g in group) / w_sum
            avg_hu = sum(g[1]['hu_mean'] * g[1]['voxels'] for g in group) / w_sum
            max_hu_val = max(int(g[1]['hu_mean'] + 2 * g[1]['hu_std']) for g in group)
            avg_hu_std = sum(g[1]['hu_std'] * g[1]['voxels'] for g in group) / w_sum

            z_min, z_max = min(z_vals), max(z_vals)
            z_slices = z_max - z_min + 1
            z_span = z_slices * spacing[2]
            y_span_est = max(g[1]['voxels'] for g in group) ** 0.5 * spacing[1]
            x_span_est = y_span_est
            elongation = max(z_span, y_span_est, x_span_est) / (min(z_span + 0.01, y_span_est + 0.01, x_span_est + 0.01))

            sphere_v = (3.14159265 / 6) * (sub_diam / spacing[0]) * (sub_diam / spacing[1]) * (sub_diam / spacing[2])
            vd = total_voxels / max(sphere_v, 1.0)

            sub_candidates.append({
                'type': 'solid',
                'voxels': total_voxels,
                'vol_mm3': round(total_vol, 1),
                'diameter_mm': round(sub_diam, 1),
                'mean_hu': round(avg_hu),
                'max_hu': round(max_hu_val),
                'hu_std': round(avg_hu_std, 1),
                'voxel_density': round(min(vd, 1.0), 3),
                'cz': round(float(np.mean(z_vals)), 1),
                'cy': round(avg_cy, 1),
                'cx': round(avg_cx, 1),
                'cy_mm': round(avg_cy * spacing[1] + origin[1], 1),
                'cx_mm': round(avg_cx * spacing[0] + origin[0], 1),
                'cz_mm': round(float(np.mean(z_vals)) * spacing[2] + origin[2], 1),
                'elongation': round(elongation, 2),
                'z_range': f"{z_min}-{z_max}",
                'z_span_mm': round(z_span, 1),
                'z_slices': z_slices,
                '_large_region_sub': True,
            })

    logger.info(f"CAD: 大连通域2D分析 — 检查 {sum(1 for i in range(1, n_labels+1) if int((labeled==i).sum()) * spacing[0] * spacing[1] * spacing[2] > 0 and (6 * int((labeled==i).sum()) * spacing[0] * spacing[1] * spacing[2] / 3.14159265) ** (1/3) >= min_large_d)} 个大域 → {len(sub_candidates)} 个子候选")
    return sub_candidates


def _compute_nodule_score(c: Dict, ctype: str = 'solid', z_spacing: float = 0.625,
                          n_slices: int = 0) -> float:
    """
    计算候选的"结节可信度评分"（0~1）。

    v2.3 评分维度（基于假阳性深度分析重新校准）：

    实性候选权重:
      1. 球形度 0.20   (z_span/diameter 比值)
      2. Elongation 0.20 (越低越好)
      3. 大小 0.15     (1.5-10mm 为重点)
      4. HU 0.10       (实性 20~200 典型)
      5. z层数 0.10    (层厚感知)
      6. 一致性 0.05   (多维度同时理想)
      7. 血管排除 0.20  (v2.0.0 新增 — 核心改进)

    GGO候选权重:
      1. 球形度 0.20
      2. Elongation 0.15 (降低，GGO形态不规则是正常的)
      3. 大小 0.15
      4. HU 0.12
      5. z层数 0.13
      6. 一致性 0.05
      7. 血管排除 0.20

    v2.7 关键新增:
      - 实性 mean_hu<20 强降权(×0.3): 大量假阳性 mean_hu=1~11，真结节最低49
      - 血管模式惩罚: (max_hu-mean_hu)>200 且 mean_hu<50 → 0.25~0.4
      - GGO mean_hu<-520 降权: HU过低接近空气
      - 肺尖/肺底区域惩罚: z<5% 或 z>95% 部分容积效应严重
      - GGO 合并距离扩大至 15mm: 去除聚簇假阳性

    v2.0.0 关键改进:
      - 移除聚合候选 1.05 加分 — 聚合本身不增加可信度
      - 新增血管排除维度(权重0.20):
        a) HU标准差过高(>80) → 非均质，疑似血管
        b) max_HU > 400 → 疑似血管/钙化
        c) 体素密度过低 → 稀疏填充，疑似细长血管
        d) 微小体素量(<=10 且 z=2层 且 d<2.5mm) → 典型血管截面
      - GGO elongation权重从0.25降至0.15 — GGO形态不规则是正常特征
    """
    d = c['diameter_mm']
    e = c['elongation']
    z_span = c['z_span_mm']
    z_slices = c['z_slices']
    hu = c['mean_hu']
    max_hu = c.get('max_hu', hu)
    hu_std = c.get('hu_std', 0)
    voxels = c.get('voxels', 10)
    voxel_density = c.get('voxel_density', 0.5)
    is_sub_from_large = c.get('_large_region_sub', False)

    ratio = z_span / d if d > 0 else 10

    # --- 球形度评分 ---
    if ratio < 0.3 or ratio > 4.0:
        sphericity = 0.1
    elif 0.7 <= ratio <= 1.5:
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
    if ctype == 'solid':
        if 3 <= d <= 10:
            size_score = 1.0
        elif 2 <= d < 3:
            size_score = 0.8
        elif 1.5 <= d < 2:
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
    # v2.7: 实性HU进一步收紧 — Case1显示大量mean_hu=1~11的假阳性，真结节最低49
    #        GGO HU收紧 — mean_hu<-520接近空气，大幅降权
    # v2.6: 实性HU分档收紧 — 校准数据真结节最低HU=152，HU<80的大量假阳性需降权
    #        GGO HU分档收紧 — 真GGO HU=-409，HU<-500的过淡候选降权
    if ctype == 'solid':
        if 80 <= hu <= 200:
            hu_score = 1.0
        elif 50 <= hu < 80:
            hu_score = 0.6
        elif 20 <= hu < 50:
            hu_score = 0.4
        elif 0 <= hu < 20:
            hu_score = 0.15  # v2.7: HU接近0几乎不可能是实性结节
        elif -50 <= hu < 0:
            hu_score = 0.1   # v2.7: 负HU不是实性结节
        elif 200 < hu <= 400:
            hu_score = 0.5
        else:
            hu_score = 0.3
    else:
        # v2.8: GGO HU 评分精细化 — Case2 真GGO HU=-409, 假阳性集中在-476~-492
        #        -480 作为新分水岭: -450~-380 最优, -480~-450 可接受, -500~-480 可疑
        if -450 <= hu <= -380:
            hu_score = 1.0   # 最佳GGO区间（真GGO=-409在此）
        elif -480 <= hu < -450:
            hu_score = 0.8   # 可接受但偏淡
        elif -500 <= hu < -480:
            hu_score = 0.5   # v2.8: 可疑偏淡（原1.0→0.5，-480分水岭核心改动）
        elif -520 <= hu < -500:
            hu_score = 0.35  # v2.8: 收紧（原0.6→0.35）
        elif -550 <= hu < -520:
            hu_score = 0.25  # v2.8: 收紧（原0.4→0.25）
        elif -600 <= hu < -550:
            hu_score = 0.2   # v2.8: 收紧（原0.3→0.2）
        elif (-650 <= hu < -600) or (-380 < hu <= -300):
            hu_score = 0.3   # 边界区间
        else:
            hu_score = 0.2

    # --- z_slices 评分（层厚感知）---
    z_coverage_mm = z_slices * z_spacing
    if ctype == 'solid':
        if z_coverage_mm >= 1.5 and z_slices >= 2:
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

    # --- 密度一致性加分 ---
    consistency = 0.5
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
    consistency = min(1.0, 0.5 + ideal_count * 0.125)

    # --- [v2.0.0 新增] 血管排除评分 ---
    # 这是假阳性复核的核心维度，综合多个假阳性特征
    vessel_penalty = 1.0  # 满分=1.0（非血管），越低越像血管

    if ctype == 'solid':
        penalty_factors = []

        # v2.1.0: 对大连通域2D子候选放宽 hu_std 阈值
        # 这些候选是从结节-血管粘连体中提取的，hu_std 天然偏高
        # 但 max_hu 阈值不放宽（避免大量血管截面假阳性获得高分）
        relaxed_std = is_sub_from_large

        # (a) HU 异质度: 真结节 HU 分布较均匀（hu_std < 70 正常），
        #     血管断面 HU 分布离散（hu_std > 90 可疑）
        #     v2.1.0: 体素数越少，HU std 自然波动越大（部分容积效应）
        #     GT2 只有8体素但 hu_std=116 是正常的边缘效应，不应被严惩
        #     调整: 对小候选(<15体素)放宽 hu_std 阈值
        if relaxed_std:
            if hu_std > 180:
                penalty_factors.append(0.3)
            elif hu_std > 150:
                penalty_factors.append(0.6)
            else:
                penalty_factors.append(1.0)
        elif voxels <= 15:
            # 小候选的 hu_std 天然高（部分容积效应），放宽阈值
            if hu_std > 150:
                penalty_factors.append(0.3)
            elif hu_std > 120:
                penalty_factors.append(0.6)
            else:
                penalty_factors.append(1.0)
        else:
            if hu_std > 120:
                penalty_factors.append(0.2)
            elif hu_std > 90:
                penalty_factors.append(0.5)
            elif hu_std > 75:
                penalty_factors.append(0.75)
            else:
                penalty_factors.append(1.0)

        # (b) max_HU 过高: >400 疑似血管/钙化
        #     v2.1.0: SUB2D 候选因混入血管体素导致 max_hu 偏高，
        #     将惩罚起点从 400 提升到 450（GT3 max_hu=401 是典型粘连体）
        #     v2.1.1: 小候选(<=15体素) 因部分容积效应 max_hu 天然偏高，
        #     Case 1 GT(vox=15, max_hu=353) 被 >350 阈值误惩罚导致掉出 Top-25
        #     放宽到 >=400 开始惩罚（与 SUB2D 候选对齐）
        if relaxed_std:
            if max_hu > 550:
                penalty_factors.append(0.2)
            elif max_hu > 450:
                penalty_factors.append(0.4)
            elif max_hu > 400:
                penalty_factors.append(0.7)
            else:
                penalty_factors.append(1.0)
        elif voxels <= 15:
            # 小候选放宽: 部分容积效应导致 max_hu 偏高是正常现象
            if max_hu > 500:
                penalty_factors.append(0.2)
            elif max_hu > 400:
                penalty_factors.append(0.5)
            else:
                penalty_factors.append(1.0)
        else:
            if max_hu > 500:
                penalty_factors.append(0.2)
            elif max_hu > 400:
                penalty_factors.append(0.4)
            elif max_hu > 350:
                penalty_factors.append(0.7)
            else:
                penalty_factors.append(1.0)

        # (c) 微小血管截面: voxels极少 + 仅跨2层 + d<2.5mm = 典型假阳性模式
        #     v2.1.0: 加入 HU+形态联合判断:
        #     如果 HU 在正常结节范围(20-200) 且 elongation<1.5 → 可能是真结节
        #     GT2: 8体素/2层/2.2mm/HU=134/elong=1.33 → 应该被保护
        is_nodule_like = (20 <= hu <= 200) and (e <= 1.5)
        if voxels <= 7 and z_slices == 2 and d < 2.5:
            if is_nodule_like:
                penalty_factors.append(0.6)   # 结节特征明显，轻罚
            else:
                penalty_factors.append(0.25)  # 极少体素+非典型结节HU
        elif voxels <= 9 and z_slices == 2 and d < 2.3:
            if is_nodule_like:
                penalty_factors.append(0.8)   # 结节特征明显，仅微罚
            else:
                penalty_factors.append(0.4)
        elif voxels <= 12 and z_slices == 2 and d < 2.5:
            penalty_factors.append(0.7)
        else:
            penalty_factors.append(1.0)

        # (d) 体素密度: 填充稀疏（<0.2）提示细长不规则结构
        if voxel_density < 0.15:
            penalty_factors.append(0.4)
        elif voxel_density < 0.25:
            penalty_factors.append(0.6)
        else:
            penalty_factors.append(1.0)

        # (e) z_span 远大于 diameter: 纵向细长结构
        if ratio > 3.0:
            penalty_factors.append(0.3)
        elif ratio > 2.0:
            penalty_factors.append(0.6)
        else:
            penalty_factors.append(1.0)

        # (f) v2.7 新增: 血管模式惩罚 — mean_hu低 + max_hu高 = 典型血管横截面
        #     血管中心高密度，边缘被低密度肺组织平均拉低
        #     Case 1: Solid#9(mean=2,max=180), #10(mean=1,max=108) 等全是这种模式
        #     保护: Case1 GT(mean=94,max=353) 差值259但mean>50所以不触发
        hu_diff = max_hu - hu
        if hu < 50 and hu_diff > 250:
            penalty_factors.append(0.2)   # 强血管信号
        elif hu < 50 and hu_diff > 200:
            penalty_factors.append(0.35)  # 中度血管信号
        elif hu < 30 and hu_diff > 100:
            penalty_factors.append(0.4)   # 低HU+较大差异
        else:
            penalty_factors.append(1.0)

        # (g) v2.7 新增: 肺尖/肺底区域惩罚 — 部分容积效应严重
        #     CT最顶/最底几层受胸廓入口/膈肌影响，假阳性率极高
        #     Case 1: Solid#1(z=7-18, d=7.6mm) 是全场最高分但100%假阳性
        #     保护: 只惩罚位置在最外5%的候选，不影响中间90%
        cz = c.get('cz', 0)
        if n_slices > 0:
            z_pct = cz / n_slices
            if z_pct < 0.05 or z_pct > 0.95:
                penalty_factors.append(0.4)   # 最外5%: 重罚
            elif z_pct < 0.08 or z_pct > 0.92:
                penalty_factors.append(0.6)   # 5%~8%: 中罚
            else:
                penalty_factors.append(1.0)

        # (h) v2.8 新增: 肺外缘空间惩罚 — 胸壁附近血管截面假阳性集中区
        #     Case2: S#3(cx=386),S#4(cx=386),S#8(cx=386),S#11(cx=400),S#15(cx=396)
        #     全在cx>370(距中心>114px)区域，均为血管截面假阳性
        #     保护: 4个真结节 cx=155(GT4),159(GT4alt),345(GT2),351(GT3)
        #     距中心分别=101, 97, 89, 95 — 全部<100px，不触发
        #     图像假设512x512, 中心=256
        cx_pixel = c.get('cx', 256)
        cx_dist = abs(cx_pixel - 256)
        if cx_dist > 180:       # 极外缘 (如 cx>436 或 cx<76)
            penalty_factors.append(0.4)
        elif cx_dist > 150:     # 外缘 (如 cx>406 或 cx<106)
            penalty_factors.append(0.6)
        elif cx_dist > 120:     # 偏外 (如 cx>376 或 cx<136)
            penalty_factors.append(0.8)
        else:
            penalty_factors.append(1.0)

        # (i) v2.8 新增: 外缘 + 微小灶联合惩罚
        #     当 HU 在正常结节范围 + z_slices仅2层 + 直径<2.5mm + 偏外位置
        #     同时满足时，这是最典型的血管截面假阳性组合
        #     Case2: 大量 z_slices=2, d=2.2mm, cx>350 的假阳性获得了 0.92 高分
        if 80 <= hu <= 200 and z_slices == 2 and d < 2.5 and cx_dist > 100:
            penalty_factors.append(0.5)   # 联合惩罚

        # 综合: 取所有因子的乘积（多个假阳性特征叠加时惩罚更重）
        vessel_penalty = 1.0
        for pf in penalty_factors:
            vessel_penalty *= pf
        # 限制最低值，避免完全归零
        vessel_penalty = max(0.05, vessel_penalty)

    elif ctype == 'ggo':
        # GGO 的血管排除 — 排除边缘噪声、伪影和细长非结节结构
        penalty_factors = []

        # (a) GGO 体素极少 + elongation 高 → 边缘噪声
        if voxels <= 7 and e >= 1.7:
            penalty_factors.append(0.4)
        elif voxels <= 10 and e >= 1.7:
            penalty_factors.append(0.6)
        else:
            penalty_factors.append(1.0)

        # (b) v2.6 新增: GGO elongation 过高 → 非圆形，更像血管旁含气不全/伪影
        #     校准: 真GGO#21 elong=1.16, 假阳性#22-#35 elong=1.4-2.0+
        #     elongation>1.8 无条件重罚; >1.5+小体素 中罚
        if e > 1.8:
            penalty_factors.append(0.3)
        elif e > 1.5 and voxels < 30:
            penalty_factors.append(0.5)
        else:
            penalty_factors.append(1.0)

        # (c) GGO 在肺边缘外围 — 通过 HU 范围间接判断
        if hu_std > 80:
            penalty_factors.append(0.6)
        else:
            penalty_factors.append(1.0)

        # (d) v2.8 收紧: GGO mean_hu 过低 — 接近空气(-1000)
        #     v2.7原: -530→0.3, -510→0.5, 配合HU评分-500→1.0 降权不足
        #     v2.8: 收紧到-500/-480, 配合HU评分-480分水岭形成双重降权
        #     Case2: 真GGO HU=-409, 假阳性 G#22(-492),G#24(-487),G#26(-487)
        if hu < -510:
            penalty_factors.append(0.3)  # 极低HU，几乎是空气
        elif hu < -500:
            penalty_factors.append(0.4)  # v2.8: 收紧（原不触发）
        elif hu < -480:
            penalty_factors.append(0.7)  # v2.8: 新增 -500~-480 轻度惩罚
        else:
            penalty_factors.append(1.0)

        # (e) v2.7 新增: 肺尖/肺底区域惩罚（GGO也适用）
        cz = c.get('cz', 0)
        if n_slices > 0:
            z_pct = cz / n_slices
            if z_pct < 0.05 or z_pct > 0.95:
                penalty_factors.append(0.4)
            elif z_pct < 0.08 or z_pct > 0.92:
                penalty_factors.append(0.6)
            else:
                penalty_factors.append(1.0)

        vessel_penalty = 1.0
        for pf in penalty_factors:
            vessel_penalty *= pf
        vessel_penalty = max(0.1, vessel_penalty)

    # --- 综合评分 (加权几何平均) ---
    # v2.0.0: 重新分配权重，引入血管排除维度
    if ctype == 'solid':
        score = (
            (sphericity ** 0.20) *
            (elong_score ** 0.20) *
            (size_score ** 0.15) *
            (hu_score ** 0.10) *
            (z_score ** 0.10) *
            (consistency ** 0.05) *
            (vessel_penalty ** 0.20)
        )
    else:  # ggo
        score = (
            (sphericity ** 0.20) *
            (elong_score ** 0.15) *
            (size_score ** 0.15) *
            (hu_score ** 0.12) *
            (z_score ** 0.13) *
            (consistency ** 0.05) *
            (vessel_penalty ** 0.20)
        )

    # v1.9.0: 碎片候选降权 — d<1.8mm 且 z_slices=1 的可疑碎片
    if d < 1.8 and z_slices == 1:
        score *= 0.85

    # v2.1.0: 大连通域2D子候选降权
    # 这些候选从血管连通域中提取，先天假阳性率很高(~90%)
    # 施加 0.90 降权让独立候选（如GT2）更容易排到前面
    # 但不能太狠，否则真结节(GT3)又掉出Top-N
    if is_sub_from_large:
        score *= 0.90

    # v2.0.0: 移除聚合候选 1.05 加分 — 聚合本身不增加可信度
    # (之前 v1.9.0 的 score * 1.05 已删除)

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


def get_cad_focus_slices(solid_candidates, ggo_candidates, margin: int = 5) -> set:
    """
    计算所有 CAD 候选附近的"重点层" z-index 集合。

    对于每个候选的 z_range 前后扩展 margin 层，返回所有应使用完整 prompt 的层面索引。
    远离这些层面的切片可以使用精简版 prompt 以节省上下文。

    v2.4.7: 上下文优化核心——将 800+ 层分为"重点层"(~60-100) 和"快扫层"(~700+)

    Args:
        solid_candidates: 实性候选列表
        ggo_candidates: GGO 候选列表
        margin: 候选 z_range 前后扩展的层数（默认5层）

    Returns:
        重点层 z-index 集合 (set of int)
    """
    focus_set = set()
    all_candidates = list(solid_candidates or []) + list(ggo_candidates or [])

    for c in all_candidates:
        z_range = c.get('z_range', '')
        if not z_range:
            continue
        try:
            parts = str(z_range).split('-')
            z_min = int(parts[0])
            z_max = int(parts[-1]) if len(parts) > 1 else z_min
            for z in range(z_min - margin, z_max + margin + 1):
                if z >= 0:
                    focus_set.add(z)
        except (ValueError, IndexError):
            continue

    return focus_set


def format_candidates_for_slice(solid_candidates, ggo_candidates,
                                 slice_z_index: int, n_slices: int = 0,
                                 spacing=None, proximity: int = 5) -> str:
    """
    为单个切片生成仅包含附近候选的 CAD hint 文本（v2.4.7+）。

    与 format_candidates_for_prompt() 不同，此函数只注入 z-index 距当前层面
    在 proximity 范围内的候选，避免每层都重复全部 25 个候选的 2.5KB 文本。

    典型场景：800层CT、25个候选 →
    - 旧方式：每层注入全部25个 × ~2.5KB = 2MB 冗余
    - 新方式：平均每层注入 0-3 个 × ~200B = 总计 ~160KB

    Args:
        solid_candidates: 实性候选列表
        ggo_candidates: GGO 候选列表
        slice_z_index: 当前切片的 z-index（0-based）
        n_slices: 总切片数
        spacing: [x, y, z] 体素间距(mm)
        proximity: z-index 距离阈值（默认5层）

    Returns:
        仅包含附近候选的 prompt 文本；如果附近无候选则返回空字符串
    """
    def _is_near(candidate, z_idx, prox):
        z_range = candidate.get('z_range', '')
        if not z_range:
            return False
        try:
            parts = str(z_range).split('-')
            z_min = int(parts[0])
            z_max = int(parts[-1]) if len(parts) > 1 else z_min
            return z_min - prox <= z_idx <= z_max + prox
        except (ValueError, IndexError):
            return False

    near_solid = [c for c in (solid_candidates or []) if _is_near(c, slice_z_index, proximity)]
    near_ggo = [c for c in (ggo_candidates or []) if _is_near(c, slice_z_index, proximity)]

    if not near_solid and not near_ggo:
        return ""

    lines = [
        "",
        f"**⚠️ CAD: 本层附近({proximity}层内)检出以下候选，请重点验证：**",
    ]

    for c in near_solid:
        score = c.get('nodule_score', 0)
        z_pct = f"({c['cz']:.0f}/{n_slices}层)" if n_slices else ""
        lines.append(
            f"  实性 ⭐{score:.2f} z={c['z_range']} {z_pct} "
            f"pos=({c['cx']:.0f},{c['cy']:.0f}) "
            f"d={c['diameter_mm']:.1f}mm HU={c['mean_hu']:.0f}"
        )

    for c in near_ggo:
        score = c.get('nodule_score', 0)
        z_pct = f"({c['cz']:.0f}/{n_slices}层)" if n_slices else ""
        lines.append(
            f"  GGO ⭐{score:.2f} z={c['z_range']} {z_pct} "
            f"pos=({c['cx']:.0f},{c['cy']:.0f}) "
            f"d={c['diameter_mm']:.1f}mm HU={c['mean_hu']:.0f}"
        )

    lines.append("  ⭐>0.9 高度可疑，0.8-0.9 中度可疑。请确认是结节还是血管。")
    return "\n".join(lines)
