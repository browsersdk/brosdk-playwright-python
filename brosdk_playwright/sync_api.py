"""
brosdk_playwright.sync_api
==========================

与 Playwright ``sync_api`` 同名的同步入口。

用法
----
.. code-block:: python

    from brosdk_playwright import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(env={"proxy": "..."})
        page = browser.new_page()
        page.goto("https://example.com")
        browser.close()

签名与 Playwright 官方 ``sync_playwright`` 完全一致（无参），实现零切换成本。
"""

from __future__ import annotations

from typing import Any

from ._config import BroSDKError, get_config
from ._playwright import _BroPlaywright

__all__ = ["sync_playwright"]


def _resolve_sync_playwright():
    """根据 stealth 配置选择底层驱动：patchright（反检测）或 playwright。

    :return: 底层的 ``sync_playwright`` 可调用对象。
    :raises BroSDKError: stealth=True 但 patchright 未安装。
    """
    try:
        cfg = get_config()
    except BroSDKError:
        # 未配置 SDK 时不阻塞（用户可能只用透传 Playwright）；默认非 stealth
        cfg = None

    if cfg is not None and cfg.stealth:
        try:
            from patchright.sync_api import sync_playwright as _driver
        except ImportError as exc:
            raise BroSDKError(
                "stealth mode requires the 'patchright' package. "
                "Install it with: pip install brosdk-playwright[stealth]  (or pip install patchright)"
            ) from exc
        return _driver

    from playwright.sync_api import sync_playwright as _driver
    return _driver


class sync_playwright:
    """与 Playwright ``sync_playwright`` 签名一致的上下文管理器。

    内部启动真实 Playwright（或 stealth 模式下的 patchright），并把其
    ``Playwright`` 对象包成 :class:`_BroPlaywright`，使 ``p.chromium.launch(env=...)``
    走 BroSDK，其余 API 原样可用。

    BroSDK 的初始化是进程级的，不在每次 ``with`` 时重复初始化；
    SDK 关闭交给进程退出或显式 ``brosdk_playwright.shutdown()``。
    """

    def __init__(self) -> None:
        self._real_cm: Any = None
        self._real_pw: Any = None

    def __enter__(self) -> _BroPlaywright:
        _real_sync_playwright = _resolve_sync_playwright()

        self._real_cm = _real_sync_playwright()
        self._real_pw = self._real_cm.__enter__()
        return _BroPlaywright(self._real_pw)

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._real_cm is not None:
            self._real_cm.__exit__(exc_type, exc_val, exc_tb)
        self._real_cm = None
        self._real_pw = None
