#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 报告生成模块

生成一份医院放射科风格的 AI 辅助影像检查报告，包含：
  - 检查信息（日期、文件、影像数量、窗口类型等）
  - AI 检视统计（总检视数、正常数、异常数）
  - 检查所见（逐条列出异常发现）
  - 异常影像展示（嵌入异常片子照片 + PNG 完整文件名 + 详细异常描述）
  - 诊断意见（含 Lung-RADS 分类和随访建议）
  - 免责声明
"""

import logging
import os
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from modality_detector import ImagingProfile

# 延迟导入 reportlab，缺失时尝试自修复安装
try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        Image,
        PageBreak,
        PageTemplate,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False

logger = logging.getLogger("dicom-doctor.report")

# PDF 页数上限控制
MAX_PDF_PAGES = 50          # 默认最大 PDF 页数
_OVERHEAD_PAGES = 8         # 标题+信息+所见+诊断+分级+免责等固定区域预估页数
_PAGES_PER_IMAGE = 1.5      # 每张异常影像（含多窗图+详情表）约占页数

# 免责声明文本
DISCLAIMER_TEXT = (
    "本报告由 AI 辅助生成，仅供参考，不构成医学诊断。"
    "如有疑问，请及时咨询专业医生。"
)


class FontManager:
    """中文字体检测与加载管理器"""

    # 常见中文字体路径
    FONT_SEARCH_PATHS = [
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        # macOS
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode MS.ttf",
        # Windows
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
    ]

    def __init__(self):
        self._font_name = self._find_chinese_font()

    def _find_chinese_font(self) -> Optional[str]:
        """查找并注册可用的中文字体"""
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        # 检查项目内置字体目录
        project_font_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "assets", "fonts"
        )
        if os.path.isdir(project_font_dir):
            for fname in os.listdir(project_font_dir):
                if fname.endswith((".ttf", ".ttc", ".otf")):
                    font_path = os.path.join(project_font_dir, fname)
                    try:
                        font_name = f"CustomCN-{Path(fname).stem}"
                        pdfmetrics.registerFont(TTFont(font_name, font_path))
                        logger.info(f"使用内置中文字体: {fname}")
                        return font_name
                    except Exception:
                        continue

        # 搜索系统字体
        for font_path in self.FONT_SEARCH_PATHS:
            if os.path.exists(font_path):
                try:
                    font_name = f"SystemCN-{Path(font_path).stem}"
                    pdfmetrics.registerFont(TTFont(font_name, font_path))
                    logger.info(f"使用系统中文字体: {font_path}")
                    return font_name
                except Exception:
                    continue

        logger.warning("未找到可用的中文字体，报告中的中文可能无法正确显示")
        return None

    @property
    def font_name(self) -> str:
        """返回可用的字体名称，无中文字体时回退到 Helvetica"""
        return self._font_name if self._font_name else "Helvetica"

    @property
    def has_chinese_font(self) -> bool:
        """是否找到了中文字体"""
        return self._font_name is not None


class ReportGenerator:
    """PDF 报告生成器 — 输出一份医院放射科风格的 AI 辅助影像检查报告"""

    def __init__(self):
        global _REPORTLAB_AVAILABLE
        if not _REPORTLAB_AVAILABLE:
            # [自修复] 尝试自动安装 reportlab（镜像感知）
            logger.warning("[自修复] reportlab 未安装，尝试自动安装 ...")
            try:
                from pip_utils import pip_install as pip_install_mirror
                if pip_install_mirror("reportlab>=4.0.0"):
                    import importlib
                    importlib.invalidate_caches()
                    global colors, TA_CENTER, TA_LEFT, TA_RIGHT, A4
                    global ParagraphStyle, getSampleStyleSheet
                    global cm, mm, BaseDocTemplate, Frame, Image, PageBreak, PageTemplate
                    global Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

                    from reportlab.lib import colors as _colors
                    from reportlab.lib.enums import (
                        TA_CENTER as _TA_CENTER, TA_LEFT as _TA_LEFT, TA_RIGHT as _TA_RIGHT,
                    )
                    from reportlab.lib.pagesizes import A4 as _A4
                    from reportlab.lib.styles import (
                        ParagraphStyle as _PS, getSampleStyleSheet as _gSS,
                    )
                    from reportlab.lib.units import cm as _cm, mm as _mm
                    from reportlab.platypus import (
                        BaseDocTemplate as _BDT, Frame as _Frame, Image as _Image,
                        PageBreak as _PB, PageTemplate as _PT, Paragraph as _Para,
                        SimpleDocTemplate as _SDT, Spacer as _Spacer,
                        Table as _Table, TableStyle as _TS,
                    )
                    colors = _colors; TA_CENTER = _TA_CENTER; TA_LEFT = _TA_LEFT
                    TA_RIGHT = _TA_RIGHT; A4 = _A4
                    ParagraphStyle = _PS; getSampleStyleSheet = _gSS
                    cm = _cm; mm = _mm; BaseDocTemplate = _BDT; Frame = _Frame
                    Image = _Image; PageBreak = _PB; PageTemplate = _PT
                    Paragraph = _Para; SimpleDocTemplate = _SDT; Spacer = _Spacer
                    Table = _Table; TableStyle = _TS
                    _REPORTLAB_AVAILABLE = True
                    logger.info("[自修复] reportlab 安装成功")
                else:
                    raise RuntimeError("pip 安装失败（已尝试所有镜像源）")
            except Exception as e:
                raise ImportError(
                    f"[自修复] reportlab 自动安装失败: {e}\n"
                    f"请手动执行: pip install reportlab>=4.0.0 -i https://pypi.tuna.tsinghua.edu.cn/simple/"
                )

        self._font_mgr = FontManager()

    def generate(self, review_results: list, input_path: str,
                 output_dir: str, report_path: str = None,
                 window_type: str = "lung", min_size: int = 1024,
                 enhance: bool = False, enhance_scale: int = 2,
                 version: str = "unknown",
                 imaging_profile: 'Optional[ImagingProfile]' = None,
                 task_start_time: Optional[datetime] = None,
                 task_end_time: Optional[datetime] = None,
                 timings = None,
                 model_name: str = None,
                 patient_info: Optional[dict] = None,
                 max_pages: int = MAX_PDF_PAGES,
                 cross_validation: Optional[dict] = None) -> str:
        """
        生成一份医院风格的 PDF 检视报告。

        Args:
            review_results: ReviewResult 对象列表
            input_path: 原始输入文件路径
            output_dir: 输出目录
            report_path: 指定的报告输出路径（可选）
            window_type: 使用的窗口类型（如 lung/mediastinum/bone/soft_tissue/all）
            min_size: Lanczos 放大的最小尺寸
            enhance: 是否启用了超分增强
            enhance_scale: 超分放大倍数
            version: Skill 版本号，展示在报告中
            imaging_profile: 影像类型策略配置（可选）。传入后报告将根据影像类型
                            动态生成标题、分区和分级系统展示。
            task_start_time: 任务开始时间（精确到秒）
            task_end_time: 任务完成时间（精确到秒）
            timings: PipelineTimings 实例，包含各阶段耗时统计（可选）
            model_name: 阅片使用的大模型名称（如 claude-4.6-opus），展示在报告中
            max_pages: PDF 最大页数限制（默认 50）。超出时自动裁剪异常影像展示数量，
                       优先保留每个结节的代表层面，被省略的层面用简明表格汇总。

        Returns:
            dict，包含 'pdf_path' 和 'md_path' 两个键，分别为 PDF 和 Markdown 报告路径
        """
        self._window_type = window_type
        self._min_size = min_size
        self._enhance = enhance
        self._enhance_scale = enhance_scale
        self._version = version
        self._imaging_profile = imaging_profile
        self._task_start_time = task_start_time
        self._task_end_time = task_end_time
        self._timings = timings
        self._model_name = model_name
        self._patient_info = patient_info or {}
        self._max_pages = max_pages
        self._cross_validation = cross_validation
        if report_path:
            pdf_path = report_path
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_path = os.path.join(output_dir, f"dicom_report_{timestamp}.pdf")

        os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)

        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            topMargin=2 * cm,
            bottomMargin=2.5 * cm,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
        )

        styles = self._build_styles()
        story = []

        # 1. 报告标题
        story.extend(self._build_title(styles))

        # 2. 检查信息表 + AI 检视统计 + 检查参数
        story.extend(self._build_scan_info(styles, review_results, input_path))

        # 2.5 阶段耗时明细表（如有计时数据）
        story.extend(self._build_timing_detail(styles))

        # 3. 检查所见
        story.extend(self._build_findings(styles, review_results))

        # 4. 异常影像展示（嵌入照片 + PNG 文件名 + 详细异常描述）
        story.extend(self._build_abnormal_images(styles, review_results))

        # 5. 诊断意见
        story.extend(self._build_diagnosis(styles, review_results))

        # 5.5 CAD 交叉验证告警（如有告警）
        story.extend(self._build_cross_validation_section(styles))

        # 6. 分级系统参考表（根据影像类型动态选择）
        story.extend(self._build_classification_reference_table(styles))

        # 7. 免责声明
        story.extend(self._build_disclaimer(styles))

        # 使用自定义页脚（含版本号和页码）
        version_str = self._version
        font_name = self._font_mgr.font_name

        def _add_page_footer(canvas, doc):
            """在每页底部添加版本号和页码"""
            canvas.saveState()
            footer_text = f"DICOM Doctor v{version_str}"
            page_text = f"第 {doc.page} 页"
            canvas.setFont(font_name, 8)
            canvas.setFillColor(colors.grey)
            # 左下角：版本号
            canvas.drawString(2 * cm, 1.2 * cm, footer_text)
            # 右下角：页码
            canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, page_text)
            # 页脚分隔线
            canvas.setStrokeColor(colors.HexColor("#bdc3c7"))
            canvas.setLineWidth(0.5)
            canvas.line(2 * cm, 1.6 * cm, A4[0] - 2 * cm, 1.6 * cm)
            canvas.restoreState()

        doc.build(story, onFirstPage=_add_page_footer, onLaterPages=_add_page_footer)
        logger.info(f"PDF 报告已生成: {pdf_path}")

        # 同时生成 Markdown 格式报告，放在同一目录下
        md_path = self._generate_markdown(review_results, input_path, pdf_path)

        return {"pdf_path": pdf_path, "md_path": md_path}

    # ================================================================
    # 样式定义
    # ================================================================

    def _build_styles(self) -> dict:
        """构建报告所需的段落样式"""
        font = self._font_mgr.font_name
        base = getSampleStyleSheet()

        return {
            # 报告大标题（24pt 加粗居中）
            "title": ParagraphStyle(
                "RptTitle", parent=base["Title"], fontName=font,
                fontSize=24, alignment=TA_CENTER, spaceAfter=4,
                textColor=colors.HexColor("#1a5276"),
            ),
            # 副标题（12pt 灰色居中，用于系统名称）
            "subtitle": ParagraphStyle(
                "RptSubtitle", parent=base["Normal"], fontName=font,
                fontSize=12, alignment=TA_CENTER,
                textColor=colors.HexColor("#666666"), spaceAfter=4,
            ),
            # 报告日期副标题（10pt 灰色居中）
            "subtitle_date": ParagraphStyle(
                "RptSubtitleDate", parent=base["Normal"], fontName=font,
                fontSize=10, alignment=TA_CENTER,
                textColor=colors.grey, spaceAfter=12,
            ),
            # 章节标题（如"一、检查所见"）— 加粗 + 底部细线分隔
            "section": ParagraphStyle(
                "RptSection", parent=base["Heading2"], fontName=font,
                fontSize=14, spaceBefore=18, spaceAfter=8,
                textColor=colors.HexColor("#1a5276"),
                borderPadding=0, borderWidth=0,
            ),
            # 小节标签（如"检查部位："）
            "label": ParagraphStyle(
                "RptLabel", parent=base["Normal"], fontName=font,
                fontSize=11, leading=16, spaceBefore=8, spaceAfter=4,
                textColor=colors.HexColor("#2c3e50"),
            ),
            # 正文
            "body": ParagraphStyle(
                "RptBody", parent=base["Normal"], fontName=font,
                fontSize=10, leading=18, spaceAfter=4, leftIndent=12,
            ),
            # 正文（加粗红色，用于异常描述）
            "body_abnormal": ParagraphStyle(
                "RptBodyAbnormal", parent=base["Normal"], fontName=font,
                fontSize=10, leading=18, spaceAfter=4, leftIndent=12,
                textColor=colors.HexColor("#c0392b"),
            ),
            # 诊断意见（红色）
            "diagnosis": ParagraphStyle(
                "RptDiagnosis", parent=base["Normal"], fontName=font,
                fontSize=10, leading=18, spaceAfter=4, leftIndent=12,
                textColor=colors.HexColor("#c0392b"),
            ),
            # 图片标题（PNG 文件名）
            "img_caption": ParagraphStyle(
                "RptImgCaption", parent=base["Normal"], fontName=font,
                fontSize=9, leading=12, alignment=TA_CENTER,
                textColor=colors.HexColor("#555555"), spaceAfter=4,
            ),
            # 图片下方异常详情
            "img_detail": ParagraphStyle(
                "RptImgDetail", parent=base["Normal"], fontName=font,
                fontSize=9, leading=14, spaceAfter=2, leftIndent=16,
                textColor=colors.HexColor("#2c3e50"),
            ),
            # 免责声明
            "disclaimer": ParagraphStyle(
                "RptDisclaimer", parent=base["Normal"], fontName=font,
                fontSize=9, textColor=colors.grey,
                alignment=TA_CENTER, spaceBefore=20, spaceAfter=10,
            ),
            # 报告生成时间戳（9pt 灰色）
            "timestamp": ParagraphStyle(
                "RptTimestamp", parent=base["Normal"], fontName=font,
                fontSize=9, textColor=colors.HexColor("#999999"),
                alignment=TA_CENTER, spaceBefore=4, spaceAfter=4,
            ),
            # 窗口标签（图片下方标注）
            "window_label": ParagraphStyle(
                "RptWindowLabel", parent=base["Normal"], fontName=font,
                fontSize=8, leading=11, alignment=TA_CENTER,
                textColor=colors.HexColor("#555555"), spaceAfter=2,
            ),
            # 表格单元格内长文本（8pt，左对齐，自动换行）
            "cell": ParagraphStyle(
                "RptCell", parent=base["Normal"], fontName=font,
                fontSize=8, leading=11, alignment=TA_LEFT,
                textColor=colors.HexColor("#333333"),
            ),
        }

    # ================================================================
    # 报告各区域构建
    # ================================================================

    def _build_title(self, styles: dict) -> list:
        """报告标题区域 — 大标题 + 副标题 + 分隔线，参照参考模板"""
        elements = []

        # 大标题：AI 辅助影像检查报告（24pt 加粗居中）
        profile = getattr(self, '_imaging_profile', None)
        if profile:
            title_text = f"{profile.display_name} AI 辅助阅片报告"
        else:
            title_text = "AI 辅助影像检查报告"
        elements.append(Paragraph(title_text, styles["title"]))

        # 副标题：系统名称（12pt 灰色居中）
        elements.append(Paragraph(
            "DICOM Doctor — 人工智能辅助医学影像阅片系统",
            styles["subtitle"]
        ))

        # 报告日期（10pt 灰色居中）
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elements.append(Paragraph(f"报告日期：{now}", styles["subtitle_date"]))

        # 主分隔线（2pt 深蓝色）
        line_table = Table([[""]], colWidths=[17 * cm])
        line_table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 2, colors.HexColor("#1a5276")),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 12))
        return elements

    def _build_scan_info(self, styles: dict, review_results: list,
                         input_path: str) -> list:
        """检查信息表 + AI 检视统计"""
        elements = []
        font = self._font_mgr.font_name

        total = len(review_results)
        normal = sum(1 for r in review_results if r.conclusion.value == "正常")
        abnormal = sum(1 for r in review_results if r.conclusion.value == "异常")
        unrecog = sum(1 for r in review_results if r.conclusion.value == "无法识别")

        body_part = self._infer_body_part(review_results)
        # 如果有 Profile，使用 Profile 的 display_name
        profile = getattr(self, '_imaging_profile', None)
        if profile:
            body_part = profile.display_name

        # 窗口类型显示名称
        profile = getattr(self, '_imaging_profile', None)
        if profile and profile.window_presets:
            window_parts = []
            for wname, (wc, ww) in profile.window_presets.items():
                window_parts.append(f"{wname} (WC={wc}, WW={ww})")
            window_name = " + ".join(window_parts) if window_parts else "DICOM 自带窗位"
        elif profile:
            window_name = "DICOM 自带窗位"
        else:
            window_display = {
                "lung": "肺窗 (WC=-600, WW=1500)",
                "mediastinum": "纵隔窗 (WC=40, WW=400)",
                "bone": "骨窗 (WC=400, WW=1800)",
                "soft_tissue": "软组织窗 (WC=50, WW=350)",
                "all": "全窗口 (肺窗+纵隔窗+骨窗+软组织窗)",
            }
            wtype = getattr(self, '_window_type', 'lung') or 'lung'
            window_name = window_display.get(wtype, f"{wtype}")

        # 图像增强方式
        min_sz = getattr(self, '_min_size', 1024) or 1024
        enhance_on = getattr(self, '_enhance', False)
        if enhance_on:
            enhance_desc = f"Real-ESRGAN {getattr(self, '_enhance_scale', 2)}x 超分"
        elif min_sz > 0:
            enhance_desc = f"Lanczos 高质量插值放大 (≥{min_sz}px)"
        else:
            enhance_desc = "原始分辨率"

        # --- 检查信息表（4列紧凑布局，参照参考模板） ---
        model_name = getattr(self, '_model_name', None)
        task_start = getattr(self, '_task_start_time', None)
        task_end = getattr(self, '_task_end_time', None)
        timings = getattr(self, '_timings', None)

        data = [
            ["检查类型", body_part, "检查日期", datetime.now().strftime("%Y-%m-%d")],
            ["影像类型", profile.display_name if profile else "胸部CT（推断）", "影像总数", f"{total} 层/张"],
            ["窗口类型", window_name, "图像增强", enhance_desc],
            ["重建方式", "轴位 + 冠状位 + 定位像", "报告日期", datetime.now().strftime("%Y-%m-%d %H:%M")],
        ]
        # 患者信息（脱敏后）
        pinfo = getattr(self, '_patient_info', {})
        if pinfo:
            p_name = pinfo.get("patient_name", "—")
            p_sex = pinfo.get("patient_sex", "—")
            data.insert(0, ["患者姓名", p_name, "性别", p_sex])
            p_id = pinfo.get("patient_id", "")
            study_date = pinfo.get("study_date", "")
            if p_id or study_date:
                data.insert(1, ["患者编号", p_id or "—", "检查日期", study_date or "—"])
            institution = pinfo.get("institution", "")
            if institution:
                data.insert(2, ["检查机构", institution, "", ""])
        # 阅片大模型名称
        if model_name:
            data.append(["阅片大模型", model_name, "Skill 版本", getattr(self, '_version', 'unknown')])
        else:
            data.append(["Skill 版本", getattr(self, '_version', 'unknown'), "", ""])
        # 任务时间
        if task_start and task_end:
            data.append(["检视开始时间", task_start.strftime("%H:%M:%S"), "检视结束时间", task_end.strftime("%H:%M:%S")])
        elif task_start:
            data.append(["检视开始时间", task_start.strftime("%Y-%m-%d %H:%M:%S"), "", ""])
        # 耗时
        if timings:
            total_secs = timings.total_seconds
            if total_secs >= 60:
                total_time_str = f"{int(total_secs // 60)}分{int(total_secs % 60)}秒"
            else:
                total_time_str = f"{total_secs:.1f}秒"
            data.append(["总耗时", total_time_str, "DICOM/PNG", f"{timings.dicom_file_count} / {timings.png_file_count}"])

        col_widths = [3 * cm, 5.5 * cm, 3 * cm, 5.5 * cm]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            # 标签列使用浅灰背景
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F5F5")),
            ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F5F5F5")),
            # 数值列白色背景
            ("BACKGROUND", (1, 0), (1, -1), colors.white),
            ("BACKGROUND", (3, 0), (3, -1), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdc3c7")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 8))

        # --- 检视统计表（独立小表，参照参考模板） ---
        elements.append(Paragraph("AI 检视统计", styles["label"]))
        stats_data = [
            ["检视总数", str(total), "正常层面", f"{normal} 张"],
            ["疑似异常层面", f"{abnormal} 张", "无法识别", f"{unrecog} 张"],
        ]
        stats_table = Table(stats_data, colWidths=col_widths)
        stats_style_cmds = [
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F5F5")),
            ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F5F5F5")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdc3c7")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        # 异常数标红
        if abnormal > 0:
            stats_style_cmds.append(
                ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor("#e74c3c"))
            )
        stats_table.setStyle(TableStyle(stats_style_cmds))
        elements.append(stats_table)
        elements.append(Spacer(1, 12))
        return elements

    # ================================================================
    # 结节聚合逻辑
    # ================================================================

    @staticmethod
    def _normalize_location(location: str) -> str:
        """
        归一化位置描述，去掉层面编号等动态部分，提取纯解剖位置。

        示例:
          "左肺上叶下舌段(S5) (第218-221层)"       → "左肺上叶下舌段(S5)"
          "右肺中叶内段(S5) (第197-199层)"          → "右肺中叶内段(S5)"
          "左肺下叶上段(S6)（第344/832层）"          → "左肺下叶上段(S6)"
          "右肺上叶(第100/500层)"                    → "右肺上叶"
          "左肺上叶 第218层"                         → "左肺上叶"
          "右肺中叶，第197-199层"                    → "右肺中叶"
        """
        if not location:
            return ""
        # 去掉各种层面编号格式：
        #   (第NNN层)  (第NNN-NNN层)  (第NNN/MMM层)  （第NNN/MMM层）
        #   第NNN层  第NNN-NNN层  第NNN/MMM层（无括号版本）
        # 支持: 数字、连字符、斜杠、逗号（如 "第218,219,220层"）
        normalized = re.sub(
            r'\s*[，,]?\s*[（(]?\s*第[\d\-/,\s]+层\s*[）)]?',
            '', location
        ).strip()
        # 清理可能残留的尾部标点
        normalized = re.sub(r'[，,\s]+$', '', normalized)
        return normalized

    @staticmethod
    def _aggregate_nodules(abnormal_results: list) -> List[dict]:
        """
        将逐层异常记录聚合为独立结节列表。

        聚合依据：相同归一化位置（去掉层号后缀）的异常记录归为同一结节。
        每个结节选择置信度最高（高>中>低）的层面作为代表。

        Args:
            abnormal_results: 结论为"异常"的 ReviewResult 对象列表

        Returns:
            结节列表，每个元素为 dict:
            {
                "representative": ReviewResult,  # 代表层面（置信度最高）
                "slices": [ReviewResult, ...],    # 该结节所有层面
                "location": str,                  # 归一化后的位置
                "slice_count": int,               # 出现层面数
                "slice_range": str,               # 层面范围描述（如 "IM 218-221"）
            }
        """
        confidence_rank = {"高": 3, "中": 2, "低": 1, "": 0}

        # 按归一化位置分组（保持发现顺序）
        groups: OrderedDict[str, list] = OrderedDict()
        for r in abnormal_results:
            loc = r.location if hasattr(r, 'location') else ""
            norm_loc = ReportGenerator._normalize_location(loc)
            if not norm_loc:
                norm_loc = f"_unknown_{id(r)}"
            if norm_loc not in groups:
                groups[norm_loc] = []
            groups[norm_loc].append(r)

        nodules = []
        for norm_loc, slices in groups.items():
            # 选择置信度最高的作为代表
            conf_key = lambda r: confidence_rank.get(
                getattr(r, 'confidence', '') or '', 0
            )
            representative = max(slices, key=conf_key)

            # 提取层面范围
            slice_indices = []
            for r in slices:
                si = getattr(r, 'slice_index', '') or ''
                if '/' in si:
                    try:
                        slice_indices.append(int(si.split('/')[0]))
                    except ValueError:
                        pass

            if slice_indices:
                slice_indices.sort()
                if len(slice_indices) == 1:
                    slice_range = f"第 {slice_indices[0]} 层"
                else:
                    slice_range = f"第 {slice_indices[0]}-{slice_indices[-1]} 层"
            else:
                slice_range = f"{len(slices)} 个层面"

            nodules.append({
                "representative": representative,
                "slices": slices,
                "location": norm_loc,
                "slice_count": len(slices),
                "slice_range": slice_range,
            })

        return nodules

    def _build_findings(self, styles: dict, review_results: list) -> list:
        """检查所见 — 先展示聚合结节汇总，再保留逐层异常明细"""
        elements = []
        elements.extend(self._section_heading("一、检查所见", styles))

        abnormal_results = [r for r in review_results if r.conclusion.value == "异常"]
        total = len(review_results)
        normal = sum(1 for r in review_results if r.conclusion.value == "正常")
        unrecog = sum(1 for r in review_results if r.conclusion.value == "无法识别")

        font = self._font_mgr.font_name

        if abnormal_results:
            # --- 聚合结节汇总 ---
            nodules = self._aggregate_nodules(abnormal_results)

            elements.append(Paragraph(
                f"<b>AI 共检出 {len(nodules)} 个独立结节"
                f"（涉及 {len(abnormal_results)} 个异常层面）：</b>",
                styles["label"]
            ))

            # 结节汇总表
            header = ["序号", "位置", "类型", "大小", "出现层面", "分级", "置信度"]
            rows = [header]
            for idx, nod in enumerate(nodules, 1):
                rep = nod["representative"]
                # 推断类型（GGO/实性）
                desc = getattr(rep, 'abnormality_desc', '') or ''
                if 'GGO' in desc or '磨玻璃' in desc:
                    nodule_type = "GGO"
                elif '实性' in desc:
                    nodule_type = "实性"
                else:
                    nodule_type = "—"

                size = getattr(rep, 'size_mm', '') or '—'
                if size and 'mm' not in size:
                    size = f"{size}mm"

                lung_rads = getattr(rep, 'lung_rads', '') or ''
                if not lung_rads:
                    if hasattr(rep, 'classification_system') and rep.classification_system:
                        lung_rads = f"{rep.classification_system} {getattr(rep, 'classification_value', '')}"
                    else:
                        lung_rads = "—"

                confidence = getattr(rep, 'confidence', '') or '—'

                rows.append([
                    str(idx),
                    nod["location"],
                    nodule_type,
                    size,
                    f"{nod['slice_range']}\n({nod['slice_count']}层)",
                    lung_rads,
                    confidence,
                ])

            col_widths = [1.2 * cm, 4 * cm, 1.5 * cm, 2 * cm, 2.8 * cm, 2.5 * cm, 2 * cm]
            nodule_table = Table(rows, colWidths=col_widths)
            nodule_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                # 表头
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                # 奇数行浅灰
                *[("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FDF2F0"))
                  for i in range(1, len(rows)) if i % 2 == 0],
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e6b0aa")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (2, 0), (2, -1), "CENTER"),
                ("ALIGN", (5, 0), (6, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            elements.append(nodule_table)
            elements.append(Spacer(1, 10))

            # --- 逐层异常明细（保留原有逻辑） ---
            elements.append(Paragraph(
                f"<b>逐层异常明细（{len(abnormal_results)} 个异常层面）：</b>",
                styles["label"]
            ))

            for i, r in enumerate(abnormal_results, 1):
                finding = f"<b>发现 {i}：</b>"
                parts = []
                if r.location:
                    parts.append(r.location)
                if r.abnormality_desc:
                    parts.append(r.abnormality_desc)
                if r.size_mm:
                    parts.append(f"大小约 {r.size_mm}mm")
                if r.lung_rads:
                    parts.append(f"Lung-RADS {r.lung_rads}")
                elif hasattr(r, 'classification_system') and r.classification_system and hasattr(r, 'classification_value') and r.classification_value:
                    parts.append(f"{r.classification_system} {r.classification_value}")
                if parts:
                    finding += "，".join(parts) + "。"
                else:
                    finding += f"影像 {r.dicom_name} 检测到疑似异常。"

                elements.append(Paragraph(f"　· {finding}", styles["body_abnormal"]))

            # 描述其余正常部分
            if normal > 0:
                elements.append(Paragraph(
                    f"　　其余 {normal} 层/张影像未见明显异常征象。",
                    styles["body"]
                ))
            if unrecog > 0:
                elements.append(Paragraph(
                    f"　　另有 {unrecog} 层/张影像未能自动识别，建议人工复核。",
                    styles["body"]
                ))
        else:
            # 无异常
            if unrecog == total:
                elements.append(Paragraph(
                    "　　所有影像尚未完成 AI 分析（状态为'待检视'）。"
                    "请确保宿主 AI 工具已逐张执行阅片分析。",
                    styles["body_abnormal"]
                ))
            else:
                elements.append(Paragraph(
                    f"　　共检视 {total} 层/张影像，未见明显异常征象。",
                    styles["body"]
                ))
                elements.append(Paragraph(
                    "　　双肺纹理清晰，走行自然。气管及主要支气管通畅。纵隔内未见明显肿大淋巴结。",
                    styles["body"]
                ))

        elements.append(Spacer(1, 8))
        return elements

    def _build_abnormal_images(self, styles: dict, review_results: list) -> list:
        """
        异常影像展示区域（带页数预算控制）。

        页数预算策略:
        1. 计算可用于异常影像的页数 = max_pages - 固定区域页数
        2. 计算最大可展示图片数 = 可用页数 / 每张图片估算页数
        3. 优先展示每个聚合结节的"代表层面"（置信度最高的那张）
        4. 若代表层面数 < 预算，则按顺序补充其余非代表层面
        5. 被省略的层面用一个简明汇总表代替
        """
        abnormal_results = [r for r in review_results if r.conclusion.value == "异常"]
        if not abnormal_results:
            return []

        elements = []
        font = self._font_mgr.font_name

        # ---- 页数预算计算 ----
        max_pages = getattr(self, '_max_pages', MAX_PDF_PAGES)
        available_pages = max(max_pages - _OVERHEAD_PAGES, 5)  # 至少留5页给影像
        max_images = max(int(available_pages / _PAGES_PER_IMAGE), 3)  # 至少展示3张

        # ---- 选择要展示的影像 ----
        # 先聚合结节，提取每个结节的代表层面
        nodules = self._aggregate_nodules(abnormal_results)
        representative_set = set()
        for nod in nodules:
            representative_set.add(id(nod["representative"]))

        # 分为代表层面和非代表层面
        representative_results = []
        non_representative_results = []
        for r in abnormal_results:
            if id(r) in representative_set:
                representative_results.append(r)
            else:
                non_representative_results.append(r)

        # 优先展示代表层面，余额给非代表层面
        if len(representative_results) <= max_images:
            display_results = list(representative_results)
            remaining_budget = max_images - len(display_results)
            if remaining_budget > 0:
                display_results.extend(non_representative_results[:remaining_budget])
        else:
            # 代表层面都放不下，按结节重要性截断（保留前 max_images 个结节代表）
            display_results = representative_results[:max_images]

        # 被省略的层面
        display_set = set(id(r) for r in display_results)
        omitted_results = [r for r in abnormal_results if id(r) not in display_set]
        is_truncated = len(omitted_results) > 0

        # ---- 构建区域标题 ----
        if is_truncated:
            elements.extend(self._section_heading(
                f"二、异常影像详情（展示 {len(display_results)}/{len(abnormal_results)} 张，"
                f"页数预算 {max_pages} 页）",
                styles
            ))
        else:
            elements.extend(self._section_heading(
                f"二、异常影像详情（共 {len(abnormal_results)} 张）",
                styles
            ))

        # ---- 逐张展示（与原逻辑一致） ----
        for idx, r in enumerate(display_results, 1):
            # 标注是否为代表层面
            is_rep = id(r) in representative_set
            rep_tag = " ★" if is_rep else ""

            elements.append(Paragraph(
                f"<b>异常影像 {idx}{rep_tag}：{r.dicom_name}</b>",
                styles["label"]
            ))

            # 嵌入影像照片 — 支持多窗口并排对比展示
            if os.path.exists(r.png_path):
                try:
                    annotated_path = self._annotate_abnormal_image(
                        r.png_path, r, idx
                    )
                    display_path = annotated_path if annotated_path else r.png_path

                    ggo_path = self._find_alternate_window_image(r.png_path, "ggo")
                    med_path = self._find_alternate_window_image(r.png_path, "mediastinum")

                    if ggo_path or med_path:
                        img_cells = []
                        label_cells = []
                        img_width = 5.5 * cm

                        lung_img = Image(display_path, width=img_width, height=img_width)
                        lung_img.hAlign = "CENTER"
                        img_cells.append(lung_img)
                        label_cells.append(Paragraph("肺窗", styles["window_label"]))

                        if ggo_path:
                            ggo_img = Image(ggo_path, width=img_width, height=img_width)
                            ggo_img.hAlign = "CENTER"
                            img_cells.append(ggo_img)
                            label_cells.append(Paragraph("GGO窗", styles["window_label"]))

                        if med_path:
                            med_img = Image(med_path, width=img_width, height=img_width)
                            med_img.hAlign = "CENTER"
                            img_cells.append(med_img)
                            label_cells.append(Paragraph("纵隔窗", styles["window_label"]))

                        num_cols = len(img_cells)
                        col_w = [17 * cm / num_cols] * num_cols
                        img_table = Table([img_cells, label_cells], colWidths=col_w)
                        img_table.setStyle(TableStyle([
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 2),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                        ]))
                        elements.append(img_table)
                    else:
                        img = Image(display_path, width=8 * cm, height=8 * cm)
                        img.hAlign = "CENTER"
                        elements.append(img)
                except Exception as e:
                    logger.warning(f"无法嵌入影像 {r.png_path}: {e}")
                    elements.append(Paragraph(
                        f"[影像加载失败: {r.png_name}]", styles["body"]
                    ))
            else:
                elements.append(Paragraph(
                    f"[影像文件不存在: {r.png_path}]", styles["body"]
                ))

            # PNG 完整文件名
            elements.append(Paragraph(
                f"PNG 文件：{r.png_name}", styles["img_caption"]
            ))

            # 详细异常信息表格
            detail_rows = []
            detail_rows.append(["DICOM 原始文件", r.dicom_name])
            slice_info_parts = []
            if hasattr(r, 'slice_index') and r.slice_index:
                slice_info_parts.append(f"第{r.slice_index}层")
            if hasattr(r, 'slice_location') and r.slice_location:
                slice_info_parts.append(f"SliceLocation={r.slice_location}mm")
            if slice_info_parts:
                detail_rows.append(["层面位置", ", ".join(slice_info_parts)])
            detail_rows.append(["检视结论", r.conclusion.value])
            detail_rows.append(["置信度", r.confidence or "—"])

            if r.location:
                detail_rows.append(["异常位置", r.location])
            if r.size_mm:
                detail_rows.append(["病灶大小", f"{r.size_mm} mm"])
            if r.abnormality_desc:
                detail_rows.append(["异常描述", r.abnormality_desc])
            if r.lung_rads:
                detail_rows.append(["Lung-RADS 分类", r.lung_rads])
            elif hasattr(r, 'classification_system') and r.classification_system and hasattr(r, 'classification_value') and r.classification_value:
                detail_rows.append([f"{r.classification_system} 分类", r.classification_value])
            if r.recommendation:
                detail_rows.append(["随访建议", r.recommendation])
            if r.details:
                detail_rows.append(["影像整体描述", r.details])

            detail_table = Table(detail_rows, colWidths=[3.5 * cm, 13.5 * cm])
            detail_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#fdecea")),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#922b21")),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e6b0aa")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            elements.append(detail_table)
            elements.append(Spacer(1, 16))

        # ---- 被省略层面的简明汇总表 ----
        if omitted_results:
            elements.append(Paragraph(
                f"<b>其余 {len(omitted_results)} 个异常层面（已省略影像展示）：</b>",
                styles["label"]
            ))

            omit_header = ["序号", "DICOM 文件", "位置", "异常描述", "置信度"]
            omit_rows = [omit_header]
            for oi, r in enumerate(omitted_results, 1):
                loc = getattr(r, 'location', '') or '—'
                desc = getattr(r, 'abnormality_desc', '') or '—'
                conf = getattr(r, 'confidence', '') or '—'
                # 截断过长文本
                if len(desc) > 30:
                    desc = desc[:28] + "…"
                if len(loc) > 25:
                    loc = loc[:23] + "…"
                omit_rows.append([str(oi), r.dicom_name, loc, desc, conf])

            omit_col_widths = [1.2 * cm, 4 * cm, 4 * cm, 5.5 * cm, 2.3 * cm]
            omit_table = Table(omit_rows, colWidths=omit_col_widths)
            omit_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (4, 0), (4, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            elements.append(omit_table)
            elements.append(Spacer(1, 8))

            elements.append(Paragraph(
                f"注：完整异常影像请查阅输出目录下的 PNG 文件。",
                styles["body"]
            ))
            elements.append(Spacer(1, 12))

        return elements

    @staticmethod
    def _classification_followup_advice(classification_system: str, classification_value: str) -> str:
        """根据分级系统和分级值返回具体随访建议文本。"""
        val = (classification_value or "").strip().upper()

        if classification_system == "LI-RADS":
            if "LR-1" in val or val == "1":
                return "，明确良性，无需特殊随访。"
            elif "LR-2" in val or val == "2":
                return "，可能良性，建议常规随访（6-12个月超声或增强CT/MRI）。"
            elif "LR-3" in val or val == "3":
                return "，性质不确定，建议3-6个月增强CT或MRI密切随访。"
            elif "LR-4" in val or val == "4":
                return "，可能恶性（HCC），建议多学科会诊，考虑活检或影像密切随访。"
            elif "LR-5" in val or val == "5":
                return "，高度提示HCC，建议立即肝胆外科或介入科就诊，制定治疗方案。"
            elif "LR-M" in val or val == "M":
                return "，可能恶性（非HCC类型），建议活检明确病理，多学科会诊。"
            elif "LR-TIV" in val or "TIV" in val:
                return "，肿瘤侵犯静脉，建议立即肝胆外科就诊。"
            else:
                return "，建议结合临床及增强影像进一步评估。"

        elif classification_system == "Fazekas":
            if val in ("0", "0级"):
                return "，白质未见异常信号，无需特殊处理。"
            elif val in ("1", "1级", "轻度"):
                return "，轻度白质病变，建议控制血管危险因素（血压、血糖、血脂），12个月复查。"
            elif val in ("2", "2级", "中度"):
                return "，中度白质病变，建议神经内科就诊，评估认知功能，积极控制血管危险因素，6-12个月复查。"
            elif val in ("3", "3级", "重度"):
                return "，重度白质病变，建议尽快神经内科就诊，全面评估认知功能及脑血管状况。"
            else:
                return "，建议结合临床评估白质病变程度。"

        else:
            return "，建议结合临床随访。"

    def _build_diagnosis(self, styles: dict, review_results: list) -> list:
        """诊断意见 — 按聚合结节输出"""
        abnormal_results = [r for r in review_results if r.conclusion.value == "异常"]
        total = len(review_results)
        unrecog = sum(1 for r in review_results if r.conclusion.value == "无法识别")

        elements = []

        # 章节标题编号根据是否有异常影像区来定
        section_num = "三" if abnormal_results else "二"
        elements.extend(self._section_heading(f"{section_num}、诊断意见", styles))

        if abnormal_results:
            nodules = self._aggregate_nodules(abnormal_results)

            for i, nod in enumerate(nodules, 1):
                r = nod["representative"]
                diag = f"{i}、"
                parts = []
                if nod["location"]:
                    parts.append(nod["location"])
                if r.abnormality_desc:
                    parts.append(r.abnormality_desc)
                if r.size_mm:
                    parts.append(f"大小约 {r.size_mm}mm")

                diag += "，".join(parts) if parts else f"影像 {r.dicom_name} 疑似异常"

                # 层面范围备注
                if nod["slice_count"] > 1:
                    diag += f"（连续 {nod['slice_count']} 个层面可见）"

                # 随访建议
                if r.recommendation:
                    diag += f"，{r.recommendation}"
                elif r.lung_rads:
                    diag += f"（Lung-RADS {r.lung_rads}）"
                    if "1" in r.lung_rads:
                        diag += "，无需特殊随访。"
                    elif "2" in r.lung_rads:
                        diag += "，考虑良性，建议12个月复查。"
                    elif "3" in r.lung_rads:
                        diag += "，建议6个月复查。"
                    elif "4" in r.lung_rads:
                        diag += "，建议进一步检查或活检。"
                    else:
                        diag += "。"
                elif hasattr(r, 'classification_system') and r.classification_system and hasattr(r, 'classification_value') and r.classification_value:
                    diag += f"（{r.classification_system} {r.classification_value}）"
                    diag += self._classification_followup_advice(r.classification_system, r.classification_value)
                else:
                    diag += "，建议结合临床随访。"

                elements.append(Paragraph(f"　　{diag}", styles["diagnosis"]))

            # 附见
            if unrecog > 0:
                elements.append(Paragraph(
                    f"　　附见：{unrecog} 层/张影像未能自动识别，建议人工复核。",
                    styles["body"]
                ))
        else:
            if unrecog == total:
                elements.append(Paragraph(
                    "　　AI 分析尚未完成，暂无诊断意见。",
                    styles["diagnosis"]
                ))
            else:
                elements.append(Paragraph(
                    "　　未见明显异常。",
                    styles["body"]
                ))

        elements.append(Spacer(1, 12))
        return elements

    def _build_classification_reference_table(self, styles: dict) -> list:
        """
        分级系统参考表（根据影像类型动态选择）。
        位于诊断意见之后、免责声明之前。
        支持: Lung-RADS / LI-RADS / Fazekas
        """
        profile = getattr(self, '_imaging_profile', None)
        classification_system = ""

        if profile:
            classification_system = getattr(profile, 'classification_system', '') or ''

        # 无分级系统时不展示
        if not classification_system:
            return []

        elements = []
        font = self._font_mgr.font_name
        section_num = "四"  # 默认编号

        if classification_system == "Lung-RADS":
            elements.extend(self._section_heading(f"{section_num}、Lung-RADS 分类参考", styles))
            header = ["分类", "含义", "处理建议"]
            rows = [
                header,
                ["1类", "阴性（无肺结节）", "继续每年低剂量CT筛查"],
                ["2类", "良性表现（实性<6mm / GGO<30mm）", "继续每年低剂量CT筛查"],
                ["3类", "可能良性（实性 6-8mm / GGO≥30mm）", "6个月后低剂量CT随访"],
                ["4A类", "可疑（实性 8-15mm / 新发GGO）", "3个月后低剂量CT随访或PET-CT"],
                ["4B类", "高度可疑（实性>15mm）", "胸外科/呼吸科就诊，组织活检"],
                ["4X类", "可疑 + 恶性征象（毛刺/分叶）", "立即活检，建议MDT会诊"],
            ]
            col_widths = [2.5 * cm, 7.5 * cm, 7 * cm]

        elif classification_system == "LI-RADS":
            elements.extend(self._section_heading(f"{section_num}、LI-RADS 分类参考", styles))
            header = ["分类", "含义", "处理建议"]
            rows = [
                header,
                ["LR-1", "明确良性（囊肿、血管瘤等）", "无需特殊随访"],
                ["LR-2", "可能良性", "常规随访"],
                ["LR-3", "中间概率恶性", "增强CT/MRI进一步评估（3-6个月）"],
                ["LR-4", "可能肝细胞癌（HCC）", "MDT会诊，考虑活检或治疗"],
                ["LR-5", "明确肝细胞癌（HCC）", "立即治疗（无需活检确认）"],
                ["LR-M", "可能或明确非HCC型恶性", "活检明确病理类型"],
                ["LR-TIV", "肿瘤静脉侵犯", "紧急评估治疗方案"],
            ]
            col_widths = [2.5 * cm, 7 * cm, 7.5 * cm]

        elif classification_system == "Fazekas":
            elements.extend(self._section_heading(f"{section_num}、Fazekas 白质病变分级参考", styles))
            header = ["分级", "脑室旁白质", "深部白质", "临床意义"]
            rows = [
                header,
                ["0级", "无病灶", "无病灶", "正常"],
                ["1级", "点状或帽状高信号", "点状高信号", "轻度缺血性改变，常见于中老年"],
                ["2级", "光滑的晕圈状高信号", "开始融合的高信号", "中度缺血性白质病变，需控制危险因素"],
                ["3级", "不规则高信号延伸至深部白质", "大片融合的高信号", "重度缺血性白质病变，认知障碍风险增高"],
            ]
            col_widths = [1.8 * cm, 5 * cm, 5 * cm, 5.2 * cm]

        else:
            # 未知分级系统，不展示
            return []

        table = Table(rows, colWidths=col_widths)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            # 表头样式
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            # 奇数行浅灰背景
            *[("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F9F9F9"))
              for i in range(2, len(rows), 2)],
            # 网格和内边距
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#bdc3c7")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))
        return elements

    def _build_cross_validation_section(self, styles: dict) -> list:
        """
        CAD vs AI 交叉验证告警章节（v2.4.8+）。

        仅当存在告警时才生成此章节；全部通过则不显示。
        """
        elements = []
        cv = self._cross_validation
        if not cv or cv.get("ok", True):
            return elements

        alerts = cv.get("alerts", [])
        if not alerts:
            return elements

        font = self._font_mgr.font_name

        # 节标题
        elements.extend(self._section_heading("六、CAD 交叉验证告警", styles))

        # 摘要文字
        summary = cv.get("summary", "")
        if summary:
            elements.append(Paragraph(summary, styles["body"]))
            elements.append(Spacer(1, 6))

        # 告警表格
        header = ["严重度", "类型", "候选", "评分", "z-range", "说明"]
        rows = [header]

        type_labels = {
            "missed_candidate": "遗漏候选",
            "described_but_not_reported": "描述未报",
            "no_coverage": "无覆盖",
        }

        for alert in alerts:
            rows.append([
                alert.get("severity", "?"),
                type_labels.get(alert.get("type", ""), alert.get("type", "")),
                f"{alert.get('candidate_type', '').upper()}#{alert.get('candidate_rank', '?')}",
                f"{alert.get('nodule_score', 0):.3f}",
                alert.get("z_range", "?"),
                Paragraph(alert.get("message", ""), styles["cell"]),
            ])

        col_widths = [1.5 * cm, 2 * cm, 2 * cm, 1.5 * cm, 2 * cm, 8 * cm]
        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            # 表头样式
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e74c3c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            # HIGH 行标红
            *[("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FDEDEC"))
              for i, alert in enumerate(alerts, 1)
              if alert.get("severity") == "HIGH"],
            # MEDIUM 行标黄
            *[("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FEF9E7"))
              for i, alert in enumerate(alerts, 1)
              if alert.get("severity") == "MEDIUM"],
            # 网格
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#bdc3c7")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 6))

        # 提示文字
        elements.append(Paragraph(
            "※ 以上告警表示 CAD 算法检测到的高置信度候选在 AI 阅片结论中未被标记为异常，"
            "建议对这些区域进行人工复核。",
            styles["disclaimer"],
        ))
        elements.append(Spacer(1, 12))

        return elements

    def _build_disclaimer(self, styles: dict) -> list:
        """免责声明 + 报告生成时间戳"""
        elements = []

        # 分隔线
        line_table = Table([[""]],colWidths=[17 * cm])
        line_table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#bdc3c7")),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 8))

        elements.append(
            Paragraph(f"※ {DISCLAIMER_TEXT}", styles["disclaimer"])
        )

        # 报告生成时间戳
        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        version = getattr(self, '_version', 'unknown')
        elements.append(
            Paragraph(
                f"报告生成时间: {gen_time} | Powered by DICOM Doctor AI Skill v{version}",
                styles["timestamp"]
            )
        )
        return elements
    # ================================================================
    # 辅助方法
    # ================================================================

    def _section_heading(self, title: str, styles: dict) -> list:
        """
        生成统一的节标题：中文编号 + 加粗文字 + 底部细线分隔 + Spacer。
        用于"一、检查所见""二、异常影像详情"等标题。
        """
        elements = []
        elements.append(Paragraph(title, styles["section"]))
        # 底部细分隔线
        line_table = Table([[""]], colWidths=[17 * cm])
        line_table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#1a5276")),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 6))
        return elements

    # 解剖位置到影像区域的映射（归一化坐标 0~1）
    # 胸部 CT 轴位图：x=0 为患者右侧，x=1 为患者左侧；y=0 为前方，y=1 为后方
    _ANATOMY_REGION_MAP = {
        # 右肺区域（影像左侧，因为 CT 左右镜像）
        "右肺上叶": (0.25, 0.30),
        "右肺中叶": (0.30, 0.45),
        "右肺中叶内段": (0.35, 0.45),
        "右肺下叶": (0.30, 0.60),
        "右肺下叶前基底段": (0.30, 0.55),
        "右肺下叶背段": (0.25, 0.65),
        # 左肺区域（影像右侧）
        "左肺上叶": (0.75, 0.30),
        "左肺上叶下舌段": (0.72, 0.42),
        "左肺舌段": (0.72, 0.42),
        "左肺下叶": (0.70, 0.60),
        "左肺下叶背段": (0.75, 0.65),
        # 纵隔
        "纵隔": (0.50, 0.40),
        # 默认中心
        "default": (0.50, 0.50),
    }

    def _annotate_abnormal_image(self, png_path: str, review_result,
                                  finding_index: int) -> Optional[str]:
        """
        在异常影像上绘制黄色标注（矩形框或圆圈），生成带标注的副本。

        优先使用 AI 返回的 bounding_boxes 坐标绘制精确黄色矩形框，
        无 bounding_boxes 时回退到解剖位置文本映射逻辑。

        Args:
            png_path: 原始 PNG 文件路径
            review_result: ReviewResult 对象（包含 bounding_boxes 和 location）
            finding_index: 发现编号（用于标注序号）

        Returns:
            带标注的副本文件路径，失败时返回 None
        """
        try:
            from PIL import Image as PILImage, ImageDraw, ImageFont
        except ImportError:
            logger.warning("Pillow 未安装，无法绘制异常标注")
            return None

        # ---- 标注颜色配置（黄色，用户偏好） ----
        ANNOT_COLOR = (255, 255, 0, 220)      # 黄色框/圆
        ANNOT_BADGE_BG = (255, 255, 0, 220)   # 编号背景
        ANNOT_BADGE_FG = (0, 0, 0, 255)       # 编号文字（黑色，黄底白字不清晰）

        try:
            img = PILImage.open(png_path).convert("RGBA")
            w, h = img.size

            # 创建半透明覆盖层
            overlay = PILImage.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # 获取字体（跨平台兼容）
            font = self._get_annotation_font(w, h)

            # 优先使用 bounding_boxes 坐标绘制精确黄色矩形框
            bboxes = getattr(review_result, 'bounding_boxes', [])
            if bboxes:
                for box_idx, bbox in enumerate(bboxes, 1):
                    x = bbox.get("x", 0)
                    y = bbox.get("y", 0)
                    bw = bbox.get("width", 0.05)
                    bh = bbox.get("height", 0.05)

                    # 转换为像素坐标
                    x1 = int(x * w)
                    y1 = int(y * h)
                    x2 = int((x + bw) * w)
                    y2 = int((y + bh) * h)

                    # 绘制 3px 黄色矩形框
                    draw.rectangle([x1, y1, x2, y2], outline=ANNOT_COLOR, width=3)

                    # 绘制编号文字（矩形框右上角）
                    number_text = f"{finding_index}.{box_idx}"
                    text_x = x2 + 2
                    text_y = y1 - 2
                    text_bbox = draw.textbbox((text_x, text_y), number_text, font=font)
                    draw.rectangle(
                        [text_bbox[0] - 2, text_bbox[1] - 2,
                         text_bbox[2] + 2, text_bbox[3] + 2],
                        fill=ANNOT_BADGE_BG
                    )
                    draw.text((text_x, text_y), number_text, fill=ANNOT_BADGE_FG, font=font)
            else:
                # 回退：使用解剖位置文本映射绘制圆圈
                location = getattr(review_result, 'location', '')
                regions = self._parse_location_to_regions(location)

                for i, (cx_ratio, cy_ratio) in enumerate(regions):
                    cx = int(cx_ratio * w)
                    cy = int(cy_ratio * h)
                    radius = int(min(w, h) * 0.08)

                    bbox_circle = [
                        cx - radius, cy - radius,
                        cx + radius, cy + radius
                    ]
                    draw.ellipse(bbox_circle, outline=ANNOT_COLOR, width=3)

                    number_text = f"{finding_index}"
                    text_x = cx + radius - 5
                    text_y = cy - radius - 5
                    text_bbox = draw.textbbox((text_x, text_y), number_text, font=font)
                    draw.rectangle(
                        [text_bbox[0] - 2, text_bbox[1] - 2,
                         text_bbox[2] + 2, text_bbox[3] + 2],
                        fill=ANNOT_BADGE_BG
                    )
                    draw.text((text_x, text_y), number_text, fill=ANNOT_BADGE_FG, font=font)

            # 合并覆盖层
            annotated = PILImage.alpha_composite(img, overlay)
            annotated = annotated.convert("RGB")

            annotated_path = png_path.replace(".png", "_annotated.png")
            annotated.save(annotated_path)
            logger.info(f"已生成标注副本: {os.path.basename(annotated_path)}")
            return annotated_path

        except Exception as e:
            logger.warning(f"绘制异常标注失败（不影响报告生成）: {e}")
            return None

    @staticmethod
    def _get_annotation_font(img_width: int, img_height: int):
        """跨平台获取标注字体（macOS / Linux / Windows）"""
        from PIL import ImageFont
        import platform

        font_size = max(16, int(min(img_width, img_height) * 0.04))

        # 按平台优先级查找字体
        candidates = []
        system = platform.system()
        if system == "Darwin":  # macOS
            candidates = [
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/SFNSMono.ttf",
                "/Library/Fonts/Arial.ttf",
            ]
        elif system == "Linux":
            candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ]
        else:  # Windows
            candidates = [
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/consola.ttf",
            ]

        for path in candidates:
            try:
                if os.path.exists(path):
                    return ImageFont.truetype(path, font_size)
            except Exception:
                continue

        return ImageFont.load_default()

    def _parse_location_to_regions(self, location: str) -> list:
        """
        将解剖位置描述解析为影像上的归一化坐标列表。

        Args:
            location: 异常位置描述，多个位置用分号分隔

        Returns:
            [(cx_ratio, cy_ratio), ...] 归一化坐标列表
        """
        if not location:
            return [self._ANATOMY_REGION_MAP["default"]]

        regions = []
        # 按分号分割多个位置
        parts = [p.strip() for p in location.replace("；", ";").split(";") if p.strip()]

        for part in parts:
            matched = False
            # 从最长的键开始匹配（优先精确匹配）
            sorted_keys = sorted(
                self._ANATOMY_REGION_MAP.keys(),
                key=len, reverse=True
            )
            for key in sorted_keys:
                if key == "default":
                    continue
                if key in part:
                    regions.append(self._ANATOMY_REGION_MAP[key])
                    matched = True
                    break
            if not matched:
                regions.append(self._ANATOMY_REGION_MAP["default"])

        return regions if regions else [self._ANATOMY_REGION_MAP["default"]]

    def _find_alternate_window_image(self, png_path: str, window_type: str) -> Optional[str]:
        """
        查找异常影像对应的其他窗口版本图片。

        查找策略（按优先级）：
        1. 在同级目录的兄弟窗口子目录中查找同名文件（如 ../ggo/同名.png）
        2. 查找文件名中包含 _ggo / _mediastinum 后缀的文件

        Args:
            png_path: 原始 PNG 文件路径（通常是肺窗）
            window_type: 目标窗口类型（"ggo" / "mediastinum"）

        Returns:
            对应窗口版本的文件路径，未找到返回 None
        """
        if not os.path.exists(png_path):
            return None

        basename = os.path.basename(png_path)
        parent_dir = os.path.dirname(png_path)
        grandparent_dir = os.path.dirname(parent_dir)

        # 策略1：在兄弟子目录中查找（如 lung/ → ggo/）
        # 常见目录结构：png/lung/xxx.png → png/ggo/xxx.png
        sibling_dir = os.path.join(grandparent_dir, window_type)
        if os.path.isdir(sibling_dir):
            sibling_path = os.path.join(sibling_dir, basename)
            if os.path.exists(sibling_path):
                return sibling_path

        # 策略2：在同目录中查找带窗口后缀的文件
        name_no_ext = os.path.splitext(basename)[0]
        ext = os.path.splitext(basename)[1]

        # 尝试替换现有窗口后缀
        for existing_suffix in ["_lung", "_肺窗"]:
            if existing_suffix in name_no_ext:
                alt_name = name_no_ext.replace(existing_suffix, f"_{window_type}") + ext
                alt_path = os.path.join(parent_dir, alt_name)
                if os.path.exists(alt_path):
                    return alt_path

        # 尝试添加窗口后缀
        alt_name = f"{name_no_ext}_{window_type}{ext}"
        alt_path = os.path.join(parent_dir, alt_name)
        if os.path.exists(alt_path):
            return alt_path

        return None

    def _build_timing_detail(self, styles: dict) -> list:
        """
        构建各阶段耗时明细小表格。

        在检查信息表下方展示 4 行耗时明细：
        DICOM 解析/PNG 转换 | AI 阅片 | PDF 生成，每行含耗时和占比。
        """
        timings = getattr(self, '_timings', None)
        if not timings or timings.total_seconds <= 0:
            return []

        elements = []
        font = self._font_mgr.font_name

        elements.append(Paragraph("阶段耗时明细", styles["label"]))

        total_secs = timings.total_seconds
        stages = [
            ["DICOM/PNG 转换", timings.png_convert_seconds],
            ["AI 阅片", timings.ai_review_seconds],
            ["PDF 生成", timings.pdf_generate_seconds],
        ]

        data = [["阶段", "耗时（秒）", "占比"]]
        for stage_name, stage_secs in stages:
            pct = (stage_secs / total_secs * 100) if total_secs > 0 else 0
            data.append([stage_name, f"{stage_secs:.1f}", f"{pct:.1f}%"])

        col_widths = [5 * cm, 4 * cm, 3 * cm]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2f8")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#bdc3c7")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))
        return elements

    # ================================================================
    # Markdown 报告生成
    # ================================================================

    def _generate_markdown(self, review_results: list, input_path: str,
                           pdf_path: str) -> str:
        """
        生成 Markdown 格式的阅片报告，与 PDF 报告内容一致。

        Markdown 文件与 PDF 放在同一目录下，文件名相同但后缀为 .md。

        Args:
            review_results: ReviewResult 对象列表
            input_path: 原始输入文件路径
            pdf_path: 已生成的 PDF 文件路径（用于推导 .md 路径）

        Returns:
            生成的 Markdown 文件路径
        """
        md_path = pdf_path.replace(".pdf", ".md")

        total = len(review_results)
        normal = sum(1 for r in review_results if r.conclusion.value == "正常")
        abnormal = sum(1 for r in review_results if r.conclusion.value == "异常")
        unrecog = sum(1 for r in review_results if r.conclusion.value == "无法识别")

        profile = getattr(self, '_imaging_profile', None)
        body_part = profile.display_name if profile else self._infer_body_part(review_results)

        # 窗口类型显示
        if profile and profile.window_presets:
            window_parts = []
            for wname, (wc, ww) in profile.window_presets.items():
                window_parts.append(f"{wname} (WC={wc}, WW={ww})")
            window_name = " + ".join(window_parts) if window_parts else "DICOM 自带窗位"
        elif profile:
            window_name = "DICOM 自带窗位"
        else:
            window_display = {
                "lung": "肺窗 (WC=-600, WW=1500)",
                "mediastinum": "纵隔窗 (WC=40, WW=400)",
                "bone": "骨窗 (WC=400, WW=1800)",
                "soft_tissue": "软组织窗 (WC=50, WW=350)",
                "all": "全窗口 (肺窗+纵隔窗+骨窗+软组织窗)",
            }
            wtype = getattr(self, '_window_type', 'lung') or 'lung'
            window_name = window_display.get(wtype, f"{wtype}")

        # 图像增强方式
        min_sz = getattr(self, '_min_size', 1024) or 1024
        enhance_on = getattr(self, '_enhance', False)
        if enhance_on:
            enhance_desc = f"Real-ESRGAN {getattr(self, '_enhance_scale', 2)}x 超分"
        elif min_sz > 0:
            enhance_desc = f"Lanczos 高质量插值放大 (≥{min_sz}px)"
        else:
            enhance_desc = "原始分辨率"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 根据影像类型动态生成标题
        if profile:
            title_text = f"{profile.display_name} AI 辅助阅片报告"
        else:
            title_text = "AI 辅助影像检查报告"

        lines = []
        lines.append(f"# {title_text}")
        lines.append(f"")
        lines.append(f"**报告日期：{now}**")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

        # 检查信息表
        lines.append(f"## 检查信息")
        lines.append(f"")
        lines.append(f"| 项目 | 内容 | 项目 | 内容 |")
        lines.append(f"| --- | --- | --- | --- |")

        # 患者信息（脱敏后）
        pinfo = getattr(self, '_patient_info', {})
        if pinfo:
            lines.append(f"| 患者姓名 | {pinfo.get('patient_name', '—')} | 性别 | {pinfo.get('patient_sex', '—')} |")
            if pinfo.get('patient_id') or pinfo.get('study_date'):
                lines.append(f"| 患者编号 | {pinfo.get('patient_id', '—')} | 检查日期 | {pinfo.get('study_date', '—')} |")
            if pinfo.get('institution'):
                lines.append(f"| 检查机构 | {pinfo.get('institution')} | | |")

        lines.append(f"| 检查项目 | {body_part} | 检查日期 | {datetime.now().strftime('%Y-%m-%d')} |")
        lines.append(f"| 报告日期 | {datetime.now().strftime('%Y-%m-%d %H:%M')} | 影像数量 | {total} 层/张 |")
        lines.append(f"| 窗口类型 | {window_name} | 图像增强 | {enhance_desc} |")
        lines.append(f"| 影像类型 | {profile.display_name if profile else '胸部CT（推断）'} | 重建方式 | 轴位 + 冠状位 + 定位像 |")
        lines.append(f"| Skill 版本 | {getattr(self, '_version', 'unknown')} | AI 检视总数 | {total} |")
        lines.append(f"| 发现异常 | {abnormal} 张 | 未见异常 | {normal} 张 |")
        lines.append(f"| 无法识别 | {unrecog} 张 | | |")

        model_name = getattr(self, '_model_name', None)
        if model_name:
            lines.append(f"| 阅片大模型 | {model_name} | | |")

        task_start = getattr(self, '_task_start_time', None)
        task_end = getattr(self, '_task_end_time', None)
        timings = getattr(self, '_timings', None)

        if task_start:
            lines.append(f"| 任务开始时间 | {task_start.strftime('%Y-%m-%d %H:%M:%S')} | | |")
        if task_end:
            lines.append(f"| 任务完成时间 | {task_end.strftime('%Y-%m-%d %H:%M:%S')} | | |")
        if timings:
            total_secs = timings.total_seconds
            if total_secs >= 60:
                total_time_str = f"{int(total_secs // 60)}分{int(total_secs % 60)}秒"
            else:
                total_time_str = f"{total_secs:.1f}秒"
            lines.append(f"| 总耗时 | {total_time_str} | | |")
            lines.append(f"| DICOM 文件数 | {timings.dicom_file_count} | PNG 文件数 | {timings.png_file_count} |")

        lines.append(f"")

        # 阶段耗时明细
        if timings and timings.total_seconds > 0:
            lines.append(f"### 阶段耗时明细")
            lines.append(f"")
            lines.append(f"| 阶段 | 耗时（秒） | 占比 |")
            lines.append(f"| --- | --- | --- |")
            total_secs = timings.total_seconds
            stages = [
                ("DICOM/PNG 转换", timings.png_convert_seconds),
                ("AI 阅片", timings.ai_review_seconds),
                ("PDF 生成", timings.pdf_generate_seconds),
            ]
            for stage_name, stage_secs in stages:
                pct = (stage_secs / total_secs * 100) if total_secs > 0 else 0
                lines.append(f"| {stage_name} | {stage_secs:.1f} | {pct:.1f}% |")
            lines.append(f"")

        # 检查所见
        abnormal_results = [r for r in review_results if r.conclusion.value == "异常"]

        lines.append(f"## 一、检查所见")
        lines.append(f"")

        if abnormal_results:
            # --- 聚合结节汇总 ---
            nodules = self._aggregate_nodules(abnormal_results)

            lines.append(f"**AI 共检出 {len(nodules)} 个独立结节（涉及 {len(abnormal_results)} 个异常层面）：**")
            lines.append(f"")
            lines.append(f"| 序号 | 位置 | 类型 | 大小 | 出现层面 | 分级 | 置信度 |")
            lines.append(f"| --- | --- | --- | --- | --- | --- | --- |")

            for idx, nod in enumerate(nodules, 1):
                rep = nod["representative"]
                desc = getattr(rep, 'abnormality_desc', '') or ''
                if 'GGO' in desc or '磨玻璃' in desc:
                    nodule_type = "GGO"
                elif '实性' in desc:
                    nodule_type = "实性"
                else:
                    nodule_type = "—"

                size = getattr(rep, 'size_mm', '') or '—'
                if size and 'mm' not in size:
                    size = f"{size}mm"

                lung_rads = getattr(rep, 'lung_rads', '') or ''
                if not lung_rads:
                    if hasattr(rep, 'classification_system') and rep.classification_system:
                        lung_rads = f"{rep.classification_system} {getattr(rep, 'classification_value', '')}"
                    else:
                        lung_rads = "—"

                confidence = getattr(rep, 'confidence', '') or '—'

                lines.append(
                    f"| {idx} | {nod['location']} | {nodule_type} | {size} "
                    f"| {nod['slice_range']} ({nod['slice_count']}层) | {lung_rads} | {confidence} |"
                )

            lines.append(f"")

            # --- 逐层异常明细（保留原有逻辑） ---
            lines.append(f"### 逐层异常明细（{len(abnormal_results)} 个异常层面）")
            lines.append(f"")

            for i, r in enumerate(abnormal_results, 1):
                parts = []
                if r.location:
                    parts.append(r.location)
                if r.abnormality_desc:
                    parts.append(r.abnormality_desc)
                if r.size_mm:
                    parts.append(f"大小约 {r.size_mm}mm")
                if r.lung_rads:
                    parts.append(f"Lung-RADS {r.lung_rads}")
                elif hasattr(r, 'classification_system') and r.classification_system and hasattr(r, 'classification_value') and r.classification_value:
                    parts.append(f"{r.classification_system} {r.classification_value}")
                finding_text = "，".join(parts) + "。" if parts else f"影像 {r.dicom_name} 检测到疑似异常。"
                lines.append(f"**发现 {i}：**{finding_text}")
                lines.append(f"")
            if normal > 0:
                lines.append(f"其余 {normal} 层/张影像未见明显异常征象。")
                lines.append(f"")
            if unrecog > 0:
                lines.append(f"另有 {unrecog} 层/张影像未能自动识别，建议人工复核。")
                lines.append(f"")
        else:
            if unrecog == total:
                lines.append(f"所有影像尚未完成 AI 分析（状态为'待检视'）。请确保宿主 AI 工具已逐张执行阅片分析。")
            else:
                lines.append(f"共检视 {total} 层/张影像，未见明显异常征象。")
                lines.append(f"")
                lines.append(f"双肺纹理清晰，走行自然。气管及主要支气管通畅。纵隔内未见明显肿大淋巴结。")
            lines.append(f"")

        # 异常影像详情
        if abnormal_results:
            lines.append(f"## 二、异常影像详情（共 {len(abnormal_results)} 张）")
            lines.append(f"")

            for idx, r in enumerate(abnormal_results, 1):
                lines.append(f"### 异常影像 {idx}：{r.dicom_name}")
                lines.append(f"")

                # 嵌入影像（使用带标注的副本，如有）
                annotated_path = r.png_path.replace(".png", "_annotated.png")
                if os.path.exists(annotated_path):
                    lines.append(f"![异常影像 {idx}]({annotated_path})")
                elif os.path.exists(r.png_path):
                    lines.append(f"![异常影像 {idx}]({r.png_path})")
                lines.append(f"")

                lines.append(f"| 项目 | 内容 |")
                lines.append(f"| --- | --- |")
                lines.append(f"| DICOM 原始文件 | {r.dicom_name} |")

                slice_info_parts = []
                if hasattr(r, 'slice_index') and r.slice_index:
                    slice_info_parts.append(f"第{r.slice_index}层")
                if hasattr(r, 'slice_location') and r.slice_location:
                    slice_info_parts.append(f"SliceLocation={r.slice_location}mm")
                if slice_info_parts:
                    slice_info_text = ", ".join(slice_info_parts)
                    lines.append(f"| 层面位置 | {slice_info_text} |")

                lines.append(f"| 检视结论 | {r.conclusion.value} |")
                lines.append(f"| 置信度 | {r.confidence or '—'} |")
                if r.location:
                    lines.append(f"| 异常位置 | {r.location} |")
                if r.size_mm:
                    lines.append(f"| 病灶大小 | {r.size_mm} mm |")
                if r.abnormality_desc:
                    lines.append(f"| 异常描述 | {r.abnormality_desc} |")
                if r.lung_rads:
                    lines.append(f"| Lung-RADS 分类 | {r.lung_rads} |")
                elif hasattr(r, 'classification_system') and r.classification_system and hasattr(r, 'classification_value') and r.classification_value:
                    lines.append(f"| {r.classification_system} 分类 | {r.classification_value} |")
                if r.recommendation:
                    lines.append(f"| 随访建议 | {r.recommendation} |")
                if r.details:
                    lines.append(f"| 影像整体描述 | {r.details} |")

                lines.append(f"")

        # 诊断意见
        section_num = "三" if abnormal_results else "二"
        lines.append(f"## {section_num}、诊断意见")
        lines.append(f"")

        if abnormal_results:
            nodules = self._aggregate_nodules(abnormal_results)

            for i, nod in enumerate(nodules, 1):
                r = nod["representative"]
                parts = []
                if nod["location"]:
                    parts.append(nod["location"])
                if r.abnormality_desc:
                    parts.append(r.abnormality_desc)
                if r.size_mm:
                    parts.append(f"大小约 {r.size_mm}mm")
                diag = "，".join(parts) if parts else f"影像 {r.dicom_name} 疑似异常"

                if nod["slice_count"] > 1:
                    diag += f"（连续 {nod['slice_count']} 个层面可见）"

                if r.recommendation:
                    diag += f"，{r.recommendation}"
                elif r.lung_rads:
                    diag += f"（Lung-RADS {r.lung_rads}）"
                    if "1" in r.lung_rads:
                        diag += "，无需特殊随访。"
                    elif "2" in r.lung_rads:
                        diag += "，考虑良性，建议12个月复查。"
                    elif "3" in r.lung_rads:
                        diag += "，建议6个月复查。"
                    elif "4" in r.lung_rads:
                        diag += "，建议进一步检查或活检。"
                    else:
                        diag += "。"
                elif hasattr(r, 'classification_system') and r.classification_system and hasattr(r, 'classification_value') and r.classification_value:
                    diag += f"（{r.classification_system} {r.classification_value}）"
                    diag += self._classification_followup_advice(r.classification_system, r.classification_value)
                else:
                    diag += "，建议结合临床随访。"

                lines.append(f"{i}、{diag}")
                lines.append(f"")

            if unrecog > 0:
                lines.append(f"附见：{unrecog} 层/张影像未能自动识别，建议人工复核。")
                lines.append(f"")
        else:
            if unrecog == total:
                lines.append(f"AI 分析尚未完成，暂无诊断意见。")
            else:
                lines.append(f"未见明显异常。")
            lines.append(f"")

        # 免责声明
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"※ {DISCLAIMER_TEXT}")
        lines.append(f"")
        lines.append(f"*DICOM Doctor v{getattr(self, '_version', 'unknown')}*")

        # 写入文件
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"Markdown 报告已生成: {md_path}")
        return md_path

    @staticmethod
    def _infer_body_part(review_results: list) -> str:
        """从检视结果推断检查部位"""
        all_text = " ".join(
            (getattr(r, "details", "") or "") + " " +
            (getattr(r, "abnormality_desc", "") or "")
            for r in review_results
        ).lower()

        if any(kw in all_text for kw in ["肺", "lung", "胸", "chest", "结节", "nodule", "ct"]):
            return "胸部CT平扫"
        elif any(kw in all_text for kw in ["头", "brain", "颅", "head"]):
            return "头颅CT/MRI"
        elif any(kw in all_text for kw in ["腹", "abdomen", "肝", "liver"]):
            return "腹部CT"
        elif any(kw in all_text for kw in ["骨", "bone", "脊", "spine"]):
            return "骨骼/脊柱检查"
        else:
            return "影像检查（AI 未能确定具体部位）"
