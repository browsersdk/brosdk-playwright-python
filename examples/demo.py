#!/usr/bin/env python3
"""
brosdk-playwright Demo
======================

交互式命令行演示：配置 SDK → 启动指纹浏览器 → 用 Playwright 操作页面 → 关闭。

用法
----
    python examples/demo.py                         # 交互式菜单
    python examples/demo.py --api-key YOUR_KEY      # 预填 API Key
    python examples/demo.py --quick --api-key KEY   # 快速演示（非交互）
    python examples/demo.py --help
"""

import argparse
import os
import sys

import brosdk_playwright as bp

# ── 颜色输出 ──────────────────────────────────────────────────────────────────

try:
    import colorama
    colorama.init(autoreset=True)
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False


def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if _HAS_COLOR else text

def green(s):  return _c(s, "32")
def red(s):    return _c(s, "31")
def yellow(s): return _c(s, "33")
def cyan(s):   return _c(s, "36")
def bold(s):   return _c(s, "1")
def dim(s):    return _c(s, "2")

def ok(msg):   print(f"  {green('✓')} {msg}")
def err(msg):  print(f"  {red('✗')} {msg}")
def info(msg): print(f"  {cyan('·')} {msg}")
def warn(msg): print(f"  {yellow('!')} {msg}")


# ── 配置 ──────────────────────────────────────────────────────────────────────

def do_configure(api_key, work_dir):
    print()
    print(bold("═══ 配置 BroSDK ═══"))
    if not api_key:
        try:
            api_key = input(f"  请输入 API Key {dim('[必填]')}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
    if not api_key:
        err("API Key 不能为空")
        return False
    if not work_dir:
        work_dir = "./.brosdk"
    try:
        bp.configure(api_key=api_key, work_dir=work_dir)
        ok(f"已配置 (work_dir={work_dir})")
        return True
    except bp.BroSDKError as e:
        err(str(e))
        return False


# ── 启动浏览器并用 Playwright 操作 ───────────────────────────────────────────

def do_launch_and_browse(url, kernel_version, proxy, env_id):
    print()
    print(bold("═══ 启动指纹浏览器 + Playwright 操作 ═══"))

    env = {"kernel_version": kernel_version or "134"}
    if proxy:
        env["proxy"] = proxy
    if env_id:
        env["env_id"] = env_id  # 复用已有环境（自动恢复登录态）

    info("正在启动 BroSDK 指纹浏览器（首次可能需下载内核）...")
    try:
        from brosdk_playwright import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(env=env)
            ok(f"浏览器已启动 (env_id={browser.brosdk_env_id}, cdp_port={browser.cdp_port})")
            page = browser.new_page()
            info(f"正在访问: {url}")
            page.goto(url, wait_until="domcontentloaded")
            ok(f"页面标题: {page.title()}")
            shot = "demo_screenshot.png"
            page.screenshot(path=shot)
            ok(f"截图已保存: {shot}")
            browser.close()
            ok("浏览器已关闭（cookie/storage 已自动持久化）")
    except bp.BroSDKError as e:
        err(f"启动失败: {e}")
        return False
    except Exception as e:  # noqa: BLE001
        err(f"Playwright 错误: {e}")
        return False
    return True


# ── 环境列表 ──────────────────────────────────────────────────────────────────

def do_list_envs():
    print()
    print(bold("═══ 环境列表 ═══"))
    try:
        envs = bp.list_envs()
    except bp.BroSDKError as e:
        err(str(e))
        return
    if not envs:
        info("暂无环境")
        return
    print(f"\n  {'#':<4}{'环境 ID':<28}{'环境名称':<20}")
    print(f"  {'─'*4}{'─'*28}{'─'*20}")
    for i, env in enumerate(envs, 1):
        if isinstance(env, dict):
            print(f"  {i:<4}{cyan(env.get('envId', '')):<37}{env.get('envName', '')}")
    print()


# ── 交互式菜单 ────────────────────────────────────────────────────────────────

def run_interactive(api_key, work_dir):
    print()
    print(bold(cyan("╔══════════════════════════════════════╗")))
    print(bold(cyan("║     brosdk-playwright Demo           ║")))
    print(bold(cyan("╚══════════════════════════════════════╝")))
    print()

    configured = False
    while True:
        print()
        status = green("已配置") if configured else red("未配置")
        print(f"  SDK 状态: {status}")
        print()
        print(f"  {bold('1.')} 配置 BroSDK (API Key)")
        print(f"  {bold('2.')} 查看环境列表")
        print(f"  {bold('3.')} 启动指纹浏览器并访问页面")
        print(f"  {bold('q.')} 退出")
        print()
        try:
            choice = input(f"  {bold('请选择')} [1-3/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "1":
            configured = do_configure(api_key, work_dir)
        elif choice == "2":
            if not configured:
                warn("请先配置 SDK")
                continue
            do_list_envs()
        elif choice == "3":
            if not configured:
                warn("请先配置 SDK")
                continue
            try:
                url = input(f"  访问 URL {dim('[默认 https://example.com]')}: ").strip() or "https://example.com"
                kv = input(f"  内核版本 {dim('[默认 134]')}: ").strip() or "134"
                proxy = input(f"  代理 {dim('[可选]')}: ").strip() or None
                sid = input(f"  env_id {dim('[可选，复用已有环境]')}: ").strip() or None
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            do_launch_and_browse(url, kv, proxy, sid)
        elif choice in ("q", "quit", "exit"):
            break
        else:
            warn("无效选择")

    print()
    info("正在关闭 SDK...")
    try:
        bp.shutdown()
        ok("已关闭")
    except Exception as e:  # noqa: BLE001
        warn(f"关闭出错: {e}")
    print(cyan("再见！"))


def run_quick(api_key, work_dir, url):
    print(bold(cyan("── brosdk-playwright Quick Demo ──")))
    if not do_configure(api_key, work_dir):
        sys.exit(1)
    do_launch_and_browse(url, "134", None, None)
    try:
        bp.shutdown()
    except Exception:  # noqa: BLE001
        pass


def main():
    parser = argparse.ArgumentParser(description="brosdk-playwright Demo")
    parser.add_argument("--api-key", default="", help="BroSDK API Key")
    parser.add_argument("--work-dir", default="", help="SDK 工作目录")
    parser.add_argument("--url", default="https://example.com", help="快速模式访问的 URL")
    parser.add_argument("--quick", action="store_true", help="快速演示模式")
    args = parser.parse_args()

    if args.quick:
        run_quick(args.api_key, args.work_dir, args.url)
    else:
        run_interactive(args.api_key, args.work_dir)


if __name__ == "__main__":
    main()
