<div align="center">

**🌐 Language / 语言 / 言語**

[![中文](https://img.shields.io/badge/中文-简体-red?style=flat-square)](README.md)
[![English](https://img.shields.io/badge/English-blue?style=flat-square)](README_EN.md)
[![日本語](https://img.shields.io/badge/日本語-green?style=flat-square)](README_JA.md)

---

# 🤖 Project Local

[![Python](https://img.shields.io/badge/Python-3.9--3.11-blue?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://img.shields.io/badge/CI-GitHub_Actions-orange?logo=github-actions&logoColor=white)](.github/workflows/ci.yml)
[![Code Style](https://img.shields.io/badge/Code%20Style-Black-black)](https://github.com/psf/black)

**一个带有虚拟形象的本地 AI 桌面助手**

语音对话 · 智能记忆 · 电脑控制 · 3D Avatar

[功能特性](#-功能特性) •
[快速开始](#-快速开始) •
[配置说明](#️-配置说明) •
[项目结构](#-项目结构) •
[开发指南](#-开发指南)

</div>

---

## ✨ 功能特性

<table>
<tr>
<td width="50%">

### 🎯 核心功能

- **💬 智能对话** - 基于大语言模型的自然对话
- **🎙️ 语音交互** - 实时语音识别 + 高质量语音合成
- **🧠 人类化记忆** - 多层次记忆系统，支持偏好更新
- **🖥️ 电脑控制** - 自动化操作，打开应用、网页浏览等
- **👤 3D Avatar** - WebGL 虚拟形象，表情口型同步

</td>
<td width="50%">

### 🧠 记忆系统亮点

- 📊 **多层次记忆** - 短期/工作/长期/情感记忆
- 🔄 **智能冲突检测** - 四步流程自动处理
- 🎯 **偏好自动更新** - "喜欢苹果" → "喜欢香蕉"
- ⚡ **并行检索** - 低延迟响应
- 🔒 **完全本地化** - 无需云服务

</td>
</tr>
</table>

---

## 🚀 快速开始

### 环境要求

| 要求 | 版本 |
|------|------|
| Python | 3.9 - 3.11 |
| 操作系统 | Windows / Linux / macOS |
| GPU | 推荐（用于语音合成加速） |

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. 创建虚拟环境
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量（创建 .env 文件）
cp .env.example .env
# 编辑 .env 填写 API 密钥

# 5. 运行
python main.py
```

### 环境变量配置

创建 `.env` 文件：

```ini
# LLM API 配置
ARK_API_KEY=your_api_key_here
MODEL_NAME=your_model_name

# 系统提示词（可选，支持文件路径）
SYSTEM_PROMPT_FILE=SYSTEM_PROMPT.txt

# GPT-SoVITS 路径
GPT_SOVITS_PATH=./GPT-SoVITS-v2pro-20250604-nvidia50

# 浏览器 Agent（可选）
OPENAI_API_KEY=sk-xxxxxx
```

---

## ⚙️ 配置说明

配置文件：`config.yaml`

```yaml
# API 配置
api:
  sovits_url: "http://127.0.0.1:9880"

# 音频配置
audio:
  ref_audio_path: "assets/audio_ref/ref_audio.wav"
  sample_rate: 32000

# 电脑控制配置
controller:
  enabled: true
  failsafe: true
  app_whitelist:
    notepad: "C:\\Windows\\System32\\notepad.exe"
    edge: "C:\\Program Files\\Microsoft\\Edge\\msedge.exe"
```

<details>
<summary>📋 <b>日志系统说明</b>（点击展开）</summary>

日志系统采用统一、模块化、结构化设计：

- **存放位置**：`data/logs/project_local.log`（每日轮转）
- **文件格式**：JSON（便于搜索/告警）
- **控制台**：彩色输出（INFO 及以上）

```python
from modules.logging_config import get_logger
logger = get_logger('MyModule')
logger.info('Hello!')
```

</details>

---

## 📖 使用方法

### 基本命令

| 命令 | 说明 |
|------|------|
| `exit` / `quit` | 退出程序 |
| `status` | 查看记忆系统状态 |

### 🖥️ 电脑控制

AI 可以执行以下操作：

- 📂 **打开应用** - "打开 QQ"、"打开记事本"
- 🌐 **访问网页** - "打开百度"、"搜索 Python 教程"
- 📝 **保存笔记** - "保存笔记：今天的学习内容"
- ⌨️ **输入文本** - 模拟键盘输入中英文

### 🎙️ 语音交互

- ✅ 实时语音输入（需麦克风权限）
- ✅ 高质量语音合成输出
- ✅ 自动过滤情感标签（如 `[开心]`、`[生气]`）

### 👤 Avatar 显示

- 🎨 3D 虚拟形象（WebGL）
- 😊 表情同步
- 👄 口型动画
- 🔧 可调整窗口大小和透明度

---

## 📁 项目结构

```
Local-project/
├── 📄 main.py                 # 主入口
├── 📄 config.yaml             # 配置文件
├── 📄 pyproject.toml          # 项目配置 (Poetry)
├── 📄 requirements.txt        # 依赖列表
│
├── 📂 modules/                # 核心模块
│   ├── 📂 agent/              # AI Agent（ReAct + 工具）
│   ├── 📂 avatar/             # 虚拟形象模块
│   ├── 📂 memory/             # 记忆系统
│   ├── 📄 config.py           # 配置管理
│   ├── 📄 ear.py              # 语音识别
│   ├── 📄 health.py           # 健康检查
│   ├── 📄 launcher.py         # 应用启动器
│   ├── 📄 llm.py              # LLM 接口
│   ├── 📄 resilience.py       # 错误处理与重试
│   ├── 📄 utils.py            # 工具函数
│   └── 📄 voice.py            # 语音合成
│
├── 📂 tests/                  # 测试文件
├── 📂 assets/                 # 静态资源
│   ├── 📂 audio_ref/          # 参考音频
│   └── 📂 web/                # 前端资源
├── 📂 data/                   # 数据存储
│   ├── 📂 chroma_db/          # 向量数据库
│   ├── 📂 logs/               # 日志文件
│   └── 📂 temp/               # 临时文件
│
├── 📂 .github/workflows/      # CI/CD 配置
└── 📂 scripts/                # 开发脚本
```

<details>
<summary>📋 <b>详细模块说明</b>（点击展开）</summary>

### Agent 子模块 (`modules/agent/`)
| 文件 | 说明 |
|------|------|
| `core.py` | Agent 核心逻辑（ReAct loop） |
| `tools.py` | 工具封装（含原 ActionExecutor） |
| `browser.py` | 浏览器 / 网页检索工具 |
| `safety.py` | SafetyGuard 安全白名单校验 |
| `window.py` | 窗口管理辅助 |
| `file_tools.py` | 文件/笔记助手 |

### Avatar 子模块 (`modules/avatar/`)
| 文件 | 说明 |
|------|------|
| `widget.py` | 主窗口组件 |
| `expression.py` | 表情管理 |
| `lip_sync.py` | 口型同步 |
| `click_through.py` | 点击穿透 |
| `webengine.py` | WebEngine 集成 |

### Memory 子模块 (`modules/memory/`)
| 文件 | 说明 |
|------|------|
| `core.py` | 核心记忆管理类 |
| `storage.py` | 存储层 |
| `retrieval.py` | 记忆检索与去重 |
| `conflict/` | 冲突检测与覆盖模块 |

</details>

---

## 💻 开发指南

### 开发环境设置

```powershell
# 安装开发依赖
.\scripts\dev.ps1 setup

# 设置 pre-commit hooks
.\scripts\dev.ps1 pre-commit
```

### 常用命令

| 命令 | 说明 |
|------|------|
| `.\scripts\dev.ps1 test` | 运行测试 |
| `.\scripts\dev.ps1 test-cov` | 运行测试 + 覆盖率 |
| `.\scripts\dev.ps1 lint` | 代码检查 |
| `.\scripts\dev.ps1 format` | 代码格式化 |
| `.\scripts\dev.ps1 check` | 运行所有检查 |

### 代码规范

- 🎨 **Black** - 代码格式化（行宽 120）
- 📦 **isort** - 导入排序
- 🔍 **Ruff** - 快速 linting
- 📝 **mypy** - 类型检查

详见 [CONTRIBUTING.md](CONTRIBUTING.md)

---

## ❓ 故障排除

<details>
<summary><b>🔊 语音功能无法使用</b></summary>

- 检查 GPT-SoVITS 服务是否正常启动
- 确认模型文件是否正确放置
- 查看日志：`GPT-SoVITS-v2pro-20250604-nvidia50/gpt_sovits.log`

</details>

<details>
<summary><b>🖥️ 电脑控制无法启动应用</b></summary>

- 检查应用路径是否在 `config.yaml` 白名单中
- 确认路径正确（使用 `\\` 或原始字符串）
- 查看日志确认安全检查是否通过

</details>

<details>
<summary><b>👤 Avatar 窗口无法显示</b></summary>

- 检查 WebGL 支持和显卡驱动
- 确认前端资源文件完整
- 查看浏览器控制台错误

</details>

<details>
<summary><b>🐢 记忆系统响应慢</b></summary>

- 检查 ChromaDB 数据库文件大小
- 考虑清理过期记忆数据
- 调整相似度阈值参数

</details>

<details>
<summary><b>📷 OCR / Tesseract 报错</b></summary>

1. 安装 Tesseract 并下载语言包
2. 设置环境变量 `TESSDATA_PREFIX`
3. 程序会尝试自动下载 `eng.traineddata`

</details>

<details>
<summary><b>⌨️ 中文输入显示为乱码</b></summary>

- 程序使用剪贴板方式输入中文文本
- 确保目标应用程序支持剪贴板粘贴操作

</details>

---

## ⚠️ 注意事项

> - 首次运行需要下载模型文件，可能需要较长时间
> - 确保 GPT-SoVITS 服务正常启动，否则语音功能不可用
> - 建议使用 GPU 加速以获得更好的性能
> - 记忆系统会在 `data/chroma_db/` 目录存储向量数据

### 冲突检测系统

支持四种冲突类型：

| 类型 | 说明 |
|------|------|
| 🔄 重复记忆 | 极高相似度（<0.15）的完全重复内容 |
| 📝 信息更新 | 包含更新意图 + 共同实体的更正信息 |
| ❤️ 偏好矛盾 | 同一对象的正反偏好冲突 |
| 🍎 同类偏好更新 | 同一类别偏好的更新（如食物偏好） |

---

## 📜 许可证

本项目采用 [MIT 许可证](LICENSE)。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

详见 [贡献指南](CONTRIBUTING.md)

---

<div align="center">

**Made with ❤️ by Local Project Team**

</div>
