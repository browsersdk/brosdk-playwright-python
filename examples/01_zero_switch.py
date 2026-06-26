"""示例 1：零切换 —— 只改 import，加上 env 配置即可获得指纹浏览器。

运行前提：已配置 BROSDK_API_KEY 环境变量，或修改下方 configure() 调用填入真实 API Key。
运行：python examples/01_zero_switch.py
"""

import brosdk_playwright as bp

# 1) 全局配置 SDK 认证（进程级，只需一次）
bp.configure(
    api_key="YOUR_API_KEY",          # 或设置环境变量 BROSDK_API_KEY
    work_dir="./.brosdk",            # SDK 工作目录
)

# 2) 与原生 Playwright 完全一致的用法，仅 import 路径不同
from brosdk_playwright import sync_playwright

with sync_playwright() as p:
    # launch(env=...) 走 BroSDK：创建指纹环境 → 启动浏览器 → CDP 连接
    browser = p.chromium.launch(env={
        "kernel_version": "134",
        "proxy": "socks5://user:pass@proxy.host:1080",   # 可选
    })
    page = browser.new_page()
    page.goto("https://example.com")
    print("页面标题:", page.title())
    page.screenshot(path="example.png")
    browser.close()    # 断开 CDP + 关闭浏览器（自动持久化 cookie）

bp.shutdown()
