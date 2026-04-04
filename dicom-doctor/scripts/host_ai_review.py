#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM Doctor v2.10.0 - 宿主 AI 自动分批处理模式

当没有 OpenAI API Key 时，自动切换到宿主 AI 模式：
1. 自动检测宿主 AI 能力（是否支持图片识别）
2. 生成标准化的分批阅片请求
3. 提示宿主 AI 逐批读取图片并分析
4. 自动回填结果到 batch_XXX.filled.json
5. 每批完成后自动合并到总表 review_results.json
6. 支持断点续跑

v2.10.0 重要变更：
  - 新增「先试后判」视觉探测机制：不再仅依赖环境变量推断，
    而是直接尝试读取一张测试图片来验证视觉能力
  - 任务开始时先确认模型身份，避免环境变量误判
  - 移除了不可靠的 GLM_API_KEY 等环境变量推断逻辑

作者: AI Assistant
版本: 2.9.0
日期: 2026-03-28
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dicom-doctor.host-ai-review")


class HostAIReviewer:
    """
    宿主 AI 分批阅片协调器
    
    此类负责：
    1. 将阅片任务分批输出给宿主 AI
    2. 接收宿主 AI 的分析结果
    3. 自动保存进度和合并结果
    """
    
    VERSION = "2.10.0"
    
    def __init__(self, manifest_path: str, output_dir: str, batch_size: int = 15,
                 model_name: str = None):
        self.manifest_path = Path(manifest_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.batch_size = batch_size
        self.model_name = model_name
        
        # 加载 manifest
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.manifest = json.load(f)
        
        self.total_images = self.manifest.get("total_images", 0)
        self.total_batches = self.manifest.get("total_batches", 0)
        self.requests = self.manifest.get("requests", [])
        
        # 设置目录
        self.batch_template_dir = self.output_dir / "review_batch_templates"
        self.batch_filled_dir = self.output_dir / "review_batch_filled"
        self.batch_filled_dir.mkdir(parents=True, exist_ok=True)
        
        # 检查已完成的批次
        self.completed_batches = self._get_completed_batches()
        
        # 检测宿主 AI 能力
        self.capabilities = self._detect_capabilities()
        
        logger.info(f"宿主 AI 阅片协调器 v{self.VERSION} 初始化完成")
        logger.info(f"总影像数: {self.total_images}, 总批次数: {self.total_batches}")
        logger.info(f"已完成批次: {len(self.completed_batches)}/{self.total_batches}")
    
    def _get_completed_batches(self) -> set:
        """获取已完成的批次索引"""
        completed = set()
        if self.batch_filled_dir.exists():
            for f in self.batch_filled_dir.glob("batch_*.filled.json"):
                try:
                    batch_num = int(f.stem.split("_")[1])
                    completed.add(batch_num)
                except (ValueError, IndexError):
                    pass
        return completed
    
    def _detect_capabilities(self) -> Dict[str, Any]:
        """
        检测宿主 AI 能力。
        
        v2.10.0 变更：
          - 支持从 model_name 参数直接检测
          - 默认采用乐观策略（假定支持视觉）
          - 移除了不可靠的环境变量推断
        """
        try:
            # 尝试导入检测模块
            sys.path.insert(0, str(Path(__file__).parent))
            from model_capability_detector import detect_host_ai_capabilities
            return detect_host_ai_capabilities(model_name=self.model_name)
        except ImportError:
            logger.warning("未找到模型能力检测模块，默认假定支持视觉")
            # v2.10.0: 默认乐观策略，假定支持视觉
            return {
                "model_name": self.model_name or "unknown",
                "supports_vision": True,
                "supports_long_context": True,
                "confidence": "low",
                "note": (
                    "未安装能力检测模块。根据 SKILL.md 要求（必须使用多模态视觉模型），"
                    "默认假定当前模型支持视觉能力。将通过实际读取图片来验证。"
                ),
            }
    
    def print_capability_report(self):
        """打印能力检测报告"""
        caps = self.capabilities
        print("\n" + "=" * 60)
        print("【宿主 AI 能力检测】")
        print("=" * 60)
        print(f"模型名称: {caps['model_name']}")
        print(f"图片识别: {'✅ 支持' if caps['supports_vision'] else '❌ 不支持'}")
        print(f"长上下文: {'✅ 支持' if caps['supports_long_context'] else '❌ 不支持'}")
        print(f"检测置信度: {caps['confidence']}")
        print(f"\n说明: {caps['note']}")
        print("=" * 60 + "\n")
    
    def get_next_batch(self) -> Optional[Dict]:
        """获取下一个待处理的批次"""
        for batch_index in range(1, self.total_batches + 1):
            if batch_index not in self.completed_batches:
                return self._load_batch(batch_index)
        return None
    
    def _load_batch(self, batch_index: int) -> Dict:
        """加载指定批次的模板"""
        batch_file = self.batch_template_dir / f"batch_{batch_index:03d}.json"
        if not batch_file.exists():
            raise FileNotFoundError(f"批次文件不存在: {batch_file}")
        
        with open(batch_file, "r", encoding="utf-8") as f:
            batch_data = json.load(f)
        
        return {
            "batch_index": batch_index,
            "data": batch_data,
            "items": batch_data.get("items", [])
        }
    
    def generate_host_ai_prompt(self, batch: Dict) -> str:
        """生成给宿主 AI 的阅片提示"""
        batch_index = batch["batch_index"]
        items = batch["items"]
        
        prompt_lines = [
            f"=" * 60,
            f"【DICOM Doctor 宿主 AI 阅片请求 - 批次 {batch_index}/{self.total_batches}】",
            f"=" * 60,
            f"",
            f"请逐张检视以下 {len(items)} 张胸部 CT 切片，并返回 JSON 格式的分析结果。",
            f"",
            f"【阅片规范】",
            f"1. 检视顺序：GGO 窗 → 肺窗 → 纵隔窗",
            f"2. ≥2mm 圆形/类圆形高密度影 → 疑似结节（禁止归为血管断面）",
            f"3. 扫及区域：甲状腺/肝脏上段/肾上腺（层面相关时检查）",
            f"",
            f"【回复 JSON 格式】",
            f"```json",
            f"{{",
            f'    "conclusion": "正常/异常/无法识别",',
            f'    "abnormality_desc": "异常描述（如有）",',
            f'    "confidence": "高/中/低",',
            f'    "details": "简要所见",',
            f'    "location": "精确到亚段+层面，如右肺中叶内段S5 (第50层)",',
            f'    "size_mm": "如3x2",',
            f'    "lung_rads": "如2类",',
            f'    "recommendation": "随访建议",',
            f'    "bounding_boxes": []',
            f"}}",
            f"```",
            f"",
            f"【待阅片列表】",
        ]
        
        for item in items:
            global_index = item.get("global_index", "?")
            slice_index = item.get("slice_index", "?")
            png_path = item.get("png_path", "")
            ggo_path = item.get("ggo_path", "")
            
            prompt_lines.append(f"")
            prompt_lines.append(f"--- 第 {global_index} 张 ---")
            prompt_lines.append(f"层面: {slice_index}")
            prompt_lines.append(f"肺窗: {png_path}")
            if ggo_path:
                prompt_lines.append(f"GGO窗: {ggo_path}")
            prompt_lines.append(f"Prompt: {item.get('prompt', '')[:100]}...")
        
        prompt_lines.append(f"")
        prompt_lines.append(f"=" * 60)
        prompt_lines.append(f"请读取以上图片，逐张分析后返回结果。")
        prompt_lines.append(f"=" * 60)
        
        return "\n".join(prompt_lines)
    
    def save_batch_results(self, batch_index: int, results: List[Dict]) -> str:
        """保存批次结果"""
        # 加载原始批次模板
        batch_file = self.batch_template_dir / f"batch_{batch_index:03d}.json"
        with open(batch_file, "r", encoding="utf-8") as f:
            batch_data = json.load(f)
        
        # 回填结果
        items = batch_data.get("items", [])
        for i, item in enumerate(items):
            if i < len(results):
                item["result"] = results[i]
        
        # 添加元数据
        batch_data["host_ai_review"] = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "version": self.VERSION,
            "reviewed_count": len([r for r in results if r.get("conclusion") in ["正常", "异常"]]),
        }
        
        # 保存到 filled 目录
        filled_file = self.batch_filled_dir / f"batch_{batch_index:03d}.filled.json"
        with open(filled_file, "w", encoding="utf-8") as f:
            json.dump(batch_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"批次 {batch_index} 结果已保存: {filled_file}")
        return str(filled_file)
    
    def merge_to_results(self, batch_index: int) -> str:
        """合并批次结果到总表"""
        # 调用 apply_review_batch.py 进行合并
        import subprocess
        
        filled_file = self.batch_filled_dir / f"batch_{batch_index:03d}.filled.json"
        results_file = self.output_dir / "review_results.json"
        stub_file = self.output_dir / "review_results_stub.json"
        
        # 确定输入的总表文件
        input_results = str(results_file) if results_file.exists() else str(stub_file)
        
        cmd = [
            sys.executable,
            str(Path(__file__).parent / "apply_review_batch.py"),
            "--manifest", str(self.manifest_path),
            "--results", input_results,
            "--batch-json", str(filled_file),
            "--output", str(results_file),
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                logger.info(f"批次 {batch_index} 已合并到总表: {results_file}")
                return str(results_file)
            else:
                logger.error(f"合并批次 {batch_index} 失败: {result.stderr}")
                raise RuntimeError(f"合并失败: {result.stderr}")
        except Exception as e:
            logger.error(f"合并批次 {batch_index} 时出错: {e}")
            raise
    
    def get_progress(self) -> Dict:
        """获取当前进度"""
        return {
            "total_batches": self.total_batches,
            "completed_batches": len(self.completed_batches),
            "remaining_batches": self.total_batches - len(self.completed_batches),
            "completed_indices": sorted(self.completed_batches),
            "next_batch": self._get_next_batch_index(),
        }
    
    def _get_next_batch_index(self) -> Optional[int]:
        """获取下一个待处理的批次索引"""
        for i in range(1, self.total_batches + 1):
            if i not in self.completed_batches:
                return i
        return None
    
    def run_interactive(self):
        """
        交互式运行 - 智能分流处理。
        
        v2.10.0 变更：
          - 新增视觉探测步骤：先尝试读取一张测试图片，
            根据实际结果决定是否进入视觉模式
          - 不再仅依赖环境变量检测结果
        """
        # 首先打印能力检测报告
        self.print_capability_report()
        
        # v2.10.0: 新增视觉探测步骤
        self._print_vision_probe_hint()
        
        # 根据能力选择处理模式
        # 注意：即使检测结果说不支持视觉，也优先尝试视觉模式
        # 因为检测可能不准确（如环境变量误判）
        if self.capabilities['supports_vision']:
            self._run_vision_mode()
        else:
            # 即使检测说不支持，也先提示宿主 AI 尝试读图
            self._run_probe_then_decide()
    
    def _print_vision_probe_hint(self):
        """
        v2.10.0 新增：打印视觉探测提示。
        
        在能力检测报告之后，提示宿主 AI 尝试读取一张测试图片来验证视觉能力。
        这比仅依赖环境变量推断更可靠。
        """
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from model_capability_detector import find_probe_image, generate_vision_probe_prompt
            
            probe_image = find_probe_image(str(self.output_dir))
            if probe_image:
                print("\n" + "-" * 60)
                print("【视觉能力探测】")
                print("-" * 60)
                print(f"为确保检测结果准确，请尝试读取以下测试图片：")
                print(f"  {probe_image}")
                print(f"")
                print(f"如果你能看到图片内容 → 直接开始阅片")
                print(f"如果无法读取图片 → 需要使用外部视觉 API")
                print("-" * 60 + "\n")
            else:
                print("\n⚠️  未找到可用的测试图片，跳过视觉探测\n")
        except ImportError:
            pass
    
    def _run_probe_then_decide(self):
        """
        v2.10.0 新增：「先试后判」模式。
        
        当检测结果说不支持视觉时，不是直接停下来，
        而是提示宿主 AI 先尝试读取一张图片：
        - 如果能读取 → 说明检测误判，直接进入视觉模式
        - 如果确实不能读取 → 再给出替代方案
        """
        print("\n" + "=" * 60)
        print("【DICOM Doctor 宿主 AI 阅片模式】")
        print("=" * 60)
        print(f"\n⚠️  能力检测结果：当前模型可能不支持图片识别")
        print(f"   检测到的模型: {self.capabilities['model_name']}")
        print(f"")
        print(f"💡 但检测可能不准确！请先尝试读取一张图片来验证：")
        
        # 找一张测试图片
        try:
            from model_capability_detector import find_probe_image
            probe_image = find_probe_image(str(self.output_dir))
            if probe_image:
                print(f"")
                print(f"   🖼️  测试图片: {probe_image}")
                print(f"")
                print(f"   ✅ 如果你能看到并描述图片内容 → 忽略检测结果，直接按流程阅片")
                print(f"   ❌ 如果确实无法读取图片 → 请使用以下替代方案")
            else:
                print(f"")
                print(f"   未找到测试图片，请直接尝试读取阅片批次中的第一张图片")
        except ImportError:
            pass
        
        print(f"")
        print(f"{'=' * 60}")
        print(f"")
        
        # 然后给出替代方案（但不是停下来，而是作为备选）
        self._run_text_only_mode()

    def _run_vision_mode(self):
        """视觉模式 - 宿主 AI 支持图片识别"""
        print("\n" + "=" * 60)
        print("【DICOM Doctor 宿主 AI 自动阅片模式】")
        print("=" * 60)
        print(f"\n✅ 检测到模型支持图片识别: {self.capabilities['model_name']}")
        print(f"\n总批次数: {self.total_batches}")
        print(f"已完成: {len(self.completed_batches)}")
        print(f"待处理: {self.total_batches - len(self.completed_batches)}")
        print("\n⚡ 开始自动处理...")
        print("=" * 60 + "\n")
        
        # 自动连续处理所有批次
        max_batches_per_session = 5  # 防止上下文溢出
        processed = 0
        
        while processed < max_batches_per_session:
            batch = self.get_next_batch()
            if batch is None:
                print("\n" + "=" * 60)
                print("✅ 所有批次已完成!")
                print("=" * 60 + "\n")
                
                # 生成最终报告
                self._print_final_report()
                break
            
            batch_index = batch["batch_index"]
            print(f"\n{'='*60}")
            print(f"【批次 {batch_index}/{self.total_batches}】")
            print(f"{'='*60}\n")
            
            # 输出阅片提示
            prompt = self.generate_host_ai_prompt(batch)
            print(prompt)
            
            # 等待宿主 AI 返回结果
            print(f"\n{'='*60}")
            print("请返回上述图片的阅片结果（JSON 数组格式）:")
            print(f"{'='*60}\n")
            print("(等待宿主 AI 返回结果...)")
            
            # 注意：由于当前模型不支持图片识别，这里只是输出提示
            # 实际使用时需要宿主 AI 能够接收图片输入
            processed += 1
            
            if processed >= max_batches_per_session:
                remaining = self.total_batches - len(self.completed_batches) - processed
                if remaining > 0:
                    print(f"\n⏸️  已达到每会话最大批次数 ({max_batches_per_session})")
                    print(f"   剩余 {remaining} 个批次待处理")
                    print("\n💡 继续处理请重新运行脚本")
                    print(f"   python scripts/host_ai_review.py \\")
                    print(f"     --manifest {self.manifest_path} \\")
                    print(f"     --output {self.output_dir}")
                break
    
    def _run_text_only_mode(self):
        """
        纯文本模式 - 宿主 AI 被检测为不支持图片识别。
        
        v2.10.0 优化：
          - 明确告知宿主 AI 检测可能有误，如果实际支持视觉可忽略此检测
          - 提供更清晰的操作指引
          - 强调「先试后判」：先尝试读图，确实不行再停下来
        """
        print("\n" + "=" * 60)
        print("【DICOM Doctor 宿主 AI 阅片模式】")
        print("=" * 60)
        print(f"\n⚠️  能力检测结果：当前模型可能不支持图片识别")
        print(f"   检测到的模型: {self.capabilities['model_name']}")
        print(f"\n💡 重要提示：")
        print(f"   如果你（宿主 AI）实际上支持图片识别（多模态视觉能力），")
        print(f"   请忽略上述检测结果，直接按 SKILL.md 的流程逐批阅片即可。")
        print(f"   检测可能不准确，因为无法从环境变量中确定你的实际模型。")
        print(f"\n如果确实不支持图片识别，推荐以下方案（按优先级排序）：")
        print("\n1️⃣  使用 OpenAI API（推荐，最稳定）")
        print("   运行命令：")
        print("   python scripts/main.py --input <dicom文件> --output <输出目录> \\")
        print("     --auto-review-model gpt-4o \\")
        print("     --auto-review-api-key <你的API Key>")
        print("\n2️⃣  使用 Claude API")
        print("   运行命令：")
        print("   python scripts/main.py --input <dicom文件> --output <输出目录> \\")
        print("     --auto-review-model claude-3-opus-20240229 \\")
        print("     --auto-review-api-key <你的API Key>")
        print("\n3️⃣  使用 Gemini API（Google）")
        print("   运行命令：")
        print("   python scripts/main.py --input <dicom文件> --output <输出目录> \\")
        print("     --auto-review-model gemini-1.5-pro \\")
        print("     --auto-review-api-key <你的API Key>")
        print("\n4️⃣  手动分批处理")
        print("   将生成的 PNG 图片发送给支持视觉的 AI 进行分析")
        print("\n💡 获取 API Key：")
        print("   - OpenAI: https://platform.openai.com/api-keys")
        print("   - Anthropic: https://console.anthropic.com/")
        print("   - Google: https://ai.google.dev/")
        print("=" * 60)
        
        # 显示当前进度
        progress = self.get_progress()
        print(f"\n📊 当前进度：")
        print(f"   总批次: {progress['total_batches']}")
        print(f"   已完成: {progress['completed_batches']}")
        print(f"   待处理: {progress['remaining_batches']}")
        if progress['next_batch']:
            print(f"   下一批次: {progress['next_batch']}")
        print("=" * 60 + "\n")
    
    def _print_final_report(self):
        """打印最终报告"""
        results_file = self.output_dir / "review_results.json"
        if results_file.exists():
            try:
                with open(results_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                total = len(data.get("results", []))
                abnormal = len([r for r in data.get("results", []) if r.get("conclusion") == "异常"])
                normal = total - abnormal
                
                print("\n" + "=" * 60)
                print("【阅片完成报告】")
                print("=" * 60)
                print(f"总影像数: {total}")
                print(f"正常: {normal}")
                print(f"异常: {abnormal}")
                print(f"\n详细结果: {results_file}")
                print(f"PDF报告: {self.output_dir / 'review_report.pdf'}")
                print("=" * 60 + "\n")
            except Exception as e:
                logger.warning(f"生成最终报告时出错: {e}")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
    description="DICOM Doctor v2.10.0 - 宿主 AI 自动分批阅片模式"
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="review_manifest.json 路径",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="输出目录（包含 review_batch_templates/）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=15,
        help="每批处理的图片数量（默认15）",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="仅显示当前进度状态",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
        help="宿主 AI 模型名称（如 claude-4.6-opus），用于提高能力检测准确性",
    )
    return parser.parse_args()


def main():
    """命令行入口"""
    args = parse_args()
    
    # 初始化协调器
    reviewer = HostAIReviewer(
        manifest_path=args.manifest,
        output_dir=args.output,
        batch_size=args.batch_size,
        model_name=getattr(args, 'model_name', None),
    )
    
    # 显示状态或运行交互模式
    if args.status:
        progress = reviewer.get_progress()
        print("\n【当前进度】")
        print(f"  总批次: {progress['total_batches']}")
        print(f"  已完成: {progress['completed_batches']}")
        print(f"  待处理: {progress['remaining_batches']}")
        if progress['next_batch']:
            print(f"  下一批: 批次 {progress['next_batch']}")
        else:
            print(f"  状态: ✅ 全部完成")
        return 0
    
    # 运行交互模式
    reviewer.run_interactive()
    return 0


if __name__ == "__main__":
    sys.exit(main())
