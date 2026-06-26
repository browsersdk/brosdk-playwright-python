# brosdk-playwright

English | [简体中文](README.md)

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

`brosdk-playwright` is a one-stop integration of the [BroSDK](https://www.brosdk.com/) fingerprint browser with [Playwright](https://playwright.dev/) automation.

> **BroSDK "creates the environment"** (fingerprint / proxy / session persistence), **Playwright "does the work"** (page automation), bridged over CDP (Chrome DevTools Protocol).

Just change the import path from `playwright.sync_api` to `brosdk_playwright` and gain multi-version fingerprint kernels, independent proxy IPs, and Cookie/Storage session persistence — **without changing any Playwright usage habits**.

```python
import brosdk_playwright as bp
bp.configure(api_key="your-api-key", work_dir="./.brosdk")

from brosdk_playwright import sync_playwright   # identical signature to native

with sync_playwright() as p:
    browser = p.chromium.launch(env={           # per-browser env config
        "env_id": "2070365861541056512",   # reuse existing env, auto-restore login
        "kernel_version": "134",
        "proxy": "socks5://user:pass@host:1080",
    })
    page = browser.new_page()
    page.goto("https://example.com")
    browser.close()                              # disconnect CDP + close browser (auto-persists cookies)

bp.shutdown()
```

---

## Key Features

- **Zero switching cost**: `sync_playwright()` matches the official Playwright signature; all Playwright APIs (`new_page`/`goto`/`click`/`screenshot`/…) work as-is.
- **Fingerprint env management**: auto-creates/reuses BroSDK browser environments (independent fingerprint, independent proxy).
- **Session persistence**: reuse an existing env via `env_id`; the same env auto-restores the previous Cookie/Storage/login state.
- **Automatic CDP bridging**: internally bridges BroSDK's async launch event (`browser-open-success`) into a synchronous `launch()`, fetching the CDP port and connecting Playwright.
- **Concurrent multi-env**: each env gets an independent auto-assigned CDP port, avoiding port conflicts.
- **Mixed usage**: `p.chromium.launch()` (no `env`) uses native Playwright; `p.firefox`/`p.webkit` pass through to native Playwright.

---

## How It Works

```
User code (Playwright API, unchanged)
        │
        ▼
brosdk-playwright wrapper layer
  ┌─────────────────────────────────────────┐
  │ _BroBrowserType.launch(env=...)         │
  │   1. resolve_env  → create/reuse env    │
  │   2. launch_browser → sdk.browser_open  │
  │      (async event 20111 → sync wait for │
  │       CDP port)                          │
  │   3. connect_over_cdp → Playwright links│
  └─────────────────────────────────────────┘
        │
        ▼
BroSDK native SDK (brosdk.dll/.dylib/.so)
  fingerprint kernel · proxy · Cookie/Storage persistence
```

**Key technical point**: `sdk_browser_open` is asynchronous — the CDP port is NOT in the return value, but arrives in the event callback `eventId=20111` (`browser-open-success`), in its `data.remoteDebuggingPort` field. This package bridges that async event into a synchronous `launch()` using `threading.Event` — the core value of this project (the official BroSDK demos in every language merely `sleep` and never extract the port).

---

## Installation

```bash
pip install brosdk-playwright
```

From source:

```bash
git clone https://github.com/browsersdk/brosdk-playwright-python.git
cd brosdk-playwright-python
pip install .
```

You also need:

| Item | Requirement |
|------|------|
| Python | 3.8+ |
| Native lib | BroSDK dynamic library (`brosdk.dll` / `brosdk.dylib` / `libbrosdk.so`). The `brosdk` PyPI package does **not** ship the native lib, but brosdk-playwright **auto-downloads** it from GitHub Releases on first use (see "Native library auto-download" below) |
| Auth | BroSDK API Key (or a userSig directly) |

Playwright browser binaries are only needed when **not** going through BroSDK (`launch()` without `env`, or `firefox`/`webkit`); via BroSDK the browser kernel is managed by BroSDK.

### Native library auto-download

The `brosdk` PyPI package is pure-Python and does not bundle the native dynamic library. `brosdk-playwright` will **automatically** download and extract the current platform's library from [GitHub Releases](https://github.com/browsersdk/brosdk/releases) into the working directory's `libs/` folder when:

- `lib_path` is not specified AND the library is not found locally (in the brosdk package dir or working dir);
- enabled by default — no configuration needed.

To disable auto-download (e.g. offline environments), pass `auto_download=False` and manually point `lib_path=` to a pre-downloaded library:

```python
bp.configure(api_key="...", lib_path="/path/to/brosdk.dll", auto_download=False)
```

You can also pin a specific version: `bp.configure(api_key="...", lib_version="1.0.0.5")`.

---

## Quick Start

### 1. Configure the SDK (process-level, once)

```python
import brosdk_playwright as bp

bp.configure(
    api_key="your-api-key",     # or set BROSDK_API_KEY env var
    work_dir="./.brosdk",       # SDK working directory
    # lib_path="...",           # optional: path to the native library (auto-found/downloaded if omitted)
    # auto_download=True,       # optional: auto-download from GitHub Releases when missing (default on)
    # lib_version="1.0.1.1",    # optional: pin a library version (default latest)
    # port=0,                   # optional: 0=auto-assign port (default)
    # customer_id="default",    # optional
)
```

Pure env-var configuration is also supported (no `configure` needed):

```bash
export BROSDK_API_KEY=your-api-key
export BROSDK_WORK_DIR=./.brosdk
```

### 2. Write code like Playwright

```python
from brosdk_playwright import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(env={"kernel_version": "134"})
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())
    browser.close()
```

### Run the Demo

```bash
python examples/demo.py --api-key YOUR_API_KEY            # interactive
python examples/demo.py --quick --api-key YOUR_API_KEY    # quick demo
```

---

## `env` Configuration Reference

The `env` dict for `p.chromium.launch(env={...})` supports:

| Field | Type | Description |
|------|------|------|
| `env_id` | string | Specify a BroSDK env ID directly to reuse an existing env (auto-restores login). Omit to create a new env |
| `kernel_version` | string | Chrome kernel version, e.g. `"134"`/`"131"`/`"127"`, default `"134"` |
| `proxy` | string | Proxy URL, e.g. `socks5://user:pass@host:1080` |
| `region` | string | Country code (generates regional IP when proxy unavailable) |
| `system` | string | OS, e.g. `"Windows 11"` |
| `finger` | dict | Full fingerprint config (overrides; see BroSDK docs) |
| `env_name` | string | Environment name (auto-generated by default) |
| `args` | list | Extra Chromium launch args |
| `urls` | list | URLs to auto-open on launch |
| `cookies` | list | Cookies injected at launch (WebExtension API format) |
| `extensions` | list | Extensions to load |
| `forward` | string | Forward jump proxy for this launch |
| `launch_timeout` | float | Launch timeout (seconds), default 60 |

> Session reuse: remember `browser.brosdk_env_id` and pass it back as `env_id` next time —
> BroSDK envs persist cookie/storage, so the same envId auto-restores the login state on relaunch.
> Omit `env_id` to create a new environment.

---

## API Overview

### Module-level

| Name | Description |
|------|------|
| `configure(api_key=..., ...)` | Configure SDK auth and working directory (process-level) |
| `sync_playwright()` | Playwright-compatible context manager returning a wrapped `Playwright` |
| `BroSDKError` | Base class for all errors raised by this package |
| `list_envs()` | Return the env list under the current account |
| `destroy_env(env_id)` | Destroy an env (deletes it and all persistent data) |
| `shutdown()` | Shut down BroSDK, releasing native resources |
| `get_config()` | Read the current config |

### `browser` augmented fields

A browser launched via BroSDK additionally exposes:

| Field | Description |
|------|------|
| `browser.brosdk_env_id` | The associated BroSDK environment ID |
| `browser.cdp_port` | The browser CDP debugging port |

---

## Use Cases

1. **Multi-account SaaS**: isolate account envs with independent `env_id` — independent fingerprint/proxy/cookie.
2. **Automated testing**: existing Playwright suites gain fingerprint and proxy capabilities with zero changes.
3. **AI agent browser tasks**: inject fingerprint envs into Playwright within LangChain/AutoGPT toolchains.
4. **ERP/CRM integration**: reuse enterprise Playwright scripts with session persistence.

---

## Project Structure

```text
brosdk-playwright-python/
├── brosdk_playwright/
│   ├── __init__.py        # public API exports
│   ├── _config.py         # global config + auth (configure / get_config)
│   ├── _sdk.py            # env management + async-event→sync launch/close bridge
│   ├── _downloader.py     # native lib auto-download (GitHub Releases)
│   ├── _playwright.py     # Playwright API wrapper layer
│   └── sync_api.py        # sync_playwright() context manager
├── examples/              # usage examples + interactive CLI demo (demo.py)
├── config/               # E2E test config (e2e.config.json, contains secrets, gitignored)
├── tests/                # unit tests + e2e/ subdir (no real SDK/browser needed)
└── pyproject.toml
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests do not depend on a real SDK, browser, or API key — they inject a fake `BrosdkManager` to validate the core async→sync bridging logic in isolation.

## Relationship to the BroSDK Ecosystem

| Repo | Description |
|------|------|
| [brosdk](https://github.com/browsersdk/brosdk) | Native C/C++ SDK |
| [brosdk-python](https://github.com/browsersdk/brosdk-python) | Python language bindings (this package depends on it) |
| [brosdk-docs](https://github.com/browsersdk/brosdk-docs) | Official docs and API reference |
| [brosdk-typescript](https://github.com/browsersdk/brosdk-typescript) | TypeScript language bindings |

## License

MIT
