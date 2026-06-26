# brosdk-playwright

[English](README_EN.md) | 简体中文

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

`brosdk-playwright` 是 [BroSDK](https://www.brosdk.com/) 指纹浏览器与 [Playwright](https://playwright.dev/) 自动化的**一键式集成方案**。

> **BroSDK 负责"造环境"**（指纹 / 代理 / 会话持久化），**Playwright 负责"干活"**（页面自动化），两者通过 CDP（Chrome DevTools Protocol）桥接。

只需把 import 路径从 `playwright.sync_api` 换成 `brosdk_playwright`，即可在**不改变任何 Playwright 使用习惯**的前提下，获得多版本指纹内核、独立代理 IP、Cookie/Storage 会话持久化能力。

```python
import brosdk_playwright as bp
bp.configure(api_key="your-api-key", work_dir="./.brosdk")

from brosdk_playwright import sync_playwright   # 与原生签名完全一致

with sync_playwright() as p:
    browser = p.chromium.launch(env={           # per-browser 环境配置
        "env_id": "2070365861541056512",   # 复用已有环境，自动恢复登录态
        "kernel_version": "134",
        "proxy": "socks5://user:pass@host:1080",
    })
    page = browser.new_page()
    page.goto("https://example.com")
    browser.close()                              # 断开 CDP + 关闭浏览器（自动持久化 cookie）

bp.shutdown()
```

---

## 核心能力

- **零切换成本**：`sync_playwright()` 与 Playwright 官方签名完全一致；所有 Playwright API（`new_page`/`goto`/`click`/`screenshot`/…）原样可用。
- **指纹环境管理**：自动创建/复用 BroSDK 浏览器环境（独立指纹、独立代理）。
- **会话持久化**：通过 `env_id` 复用已有环境，同一环境自动恢复上次的 Cookie/Storage/登录态。
- **CDP 自动桥接**：内部把 BroSDK 异步启动事件（`browser-open-success`）桥接成同步的 `launch()`，自动获取 CDP 端口并连接 Playwright。
- **多环境并发**：每个环境自动分配独立 CDP 端口，规避端口冲突。
- **混合用法**：`p.chromium.launch()`（无 `env`）走原生 Playwright；`p.firefox`/`p.webkit` 透传给原生 Playwright。

---

## 工作原理

```
用户代码 (Playwright API, 不变)
        │
        ▼
brosdk-playwright 包装层
  ┌─────────────────────────────────────────┐
  │ _BroBrowserType.launch(env=...)         │
  │   1. resolve_env  → 创建/复用环境        │
  │   2. launch_browser → sdk.browser_open  │
  │      (异步事件 20111 → 同步等待 CDP 端口) │
  │   3. connect_over_cdp → Playwright 连接  │
  └─────────────────────────────────────────┘
        │
        ▼
BroSDK 原生 SDK (brosdk.dll/.dylib/.so)
  指纹内核 · 代理 · Cookie/Storage 持久化
```

**关键技术点**：`sdk_browser_open` 是异步的——CDP 端口不在返回值里，而是在事件回调 `eventId=20111`（`browser-open-success`）的 `data.remoteDebuggingPort` 字段中送达。本包用 `threading.Event` 把这个异步事件桥接成同步的 `launch()`，这是本项目的核心价值（BroSDK 官方各语言 Demo 都只是 `sleep` 等待，从未提取过该端口）。

---

## 安装

```bash
pip install brosdk-playwright
```

从源码安装：

```bash
git clone https://github.com/browsersdk/brosdk-playwright-python.git
cd brosdk-playwright-python
pip install .
```

还需要：

| 项目 | 要求 |
|------|------|
| Python | 3.8+ |
| 原生库 | BroSDK 动态库（`brosdk.dll` / `brosdk.dylib` / `libbrosdk.so`）。`brosdk` PyPI 包**不含**原生库，但 brosdk-playwright 会在首次使用时**自动从 GitHub Releases 下载**（见下文"原生库自动下载"） |
| 认证 | BroSDK API Key（或直接提供 userSig） |

Playwright 浏览器二进制仅在 **不走 BroSDK**（`launch()` 不传 `env`，或用 `firefox`/`webkit`）时才需要 `playwright install`；走 BroSDK 时浏览器内核由 BroSDK 管理。

### 原生库自动下载

`brosdk` PyPI 包是纯 Python 包，不附带原生动态库。`brosdk-playwright` 在以下情况会**自动**从 [GitHub Releases](https://github.com/browsersdk/brosdk/releases) 下载并解压当前平台的动态库到工作目录的 `libs/` 下：

- 未指定 `lib_path`，且本地（brosdk 包目录或工作目录）找不到动态库时；
- 默认开启，无需任何配置。

如需关闭自动下载（例如离线环境），传入 `auto_download=False`，并手动通过 `lib_path=` 指定已下载的库路径：

```python
bp.configure(api_key="...", lib_path="/path/to/brosdk.dll", auto_download=False)
```

也可指定下载特定版本：`bp.configure(api_key="...", lib_version="1.0.0.5")`。

---

## 快速开始

### 1. 配置 SDK（进程级，只需一次）

```python
import brosdk_playwright as bp

bp.configure(
    api_key="your-api-key",     # 或设置环境变量 BROSDK_API_KEY
    work_dir="./.brosdk",       # SDK 工作目录
    # lib_path="...",           # 可选：指定动态库路径（缺省时自动查找/下载）
    # auto_download=True,       # 可选：找不到库时自动从 GitHub Releases 下载（默认开启）
    # lib_version="1.0.1.1",    # 可选：指定下载的库版本（默认 latest）
    # port=0,                   # 可选：0=自动分配端口（默认）
    # customer_id="default",    # 可选
)
```

也支持纯环境变量配置（无需 `configure`）：

```bash
export BROSDK_API_KEY=your-api-key
export BROSDK_WORK_DIR=./.brosdk
```

### 2. 像 Playwright 一样写代码

```python
from brosdk_playwright import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(env={"kernel_version": "134"})
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())
    browser.close()
```

### 运行 Demo

```bash
python examples/demo.py --api-key YOUR_API_KEY            # 交互式
python examples/demo.py --quick --api-key YOUR_API_KEY    # 快速演示
```

---

## `env` 配置参考

`p.chromium.launch(env={...})` 的 `env` 字典支持以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `env_id` | string | 直接指定 BroSDK 环境 ID，复用已有环境（自动恢复登录态）。省略则创建新环境 |
| `kernel_version` | string | Chrome 内核版本，如 `"134"`/`"131"`/`"127"`，默认 `"134"` |
| `proxy` | string | 代理地址，如 `socks5://user:pass@host:1080` |
| `region` | string | 国家代号（无法获取代理时生成对应区域 IP） |
| `system` | string | 操作系统，如 `"Windows 11"` |
| `finger` | dict | 完整指纹配置（整体覆盖，详见 BroSDK 文档） |
| `env_name` | string | 环境名称（默认自动生成） |
| `args` | list | 追加的 Chromium 启动参数 |
| `urls` | list | 启动后自动打开的 URL 列表 |
| `cookies` | list | 启动时注入的 Cookie（WebExtension API 格式） |
| `extensions` | list | 加载的扩展列表 |
| `forward` | string | 本次启动使用的前置跳板 |
| `launch_timeout` | float | 启动超时（秒），默认 60 |

> 会话复用：记住 `browser.brosdk_env_id`，下次 `launch(env={"env_id": ...})` 传入即可——
> BroSDK 环境本身持久化 cookie/storage，同一 envId 再次启动自动恢复登录态。
> 省略 `env_id` 时创建新环境。

---

## API 概览

### 模块级

| 名称 | 说明 |
|------|------|
| `configure(api_key=..., ...)` | 配置 SDK 认证与工作目录（进程级） |
| `sync_playwright()` | 与 Playwright 同名上下文管理器，返回包装后的 `Playwright` |
| `BroSDKError` | 本包抛出的所有错误的基类 |
| `list_envs()` | 返回当前账号下的环境列表 |
| `destroy_env(env_id)` | 销毁环境（删除环境及其所有持久化数据） |
| `shutdown()` | 关闭 BroSDK，释放原生资源 |
| `get_config()` | 读取当前配置 |

### `browser` 增强字段

走 BroSDK 启动的 `browser` 对象额外暴露：

| 字段 | 说明 |
|------|------|
| `browser.brosdk_env_id` | 关联的 BroSDK 环境 ID |
| `browser.cdp_port` | 浏览器 CDP 调试端口 |

---

## 适用场景

1. **多账号运营 SaaS**：每个账号用独立 `env_id` 隔离环境，独立指纹/代理/cookie。
2. **自动化测试**：现有 Playwright 测试套件零改动获得指纹和代理能力。
3. **AI Agent 浏览器任务**：在 LangChain/AutoGPT 工具链中为 Playwright 注入指纹环境。
4. **ERP/CRM 集成**：企业 Playwright 脚本复用，带会话持久化。

---

## 项目结构

```text
brosdk-playwright-python/
├── brosdk_playwright/
│   ├── __init__.py        # 公共 API 导出
│   ├── _config.py         # 全局配置 + 认证（configure / get_config）
│   ├── _sdk.py            # 环境管理 + 异步事件→同步 launch/close 桥接
│   ├── _downloader.py     # 原生库自动下载（GitHub Releases）
│   ├── _playwright.py     # Playwright API 包装层
│   └── sync_api.py        # sync_playwright() 上下文管理器
├── examples/              # 使用示例 + 交互式 CLI Demo (demo.py)
├── config/               # E2E 测试配置（e2e.config.json，含密钥，已 gitignore）
├── tests/                # 单元测试 + e2e/ 子目录（无需真实 SDK/浏览器）
└── pyproject.toml
```

## 开发

```bash
pip install -e ".[dev]"
pytest
```

测试不依赖真实 SDK、浏览器或 API Key——通过伪 `BrosdkManager` 注入验证核心的异步→同步桥接逻辑。

## 与 BroSDK 生态的关系

| 仓库 | 说明 |
|------|------|
| [brosdk](https://github.com/browsersdk/brosdk) | 原生 C/C++ SDK |
| [brosdk-python](https://github.com/browsersdk/brosdk-python) | Python 语言绑定（本包依赖） |
| [brosdk-docs](https://github.com/browsersdk/brosdk-docs) | 官方文档和 API 参考 |
| [brosdk-typescript](https://github.com/browsersdk/brosdk-typescript) | TypeScript 语言绑定 |

## License

MIT
