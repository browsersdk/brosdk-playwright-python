"""
brosdk_playwright._downloader
=============================

从 GitHub Releases 自动下载 BroSDK 原生动态库。

PyPI 上的 ``brosdk`` 是纯 Python 包，**不附带** ``brosdk.dll`` / ``.dylib`` /
``.so``。本模块在本地找不到原生库时，按平台从
https://github.com/browsersdk/brosdk/releases 下载并解压到工作目录的
``libs/<platform>/`` 下，使 brosdk-playwright 在干净环境下也能即装即用。

平台 → asset 命名
-----------------
- Windows x64: ``brosdk-<ver>-windows-x64.zip``
- macOS arm64: ``brosdk-<ver>-darwin-arm64.tar.gz``
- Linux amd64: ``brosdk-<ver>-linux-amd64.tar.gz``
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from typing import Optional, Tuple

from ._config import BroSDKError

logger = logging.getLogger(__name__)

__all__ = ["download_native_lib", "default_lib_filename", "detect_platform_key"]

_GITHUB_RELEASES_API = "https://api.github.com/repos/browsersdk/brosdk/releases/latest"

# 平台 → (asset 文件名模板, libs 子目录, 动态库文件名)
_PLATFORM_MAP = {
    ("Windows", "AMD64"): ("brosdk-{version}-windows-x64.zip", "windows-x64", "brosdk.dll"),
    ("Windows", "x86_64"): ("brosdk-{version}-windows-x64.zip", "windows-x64", "brosdk.dll"),
    ("Darwin",  "ARM64"):  ("brosdk-{version}-darwin-arm64.tar.gz", "macos-arm64", "brosdk.dylib"),
    ("Darwin",  "arm64"):  ("brosdk-{version}-darwin-arm64.tar.gz", "macos-arm64", "brosdk.dylib"),
    ("Linux",   "x86_64"): ("brosdk-{version}-linux-amd64.tar.gz", "linux-x64", "libbrosdk.so"),
    ("Linux",   "amd64"):  ("brosdk-{version}-linux-amd64.tar.gz", "linux-x64", "libbrosdk.so"),
}

# 支持的动态库文件名（解压后用来定位实际库文件）
_LIB_FILENAMES = ("brosdk.dll", "brosdk.dylib", "libbrosdk.so")


def detect_platform_key() -> Tuple[str, str]:
    """返回 (system, machine) 元组。"""
    return platform.system(), platform.machine()


def default_lib_filename() -> str:
    """返回当前平台应有的动态库文件名。"""
    for (sysn, mach), (_, _, libname) in _PLATFORM_MAP.items():
        if sysn == platform.system() and mach.lower() == platform.machine().lower():
            return libname
    raise BroSDKError(
        f"Unsupported platform: {platform.system()}/{platform.machine()}. "
        f"Supported: Windows/x64, macOS/arm64, Linux/amd64."
    )


def _resolve_asset(version: Optional[str] = None) -> Tuple[str, str, str]:
    """返回 (asset_url, asset_name, version)。version=None 时查 latest。

    :raises BroSDKError: 无法获取 release 信息或找不到匹配 asset。
    """
    if version:
        # 用户指定版本：直接拼 URL
        asset_tpl, _, _ = _lookup_platform_entry()
        asset_name = asset_tpl.format(version=version)
        url = f"https://github.com/browsersdk/brosdk/releases/download/v{version}/{asset_name}"
        return url, asset_name, version

    # 查 latest
    try:
        req = urllib.request.Request(_GITHUB_RELEASES_API)
        req.add_header("User-Agent", "brosdk-playwright")
        req.add_header("Accept", "application/vnd.github+json")
        with urllib.request.urlopen(req, timeout=20) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise BroSDKError(f"Failed to fetch BroSDK releases from GitHub: {exc}") from exc

    tag = release.get("tag_name", "")
    ver = tag.lstrip("v")
    if not ver:
        raise BroSDKError(f"Cannot parse version from release tag: {tag!r}")

    asset_tpl, _, _ = _lookup_platform_entry()
    asset_name = asset_tpl.format(version=ver)

    for a in release.get("assets", []):
        if a.get("name") == asset_name:
            return a.get("browser_download_url", ""), asset_name, ver

    available = [a.get("name") for a in release.get("assets", [])]
    raise BroSDKError(
        f"No BroSDK asset matching current platform ({asset_name}) in release {tag}. "
        f"Available: {available}"
    )


def _lookup_platform_entry() -> Tuple[str, str, str]:
    """返回当前平台对应的 (asset 模板, libs 子目录, 库文件名)。"""
    sysn, mach = detect_platform_key()
    key = (sysn, mach)
    if key in _PLATFORM_MAP:
        return _PLATFORM_MAP[key]
    # 宽松匹配 machine 大小写
    for (s, m), entry in _PLATFORM_MAP.items():
        if s == sysn and m.lower() == mach.lower():
            return entry
    raise BroSDKError(
        f"Unsupported platform: {sysn}/{mach}. "
        f"Supported: Windows/x64, macOS/arm64, Linux/amd64."
    )


def _download(url: str, dest_path: str, progress: bool = True) -> None:
    """下载文件到 dest_path，带进度回调。"""
    def _reporthook(block_num, block_size, total_size):
        if not progress or total_size <= 0:
            return
        downloaded = block_num * block_size
        pct = min(downloaded * 100 // total_size, 100)
        mb_d = downloaded / (1024 * 1024)
        mb_t = total_size / (1024 * 1024)
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        sys.stdout.write(f"\r  下载中: [{bar}] {pct}% ({mb_d:.1f}/{mb_t:.1f} MB)")
        sys.stdout.flush()

    max_attempts = 3
    last_exc = None
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                urllib.request.urlretrieve(url, dest_path, reporthook=_reporthook)
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_attempts:
                    logger.warning("Download attempt %d/%d failed (%s); retrying...", attempt, max_attempts, exc)
                    # 删除可能写了一半的文件再重试
                    try:
                        os.remove(dest_path)
                    except OSError:
                        pass
                    time.sleep(1.5 * attempt)
        raise BroSDKError(f"Failed to download {url} after {max_attempts} attempts: {last_exc}") from last_exc
    finally:
        if progress:
            sys.stdout.write("\n")
            sys.stdout.flush()


def _extract(archive_path: str, dest_dir: str, asset_name: str) -> str:
    """解压归档到 dest_dir，返回找到的动态库绝对路径。

    :raises BroSDKError: 解压后未找到动态库文件。
    """
    os.makedirs(dest_dir, exist_ok=True)
    if asset_name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    else:
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(dest_dir)

    # 在解压结果中递归查找动态库
    for root, _dirs, files in os.walk(dest_dir):
        for fname in files:
            if fname in _LIB_FILENAMES:
                return os.path.join(root, fname)

    raise BroSDKError(
        f"Extracted {asset_name} but found no native library "
        f"({_LIB_FILENAMES}) in {dest_dir}."
    )


def download_native_lib(
    dest_dir: str,
    version: Optional[str] = None,
    progress: bool = True,
) -> str:
    """下载并解压当前平台的 BroSDK 原生库，返回库文件绝对路径。

    :param dest_dir: 解压目标目录（通常是 ``<work_dir>/libs``）。
    :param version:  指定版本号；None 时下载 latest。
    :param progress: 是否在 stderr 打印下载进度条。
    :return: 动态库文件的绝对路径。
    :raises BroSDKError: 下载或解压失败。
    """
    url, asset_name, ver = _resolve_asset(version=version)
    logger.info("Downloading BroSDK native lib %s (version %s)", asset_name, ver)
    if progress:
        print(f"  正在下载 BroSDK 原生库: {asset_name}", file=sys.stderr)

    tmp_dir = tempfile.mkdtemp(prefix="brosdk-dl-")
    try:
        archive = os.path.join(tmp_dir, asset_name)
        _download(url, archive, progress=progress)

        # 解压到 dest_dir/<platform_subdir>
        _, subdir, _ = _lookup_platform_entry()
        extract_dir = os.path.join(dest_dir, subdir)
        lib_path = _extract(archive, extract_dir, asset_name)
        logger.info("BroSDK native lib installed at %s", lib_path)
        if progress:
            print(f"  已安装: {os.path.relpath(lib_path, dest_dir)}", file=sys.stderr)
        return lib_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
