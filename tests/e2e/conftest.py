"""E2E 测试共享夹具：读取 config/e2e.config.json，配置真实 SDK。

位于 tests/e2e/ 子目录，与 tests/conftest.py 的 _isolate_config 夹具隔离
（pytest 只向上收集最近的 conftest，但 _isolate_config 是 autouse ——
为避免它污染 e2e，本文件覆盖同名夹具为空操作）。
"""

import json
import os
import sys

import pytest

# 项目根目录（tests/e2e/ 往上三级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 可 import 兄弟包 brosdk_playwright
sys.path.insert(0, _PROJECT_ROOT)

CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "e2e.config.json")


def _load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        pytest.skip(f"e2e.config.json not found at {CONFIG_PATH}; copy e2e.config.template.json and fill in api_key")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def _isolate_config():
    """覆盖 tests/conftest.py 的同名 autouse 夹具。

    e2e 测试需要保留真实 SDK 配置，不能被重置，故此处替换为空操作。
    """
    yield


@pytest.fixture(scope="session")
def e2e_cfg() -> dict:
    return _load_config()


@pytest.fixture(scope="session")
def configured(e2e_cfg):
    """在整个 e2e session 内配置一次真实 SDK。"""
    import brosdk_playwright as bp
    bp.configure(
        api_key=e2e_cfg["api_key"],
        work_dir=e2e_cfg.get("work_dir", "./.brosdk"),
        customer_id=e2e_cfg.get("customer_id", "default"),
        port=e2e_cfg.get("port", 0),
        lib_path=e2e_cfg.get("lib_path"),
    )
    yield e2e_cfg
    # session 结束时关闭 SDK
    try:
        bp.shutdown()
    except Exception:
        pass
