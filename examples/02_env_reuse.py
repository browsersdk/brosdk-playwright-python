"""示例 2：环境复用 —— 用 env_id 复用已有环境，自动恢复登录态。

BroSDK 环境本身持久化 cookie/storage：同一 envId 再次启动会自动恢复上次的
登录状态。所以"会话复用"= 记住 envId 并在下次 launch(env={"env_id": ...}) 时传回。

本示例演示：第一次启动创建环境并拿到 envId，保存它；第二次用同一 envId 启动，
登录态自动恢复。
运行：python examples/02_env_reuse.py
"""

import brosdk_playwright as bp

bp.configure(api_key="YOUR_API_KEY", work_dir="./.brosdk")

from brosdk_playwright import sync_playwright

# 第一次：创建环境，拿到 envId
with sync_playwright() as p:
    browser = p.chromium.launch(env={
        "kernel_version": "134",
        "proxy": "socks5://user:pass@proxy.host:1080",
    })
    env_id = browser.brosdk_env_id
    print(f"新建环境 env_id={env_id}")

    page = browser.new_page()
    page.goto("https://example.com/login")
    # ... 完成登录 ...
    print("页面标题:", page.title())
    browser.close()  # 关闭浏览器，cookie/storage 自动持久化

print(f"\n请保存 env_id={env_id}，下次复用\n")

# 第二次：用同一 env_id 启动，自动恢复登录态
with sync_playwright() as p:
    browser = p.chromium.launch(env={"env_id": env_id})
    page = browser.new_page()
    page.goto("https://example.com/dashboard")
    print("复用环境后页面标题:", page.title())
    print("(登录态已自动恢复)")
    browser.close()

# 用完可销毁环境（删除环境及其所有持久化数据）
# bp.destroy_env(env_id)

bp.shutdown()
