"""_playwright 包装层测试：属性透传、launch(env=) 路由、close 桥接。

用 FakePlaywright / FakeBrowserType / FakeBrowser 模拟真实对象，不启动浏览器。
"""

import pytest

from brosdk_playwright._playwright import _BroPlaywright, _BroBrowserType, _BroBrowser
from brosdk_playwright._config import BroSDKError


# ── Fake Playwright 对象 ─────────────────────────────────────────────────────

class FakeBrowser:
    def __init__(self):
        self.closed = False
        self.pages = []

    def close(self):
        self.closed = True

    def new_page(self):
        self.pages.append("page")
        return "page"


class FakeBrowserType:
    name = "chromium"

    def __init__(self):
        self.launch_calls = []
        self.connect_over_cdp_calls = []

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        return FakeBrowser()

    def connect_over_cdp(self, endpoint):
        self.connect_over_cdp_calls.append(endpoint)
        return FakeBrowser()

    @property
    def executable_path(self):
        return "/fake/chrome"


class FakePlaywright:
    def __init__(self):
        self.chromium = FakeBrowserType()
        self.firefox = FakeBrowserType()
        self.webkit = FakeBrowserType()
        self.devices = {"Desktop": {}}
        self.stopped = False

    def stop(self):
        self.stopped = True


# ── _BroPlaywright 透传 ──────────────────────────────────────────────────────

def test_bro_playwright_passes_through_devices():
    fp = FakePlaywright()
    bp = _BroPlaywright(fp)
    assert bp.devices == fp.devices


def test_bro_playwright_chromium_is_wrapper():
    fp = FakePlaywright()
    bp = _BroPlaywright(fp)
    assert isinstance(bp.chromium, _BroBrowserType)


def test_bro_playwright_firefox_passthrough_warns(caplog):
    import logging
    fp = FakePlaywright()
    bp = _BroPlaywright(fp)
    with caplog.at_level(logging.WARNING):
        ff1 = bp.firefox
        ff2 = bp.firefox  # 第二次不应再警告
    assert ff1 is fp.firefox
    msgs = [r.message for r in caplog.records if "Chrome kernel only" in r.message]
    assert len(msgs) == 1  # 只警告一次


def test_bro_playwright_stop_delegates():
    fp = FakePlaywright()
    bp = _BroPlaywright(fp)
    bp.stop()
    assert fp.stopped is True


# ── _BroBrowserType 路由 ─────────────────────────────────────────────────────

def test_launch_without_env_delegates_to_real():
    fp = FakePlaywright()
    bt = _BroBrowserType(fp.chromium, "chromium")
    result = bt.launch(headless=True)
    assert fp.chromium.launch_calls == [{"headless": True}]
    assert isinstance(result, FakeBrowser)


def test_launch_with_env_routes_to_brosdk(manager_with_fake, fake_manager, monkeypatch):
    fp = FakePlaywright()
    bt = _BroBrowserType(fp.chromium, "chromium")

    browser = bt.launch(env={"kernel_version": "134", "proxy": "socks5://h:1"})

    # 应创建了环境
    assert len(fake_manager.created_envs) == 1
    # 应通过 CDP 连接
    assert len(fp.chromium.connect_over_cdp_calls) == 1
    assert "127.0.0.1" in fp.chromium.connect_over_cdp_calls[0]
    # 返回的是包装器
    assert isinstance(browser, _BroBrowser)
    assert browser.brosdk_env_id in fake_manager.created_envs
    assert browser.cdp_port >= 9222


def test_launch_with_env_ignores_native_kwargs(manager_with_fake, fake_manager, caplog):
    import logging
    fp = FakePlaywright()
    bt = _BroBrowserType(fp.chromium, "chromium")
    with caplog.at_level(logging.WARNING):
        bt.launch(env={"kernel_version": "134"}, executable_path="/x", headless=True)
    assert any("ignoring Playwright launch kwargs" in r.message for r in caplog.records)


def test_connect_over_cdp_passthrough():
    fp = FakePlaywright()
    bt = _BroBrowserType(fp.chromium, "chromium")
    # 走 __getattr__ 透传
    result = bt.connect_over_cdp("http://localhost:9222")
    assert fp.chromium.connect_over_cdp_calls == ["http://localhost:9222"]


def test_executable_path_passthrough():
    fp = FakePlaywright()
    bt = _BroBrowserType(fp.chromium, "chromium")
    assert bt.executable_path == "/fake/chrome"


# ── _BroBrowser close 桥接 ───────────────────────────────────────────────────

def test_browser_close_disconnects_and_closes_sdk(manager_with_fake, fake_manager):
    fp = FakePlaywright()
    bt = _BroBrowserType(fp.chromium, "chromium")
    browser = bt.launch(env={"kernel_version": "134"})
    env_id = browser.brosdk_env_id

    browser.close()

    assert browser._real.closed is True   # Playwright 侧已断开
    # BroSDK 侧 close_browser 被调用（fake_manager 不会报错即可）


def test_browser_close_idempotent(manager_with_fake, fake_manager):
    fp = FakePlaywright()
    bt = _BroBrowserType(fp.chromium, "chromium")
    browser = bt.launch(env={"kernel_version": "134"})
    browser.close()
    browser.close()  # 第二次不报错


def test_browser_new_page_passthrough(manager_with_fake, fake_manager):
    fp = FakePlaywright()
    bt = _BroBrowserType(fp.chromium, "chromium")
    browser = bt.launch(env={"kernel_version": "134"})
    # new_page 走 __getattr__ 透传到真实 Browser
    page = browser.new_page()
    assert page == "page"
