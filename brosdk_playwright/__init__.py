"""
brosdk-playwright
=================

Playwright 的 BroSDK 一键集成方案。

BroSDK 负责"造环境"（指纹 / 代理 / 会话持久化），Playwright 负责"干活"（页面自动化），
两者通过 CDP 桥接。本包把"创建环境 → 启动浏览器 → 获取 CDP 端点 → 连接 Playwright"
封装成与 Playwright 原生 API 几乎一致的调用，实现零切换成本。

快速开始
--------
.. code-block:: python

    import brosdk_playwright as bp
    bp.configure(api_key="your-api-key", work_dir="./.brosdk")

    from brosdk_playwright import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(env={
            "env_id": "2070365861541056512",   # 复用已有环境，自动恢复登录态
            "kernel_version": "134",
            "proxy": "socks5://user:pass@host:1080",
        })
        page = browser.new_page()
        page.goto("https://example.com")
        browser.close()                    # 断开 CDP + 关闭浏览器（自动持久化 cookie）

    bp.shutdown()

仅支持 Chrome 内核的指纹环境；``p.firefox`` / ``p.webkit`` 透传给原生 Playwright（无指纹）。
"""

from ._config import (
    BroSDKError,
    Config,
    configure,
    get_config,
)
from ._sdk import ENV_MANAGER, BroSDKEnvManager
from .sync_api import sync_playwright

__version__ = "0.1.0"

__all__ = [
    # 入口
    "sync_playwright",
    "configure",
    "BroSDKError",
    # 配置 / 状态
    "get_config",
    "Config",
    # 环境管理（进阶）
    "destroy_env",
    "list_envs",
    "shutdown",
    "__version__",
]


def destroy_env(env_id: str) -> None:
    """销毁指定的 BroSDK 环境（删除环境及其所有持久化数据）。

    :param env_id: 要销毁的环境 ID。
    """
    ENV_MANAGER.destroy_env(env_id)


def list_envs():
    """返回当前账号下的所有环境列表（dict 列表）。"""
    return ENV_MANAGER.list_envs()


def shutdown() -> None:
    """关闭 BroSDK（释放原生资源）。通常在进程退出前调用一次。"""
    ENV_MANAGER.shutdown()
