"""_sdk 模块测试：异步事件 → 同步 launch/close 桥接（核心价值）。

用 FakeBrosdkManager（conftest 提供）注入伪 SDK，验证：
- launch_browser 同步等待 20111 事件并返回 cdp_port
- 20112/20113 失败事件正确抛出 BroSDKError
- 超时正确处理
- resolve_env 的 env_id 复用 / 临时创建两条路径
- 环境创建、销毁、列表
"""

import json

import pytest

from brosdk_playwright._config import BroSDKError
from brosdk_playwright._sdk import (
    ENV_MANAGER,
    EVT_BROWSER_OPEN_FAILED,
    EVT_BROWSER_OPEN_SUCCESS,
    EVT_BROWSER_OPEN_TIMEOUT,
)
from tests.conftest import FakeSdkEvent


# ── launch_browser 异步→同步桥接 ────────────────────────────────────────────

def test_launch_browser_returns_cdp_port(manager_with_fake, fake_manager):
    port = ENV_MANAGER.launch_browser("env-1")
    assert isinstance(port, int)
    assert port >= 9222


def test_launch_browser_failure_raises(manager_with_fake, fake_manager):
    fake_manager.open_events = [
        FakeSdkEvent(EVT_BROWSER_OPEN_FAILED, '{"type":"browser-open-failed","data":{"envId":"env-1"}}'),
    ]
    with pytest.raises(BroSDKError, match="browser open failed"):
        ENV_MANAGER.launch_browser("env-1", timeout=5)


def test_launch_browser_timeout_event_raises(manager_with_fake, fake_manager):
    fake_manager.open_events = [
        FakeSdkEvent(EVT_BROWSER_OPEN_TIMEOUT, '{"type":"browser-open-timeout"}'),
    ]
    with pytest.raises(BroSDKError, match="timeout"):
        ENV_MANAGER.launch_browser("env-1", timeout=5)


def test_launch_browser_no_event_timeout(manager_with_fake, fake_manager):
    # open_events 为空且 fake_manager 不派发任何事件 → 走 wait 超时
    fake_manager.open_events = []  # browser_open 不会派发
    # 覆盖 browser_open 使其不派发
    fake_manager.browser_open = lambda json_str: None
    with pytest.raises(BroSDKError, match="timed out"):
        ENV_MANAGER.launch_browser("env-1", timeout=1.0)


def test_launch_browser_browser_open_rejected(manager_with_fake, fake_manager):
    fake_manager.browser_open_should_raise = "rejected by SDK"
    with pytest.raises(BroSDKError, match="rejected"):
        ENV_MANAGER.launch_browser("env-1", timeout=5)


def test_launch_browser_adds_remote_debugging_port_zero(manager_with_fake, fake_manager):
    ENV_MANAGER.launch_browser("env-1")
    # 检查传给 browser_open 的请求里含 --remote-debugging-port=0
    # fake_manager.browser_open 解析了 json_str，但没保存；通过事件间接验证
    # 改为直接检查：重新触发并捕获请求
    captured = {}
    original = fake_manager.browser_open

    def capture(json_str):
        captured["req"] = json.loads(json_str)
        original(json_str)

    fake_manager.browser_open = capture
    ENV_MANAGER.launch_browser("env-2", args=["--no-first-run"])
    req = captured["req"]
    args = req["envs"][0]["args"]
    assert "--no-first-run" in args
    assert "--remote-debugging-port=0" in args
    assert "--remote-allow-origins=*" in args


def test_launch_browser_does_not_duplicate_debugging_port(manager_with_fake, fake_manager):
    captured = {}
    original = fake_manager.browser_open

    def capture(json_str):
        captured["req"] = json.loads(json_str)
        original(json_str)

    fake_manager.browser_open = capture
    # 用户已指定端口，不应重复添加
    ENV_MANAGER.launch_browser("env-3", args=["--remote-debugging-port=9333"])
    args = captured["req"]["envs"][0]["args"]
    assert args.count("--remote-debugging-port=9333") == 1
    assert "--remote-debugging-port=0" not in args


def test_launch_browser_passes_urls_cookies_extensions(manager_with_fake, fake_manager):
    captured = {}
    original = fake_manager.browser_open

    def capture(json_str):
        captured["req"] = json.loads(json_str)
        original(json_str)

    fake_manager.browser_open = capture
    ENV_MANAGER.launch_browser(
        "env-4",
        urls=["https://example.com"],
        cookies=[{"name": "k", "value": "v", "domain": ".x.com"}],
        extensions=[{"name": "ext", "id": "abc", "packType": "unpack", "component": False}],
        forward="socks5://jump:1",
    )
    spec = captured["req"]["envs"][0]
    assert spec["urls"] == ["https://example.com"]
    assert spec["cookies"][0]["name"] == "k"
    assert spec["extensions"][0]["id"] == "abc"
    assert spec["forward"] == "socks5://jump:1"


# ── 事件 data 解析（多结构兼容）──────────────────────────────────────────────

def test_extract_env_port_flat():
    from brosdk_playwright._sdk import BroSDKEnvManager
    payload = {"envId": "env-1", "remoteDebuggingPort": 9999}
    assert BroSDKEnvManager._extract_env_port(payload, "env-1") == 9999


def test_extract_env_port_envelope():
    from brosdk_playwright._sdk import BroSDKEnvManager
    payload = {
        "type": "browser-open-success",
        "data": {"envId": "env-1", "remoteDebuggingPort": 8888, "cdpReady": True},
    }
    assert BroSDKEnvManager._extract_env_port(payload, "env-1") == 8888


def test_extract_env_port_env_list():
    from brosdk_playwright._sdk import BroSDKEnvManager
    payload = {
        "type": "browser-open-success",
        "data": {"envId": "other"},
        "envList": [
            {"envId": "other", "remoteDebuggingPort": 1},
            {"envId": "env-1", "remoteDebuggingPort": 7777},
        ],
    }
    assert BroSDKEnvManager._extract_env_port(payload, "env-1") == 7777


def test_extract_env_port_string_payload():
    from brosdk_playwright._sdk import BroSDKEnvManager
    payload = json.dumps({"envId": "env-1", "remoteDebuggingPort": 6666})
    assert BroSDKEnvManager._extract_env_port(payload, "env-1") == 6666


def test_extract_env_port_no_match():
    from brosdk_playwright._sdk import BroSDKEnvManager
    assert BroSDKEnvManager._extract_env_port({"data": {"envId": "other"}}, "env-1") is None


# ── resolve_env ──────────────────────────────────────────────────────────────

def test_resolve_env_explicit_env_id(manager_with_fake, fake_manager):
    env_id = ENV_MANAGER.resolve_env({"env_id": "explicit-123"})
    assert env_id == "explicit-123"
    assert len(fake_manager.created_envs) == 0  # 不创建


def test_resolve_env_creates_when_no_env_id(manager_with_fake, fake_manager):
    env_id = ENV_MANAGER.resolve_env({"kernel_version": "134"})
    assert env_id in fake_manager.created_envs


def test_resolve_env_ephemeral_distinct(manager_with_fake, fake_manager):
    a = ENV_MANAGER.resolve_env({"kernel_version": "134"})
    b = ENV_MANAGER.resolve_env({"kernel_version": "134"})
    assert a != b  # 无 env_id 时每次创建新环境
    assert len(fake_manager.created_envs) == 2


def test_resolve_env_builds_finger_with_proxy(manager_with_fake, fake_manager):
    ENV_MANAGER.resolve_env({"kernel_version": "131", "proxy": "socks5://h:1", "region": "US"})
    env_id = list(fake_manager.created_envs)[0]
    cfg = fake_manager.created_envs[env_id]
    assert cfg["finger"]["kernelVersion"] == "131"
    assert cfg["proxy"] == "socks5://h:1"
    assert cfg["region"] == "US"


def test_resolve_env_finger_override(manager_with_fake, fake_manager):
    custom_finger = {"kernel": "Chrome", "kernelVersion": "134", "canvas": 4, "webGl": 1}
    ENV_MANAGER.resolve_env({"finger": custom_finger})
    env_id = list(fake_manager.created_envs)[0]
    assert fake_manager.created_envs[env_id]["finger"] == custom_finger


# ── list_envs / destroy_env ──────────────────────────────────────────────────

def test_list_envs(manager_with_fake, fake_manager):
    ENV_MANAGER.resolve_env({"kernel_version": "134"})
    ENV_MANAGER.resolve_env({"kernel_version": "134"})
    envs = ENV_MANAGER.list_envs()
    assert len(envs) == 2


def test_destroy_env(manager_with_fake, fake_manager):
    env_id = ENV_MANAGER.resolve_env({"kernel_version": "134"})
    assert env_id in fake_manager.created_envs
    ENV_MANAGER.destroy_env(env_id)
    assert env_id in fake_manager.destroyed_envs
    assert env_id not in fake_manager.created_envs


# ── close_browser ────────────────────────────────────────────────────────────

def test_close_browser_succeeds(manager_with_fake, fake_manager):
    # 不抛异常即成功（fake_manager 默认派发 close-success）
    ENV_MANAGER.close_browser("env-1", timeout=5)


def test_close_browser_best_effort_on_error(manager_with_fake, fake_manager):
    # browser_close 抛错也不应让 close_browser 抛出
    def raise_close(env_id):
        raise RuntimeError("close failed")
    fake_manager.browser_close = raise_close
    ENV_MANAGER.close_browser("env-1", timeout=5)  # 不抛
