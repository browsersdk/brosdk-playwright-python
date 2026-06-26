"""示例 3：混合用法 —— BroSDK 指纹环境 + 原生 Playwright 透传。

- p.chromium.launch(env=...) 走 BroSDK 指纹环境（仅 Chrome 内核）
- p.chromium.launch() （无 env）走原生 Playwright 本地浏览器
- p.firefox / p.webkit 透传给原生 Playwright（无指纹，首次访问会 warning）
运行：python examples/03_pass_through.py
"""

import brosdk_playwright as bp

bp.configure(api_key="YOUR_API_KEY", work_dir="./.brosdk")

from brosdk_playwright import sync_playwright

with sync_playwright() as p:
    # 1) BroSDK 指纹环境（Chrome 内核）
    bro_browser = p.chromium.launch(env={"kernel_version": "134"})
    page = bro_browser.new_page()
    page.goto("https://example.com")
    print("[BroSDK] 标题:", page.title(), "| env:", bro_browser.brosdk_env_id)
    bro_browser.close()

    # 2) 原生 Playwright 本地浏览器（不传 env）
    #    需本地已安装 playwright 浏览器：playwright install chromium
    # local = p.chromium.launch(headless=True)
    # page = local.new_page()
    # page.goto("https://example.com")
    # print("[Local] 标题:", page.title())
    # local.close()

    # 3) firefox / webkit 透传（无指纹，仅控制台 warning）
    # fx = p.firefox.launch(headless=True)
    # page = fx.new_page()
    # page.goto("https://example.com")
    # print("[Firefox] 标题:", page.title())
    # fx.close()

bp.shutdown()
