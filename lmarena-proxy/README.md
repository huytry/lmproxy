# LMArena Reverse Proxy Server

<div align="center">

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/github/license/zhongruichen/lmarena-proxy)](https://github.com/zhongruichen/lmarena-proxy/blob/main/LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#-快速开始)

一个功能强大的 LMArena 反向代理服务器，提供 OpenAI 兼容的 API 接口、实时监控面板、动态配置管理等企业级功能。

[English](./README_EN.md) | [功能特性](#-功能特性) | [快速开始](#-快速开始) | [API文档](#-api-文档) | [监控面板](#-监控面板) | [配置管理](#-配置管理)

</div>

## ✨ 功能特性

### 🚀 核心功能
- **OpenAI API 兼容**：完全兼容 OpenAI API 格式，支持流式和非流式响应，无缝接入现有应用。
- **多模型支持**：支持 LMArena 上的 100+ AI 模型，包括 Claude、GPT、Gemini、DeepSeek 等。
- **智能请求管理**：强大的断线重连、请求持久化和自动重试机制，从容应对 Cloudflare 验证和网络波动。
- **实时监控面板**：提供美观的 Web 界面，实时监控系统状态、请求日志、性能指标。

### 📊 监控与分析
- **实时统计**：QPS、响应时间、成功率、Token 使用量一目了然。
- **性能指标**：P50/P95/P99 响应时间分析，精准定位性能瓶颈。
- **告警系统**：自动监测异常（如高错误率、慢响应）并发送告警。
- **Prometheus 集成**：暴露标准 `/metrics` 端点，轻松接入 Grafana 等专业监控工具。

### ⚙️ 配置管理
- **Web 配置界面**：在监控面板中即可动态修改配置，无需重启服务。
- **动态 IP 管理**：支持自动检测或手动设置 IP，轻松应对复杂的网络环境。
- **请求参数调优**：超时时间、并发数等核心参数均可动态调整。

### 🛡️ 可靠性保障
- **断线重连**：浏览器与服务器之间的 WebSocket 连接拥有强大的自动重连机制。
- **请求持久化**：即使浏览器刷新或关闭，正在处理的 API 请求也不会丢失，会在重连后继续执行。
- **完善的错误处理**：对网络错误、Cloudflare 挑战、速率限制等问题有专门的处理逻辑。
- **健康检查**：内置详细的健康检查和评分系统，随时掌握服务状态。

## 🏗️ 系统架构

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Client    │────▶│ Proxy Server │────▶│ Browser w/Script │
│  (OpenAI)   │◀────│  (FastAPI)   │◀────│   (LMArena Tab)  │
└─────────────┘     └──────────────┘     └──────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │   Monitor    │
                    │  Dashboard   │
                    └──────────────┘
```

- **Python 服务端** (`proxy_server.py`): 核心 FastAPI 服务器，负责处理 API 请求和与浏览器脚本的 WebSocket 通信。
- **浏览器脚本** (`lmarena_injector.user.js`): 通过 Tampermonkey 注入到 LMArena 网站，作为服务器的“手臂”，执行实际的 AI 请求。
- **监控面板**: 一个 Vue.js 单页应用，用于实时显示系统状态和性能指标。

## 📦 安装要求

- **Python 3.8+**
- **支持的操作系统**: Windows, Linux, macOS
- **浏览器**: 最新版的 Chrome / Edge / Firefox
- **浏览器扩展**: [Tampermonkey](https://www.tampermonkey.net/)

## 🚀 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/zhongruichen/lmarena-proxy.git
cd lmarena-proxy
```

### 2. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 3. 安装浏览器脚本 (Tampermonkey)

这是最关键的一步。此脚本负责连接代理服务器并执行请求。

**推荐方式 (自动更新):**

1.  点击此链接进行安装: [**Install Script from GitHub**](https://raw.githubusercontent.com/zhongruichen/lmarena-proxy/main/lmarena_injector.user.js)
2.  Tampermonkey 会自动打开一个页面，显示脚本信息，点击 **“安装”** 按钮。

**手动方式:**

1.  安装 [Tampermonkey](https://www.tampermonkey.net/) 浏览器扩展。
2.  打开项目中的 `lmarena_injector.user.js` 文件。
3.  复制文件的 **全部** 内容。
4.  点击 Tampermonkey 浏览器图标，选择 **“创建新脚本”**。
5.  将复制的内容粘贴到编辑器中，替换掉所有默认内容。
6.  保存脚本 (Ctrl+S)。

### 4. 启动服务器

- **Windows 用户:**
  直接双击运行 `start_windows.bat` 文件。

- **Linux / macOS 用户:**
  ```bash
  # 首次运行需要给脚本添加执行权限
  chmod +x start.sh
  
  # 启动脚本
  ./start.sh
  ```
脚本会自动启动 Python 服务器，并尝试打开 LMArena 和监控面板页面。

### 5. 检查连接状态

1.  打开或刷新 [LMArena 网站](https://lmarena.ai/)。
2.  打开浏览器开发者工具 (F12)，切换到 **Console (控制台)**。
3.  如果你看到 `[Injector] ✅ Connection established with local server.` 的绿色消息，说明连接成功！

### 6. 使用 API

现在，你可以使用任何兼容 OpenAI 的客户端来调用 API。

```python
from openai import OpenAI

# 如果你的服务器在另一台机器上，请修改 base_url
client = OpenAI(
    base_url="http://localhost:9080/v1",
    api_key="sk-any-string-you-like" # api_key 可以是任意字符串
)

try:
    response = client.chat.completions.create(
        model="claude-3-5-sonnet-20241022", # 使用你需要的模型
        messages=[{"role": "user", "content": "Hello, what can you do?"}],
        stream=True
    )

    print("Response from model:")
    for chunk in response:
        content = chunk.choices[0].delta.content
        if content:
            print(content, end="", flush=True)
    print()

except Exception as e:
    print(f"An error occurred: {e}")

```

## 📊 监控面板

访问 `http://localhost:9080/monitor` 来查看实时监控面板。

<details>
<summary><b>点击查看监控面板功能截图</b></summary>

*   **实时请求监控**: 跟踪每一个请求的完整生命周期。
*   **性能指标可视化**: 图表展示 QPS、延迟等关键指标。
*   **模型使用分析**: 统计每个模型的使用频率和性能。
*   **系统健康状态**: 全面的健康评分和优化建议。
*   **动态配置管理**: 在线修改系统参数。

*(此处可以放截图)*

</details>

## ⚙️ 配置管理

### 服务端配置 (`logs/config.json`)
服务器首次启动后，会在 `logs` 目录下创建一个 `config.json` 文件。你可以在监控面板的“系统设置”页面修改这些配置，它们会自动保存到这里。

### 用户脚本配置 (`lmarena_injector.user.js`)
如果你在另一台电脑上运行代理服务器，你需要修改用户脚本的配置。

1.  点击 Tampermonkey 图标，进入“管理面板”。
2.  找到 `LMArena Proxy Injector` 脚本，点击编辑按钮。
3.  修改顶部的 `CONFIG` 对象：
    ```javascript
    // --- CONFIGURATION ---
    // 如果你的代理服务器不在本机运行，请修改此处的 IP 地址。
    const CONFIG = {
        SERVER_URL: "ws://192.168.1.100:9080/ws", // 修改为你的服务器IP
    };
    ```
4.  保存脚本。

## 🐛 故障排除

- **浏览器脚本无法连接?**
  1.  **检查服务器是否运行**: 确保 `proxy_server.py` 正在运行且没有报错。
  2.  **检查防火墙**: 确保你的系统防火墙允许 9080 端口的入站连接。
  3.  **检查 IP 地址**: 如果服务器和浏览器不在同一台机器上，请确保 `lmarena_injector.user.js` 中的 `SERVER_URL` 已正确配置为服务器的局域网 IP。
  4.  **查看浏览器控制台**: 按 F12 打开开发者工具，查看 Console 中的错误信息。

- **请求超时或失败?**
  1.  **查看服务器日志**: `logs/server.log` 和 `logs/errors.jsonl` 提供了详细的错误信息。
  2.  **检查 LMArena 网站**: 确保你能手动在 LMArena 网站上正常使用模型。有时网站本身可能出现问题。
  3.  **Cloudflare 挑战**: 如果日志显示请求因 Cloudflare 验证失败，尝试刷新 LMArena 页面。脚本会自动处理大多数情况，但手动刷新有时能解决问题。

- **模型列表为空?**
  1.  确保你已登录 LMArena 网站。
  2.  尝试在监控面板点击“刷新模型列表”按钮，或直接访问 `POST /v1/refresh-models` 端点。

## ⚠️ 局限性

- **依赖前端**: 本项目强依赖于 LMArena 网站的前端结构。当 LMArena 进行重大更新时，用户脚本 (`lmarena_injector.user.js`) **可能会失效**。届时需要等待项目更新，或者有经验的用户可以自行更新脚本中的选择器和请求逻辑。
- **单点实例**: 当前设计为单浏览器实例工作。不支持同时在多个浏览器或多个标签页中运行此脚本连接到同一个服务器。

## 🤝 贡献

我们欢迎所有形式的贡献！无论是报告问题、提出功能建议还是提交代码。

1.  Fork 本项目。
2.  创建你的特性分支 (`git checkout -b feature/AmazingFeature`)。
3.  提交你的更改 (`git commit -m 'Add some AmazingFeature'`)。
4.  推送到分支 (`git push origin feature/AmazingFeature`)。
5.  开启一个 Pull Request。

## 📄 许可证

本项目采用 MIT 许可证。详情请见 [LICENSE](LICENSE) 文件。
