"""pytest 共享夹具：伪 BrosdkManager + 配置隔离。"""

import os
import sys
import threading
import time
import uuid

import pytest

# 让测试能 import 兄弟包 brosdk_playwright
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _set_env(monkeypatch, **kw):
    """清空所有 BROSDK_* 环境变量后按 kw 设置。"""
    for k in list(os.environ):
        if k.startswith("BROSDK_"):
            monkeypatch.delenv(k, raising=False)
    for k, v in kw.items():
        if v is not None:
            monkeypatch.setenv(k, v)


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    """每个测试重置全局单例配置，避免互相污染。"""
    _set_env(monkeypatch)  # 清空环境变量
    import brosdk_playwright._config as cfgmod
    cfgmod._CONFIG = None
    # 重置 ENV_MANAGER 单例的 SDK 状态
    from brosdk_playwright._sdk import ENV_MANAGER
    ENV_MANAGER._sdk = None
    ENV_MANAGER._config = None
    yield
    cfgmod._CONFIG = None


class FakeSdkEvent:
    """模拟 brosdk.manager.SdkEvent。"""

    def __init__(self, code: int, data: str = ""):
        self.code = code
        self.data = data

    def data_json(self):
        import json
        try:
            return json.loads(self.data)
        except Exception:
            return self.data


class FakeBrosdkManager:
    """伪 BrosdkManager：不加载真实动态库。

    - on_event/off_event 维护回调列表（与真实实现一致）。
    - browser_open 在后台线程延迟派发事件，模拟异步回调。
    - env_create / env_destroy / env_page 返回可控结果。
    """

    def __init__(self):
        self._callbacks = []
        self._lock = threading.Lock()
        self._next_env_seq = 1
        self.created_envs = {}      # envId -> config
        self.destroyed_envs = []
        self.open_events = []       # 每次 browser_open 要派发的事件序列
        self.close_events = []
        self.open_delay = 0.05
        self.close_delay = 0.05
        self.browser_open_should_raise = None
        # 默认：browser_open 成功，端口递增
        self._next_port = 9222

    # 事件订阅（签名与 BrosdkManager 一致）
    def on_event(self, cb):
        with self._lock:
            self._callbacks.append(cb)

    def off_event(self, cb):
        with self._lock:
            try:
                self._callbacks.remove(cb)
            except ValueError:
                pass

    def _dispatch(self, event):
        with self._lock:
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb(event)
            except Exception:
                pass

    def _dispatch_after(self, delay, events):
        def _run():
            time.sleep(delay)
            for ev in events:
                self._dispatch(ev)
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    # 环境 CRUD
    def env_create(self, config):
        env_id = str(self._next_env_seq)
        self._next_env_seq += 1
        self.created_envs[env_id] = config
        return {"data": {"envId": env_id, "envName": config.get("envName", "")}}

    def env_destroy(self, env_id):
        self.destroyed_envs.append(env_id)
        self.created_envs.pop(env_id, None)
        return {"data": None}

    def env_page(self, page=1, page_size=100):
        lst = [{"envId": eid, "envName": c.get("envName", "")} for eid, c in self.created_envs.items()]
        return {"data": {"list": lst, "total": len(lst)}}

    # 浏览器 open / close
    def browser_open(self, json_str):
        if self.browser_open_should_raise:
            raise RuntimeError(self.browser_open_should_raise)
        import json as _json
        req = _json.loads(json_str)
        env_id = req["envs"][0]["envId"]
        port = self._next_port
        self._next_port += 1
        events = self.open_events or [
            FakeSdkEvent(20110, '{"type":"browser-open"}'),
            FakeSdkEvent(20111, _json.dumps({
                "type": "browser-open-success",
                "data": {"envId": env_id, "remoteDebuggingPort": port, "cdpReady": True},
            })),
        ]
        self._dispatch_after(self.open_delay, events)

    def browser_close(self, env_id):
        events = self.close_events or [FakeSdkEvent(20141, '{"type":"browser-close-success"}')]
        self._dispatch_after(self.close_delay, events)

    def init(self, *a, **kw):
        return "{}"

    def shutdown(self):
        pass


@pytest.fixture
def fake_manager():
    return FakeBrosdkManager()


@pytest.fixture
def manager_with_fake(fake_manager, tmp_path):
    """注入伪 manager 到 ENV_MANAGER 单例。"""
    from brosdk_playwright._sdk import ENV_MANAGER
    from brosdk_playwright._config import Config
    ENV_MANAGER._set_sdk_for_test(
        fake_manager,
        config=Config(api_key="k", user_sig="sig", work_dir=str(tmp_path), configured=True),
        work_dir=str(tmp_path),
    )
    return ENV_MANAGER
