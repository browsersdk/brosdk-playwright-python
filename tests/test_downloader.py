"""_downloader 模块测试：平台检测、asset 解析、解压（mock 网络，不真下载）。

通过构造假的 zip/tar.gz 归档（内含一个假的 brosdk.dll）验证解压逻辑，
通过 mock urllib 验证 GitHub API 解析与下载逻辑。
"""

import io
import json
import os
import platform
import tarfile
import zipfile

import pytest

from brosdk_playwright._config import BroSDKError
from brosdk_playwright._downloader import (
    _PLATFORM_MAP,
    _extract,
    _resolve_asset,
    default_lib_filename,
    detect_platform_key,
    download_native_lib,
)


# ── 平台检测 ─────────────────────────────────────────────────────────────────

def test_detect_platform_key_returns_tuple():
    sysn, mach = detect_platform_key()
    assert isinstance(sysn, str)
    assert isinstance(mach, str)


def test_default_lib_filename_matches_platform():
    fname = default_lib_filename()
    sysn = platform.system()
    if sysn == "Windows":
        assert fname == "brosdk.dll"
    elif sysn == "Darwin":
        assert fname == "brosdk.dylib"
    elif sysn == "Linux":
        assert fname == "libbrosdk.so"


def test_platform_map_coverage():
    # 三个平台都有条目
    systems = {s for (s, _) in _PLATFORM_MAP}
    assert {"Windows", "Darwin", "Linux"}.issubset(systems)


# ── asset 解析（mock GitHub API）─────────────────────────────────────────────

def test_resolve_asset_latest(monkeypatch):
    release = {
        "tag_name": "v1.0.1.1",
        "assets": [
            {"name": "brosdk-1.0.1.1-windows-x64.zip",
             "browser_download_url": "https://example.com/win.zip"},
            {"name": "brosdk-1.0.1.1-darwin-arm64.tar.gz",
             "browser_download_url": "https://example.com/mac.tar.gz"},
            {"name": "brosdk-1.0.1.1-linux-amd64.tar.gz",
             "browser_download_url": "https://example.com/linux.tar.gz"},
        ],
    }

    class FakeResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return json.dumps(self._data).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=None):
        return FakeResp(release)

    monkeypatch.setattr("brosdk_playwright._downloader.urllib.request.urlopen", fake_urlopen)

    url, name, ver = _resolve_asset(version=None)
    assert ver == "1.0.1.1"
    sysn = platform.system()
    if sysn == "Windows":
        assert name == "brosdk-1.0.1.1-windows-x64.zip"
        assert url == "https://example.com/win.zip"
    elif sysn == "Darwin":
        assert name == "brosdk-1.0.1.1-darwin-arm64.tar.gz"
    elif sysn == "Linux":
        assert name == "brosdk-1.0.1.1-linux-amd64.tar.gz"


def test_resolve_asset_explicit_version():
    url, name, ver = _resolve_asset(version="1.0.0.5")
    assert ver == "1.0.0.5"
    sysn = platform.system()
    if sysn == "Windows":
        assert name == "brosdk-1.0.0.5-windows-x64.zip"
        assert url == "https://github.com/browsersdk/brosdk/releases/download/v1.0.0.5/brosdk-1.0.0.5-windows-x64.zip"


def test_resolve_asset_no_matching_asset(monkeypatch):
    release = {"tag_name": "v1.0.0", "assets": [{"name": "other.tar.gz", "browser_download_url": "x"}]}

    class FakeResp:
        def read(self):
            return json.dumps(release).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    monkeypatch.setattr("brosdk_playwright._downloader.urllib.request.urlopen",
                        lambda req, timeout=None: FakeResp())
    with pytest.raises(BroSDKError, match="No BroSDK asset matching"):
        _resolve_asset(version=None)


def test_resolve_asset_api_failure(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("network down")
    monkeypatch.setattr("brosdk_playwright._downloader.urllib.request.urlopen", boom)
    with pytest.raises(BroSDKError, match="Failed to fetch"):
        _resolve_asset(version=None)


# ── 解压逻辑（构造真实归档，不下载）──────────────────────────────────────────

def _make_zip_with_dll(path, lib_name="brosdk.dll"):
    """构造一个含 brosdk.dll 的 zip 归档。"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"subdir/{lib_name}", b"fake-dll-content")
        zf.writestr("readme.txt", b"hello")


def _make_targz_with_dylib(path, lib_name="brosdk.dylib"):
    """构造一个含 brosdk.dylib 的 tar.gz 归档。"""
    with tarfile.open(path, "w:gz") as tf:
        data = b"fake-dylib-content"
        info = tarfile.TarInfo(name=f"subdir/{lib_name}")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))


def test_extract_zip_finds_dll(tmp_path):
    archive = str(tmp_path / "test.zip")
    _make_zip_with_dll(archive)
    lib_path = _extract(archive, str(tmp_path / "out"), "brosdk-1.0.0-windows-x64.zip")
    assert os.path.basename(lib_path) == "brosdk.dll"
    assert os.path.exists(lib_path)
    with open(lib_path, "rb") as f:
        assert f.read() == b"fake-dll-content"


def test_extract_targz_finds_dylib(tmp_path):
    archive = str(tmp_path / "test.tar.gz")
    _make_targz_with_dylib(archive)
    lib_path = _extract(archive, str(tmp_path / "out"), "brosdk-1.0.0-darwin-arm64.tar.gz")
    assert os.path.basename(lib_path) == "brosdk.dylib"
    assert os.path.exists(lib_path)


def test_extract_no_lib_found_raises(tmp_path):
    archive = str(tmp_path / "empty.zip")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", b"no dll here")
    with pytest.raises(BroSDKError, match="found no native library"):
        _extract(archive, str(tmp_path / "out"), "test.zip")


# ── download_native_lib 端到端（mock 下载，真实解压）─────────────────────────

def test_download_native_lib_full_flow(monkeypatch, tmp_path):
    import brosdk_playwright._downloader as dl

    # 1) mock GitHub API 返回 latest
    release = {
        "tag_name": "v1.0.1.1",
        "assets": [
            {"name": "brosdk-1.0.1.1-windows-x64.zip",
             "browser_download_url": "https://example.com/win.zip"},
            {"name": "brosdk-1.0.1.1-darwin-arm64.tar.gz",
             "browser_download_url": "https://example.com/mac.tar.gz"},
            {"name": "brosdk-1.0.1.1-linux-amd64.tar.gz",
             "browser_download_url": "https://example.com/linux.tar.gz"},
        ],
    }

    class FakeResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return json.dumps(self._data).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    monkeypatch.setattr(dl.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResp(release))

    # 2) mock urlretrieve：把预制的归档写到目标路径（按 url 内容分支）
    def fake_urlretrieve(url, dest, reporthook=None):
        if ".zip" in url or "windows" in url:
            _make_zip_with_dll(dest, "brosdk.dll")
        elif "darwin" in url:
            _make_targz_with_dylib(dest, "brosdk.dylib")
        else:
            _make_targz_with_dylib(dest, "libbrosdk.so")

    monkeypatch.setattr(dl.urllib.request, "urlretrieve", fake_urlretrieve)

    # 3) 执行下载
    lib_path = download_native_lib(str(tmp_path), progress=False)
    assert os.path.exists(lib_path)
    fname = os.path.basename(lib_path)
    assert fname in ("brosdk.dll", "brosdk.dylib", "libbrosdk.so")

    # 4) 二次下载应正常（覆盖）
    lib_path2 = download_native_lib(str(tmp_path), progress=False)
    assert os.path.exists(lib_path2)
