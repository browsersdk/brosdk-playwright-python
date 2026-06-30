"""
brosdk_playwright._playwright
=============================

Playwright API 兼容层（包装器模式）。

Playwright 的 ``Playwright.chromium`` 是 C 扩展的只读属性，无法可靠地 monkeypatch。
因此本模块用包装器对象把真实 Playwright 对象包一层：

- :class:`_BroPlaywright`     —— 包装 ``Playwright``，转发所有属性，覆写 ``.chromium``。
- :class:`_BroBrowserType`    —— 包装 ``BrowserType``，``launch(env=...)`` 走 BroSDK。
- :class:`_BroBrowser`        —— 包装 ``Browser``，``close()`` 同时关闭 BroSDK 环境。

其余所有属性 / 方法通过 ``__getattr__`` 透传，保证 Playwright 原生 API 完全可用。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ._config import BroSDKError
from ._sdk import ENV_MANAGER, BroSDKEnvManager

logger = logging.getLogger(__name__)

__all__ = ["_BroPlaywright"]

# 非 chromium 内核首次访问时只警告一次
_warned_other_kernels = set()


class _BroPlaywright:
    """包装真实 ``playwright.sync_api.Playwright``，覆写 chromium。"""

    def __init__(self, real_playwright: Any) -> None:
        self._real = real_playwright

    def __getattr__(self, name: str) -> Any:
        # chromium 在 __init__ 之后才走 __getattr__？不会——见下方显式 property。
        return getattr(self._real, name)

    # ── 浏览器类型 ────────────────────────────────────────────────────────

    @property
    def chromium(self) -> "_BroBrowserType":
        return _BroBrowserType(self._real.chromium, "chromium")

    @property
    def firefox(self) -> Any:
        _warn_other_kernel("firefox")
        return self._real.firefox

    @property
    def webkit(self) -> Any:
        _warn_other_kernel("webkit")
        return self._real.webkit

    # 其余（request, devices, selectors, ...）走 __getattr__ 透传

    def stop(self) -> None:
        self._real.stop()


class _BroBrowserType:
    """包装 ``BrowserType``；``launch(env=...)`` 走 BroSDK CDP 流程。"""

    def __init__(self, real_browser_type: Any, kernel: str = "chromium") -> None:
        self._real = real_browser_type
        self._kernel = kernel

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    # ── 启动 ──────────────────────────────────────────────────────────────

    def launch(self, env: Optional[dict] = None, **kwargs: Any) -> Any:
        """启动浏览器。

        - ``env`` 非空：走 BroSDK 流程 —— 创建/复用环境 → 启动 → CDP 连接。
        - ``env`` 为空：透传给真实 Playwright（普通本地浏览器，无指纹）。

        BroSDK 流程下，Playwright 原生的 ``executable_path`` / ``args`` /
        ``headless`` 等参数无意义（浏览器由 BroSDK 管理），会被忽略并记录 warning。
        """
        if env is None:
            return self._real.launch(**kwargs)

        return self._launch_via_brosdk(env, **kwargs)

    def launch_persistent_context(self, env: Optional[dict] = None, **kwargs: Any) -> Any:
        """持久化上下文启动。

        BroSDK 环境本身就是持久化的（环境级 cookie/storage），因此走 BroSDK 时
        返回 CDP 连接的 Browser 的默认 context（即持久化的那个），忽略 ``user_data_dir``。
        """
        if env is None:
            return self._real.launch_persistent_context(**kwargs)

        browser = self._launch_via_brosdk(env, **kwargs)
        # BroSDK 浏览器自带持久化 profile；返回其默认 context 兼容 API。
        # 通过 connect_over_cdp 连上的浏览器必然有一个默认 context。
        contexts = browser.contexts
        if contexts:
            return contexts[0]
        # 极端情况（CDP 连上时还没创建 context）：显式建一个
        return browser.new_context()

    def _launch_via_brosdk(self, env: dict, **kwargs: Any) -> "_BroBrowser":
        # Playwright 原生参数在 BroSDK 模式下不适用
        ignored = [k for k in ("executable_path", "args", "headless", "channel") if kwargs.get(k) is not None]
        if ignored:
            logger.warning(
                "BroSDK manages the browser; ignoring Playwright launch kwargs: %s. "
                "Configure via env={...} instead (args/proxy/kernel_version).",
                ignored,
            )

        manager = ENV_MANAGER

        # 1) 解析 / 创建环境
        env_id = manager.resolve_env(env)

        # 2) 启动浏览器，同步等待 CDP 就绪
        cdp_port = manager.launch_browser(
            env_id      = env_id,
            args        = env.get("args"),
            urls        = env.get("urls"),
            cookies     = env.get("cookies"),
            extensions  = env.get("extensions"),
            forward     = env.get("forward"),
            timeout     = env.get("launch_timeout", 60.0),
        )

        # 3) Playwright 通过 CDP 连接到已启动的浏览器
        endpoint = f"http://127.0.0.1:{cdp_port}"
        try:
            real_browser = self._real.connect_over_cdp(endpoint)
        except Exception as exc:  # Playwright 自身抛错
            # 连接失败也应尝试关闭 BroSDK 浏览器进程
            try:
                manager.close_browser(env_id)
            except Exception:  # noqa: BLE001
                pass
            raise BroSDKError(
                f"Playwright failed to connect over CDP ({endpoint}): {exc}"
            ) from exc

        return _BroBrowser(real_browser, env_id, cdp_port)

    # 其余（connect_over_cdp / connect / executable_path / name）走 __getattr__ 透传


class _BroBrowser:
    """包装真实 ``Browser``；``close()`` 同时关闭 BroSDK 浏览器并持久化。"""

    def __init__(self, real_browser: Any, env_id: str, cdp_port: int) -> None:
        self._real = real_browser
        self._env_id = env_id
        self._cdp_port = cdp_port
        self._closed = False

    # ── BroSDK 增强字段 ───────────────────────────────────────────────────

    @property
    def brosdk_env_id(self) -> str:
        """关联的 BroSDK 环境 ID。"""
        return self._env_id

    @property
    def cdp_port(self) -> int:
        """浏览器 CDP 调试端口。"""
        return self._cdp_port

    # ── 生命周期 ──────────────────────────────────────────────────────────

    def close(self) -> None:
        """断开 CDP 连接并关闭 BroSDK 浏览器（触发 cookie/storage 持久化）。"""
        if self._closed:
            return
        self._closed = True

        # 1) 先断开 Playwright 的 CDP 连接
        try:
            self._real.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Playwright browser.close() error: %s", exc)

        # 2) 关闭 BroSDK 浏览器进程（best-effort，自动持久化）
        try:
            ENV_MANAGER.close_browser(self._env_id)
        except BroSDKError as exc:
            logger.warning("BroSDK close_browser error for env %s: %s", self._env_id, exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


# ── 辅助 ───────────────────────────────────────────────────────────────────

def _warn_other_kernel(kernel: str) -> None:
    """非 chromium 内核首次访问时警告一次。"""
    if kernel in _warned_other_kernels:
        return
    _warned_other_kernels.add(kernel)
    logging.getLogger(__name__).warning(
        "BroSDK supports the Chrome kernel only; "
        "p.%s runs plain Playwright without BroSDK fingerprint.", kernel
    )
