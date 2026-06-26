"""
brosdk_playwright._sdk
======================

BroSDK 环境管理 + 异步事件 → 同步 launch/close 桥接。

核心难点
--------
``sdk_browser_open`` 是异步的：它只返回"请求已受理"，真正的启动结果（含 CDP 端口）
稍后通过 ``sdk_result_cb`` 回调以 ``eventId=20111``（browser-open-success）事件送达，
其 data JSON 形如::

    {"type":"browser-open-success",
     "data":{"envId":"...","remoteDebuggingPort":65534,"cdpReady":true}}

BroSDK 官方的各语言 Demo（Rust / Python / TS）都只是打印事件然后 sleep，
**没有任何实现真正提取过这个 CDP 端口**。本模块用 ``threading.Event`` 把这个
异步事件桥接成同步的 ``launch_browser()`` —— 这是 brosdk-playwright 的核心价值。

关联策略
--------
SDK 可能不回 reqId（reqId 可能为 0），因此用 ``event.code==20111`` + ``data.envId``
匹配；同时兼容事件 data 的"扁平"与"信封包裹"两种结构，以及 ``envList`` 兜底。
"""

from __future__ import annotations

import json
import logging
import os
import platform
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ._config import BroSDKError, Config, get_config, resolve_user_sig

logger = logging.getLogger(__name__)

__all__ = ["BroSDKEnvManager", "ENV_MANAGER"]

# ── 事件码常量（见 brosdk-docs docs/integration/callback.md）─────────────────

EVT_BROWSER_OPEN          = 20110
EVT_BROWSER_OPEN_SUCCESS  = 20111
EVT_BROWSER_OPEN_FAILED   = 20112
EVT_BROWSER_OPEN_TIMEOUT  = 20113

EVT_BROWSER_CLOSE          = 20140
EVT_BROWSER_CLOSE_SUCCESS  = 20141
EVT_BROWSER_CLOSE_FAILED   = 20142
EVT_BROWSER_CLOSE_TIMEOUT  = 20143

EVT_SDK_INIT_SUCCESS = 10111

# 默认内核版本
DEFAULT_KERNEL_VERSION = "134"


class BroSDKEnvManager:
    """单例环境管理器：封装 SDK 生命周期、环境增删、异步→同步桥接。"""

    def __init__(self) -> None:
        self._sdk = None          # BrosdkManager
        self._config: Optional[Config] = None
        self._sdk_lock = threading.Lock()

    # ── 测试钩子：注入伪 SDK（仅测试用）────────────────────────────────────

    def _set_sdk_for_test(self, fake_sdk: Any, config: Optional[Config] = None,
                          work_dir: Optional[str] = None) -> None:
        """注入一个伪 BrosdkManager，跳过真实 SDK 加载。

        仅用于单元测试，生产代码不应调用。
        """
        self._sdk = fake_sdk
        if config is not None:
            self._config = config
        elif self._config is None:
            # 用一个最小可用 Config 兜底
            self._config = Config(api_key="test", user_sig="test-sig",
                                  work_dir=work_dir or "", configured=True)

    # ── SDK 初始化（懒加载 + 幂等）─────────────────────────────────────────

    def _ensure_sdk(self):
        """加载并初始化 SDK（仅一次）。"""
        if self._sdk is not None:
            return self._sdk

        with self._sdk_lock:
            if self._sdk is not None:
                return self._sdk

            cfg = get_config()
            self._config = cfg

            # 延迟导入：测试可注入 _sdk 绕过真实 SDK
            if self._sdk is None:
                from brosdk.manager import BrosdkManager

                sdk = BrosdkManager()
                lib_path = cfg.lib_path or _default_lib_path()
                try:
                    sdk.load(lib_path)
                except (FileNotFoundError, RuntimeError) as exc:
                    # 尝试自动下载原生库后重试
                    lib_path = _maybe_download_lib(cfg, exc)
                    try:
                        sdk.load(lib_path)
                    except (FileNotFoundError, RuntimeError) as exc2:
                        raise BroSDKError(
                            f"Failed to load BroSDK native library ({lib_path}): {exc2}.\n"
                            f"The 'brosdk' PyPI package is pure-Python and does NOT ship "
                            f"the native lib. Download it from "
                            f"https://github.com/browsersdk/brosdk/releases and either:\n"
                            f"  - pass lib_path= to configure() pointing at the .dll/.dylib/.so, or\n"
                            f"  - set the BROSDK_LIB_PATH env var, or\n"
                            f"  - set auto_download=True (default) to download automatically."
                        ) from exc2

                user_sig = resolve_user_sig(cfg)
                work_dir = cfg.work_dir_resolved()
                try:
                    sdk.init(user_sig, work_dir, port=cfg.port)
                except RuntimeError as exc:
                    raise BroSDKError(f"BroSDK init failed: {exc}") from exc

                self._sdk = sdk
                logger.info("BroSDK initialized (work_dir=%s, port=%d)", work_dir, cfg.port)

            return self._sdk

    # ── 内部：事件 data 解析 ───────────────────────────────────────────────

    @staticmethod
    def _extract_env_port(payload: Any, env_id: str) -> Optional[int]:
        """从事件 data 中提取匹配 envId 的 remoteDebuggingPort。

        兼容多种结构：
        - 扁平: {"envId":.., "remoteDebuggingPort":..}
        - 信封: {"type":.., "data":{"envId":.., "remoteDebuggingPort":..}}
        - envList 兜底: {"envList":[{"envId":..,"remoteDebuggingPort":..}]}
        """
        if not payload:
            return None

        # 归一化为 dict
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return None
        if not isinstance(payload, dict):
            return None

        # 信封：取内层 data
        inner = payload.get("data", payload)
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except json.JSONDecodeError:
                inner = {}
        if not isinstance(inner, dict):
            inner = {}

        # 1) 内层直接命中
        port = _to_int(inner.get("remoteDebuggingPort"))
        if port and str(inner.get("envId", "")) == str(env_id):
            return port

        # 2) envList 兜底
        env_list = payload.get("envList") or inner.get("envList")
        if isinstance(env_list, list):
            for item in env_list:
                if isinstance(item, dict) and str(item.get("envId", "")) == str(env_id):
                    p = _to_int(item.get("remoteDebuggingPort"))
                    if p:
                        return p

        # 3) 内层有端口但 envId 不匹配（仍返回，调用方已按 code 过滤）
        if port:
            return port
        return None

    # ── 环境 CRUD ──────────────────────────────────────────────────────────

    def resolve_env(self, env: Optional[Dict[str, Any]]) -> str:
        """把 ``launch(env=...)`` 的 env 字典解析为 envId。

        解析规则：
        1. ``env_id`` 直接给出 → 原样返回（复用已有环境，用户自管 envId）。
        2. 没给出 → 创建一个新环境（``brosdk-pw-<uuid>``），返回其 envId。

        会话复用：直接传上次拿到的 ``env_id`` 即可——BroSDK 环境本身持久化
        cookie/storage，同一 envId 再次启动会自动恢复登录态。

        :raises BroSDKError: 环境创建失败。
        """
        sdk = self._ensure_sdk()

        env = env or {}

        # 1) 显式 envId：复用已有环境
        env_id = env.get("env_id") or env.get("envId")
        if env_id:
            logger.debug("resolve_env: reuse explicit envId=%s", env_id)
            return str(env_id)

        # 2) 创建新环境
        new_id = self._create_env(env)
        logger.info("resolve_env: created env %s", new_id)
        return new_id

    def _create_env(self, env: Dict[str, Any]) -> str:
        """调用 sdk.env_create 创建环境，返回 envId。"""
        sdk = self._ensure_sdk()
        cfg = self._config
        assert cfg is not None

        finger = env.get("finger") or {}
        # 用户可整体覆盖 finger，否则用便捷字段拼装
        if not finger:
            finger = {
                "kernel":        "Chrome",
                "kernelVersion": env.get("kernel_version", DEFAULT_KERNEL_VERSION),
            }
            system = env.get("system")
            if system:
                finger["system"] = system

        config: Dict[str, Any] = {
            "customerId": cfg.customer_id,
            "envName":    env.get("env_name") or f"brosdk-pw-{uuid.uuid4().hex[:8]}",
            "finger":     finger,
        }
        # 代理（环境创建阶段绑定，非 browser_open 阶段）
        proxy = env.get("proxy")
        if proxy:
            config["proxy"] = proxy
        region = env.get("region")
        if region:
            config["region"] = region

        try:
            result = sdk.env_create(config)
        except RuntimeError as exc:
            raise BroSDKError(f"env_create failed: {exc}") from exc

        # SDK 返回可能是 {"data":{"envId":..}} 或 {"envId":..}
        data = result.get("data") or result
        env_id = data.get("envId") or data.get("env_id")
        if not env_id:
            raise BroSDKError(f"env_create returned no envId: {result}")
        return str(env_id)

    def list_envs(self) -> List[Dict[str, Any]]:
        """返回当前账号下的环境列表。"""
        sdk = self._ensure_sdk()
        try:
            result = sdk.env_page(page=1, page_size=100)
        except RuntimeError as exc:
            raise BroSDKError(f"env_page failed: {exc}") from exc
        data = result.get("data") or result
        return data.get("list") or []

    def destroy_env(self, env_id: str) -> None:
        """销毁环境（删除环境及其所有持久化数据）。"""
        sdk = self._ensure_sdk()
        try:
            sdk.env_destroy(env_id)
        except RuntimeError as exc:
            raise BroSDKError(f"env_destroy failed: {exc}") from exc

    # ── 异步 → 同步桥接：browser open / close ──────────────────────────────

    def launch_browser(
        self,
        env_id: str,
        args: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        cookies: Optional[List[Dict[str, Any]]] = None,
        extensions: Optional[List[Dict[str, Any]]] = None,
        forward: Optional[str] = None,
        timeout: float = 60.0,
    ) -> int:
        """启动浏览器环境并同步等待 CDP 就绪，返回 CDP 端口。

        :raises BroSDKError: 启动失败、超时或 SDK 报错。
        """
        sdk = self._ensure_sdk()

        args = list(args or [])
        # 关键：--remote-debugging-port=0 让 OS 自动分配端口，
        # 实际端口由 browser-open-success 事件中的 remoteDebuggingPort 返回，
        # 从而彻底规避文档警告的"多环境端口冲突"问题。
        if not _has_flag(args, "--remote-debugging-port"):
            args.append("--remote-debugging-port=0")
        if not _has_flag(args, "--remote-allow-origins"):
            args.append("--remote-allow-origins=*")
        # macOS 必须传 parent-bundle-identifier
        if platform.system() == "Darwin" and not _has_flag(args, "--parent-bundle-identifier"):
            args.append("--parent-bundle-identifier=com.brosdk.playwright")

        env_spec: Dict[str, Any] = {"envId": env_id, "args": args}
        if urls:
            env_spec["urls"] = urls
        if cookies:
            env_spec["cookies"] = cookies
        if extensions:
            env_spec["extensions"] = extensions
        if forward:
            env_spec["forward"] = forward

        request = json.dumps({"envs": [env_spec]}, ensure_ascii=False)

        done = threading.Event()
        result_holder: Dict[str, Any] = {"port": None, "error": None}

        def _on_event(event) -> None:
            code = event.code
            if code == EVT_BROWSER_OPEN_SUCCESS:
                port = self._extract_env_port(event.data, env_id)
                if port:
                    result_holder["port"] = port
                    done.set()
            elif code in (EVT_BROWSER_OPEN_FAILED, EVT_BROWSER_OPEN_TIMEOUT):
                result_holder["error"] = (
                    f"browser open {'failed' if code == EVT_BROWSER_OPEN_FAILED else 'timeout'} "
                    f"for env {env_id}: {event.data}"
                )
                done.set()

        sdk.on_event(_on_event)
        try:
            try:
                sdk.browser_open(request)
            except RuntimeError as exc:
                raise BroSDKError(f"browser_open request rejected: {exc}") from exc

            if not done.wait(timeout=timeout):
                raise BroSDKError(
                    f"browser open timed out after {timeout}s for env {env_id}"
                )

            if result_holder["error"]:
                raise BroSDKError(result_holder["error"])

            port = result_holder["port"]
            if not port:
                raise BroSDKError(
                    f"browser-open-success received but no remoteDebuggingPort for env {env_id}: "
                    f"{event.data if 'event' in dir() else ''}"
                )
            logger.info("browser launched: env=%s cdp_port=%d", env_id, port)
            return port
        finally:
            sdk.off_event(_on_event)

    def close_browser(self, env_id: str, timeout: float = 30.0) -> None:
        """关闭浏览器环境（触发 Cookie/Storage 自动持久化）。

        best-effort：即使等不到 close-success 事件也会调用 browser_close。
        """
        sdk = self._ensure_sdk()

        done = threading.Event()
        result_holder: Dict[str, Any] = {"error": None}

        def _on_event(event) -> None:
            code = event.code
            if code == EVT_BROWSER_CLOSE_SUCCESS:
                done.set()
            elif code in (EVT_BROWSER_CLOSE_FAILED, EVT_BROWSER_CLOSE_TIMEOUT):
                result_holder["error"] = (
                    f"browser close {'failed' if code == EVT_BROWSER_CLOSE_FAILED else 'timeout'} "
                    f"for env {env_id}: {event.data}"
                )
                done.set()

        sdk.on_event(_on_event)
        try:
            try:
                sdk.browser_close(env_id)
            except RuntimeError as exc:
                logger.warning("browser_close request error for env %s: %s", env_id, exc)
                return

            done.wait(timeout=timeout)
            if result_holder["error"]:
                logger.warning("browser close issue for env %s: %s", env_id, result_holder["error"])
            else:
                logger.info("browser closed: env=%s", env_id)
        finally:
            sdk.off_event(_on_event)

    # ── 关闭 ───────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """关闭 SDK（进程退出前调用）。"""
        sdk = self._sdk
        if sdk is None:
            return
        try:
            sdk.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("SDK shutdown error: %s", exc)
        finally:
            self._sdk = None


# ── 进程级单例 ─────────────────────────────────────────────────────────────

ENV_MANAGER = BroSDKEnvManager()


# ── 辅助函数 ───────────────────────────────────────────────────────────────

def _has_flag(args: List[str], flag: str) -> bool:
    """判断 args 中是否已包含某 flag 前缀（避免重复添加）。"""
    prefix = flag.split("=")[0] + "="
    return any(a == flag or a.startswith(prefix) for a in args)


def _to_int(val: Any) -> Optional[int]:
    """宽松地把值转为 int（兼容字符串 / bool / None）。"""
    if val is None or isinstance(val, bool):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _default_lib_path() -> str:
    """按平台返回 brosdk 动态库默认路径。

    复用 brosdk.ffi.BrosdkLib.load_default 的平台选择逻辑，但仅返回路径字符串，
    不真正加载库（便于在加载失败时给出清晰的错误信息）。
    """
    import os as _os
    import platform as _platform
    import brosdk.ffi as _ffi  # 确保包可导入，并定位 brosdk 包目录

    # brosdk 包内 libs/<platform>/brosdk.{dll,dylib,so}
    base = _os.path.dirname(_os.path.dirname(_os.path.abspath(_ffi.__file__)))
    system = _platform.system()
    if system == "Windows":
        return _os.path.join(base, "libs", "windows-x64", "brosdk.dll")
    elif system == "Darwin":
        return _os.path.join(base, "libs", "macos-arm64", "brosdk.dylib")
    elif system == "Linux":
        return _os.path.join(base, "libs", "linux-x64", "libbrosdk.so")
    raise BroSDKError(f"Unsupported platform: {system}")


def _maybe_download_lib(cfg: Config, original_exc: Exception) -> str:
    """当本地找不到原生库时，按配置自动下载。

    :return: 下载后的库文件绝对路径。
    :raises BroSDKError: auto_download 关闭或下载失败时（含原始异常信息）。
    """
    if not cfg.auto_download:
        raise BroSDKError(
            f"BroSDK native library not found and auto_download is disabled. "
            f"Original error: {original_exc}. "
            f"Pass lib_path= to configure(), set BROSDK_LIB_PATH, "
            f"or enable auto_download=True."
        ) from original_exc

    from ._downloader import download_native_lib

    work_dir = cfg.work_dir_resolved()
    libs_dir = os.path.join(work_dir, "libs")
    logger.info("Native lib missing; auto-downloading to %s", libs_dir)
    try:
        lib_path = download_native_lib(libs_dir, version=cfg.lib_version)
    except BroSDKError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BroSDKError(f"Auto-download of BroSDK native lib failed: {exc}") from exc

    # 缓存到 config，避免重复下载
    cfg.lib_path = lib_path
    return lib_path

