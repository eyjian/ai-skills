#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM Doctor — 跨平台启动脚本

解决的问题：
  - macOS/Linux 用 bash 的 $(date) / mkdir -p，Windows PowerShell 不认识
  - Windows 上 python3 可能不存在，只有 python
  - 路径分隔符差异
  - pip install 国内网络超时（自动配置国内镜像）
  - pip 本身缺失（自动 ensurepip）

本脚本是纯 Python，不依赖任何特定 shell 语法。
宿主 AI 只需执行一条命令即可启动完整流水线：

  python run.py --input <DICOM路径> --workspace <工作区> [其他参数]

脚本会自动：
  1. 检查 Python 版本（>= 3.8）
  2. 确保 pip 可用 + 自动配置国内镜像
  3. 生成时间戳 + 创建输出目录
  4. 定位 main.py 并调用（透传所有额外参数）
  5. 如果 main.py 执行失败，给出诊断建议
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ========================
# Python 版本检查（最先执行，不依赖任何第三方库）
# ========================

MIN_PYTHON = (3, 8)

def check_python_env():
    """
    检查 Python 环境是否满足最低要求。
    这个检查在导入任何其他模块之前执行。
    """
    current = sys.version_info[:2]
    if current < MIN_PYTHON:
        min_str = ".".join(map(str, MIN_PYTHON))
        cur_str = ".".join(map(str, current))
        print(f"[run.py] ❌ Python 版本过低: 当前 {cur_str}，需要 >= {min_str}")
        print(f"[run.py]")
        print(f"[run.py] 请升级 Python:")
        print(f"[run.py]   macOS:   brew install python3")
        print(f"[run.py]   Windows: https://npmmirror.com/mirrors/python/{min_str}.0/")
        print(f"[run.py]            或 https://python.org/downloads/")
        print(f"[run.py]   Linux:   sudo apt install python3 (Ubuntu/Debian)")
        print(f"[run.py]            sudo yum install python3 (CentOS/RHEL)")
        sys.exit(1)


def ensure_pip_available():
    """
    确保 pip 可用。如果不可用，尝试 ensurepip。
    
    Returns:
        是否成功
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    print("[run.py] ⚠️ pip 不可用，正在尝试自动安装 pip...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            print("[run.py] ✅ pip 安装成功")
            return True
    except Exception:
        pass

    print("[run.py] ❌ 无法自动安装 pip")
    print("[run.py] 请手动安装:")
    if platform.system() == "Windows":
        print("[run.py]   python -m ensurepip --upgrade")
    else:
        print("[run.py]   python3 -m ensurepip --upgrade")
        print("[run.py]   或: curl https://bootstrap.pypa.io/get-pip.py | python3")
    return False


def setup_pip_mirror():
    """
    自动检测网络环境，必要时配置国内 pip 镜像。
    
    策略：先测试 PyPI 官方源，不通则逐个测试国内镜像，
    找到可用的就用 pip config 设置为默认源。
    """
    import urllib.request

    mirrors = [
        ("清华TUNA", "https://pypi.tuna.tsinghua.edu.cn/simple/", "pypi.tuna.tsinghua.edu.cn"),
        ("阿里云", "https://mirrors.aliyun.com/pypi/simple/", "mirrors.aliyun.com"),
        ("华为云", "https://repo.huaweicloud.com/repository/pypi/simple/", "repo.huaweicloud.com"),
        ("中科大", "https://pypi.mirrors.ustc.edu.cn/simple/", "pypi.mirrors.ustc.edu.cn"),
    ]

    def _test(url, timeout=3.0):
        try:
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "dicom-doctor/probe")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status < 400
        except Exception:
            return False

    # 先测官方源
    if _test("https://pypi.org/simple/", timeout=3.0):
        print("[run.py] 🌐 PyPI 官方源可达，无需配置镜像")
        return

    # 逐个测国内镜像
    print("[run.py] 🌐 PyPI 官方源不可达，正在检测国内镜像...")
    for name, url, host in mirrors:
        if _test(url, timeout=3.0):
            print(f"[run.py] ✅ 选定镜像: {name}")
            # 设置为 pip 默认源（仅当前用户级别）
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "config", "set",
                     "global.index-url", url],
                    capture_output=True, text=True, timeout=10,
                )
                subprocess.run(
                    [sys.executable, "-m", "pip", "config", "set",
                     "global.trusted-host", host],
                    capture_output=True, text=True, timeout=10,
                )
                print(f"[run.py] ✅ 已将 {name} 设为 pip 默认源")
            except Exception:
                # pip config 失败不影响运行——pip_utils.py 里会在每次安装时传 -i
                print(f"[run.py] ⚠️ pip config 设置失败，后续安装将在每次调用时指定镜像")
            return

    print("[run.py] ⚠️ 所有镜像源均不可达，网络可能存在问题")
    print("[run.py]    后续安装可能会超时，请检查网络连接")


def find_python() -> str:
    """
    查找可用的 Python 解释器路径。
    
    优先级：
      1. 当前正在运行的 Python（sys.executable）—— 最可靠
      2. python3（macOS/Linux 常见）
      3. python（Windows 常见）
    
    Returns:
        Python 解释器的绝对路径
    """
    # 最可靠：用正在运行本脚本的 Python
    if sys.executable:
        return sys.executable
    
    # 回退：在 PATH 中查找
    for cmd in ("python3", "python"):
        path = shutil.which(cmd)
        if path:
            return path
    
    # 最后手段
    return "python"


def find_main_py() -> Path:
    """
    定位 main.py 的路径。
    
    main.py 与 run.py 在同一目录下（scripts/）。
    
    Returns:
        main.py 的绝对路径
    
    Raises:
        FileNotFoundError: 如果找不到 main.py
    """
    script_dir = Path(__file__).resolve().parent
    main_py = script_dir / "main.py"
    
    if main_py.exists():
        return main_py
    
    # 兜底：往上一级找 scripts/main.py
    alt = script_dir.parent / "scripts" / "main.py"
    if alt.exists():
        return alt
    
    raise FileNotFoundError(
        f"找不到 main.py。\n"
        f"已搜索路径:\n"
        f"  - {main_py}\n"
        f"  - {alt}"
    )


def main():
    # ==== 0. 环境预检 ====
    check_python_env()
    
    if not ensure_pip_available():
        sys.exit(1)
    
    # 自动配置国内镜像（仅在需要时）
    setup_pip_mirror()

    # ---- 解析 run.py 自身的参数 ----
    parser = argparse.ArgumentParser(
        description="DICOM Doctor 跨平台启动器",
        add_help=True,
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="DICOM 文件路径或 ZIP 压缩包路径",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="工作区根目录（输出目录将创建在此目录下）。不提供则使用输入文件所在目录",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="直接指定输出目录（覆盖 --workspace 自动生成逻辑）",
    )
    
    # 分离已知参数和透传参数
    args, extra_args = parser.parse_known_args()
    
    input_path = Path(args.input).resolve()
    
    # ---- 验证输入文件 ----
    if not input_path.exists():
        print(f"[run.py] ❌ 输入文件不存在: {input_path}", file=sys.stderr)
        # 尝试模糊搜索
        parent = input_path.parent
        if parent.exists():
            similar = [
                f.name for f in parent.iterdir()
                if f.suffix.lower() in (".dcm", ".zip", ".dicom")
            ][:5]
            if similar:
                print(f"[run.py] 💡 同目录下找到类似文件:", file=sys.stderr)
                for s in similar:
                    print(f"         - {s}", file=sys.stderr)
        sys.exit(1)
    
    # ---- 生成时间戳和输出目录 ----
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if args.output:
        output_dir = Path(args.output).resolve()
    else:
        workspace = Path(args.workspace).resolve() if args.workspace else input_path.parent
        output_dir = workspace / f"dicom_output_{timestamp}"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # ---- 定位 main.py ----
    try:
        main_py = find_main_py()
    except FileNotFoundError as e:
        print(f"[run.py] ❌ {e}", file=sys.stderr)
        sys.exit(1)
    
    python_cmd = find_python()
    
    # ---- 组装命令 ----
    cmd = [
        python_cmd,
        str(main_py),
        "--input", str(input_path),
        "--output", str(output_dir),
    ] + extra_args
    
    # ---- 打印启动信息 ----
    print(f"[run.py] ═══════════════════════════════════════════")
    print(f"[run.py] DICOM Doctor 跨平台启动器")
    print(f"[run.py] ═══════════════════════════════════════════")
    print(f"[run.py] 操作系统: {platform.system()} {platform.release()}")
    print(f"[run.py] Python:   {python_cmd} ({platform.python_version()})")
    print(f"[run.py] 输入文件: {input_path}")
    print(f"[run.py] 输出目录: {output_dir}")
    print(f"[run.py] 时间戳:   {timestamp}")
    if extra_args:
        print(f"[run.py] 额外参数: {' '.join(extra_args)}")
    print(f"[run.py] ═══════════════════════════════════════════")
    print(f"[run.py] 正在启动 main.py ...")
    print()
    
    # ---- 执行 ----
    env = os.environ.copy()
    
    result = subprocess.run(
        cmd,
        cwd=str(main_py.parent),
        env=env,
    )
    
    if result.returncode != 0:
        print()
        print(f"[run.py] ⚠️ main.py 退出码: {result.returncode}")
        
        # 自修复诊断
        if result.returncode == 1:
            print(f"[run.py] 💡 可能原因: 依赖缺失或输入文件问题")
            req_file = main_py.parent.parent / 'requirements.txt'
            print(f"[run.py] 💡 尝试: {python_cmd} -m pip install -r {req_file}")
            print(f"[run.py]    国内用户追加: -i https://pypi.tuna.tsinghua.edu.cn/simple/")
        elif result.returncode == 2:
            print(f"[run.py] 💡 可能原因: 阅片结果校验失败（strict-review 模式）")
            print(f"[run.py] 💡 这意味着还有切片未完成阅片，需要宿主 AI 继续处理")
    
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
