"""_config 模块测试：configure() 验证、环境变量回退、单例。"""

import pytest

import brosdk_playwright as bp
from brosdk_playwright._config import Config, configure, get_config


def test_configure_requires_auth(monkeypatch):
    # 无 api_key 也无 user_sig → 报错
    with pytest.raises(bp.BroSDKError, match="authentication"):
        configure()


def test_configure_with_api_key(monkeypatch):
    cfg = configure(api_key="ak-123", work_dir="./wd")
    assert cfg.api_key == "ak-123"
    assert cfg.user_sig is None
    assert cfg.work_dir == "./wd"
    assert cfg.port == 0
    assert cfg.customer_id == "default"
    assert cfg.configured is True


def test_configure_with_user_sig(monkeypatch):
    cfg = configure(user_sig="sig-xyz", port=9527)
    assert cfg.user_sig == "sig-xyz"
    assert cfg.api_key is None
    assert cfg.port == 9527


def test_env_var_fallback_api_key(monkeypatch):
    monkeypatch.setenv("BROSDK_API_KEY", "env-ak")
    monkeypatch.setenv("BROSDK_WORK_DIR", "./env-wd")
    monkeypatch.setenv("BROSDK_PORT", "8888")
    cfg = get_config()  # 未显式 configure，应自动用环境变量
    assert cfg.api_key == "env-ak"
    assert cfg.work_dir == "./env-wd"
    assert cfg.port == 8888


def test_env_var_fallback_user_sig(monkeypatch):
    monkeypatch.setenv("BROSDK_USER_SIG", "env-sig")
    cfg = get_config()
    assert cfg.user_sig == "env-sig"


def test_get_config_without_anything_raises(monkeypatch):
    with pytest.raises(bp.BroSDKError, match="not configured"):
        get_config()


def test_work_dir_resolved_creates_dir(tmp_path):
    cfg = Config(work_dir=str(tmp_path / "sub"), api_key="k")
    d = cfg.work_dir_resolved()
    import os
    assert os.path.isdir(d)


def test_port_coercion_from_env_string(monkeypatch):
    monkeypatch.setenv("BROSDK_API_KEY", "ak")
    monkeypatch.setenv("BROSDK_PORT", "not-a-number")
    cfg = get_config()
    assert cfg.port == 0  # 非法端口回退 0


def test_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("BROSDK_API_KEY", "env-ak")
    cfg = configure(api_key="explicit-ak")
    assert cfg.api_key == "explicit-ak"


def test_resolve_user_sig_uses_existing(monkeypatch):
    from brosdk_playwright._config import resolve_user_sig
    cfg = Config(user_sig="already-have-sig", api_key="k")
    assert resolve_user_sig(cfg) == "already-have-sig"


def test_resolve_user_sig_exchanges_when_missing(monkeypatch):
    from brosdk_playwright._config import resolve_user_sig

    class FakeClient:
        def __init__(self, api_key, customer_id="default"):
            pass
        def get_user_sig(self, duration):
            return f"exchanged-sig-{duration}"

    # patch BrosdkApiClient
    import brosdk.api as api_mod
    monkeypatch.setattr(api_mod, "BrosdkApiClient", FakeClient)

    cfg = Config(api_key="k", sig_duration=100)
    sig = resolve_user_sig(cfg)
    assert sig == "exchanged-sig-100"
    assert cfg.user_sig == "exchanged-sig-100"  # 缓存回 config
