"""stealth（反检测）开关测试。

验证：
- configure(stealth=True/False) 正确写入 Config
- _resolve_sync_playwright() 在 stealth 时选 patchright，否则选 playwright
- stealth=True 但 patchright 未安装时抛出清晰错误
- 环境变量 BROSDK_STEALTH 回退
"""

import sys
import types

import pytest

import brosdk_playwright as bp
from brosdk_playwright._config import configure


# ── Config 字段 ───────────────────────────────────────────────────────────────

def test_stealth_defaults_false():
    cfg = configure(api_key="k")
    assert cfg.stealth is False


def test_stealth_explicit_true():
    cfg = configure(api_key="k", stealth=True)
    assert cfg.stealth is True


def test_stealth_explicit_false():
    cfg = configure(api_key="k", stealth=False)
    assert cfg.stealth is False


def test_stealth_env_var(monkeypatch):
    monkeypatch.setenv("BROSDK_STEALTH", "true")
    cfg = configure(api_key="k")
    assert cfg.stealth is True


def test_stealth_env_var_off(monkeypatch):
    monkeypatch.setenv("BROSDK_STEALTH", "0")
    cfg = configure(api_key="k")
    assert cfg.stealth is False


def test_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("BROSDK_STEALTH", "true")
    cfg = configure(api_key="k", stealth=False)
    assert cfg.stealth is False


# ── 驱动选择 ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_drivers(monkeypatch):
    """注入假的 playwright / patchright 模块，sync_playwright 标注来源。"""
    def _make_pw_module(name):
        mod = types.ModuleType(name)
        sub = types.ModuleType(f"{name}.sync_api")

        def _fake_sync_playwright():
            return object()

        # 用 __module__ 标记来源，便于断言
        _fake_sync_playwright.__module__ = f"{name}.sync_api"
        _fake_sync_playwright._source = name
        sub.sync_playwright = _fake_sync_playwright
        mod.sync_api = sub
        return mod

    pw_mod = _make_pw_module("playwright")
    pr_mod = _make_pw_module("patchright")

    monkeypatch.setitem(sys.modules, "playwright", pw_mod)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", pw_mod.sync_api)
    monkeypatch.setitem(sys.modules, "patchright", pr_mod)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", pr_mod.sync_api)
    return None


def _resolved_source() -> str:
    """返回 _resolve_sync_playwright() 选中的驱动来源名。"""
    from brosdk_playwright.sync_api import _resolve_sync_playwright
    driver = _resolve_sync_playwright()
    return getattr(driver, "_source", "unknown")


def test_resolve_picks_playwright_when_not_stealth(fake_drivers):
    configure(api_key="k", stealth=False)
    assert _resolved_source() == "playwright"


def test_resolve_picks_patchright_when_stealth(fake_drivers):
    configure(api_key="k", stealth=True)
    assert _resolved_source() == "patchright"


def test_resolve_stealth_without_patchright_raises(monkeypatch):
    """stealth=True 但 patchright 不可导入 → 清晰错误。"""
    configure(api_key="k", stealth=True)

    # 让 import patchright 失败：移除缓存 + 注入 meta_path finder 抛 ImportError
    for key in list(sys.modules):
        if key == "patchright" or key.startswith("patchright."):
            monkeypatch.delitem(sys.modules, key, raising=False)
    # 同时清掉 sys.modules 里的占位，确保 import 走 finder
    monkeypatch.setitem(sys.modules, "patchright", None)

    class _BlockingFinder:
        # 现代 find_spec 协议
        def find_spec(self, name, path=None, target=None):
            import importlib.machinery as im
            if name == "patchright" or name.startswith("patchright."):
                # 返回一个会失败的 spec
                return im.ModuleSpec(name, self)
            return None
        def create_module(self, spec):
            raise ImportError(f"blocked: {spec.name}")
        def exec_module(self, module):
            raise ImportError(f"blocked: {module.__name__}")

    sys.meta_path.insert(0, _BlockingFinder())
    try:
        from brosdk_playwright.sync_api import _resolve_sync_playwright
        with pytest.raises(bp.BroSDKError, match="stealth mode requires"):
            _resolve_sync_playwright()
    finally:
        sys.meta_path.pop(0)
        # 清理 None 占位
        sys.modules.pop("patchright", None)


def test_resolve_unconfigured_falls_back_to_playwright(fake_drivers):
    # 未配置 SDK（_CONFIG 已被 conftest 重置为 None）
    assert _resolved_source() == "playwright"
