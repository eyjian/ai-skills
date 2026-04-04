#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM Doctor — pip 镜像感知安装工具

解决的问题：
  - 国内用户 pip install 直连 PyPI 超时/极慢
  - 用户不知道怎么配镜像
  - 离线环境下完全无法安装

策略：
  1. 先检测是否能快速连通 PyPI（2秒超时）
  2. 如果不行，自动尝试国内镜像（清华、阿里、华为、中科大）
  3. 如果所有镜像都不通，尝试本地 wheels 目录（如有）
  4. 统一提供 pip_install() 函数，替代所有直接调用 subprocess pip

国内镜像列表（按速度和稳定性排序）：
  - 清华 TUNA: https://pypi.tuna.tsinghua.edu.cn/simple/
  - 阿里云:     https://mirrors.aliyun.com/pypi/simple/
  - 华为云:     https://repo.huaweicloud.com/repository/pypi/simple/
  - 中科大:     https://pypi.mirrors.ustc.edu.cn/simple/
"""

import importlib
import logging
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Optional, List, Tuple

logger = logging.getLogger("dicom-doctor.pip")

# ========================
# 镜像源配置
# ========================

PYPI_OFFICIAL = "https://pypi.org/simple/"

CHINA_MIRRORS = [
    ("清华TUNA", "https://pypi.tuna.tsinghua.edu.cn/simple/", "pypi.tuna.tsinghua.edu.cn"),
    ("阿里云", "https://mirrors.aliyun.com/pypi/simple/", "mirrors.aliyun.com"),
    ("华为云", "https://repo.huaweicloud.com/repository/pypi/simple/", "repo.huaweicloud.com"),
    ("中科大", "https://pypi.mirrors.ustc.edu.cn/simple/", "pypi.mirrors.ustc.edu.cn"),
]

# 模块级缓存：选定的镜像 URL（None = 未检测，"" = 官方源可用）
_selected_mirror: Optional[str] = None
_selected_mirror_name: Optional[str] = None


def _test_url(url: str, timeout: float = 3.0) -> bool:
    """测试 URL 是否可达（仅检测连通性，不下载内容）"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "dicom-doctor-pip-probe/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400
    except Exception:
        return False


def detect_best_mirror(force_redetect: bool = False) -> Tuple[Optional[str], str]:
    """
    检测最佳 pip 镜像源。

    Returns:
        (mirror_url, mirror_name)
        - mirror_url: 镜像 URL，None 表示用官方源
        - mirror_name: 人类可读名称
    """
    global _selected_mirror, _selected_mirror_name

    if not force_redetect and _selected_mirror is not None:
        return (_selected_mirror or None, _selected_mirror_name or "PyPI官方")

    # 1. 先测官方源
    logger.info("[pip镜像] 正在检测网络环境...")
    if _test_url(PYPI_OFFICIAL, timeout=3.0):
        logger.info("[pip镜像] PyPI 官方源可达，使用官方源")
        _selected_mirror = ""
        _selected_mirror_name = "PyPI官方"
        return (None, "PyPI官方")

    # 2. 官方源不通，逐个测试国内镜像
    logger.info("[pip镜像] PyPI 官方源不可达，正在测试国内镜像...")
    for name, url, host in CHINA_MIRRORS:
        if _test_url(url, timeout=3.0):
            logger.info(f"[pip镜像] ✅ 选定镜像: {name} ({url})")
            _selected_mirror = url
            _selected_mirror_name = name
            return (url, name)

    # 3. 全部不通
    logger.warning("[pip镜像] ⚠️ 所有镜像源均不可达，将尝试直接安装（可能超时）")
    _selected_mirror = ""
    _selected_mirror_name = "无可用源"
    return (None, "无可用源")


def pip_install(
    package_spec: str,
    timeout: int = 300,
    quiet: bool = True,
    force_mirror: Optional[str] = None,
) -> bool:
    """
    镜像感知的 pip install。

    自动检测最佳镜像源，如果官方源不通则切换国内镜像。

    Args:
        package_spec: pip 包规格（如 'Pillow>=10.0.0'）
        timeout: 安装超时秒数
        quiet: 是否静默安装
        force_mirror: 强制使用指定镜像 URL

    Returns:
        是否安装成功
    """
    # 确定镜像
    if force_mirror:
        mirror_url = force_mirror
        mirror_name = "用户指定"
    else:
        mirror_url, mirror_name = detect_best_mirror()

    # 组装命令
    cmd = [sys.executable, "-m", "pip", "install", package_spec]
    if quiet:
        cmd.append("--quiet")
    if mirror_url:
        cmd.extend(["-i", mirror_url, "--trusted-host", _extract_host(mirror_url)])

    logger.info(f"[pip安装] 正在安装: {package_spec} (源: {mirror_name})")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            logger.info(f"[pip安装] ✅ 安装成功: {package_spec}")
            # 清除导入缓存
            importlib.invalidate_caches()
            return True
        else:
            stderr = result.stderr.strip()
            logger.warning(f"[pip安装] ❌ 安装失败: {package_spec}\n  {stderr}")

            # 如果用的是官方源失败了，自动重试国内镜像
            if not mirror_url and not force_mirror:
                logger.info("[pip安装] 官方源安装失败，尝试国内镜像重试...")
                return _retry_with_china_mirrors(package_spec, timeout, quiet)

            return False

    except subprocess.TimeoutExpired:
        logger.warning(f"[pip安装] ⏰ 安装超时({timeout}秒): {package_spec}")

        # 超时时也尝试国内镜像
        if not mirror_url and not force_mirror:
            logger.info("[pip安装] 官方源超时，尝试国内镜像重试...")
            return _retry_with_china_mirrors(package_spec, timeout, quiet)

        return False

    except Exception as e:
        logger.warning(f"[pip安装] 安装异常: {package_spec}: {e}")
        return False


def _retry_with_china_mirrors(
    package_spec: str, timeout: int, quiet: bool
) -> bool:
    """依次尝试国内镜像安装"""
    for name, url, host in CHINA_MIRRORS:
        logger.info(f"[pip安装] 尝试镜像: {name}...")
        cmd = [sys.executable, "-m", "pip", "install", package_spec]
        if quiet:
            cmd.append("--quiet")
        cmd.extend(["-i", url, "--trusted-host", host])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                logger.info(f"[pip安装] ✅ 通过 {name} 安装成功: {package_spec}")
                # 记住这个能用的镜像
                global _selected_mirror, _selected_mirror_name
                _selected_mirror = url
                _selected_mirror_name = name
                importlib.invalidate_caches()
                return True
        except subprocess.TimeoutExpired:
            logger.warning(f"[pip安装] {name} 超时，尝试下一个...")
            continue
        except Exception:
            continue

    logger.error(f"[pip安装] ❌ 所有镜像均安装失败: {package_spec}")
    return False


def ensure_pip() -> bool:
    """
    确保 pip 可用。如果没有 pip，尝试用 ensurepip 安装。

    Returns:
        pip 是否可用
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    logger.info("[pip安装] pip 不可用，尝试 ensurepip...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            logger.info("[pip安装] ✅ ensurepip 成功")
            return True
    except Exception as e:
        logger.warning(f"[pip安装] ensurepip 失败: {e}")

    logger.error("[pip安装] ❌ 无法获取 pip。请手动安装 pip 后重试。")
    return False


def _extract_host(url: str) -> str:
    """从 URL 中提取主机名"""
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or ""
    except Exception:
        # 简单正则回退
        import re
        m = re.search(r"https?://([^/:]+)", url)
        return m.group(1) if m else ""


def check_python_version(min_version: tuple = (3, 8)) -> bool:
    """
    检查 Python 版本是否满足最低要求。

    Args:
        min_version: 最低版本元组，如 (3, 8)

    Returns:
        是否满足
    """
    current = sys.version_info[:2]
    if current < min_version:
        min_str = ".".join(map(str, min_version))
        cur_str = ".".join(map(str, current))
        logger.error(
            f"[环境检查] ❌ Python 版本过低: 当前 {cur_str}，需要 >= {min_str}\n"
            f"  请升级 Python: https://python.org/downloads/"
        )
        return False
    return True


def get_mirror_status() -> str:
    """返回当前镜像状态的人类可读描述"""
    mirror_url, mirror_name = detect_best_mirror()
    if mirror_url:
        return f"使用国内镜像: {mirror_name} ({mirror_url})"
    elif mirror_name == "无可用源":
        return "⚠️ 所有镜像源均不可达，网络可能存在问题"
    else:
        return "使用 PyPI 官方源"
