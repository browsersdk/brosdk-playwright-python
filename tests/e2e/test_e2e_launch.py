"""E2E 测试：真实 BroSDK 指纹浏览器 + Playwright CDP 端到端流程。

前置条件：
  - config/e2e.config.json 已配置真实 API Key（见 e2e.config.template.json）
  - brosdk 原生动态库可用（自动下载或 lib_path 指定）
  - 首次运行可能需要下载浏览器内核（耗时较长，见 launch_timeout）

运行：
    pytest tests/e2e/ -v -s -m e2e
    pytest tests/e2e/test_e2e_launch.py::test_launch_navigate_and_screenshot -v -s -m e2e

这些用例会创建真实的 BroSDK 环境。默认 keep_env=false 时用例结束后销毁环境。
"""

import pytest

pytestmark = [pytest.mark.e2e]


@pytest.fixture
def env_builder(configured):
    """创建环境并在用例结束后按需销毁创建出的 envId。"""
    import brosdk_playwright as bp
    created_env_ids = []
    keep = configured.get("keep_env", False)

    def _build(env_overrides=None):
        env = {
            "kernel_version": configured.get("kernel_version", "134"),
        }
        if configured.get("proxy"):
            env["proxy"] = configured["proxy"]
        if env_overrides:
            env.update(env_overrides)
        return env

    yield _build

    # 清理：销毁创建的环境
    if not keep:
        for eid in created_env_ids:
            try:
                bp.destroy_env(eid)
            except Exception:
                pass


def _launch_and_get_env_id(p, env, timeout):
    """启动浏览器，返回 (browser, env_id)。"""
    browser = p.chromium.launch(env=env, timeout=timeout)
    return browser, browser.brosdk_env_id


def test_launch_navigate_and_screenshot(configured, env_builder):
    """核心 e2e：launch(env=) → 新建页 → 访问 URL → 校验标题 → 截图 → 关闭。"""
    from brosdk_playwright import sync_playwright

    env = env_builder()
    url = configured.get("test_url", "https://example.com")

    with sync_playwright() as p:
        browser = p.chromium.launch(env=env, timeout=configured.get("launch_timeout", 120))
        try:
            # BroSDK 增强字段
            assert browser.brosdk_env_id, "browser.brosdk_env_id should be set"
            assert isinstance(browser.cdp_port, int) and browser.cdp_port > 0

            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            title = page.title()
            assert title, "page title should not be empty"
            print(f"\n[OK] visited {url}, title={title!r}, env={browser.brosdk_env_id}, cdp={browser.cdp_port}")

            page.screenshot(path="e2e_screenshot.png")
            print("[OK] screenshot saved to e2e_screenshot.png")
        finally:
            browser.close()  # 断开 CDP + 关闭浏览器（自动持久化 cookie）


def test_env_id_reuses_env(configured, env_builder):
    """同一 env_id 二次启动复用同一环境（cookie/storage 自动恢复）。"""
    from brosdk_playwright import sync_playwright

    env = env_builder()
    timeout = configured.get("launch_timeout", 120)

    # 第一次：创建环境，拿到 envId
    with sync_playwright() as p:
        b1 = p.chromium.launch(env=env, timeout=timeout)
        first_env_id = b1.brosdk_env_id
        b1.close()

    # 第二次：用同一 env_id 启动，应复用同一环境
    with sync_playwright() as p:
        b2 = p.chromium.launch(env={"env_id": first_env_id}, timeout=timeout)
        try:
            assert b2.brosdk_env_id == first_env_id, (
                f"env reuse failed: first={first_env_id} second={b2.brosdk_env_id}"
            )
            print(f"\n[OK] env reuse confirmed: envId={first_env_id}")
        finally:
            b2.close()

    # 清理这个环境
    if not configured.get("keep_env", False):
        import brosdk_playwright as bp
        try:
            bp.destroy_env(first_env_id)
        except Exception:
            pass


def test_list_and_destroy_env(configured, env_builder):
    """list_envs 能看到刚创建的环境；destroy_env 能销毁。"""
    import brosdk_playwright as bp

    env = env_builder()
    # 触发环境创建
    from brosdk_playwright import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(env=env, timeout=configured.get("launch_timeout", 120))
        env_id = b.brosdk_env_id
        b.close()

    # list_envs 应包含该环境
    envs = bp.list_envs()
    env_ids = [str(e.get("envId", e.get("env_id", ""))) for e in envs]
    assert env_id in env_ids, f"env {env_id} not in list_envs result"
    print(f"\n[OK] list_envs contains {env_id} (total {len(envs)})")

    # destroy_env 销毁后不再出现在列表
    bp.destroy_env(env_id)
    envs_after = bp.list_envs()
    env_ids_after = [str(e.get("envId", e.get("env_id", ""))) for e in envs_after]
    assert env_id not in env_ids_after, f"env {env_id} should be destroyed"
    print(f"[OK] env {env_id} destroyed")
