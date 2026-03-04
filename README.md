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
[Runtime 配置](#-runtime-配置) •
[项目配置](#️-项目配置) •
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

### 方式一：使用独立 Runtime（推荐，Windows）

项目自带独立的 Python 3.9 运行时，无需安装系统 Python，开箱即用：

```batch
# 1. 克隆项目
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. 安装依赖（使用独立 runtime）
.\install_dependencies.ps1
# 或使用批处理脚本：install_dependencies.bat

# 3. 配置环境变量（创建 .env 文件）
copy .env.example .env
# 编辑 .env 填写 API 密钥

# 4. 运行项目
.\run_with_runtime.ps1
# 或使用批处理脚本：run_with_runtime.bat
```
详见下方 [Runtime 配置](#-runtime-配置) 部分
📖 **详细说明**: 参见 [RUNTIME.md](RUNTIME.md)

### 方式二：使用系统 Python 或虚拟环境

如果你已有 Python 3.9-3.11 环境：

```bash
# 1. 克隆项目
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. 创建虚拟环境（推荐）
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

# 浏览器 Agent（可选）
OPENAI_API_KEY=sk-xxxxxx
```

### 🎯 功能配置

编辑 `config.yaml` 来启用/禁用功能模块：

```yaml
# 电脑控制功能
controller:
  enabled: true          # 改为 false 禁用

# 语音识别功能
ear:
  enabled: false         # 改为 true 启用
  model_size: "base"     # 模型大小: tiny, base, small, medium
```

---

## 🐛 常见问题

### ❌ 找不到 python.exe

**症状**: `找不到 Python Runtime: runtime\python.exe`

**解决**:
1. 确认 `runtime` 目录下有完整的 Python 3.9 运行时
2. 运行健康检查: `.\check_runtime.ps1`
3. 参考 [RUNTIME.md](RUNTIME.md) 重新配置

### ❌ 模块导入失败

**症状**: `ModuleNotFoundError: No module named 'xxx'`

**解决**:
```powershell
# 使用 Runtime:
.\install_dependencies.ps1

# 使用系统 Python:
pip install -r requirements.txt
```

### ❌ 启动后立即退出

**检查步骤**:
1. 查看日志文件: `data/logs/project_local.log`
2. 确认 `.env` 配置正确（API 密钥等）
3. 运行健康检查: `.\check_runtime.ps1`

### ❌ ctranslate2 错误

**症状**: 与 `ctranslate2` 相关的 DLL 加载错误

**解决**:
- 已在启动脚本中自动设置 `CT2_USE_CUDA=0`
- 如果仍有问题，检查环境变量是否正确

### ❌ 语音功能无法使用

**症状**: `找不到 GPT-SoVITS 服务`

**解决**:
- 检查 GPT-SoVITS 服务是否正常启动
- 确认模型文件是否正确放置
- 查看日志：`modules/gpt_sovits/gpt_sovits.log`

### ❌ 电脑控制无法启动应用

**症状**: 应用无法打开或权限不足

**解决**:
- 检查应用路径是否在 `config.yaml` 白名单中
- 确认路径正确（使用 `\\` 或原始字符串）
- 查看日志确认安全检查是否通过

---

## 📚 延伸阅读

- **完整文档**: [README.md](README.md)
- **Runtime 详细说明**: [RUNTIME.md](RUNTIME.md)
- **贡献指南**: [CONTRIBUTING.md](CONTRIBUTING.md)
- **开发脚本**: [scripts/dev.ps1](scripts/dev.ps1)

---

## 🆘 获取帮助

1. **查看日志**: `data/logs/project_local.log`
2. **运行诊断**: `.\check_runtime.ps1`
3. **查阅文档**: 参见上方延伸阅读
4. **提交 Issue**: [GitHub Issues](https://github.com/your-org/local-project/issues)

---

## ✅ 验证安装

启动成功后，你应该看到：

```
============================================
Project Local - 使用独立 Runtime 启动
============================================
Python: d:\...\Local-project\runtime\python.exe
项目目录: d:\...\Local-project
============================================

启动 Project Local...
[INFO] 加载配置文件...
[INFO] 初始化模块...
[INFO] Avatar 窗口已启动
```

如果看到 Avatar 窗口并且没有错误，恭喜你成功启动了 Project Local！🎉

---
Runtime 配置

### 📦 概述

本项目提供独立的 Python 3.9 运行时环境（位于 `runtime`），与系统 Python 环境隔离，确保依赖版本的一致性和项目的可移植性。

### 📁 Runtime 结构

```
runtime/
├── python.exe              # Python 3.9 解释器
├── python39.dll            # Python 核心库
├── python39._pth           # Python 路径配置文件
├── python39.zip            # 标准库（压缩包）
├── Lib/                    # Python 标准库
│   └── site-packages/      # 第三方依赖包目录
├── Scripts/                # 可执行脚本目录
│   ├── pip.exe             # pip 包管理器
│   └── ...
├── include/                # C/C++ 头文件
└── libs/                   # 链接库
```

### ⚙️ python39._pth 模块搜索路径

`python39._pth` 文件定义了 Python 解释器的搜索路径：

```
python39.zip                # 标准库压缩包
.                           # runtime 目录本身
Lib                         # 标准库目录
Lib\site-packages           # 第三方包目录
..                          # 项目根目录
..\..\modules               # modules 模块

import site                 # 启用 site-packages
```

### 🚀 使用 Runtime 脚本

#### 安装依赖

```powershell
# 仅安装生产依赖
.\install_dependencies.ps1

# 安装生产 + 开发依赖
.\install_dependencies.ps1 -Dev

# 使用国内镜像加速
.\install_dependencies.ps1 -Mirror
```

#### 启动项目

```powershell
# PowerShell（推荐）
.\run_with_runtime.ps1

# 或使用批处理脚本
.\run_with_runtime.bat
```

#### 健康检查

```powershell
# 诊断 Runtime 配置
.\check_runtime.ps1
```

#### 手动使用

```batch
# 直接调用 Python
runtime\python.exe script.py

# 使用 pip
runtime\Scripts\pip.exe install package-name
```

### 🔧 自动设置的环境变量

| 变量 | 值 | 说明 |
|------|-----|------|
| `CT2_USE_CUDA` | `0` | 禁用 ctranslate2 的 CUDA 以避免路径问题 |
| `LOKY_MAX_CPU_COUNT` | 自动 | 修复中文 Windows 上的编码问题 |

### 🐛 Runtime 故障排查

<details>
<summary><b>找不到 python.exe</b></summary>

- 确认 `runtime/python.exe` 存在
- 检查 runtime 目录完整性
- 运行 `.\check_runtime.ps1` 诊断

</details>

<details>
<summary><b>模块导入失败 (ModuleNotFoundError)</b></summary>

- 检查 `python39._pth` 中的相对路径
- 验证依赖已安装：`runtime\Scripts\pip.exe list`
- 重新运行 `.\install_dependencies.ps1`

</details>

<details>
<summary><b>DLL 加载失败</b></summary>

- 安装 Visual C++ Redistributable 2015-2022
- 尝试重新安装依赖包
- 检查是否缺少系统库

</details>

### 📚 进阶配置

**更新 Runtime**:
```batch
# 备份当前版本
xcopy runtime runtime_backup /E /I /H

# 替换为新的 Python 3.9 嵌入式版本后运行
.\install_dependencies.ps1
```

**依赖管理**:
```batch
# 查看已安装的包
runtime\Scripts\pip.exe list

# 导出依赖
runtime\Scripts\pip.exe freeze > requirements.txt
```

---

## ⚙️ 项目配置
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
│   ├── 📂 memoripy/           # 记忆系统数据
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

- 检查记忆数据库文件大小
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
> - 记忆系统会在 `data/memoripy/` 目录存储交互历史数据

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
