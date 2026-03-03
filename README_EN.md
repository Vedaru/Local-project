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

**A Local AI Desktop Assistant with Virtual Avatar**

Voice Interaction · Smart Memory · PC Control · 3D Avatar

[Features](#-features) •
[Quick Start](#-quick-start) •
[Configuration](#️-configuration) •
[Project Structure](#-project-structure) •
[Development](#-development)

</div>

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🎯 Core Features

- **💬 Smart Conversation** - Natural dialogue powered by LLM
- **🎙️ Voice Interaction** - Real-time speech recognition + high-quality TTS
- **🧠 Human-like Memory** - Multi-level memory system with preference updates
- **🖥️ PC Control** - Automation: open apps, browse web, etc.
- **👤 3D Avatar** - WebGL virtual character with expression & lip sync

</td>
<td width="50%">

### 🧠 Memory System Highlights

- 📊 **Multi-level Memory** - Short-term / Working / Long-term / Emotional
- 🔄 **Smart Conflict Detection** - 4-step automatic handling
- 🎯 **Auto Preference Update** - "like apples" → "like bananas"
- ⚡ **Parallel Retrieval** - Low latency response
- 🔒 **Fully Local** - No cloud services required

</td>
</tr>
</table>

---

## 🚀 Quick Start

### Requirements

| Requirement | Version |
|-------------|---------|
| Python | 3.9 - 3.11 |
| OS | Windows / Linux / macOS |
| GPU | Recommended (for TTS acceleration) |

### Installation

```bash
# 1. Clone the project
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. Create virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables (create .env file)
cp .env.example .env
# Edit .env and fill in API keys

# 5. Run
python main.py
```

### Environment Variables

Create a `.env` file:

```ini
# LLM API Configuration
ARK_API_KEY=your_api_key_here
MODEL_NAME=your_model_name

# System Prompt (optional, supports file path)
SYSTEM_PROMPT_FILE=SYSTEM_PROMPT.txt

# GPT-SoVITS Path
GPT_SOVITS_PATH=./GPT-SoVITS-v2pro-20250604-nvidia50

# Browser Agent (optional)
OPENAI_API_KEY=sk-xxxxxx
```

---

## ⚙️ Configuration

Config file: `config.yaml`

```yaml
# API Configuration
api:
  sovits_url: "http://127.0.0.1:9880"

# Audio Configuration
audio:
  ref_audio_path: "assets/audio_ref/ref_audio.wav"
  sample_rate: 32000

# PC Control Configuration
controller:
  enabled: true
  failsafe: true
  app_whitelist:
    notepad: "C:\\Windows\\System32\\notepad.exe"
    edge: "C:\\Program Files\\Microsoft\\Edge\\msedge.exe"
```

<details>
<summary>📋 <b>Logging System</b> (click to expand)</summary>

The logging system uses a unified, modular, structured design:

- **Location**: `data/logs/project_local.log` (daily rotation)
- **File Format**: JSON (for easy searching/alerting)
- **Console**: Colored output (INFO and above)

```python
from modules.logging_config import get_logger
logger = get_logger('MyModule')
logger.info('Hello!')
```

</details>

---

## 📖 Usage

### Basic Commands

| Command | Description |
|---------|-------------|
| `exit` / `quit` | Exit the program |
| `status` | View memory system status |

### 🖥️ PC Control

The AI can perform these operations:

- 📂 **Open Apps** - "Open QQ", "Open Notepad"
- 🌐 **Visit Websites** - "Open Google", "Search Python tutorial"
- 📝 **Save Notes** - "Save note: today's learning content"
- ⌨️ **Type Text** - Simulate keyboard input (multilingual)

### 🎙️ Voice Interaction

- ✅ Real-time voice input (microphone required)
- ✅ High-quality TTS output
- ✅ Auto-filter emotion tags (e.g., `[happy]`, `[angry]`)

### 👤 Avatar Display

- 🎨 3D virtual character (WebGL)
- 😊 Expression sync
- 👄 Lip animation
- 🔧 Adjustable window size and transparency

---

## 📁 Project Structure

```
Local-project/
├── 📄 main.py                 # Entry point
├── 📄 config.yaml             # Configuration file
├── 📄 pyproject.toml          # Project config (Poetry)
├── 📄 requirements.txt        # Dependencies
│
├── 📂 modules/                # Core modules
│   ├── 📂 agent/              # AI Agent (ReAct + tools)
│   ├── 📂 avatar/             # Avatar module
│   ├── 📂 memory/             # Memory system
│   ├── 📄 config.py           # Config management
│   ├── 📄 ear.py              # Speech recognition
│   ├── 📄 health.py           # Health checks
│   ├── 📄 launcher.py         # App launcher
│   ├── 📄 llm.py              # LLM interface
│   ├── 📄 resilience.py       # Error handling & retry
│   ├── 📄 utils.py            # Utility functions
│   └── 📄 voice.py            # Text-to-speech
│
├── 📂 tests/                  # Test files
├── 📂 assets/                 # Static resources
│   ├── 📂 audio_ref/          # Reference audio
│   └── 📂 web/                # Frontend resources
├── 📂 data/                   # Data storage
│   ├── 📂 chroma_db/          # Vector database
│   ├── 📂 logs/               # Log files
│   └── 📂 temp/               # Temporary files
│
├── 📂 .github/workflows/      # CI/CD config
└── 📂 scripts/                # Dev scripts
```

<details>
<summary>📋 <b>Detailed Module Description</b> (click to expand)</summary>

### Agent Submodule (`modules/agent/`)
| File | Description |
|------|-------------|
| `core.py` | Agent core logic (ReAct loop) |
| `tools.py` | Tool wrappers (incl. ActionExecutor) |
| `browser.py` | Browser / web retrieval tools |
| `safety.py` | SafetyGuard whitelist validation |
| `window.py` | Window management helpers |
| `file_tools.py` | File/note assistant |

### Avatar Submodule (`modules/avatar/`)
| File | Description |
|------|-------------|
| `widget.py` | Main window component |
| `expression.py` | Expression management |
| `lip_sync.py` | Lip sync |
| `click_through.py` | Click-through |
| `webengine.py` | WebEngine integration |

### Memory Submodule (`modules/memory/`)
| File | Description |
|------|-------------|
| `core.py` | Core memory manager |
| `storage.py` | Storage layer |
| `retrieval.py` | Memory retrieval & dedup |
| `conflict/` | Conflict detection & override |

</details>

---

## 💻 Development

### Development Environment Setup

```powershell
# Install dev dependencies
.\scripts\dev.ps1 setup

# Set up pre-commit hooks
.\scripts\dev.ps1 pre-commit
```

### Common Commands

| Command | Description |
|---------|-------------|
| `.\scripts\dev.ps1 test` | Run tests |
| `.\scripts\dev.ps1 test-cov` | Run tests + coverage |
| `.\scripts\dev.ps1 lint` | Code linting |
| `.\scripts\dev.ps1 format` | Code formatting |
| `.\scripts\dev.ps1 check` | Run all checks |

### Code Style

- 🎨 **Black** - Code formatting (line width 120)
- 📦 **isort** - Import sorting
- 🔍 **Ruff** - Fast linting
- 📝 **mypy** - Type checking

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## ❓ Troubleshooting

<details>
<summary><b>🔊 Voice features not working</b></summary>

- Check if GPT-SoVITS service is running properly
- Confirm model files are placed correctly
- Check logs: `GPT-SoVITS-v2pro-20250604-nvidia50/gpt_sovits.log`

</details>

<details>
<summary><b>🖥️ PC control cannot start apps</b></summary>

- Check if app path is in `config.yaml` whitelist
- Confirm path is correct (use `\\` or raw strings)
- Check logs to confirm security check passed

</details>

<details>
<summary><b>👤 Avatar window not displaying</b></summary>

- Check WebGL support and graphics driver
- Confirm frontend resource files are complete
- Check browser console for errors

</details>

<details>
<summary><b>🐢 Memory system slow response</b></summary>

- Check ChromaDB database file size
- Consider cleaning up expired memory data
- Adjust similarity threshold parameters

</details>

<details>
<summary><b>📷 OCR / Tesseract errors</b></summary>

1. Install Tesseract and download language packs
2. Set environment variable `TESSDATA_PREFIX`
3. Program will try to auto-download `eng.traineddata`

</details>

<details>
<summary><b>⌨️ Chinese input shows garbled text</b></summary>

- Program uses clipboard method for Chinese text input
- Ensure target application supports clipboard paste

</details>

---

## ⚠️ Notes

> - First run requires downloading model files, which may take some time
> - Ensure GPT-SoVITS service is running, otherwise voice features are unavailable
> - GPU acceleration is recommended for better performance
> - Memory system stores vector data in `data/chroma_db/` directory

### Conflict Detection System

Supports four conflict types:

| Type | Description |
|------|-------------|
| 🔄 Duplicate Memory | Extremely high similarity (<0.15) complete duplicates |
| 📝 Info Update | Contains update intent + common entities for correction |
| ❤️ Preference Conflict | Positive/negative preference conflict for same object |
| 🍎 Same-category Update | Same category preference update (e.g., food preference) |

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).

---

## 🤝 Contributing

Issues and Pull Requests are welcome!

See [Contributing Guide](CONTRIBUTING.md) for details.

---

<div align="center">

**Made with ❤️ by Local Project Team**

</div>
