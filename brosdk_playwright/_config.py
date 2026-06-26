"""
brosdk_playwright._config
=========================

全局 SDK 配置（进程级单例）。

BroSDK 的初始化（``sdk_init`` + userSig）是进程级的，因此认证凭据和工作目录
在这里统一管理。每个浏览器环境的指纹 / 代理 / session 配置则是 per-launch 的，
在 :meth:`BroSDKBrowserType.launch` 时通过 ``env`` 参数传入。

配置优先级
----------
1. :func:`configure` 显式传入的参数
2. 环境变量（``BROSDK_API_KEY`` / ``BROSDK_USER_SIG`` / ``BROSDK_LIB_PATH`` …）
3. 失败时在真正需要 SDK 时抛出 :class:`BroSDKError`
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

__all__ = ["BroSDKError", "Config", "configure", "get_config", "resolve_user_sig"]


class BroSDKError(RuntimeError):
    """brosdk-playwright 抛出的所有错误的基类。"""


# ── 环境变量名映射 ─────────────────────────────────────────────────────────────

_ENV_KEYS = {
    "api_key":     "BROSDK_API_KEY",
    "user_sig":    "BROSDK_USER_SIG",
    "lib_path":    "BROSDK_LIB_PATH",
    "work_dir":    "BROSDK_WORK_DIR",
    "port":        "BROSDK_PORT",
    "customer_id": "BROSDK_CUSTOMER_ID",
}


def _env(name: str) -> Optional[str]:
    val = os.environ.get(name)
    return val if val else None


# ── 配置数据 ──────────────────────────────────────────────────────────────────

@dataclass
class Config:
    """已解析的全局配置。

    不直接构造；通过 :func:`configure` 设置、 :func:`get_config` 读取。
    """

    api_key:     Optional[str] = None
    user_sig:    Optional[str] = None
    lib_path:    Optional[str] = None
    work_dir:    str = ""
    port:        int = 0
    customer_id: str = "default"
    # 令牌有效期（秒），默认 30 天；仅当需要用 api_key 换 userSig 时使用
    sig_duration: int = 2_592_000
    # 找不到原生库时是否自动从 GitHub Releases 下载（默认开启）
    auto_download: bool = True
    # 指定要下载的原生库版本；None=latest
    lib_version: Optional[str] = None
    # 是否已显式 configure 过（用于区分"未配置"与"使用默认值"）
    configured: bool = field(default=False, repr=False)

    def work_dir_resolved(self) -> str:
        """返回确保存在的工作目录绝对路径。"""
        d = self.work_dir or os.path.join(tempfile.gettempdir(), ".brosdk-playwright")
        os.makedirs(d, exist_ok=True)
        return d


# 进程级单例
_CONFIG: Optional[Config] = None


def configure(
    api_key:     Optional[str] = None,
    user_sig:    Optional[str] = None,
    lib_path:    Optional[str] = None,
    work_dir:    Optional[str] = None,
    port:        Optional[int] = None,
    customer_id: Optional[str] = None,
    sig_duration: Optional[int] = None,
    auto_download: Optional[bool] = None,
    lib_version: Optional[str] = None,
) -> Config:
    """配置 BroSDK 全局凭据与工作目录。

    所有参数均可省略，缺省时回退到对应环境变量，再回退到内置默认值。
    认证只需提供 ``api_key`` 或 ``user_sig`` 之一：
    ``user_sig`` 优先；若只有 ``api_key``，则在首次需要 SDK 时自动换取 userSig。

    :param api_key: BroSDK API Key（Bearer 令牌），用于换取 userSig。
    :param user_sig: 直接提供 userSig，跳过换取步骤。
    :param lib_path: 原生动态库路径；None 时按平台自动查找，找不到则自动下载。
    :param work_dir: SDK 工作目录（cookie/storage/内核缓存等）。
    :param port: SDK 内嵌服务端口；0=自动分配（默认），>0=指定端口。
    :param customer_id: 客户 ID，默认 "default"。
    :param sig_duration: userSig 有效期（秒），默认 30 天。
    :param auto_download: 找不到原生库时是否自动从 GitHub Releases 下载，默认 True。
    :param lib_version: 指定下载的原生库版本；None=latest。
    :return: 更新后的 :class:`Config`。
    :raises BroSDKError: 既无 api_key 也无 user_sig 且无对应环境变量。
    """
    global _CONFIG

    cfg = Config(
        api_key     = api_key     or _env(_ENV_KEYS["api_key"]),
        user_sig    = user_sig    or _env(_ENV_KEYS["user_sig"]),
        lib_path    = lib_path    or _env(_ENV_KEYS["lib_path"]),
        work_dir    = work_dir    or _env(_ENV_KEYS["work_dir"]) or "",
        port        = _coerce_port(port if port is not None else _env(_ENV_KEYS["port"])),
        customer_id = customer_id or _env(_ENV_KEYS["customer_id"]) or "default",
        sig_duration= sig_duration if sig_duration is not None else 2_592_000,
        auto_download= True if auto_download is None else auto_download,
        lib_version = lib_version or _env("BROSDK_LIB_VERSION"),
        configured  = True,
    )

    if not cfg.api_key and not cfg.user_sig:
        raise BroSDKError(
            "BroSDK requires authentication: provide api_key= (or user_sig=) "
            "to configure(), or set BROSDK_API_KEY / BROSDK_USER_SIG env var."
        )

    _CONFIG = cfg
    return cfg


def get_config() -> Config:
    """返回当前配置；若从未 :func:`configure` 过则尝试用环境变量兜底。"""
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    # 兜底：环境变量齐全时自动 configure
    if _env(_ENV_KEYS["api_key"]) or _env(_ENV_KEYS["user_sig"]):
        return configure()
    raise BroSDKError(
        "BroSDK not configured. Call brosdk_playwright.configure(api_key=...) first, "
        "or set BROSDK_API_KEY env var."
    )


def resolve_user_sig(cfg: Config) -> str:
    """确保返回一个可用的 userSig。

    优先用已配置的 user_sig；否则用 api_key 换取并缓存回 Config。
    """
    if cfg.user_sig:
        return cfg.user_sig
    if not cfg.api_key:
        raise BroSDKError("Cannot resolve userSig: neither api_key nor user_sig is set.")

    # 延迟导入，避免在没有 brosdk 的环境里 import 失败
    from brosdk.api import BrosdkApiClient

    client = BrosdkApiClient(api_key=cfg.api_key, customer_id=cfg.customer_id)
    cfg.user_sig = client.get_user_sig(duration=cfg.sig_duration)
    return cfg.user_sig


def _coerce_port(val) -> int:
    """把 int / 数字字符串 / None 统一为 int 端口（None → 0 自动分配）。"""
    if val is None or val == "":
        return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0
