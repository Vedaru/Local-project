# 依赖与可复现构建

## 依赖分层概览

Project Local 的依赖按功能分为多个层级，便于按需安装：

| 层级 | 说明 | 安装方式 |
|------|------|----------|
| **核心依赖** | LLM、GUI、语音识别、记忆系统等 | `pip install -r requirements.txt` |
| **PyTorch** | 深度学习框架（GPT-SoVITS 必需） | `install_dependencies.bat -Torch` |
| **GPT-SoVITS** | 语音合成引擎依赖 | `install_dependencies.bat -GptSovits` |
| **可选依赖** | Docker、AWS、爬虫等 | `install_dependencies.bat -Optional` |
| **开发依赖** | 测试、Lint、类型检查 | `install_dependencies.bat -Dev` |

## 单一真相（Single Source of Truth）

| 用途 | 文件 | 说明 |
|------|------|------|
| **pip 安装（推荐）** | 根目录 [`requirements.txt`](../requirements.txt) | 已钉死版本，用于开发、CI 测试与安全扫描（`pip-audit`）。 |
| **包元数据与工具配置** | [`pyproject.toml`](../pyproject.toml) | PEP 621 `project` 段 + `[tool.poetry]` 用于 `poetry build` / Black / Ruff / mypy 等；**运行时依赖版本应与 `requirements.txt` 保持一致**。 |
| **分层 YAML 配置** | [`config/`](../config/) | `default.yaml` → `{APP_ENV}.yaml` → 本地 `project_config.yaml`（可选覆盖）。 |

### 配置加载顺序

1. `config/default.yaml` — 无密钥的默认项
2. `config/development.yaml` 或 `config/production.yaml` — 由 `APP_ENV` 决定（默认 `development`）
3. `project_config.yaml` — 本地覆盖（gitignore，含 API Key 等敏感项）
4. 环境变量 — 最高优先级（如 `ARK_API_KEY`、`GATEWAY_API_KEY`）

### Python / PyTorch 版本矩阵

| 组件 | 要求 |
|------|------|
| Python | `>=3.10,<3.12` |
| PyTorch | `>=2.6.0`（transformers>=4.38 安全要求） |
| CUDA（可选） | 12.1  wheel：`--index-url https://download.pytorch.org/whl/cu121` |

## 依赖详情

### 核心依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| openai | 1.35.0 | LLM API 客户端 |
| python-dotenv | 1.0.0 | 环境变量管理 |
| requests | 2.31.0 | HTTP 客户端 |
| httpx[http2] | 0.28.1 | 异步 HTTP 客户端（含 HTTP/2 支持） |
| h2 | >=4.0.0 | HTTP/2 协议支持（微服务间通信必需） |
| pyyaml | 6.0 | YAML 配置解析 |
| pydantic | 2.5.0 | 数据验证 |
| jieba | 0.42.1 | 中文分词 |
| pyaudio | 0.2.14 | 音频输入/输出（TTS 播放必需） |
| python-pptx | 1.0.2 | PowerPoint 文档处理 |
| python-docx | 1.1.2 | Word 文档处理 |
| reportlab | 4.2.0 | PDF 生成 |
| faiss-cpu | 1.7.4 | 向量检索（记忆系统） |
| scikit-learn | 1.3.2 | 机器学习工具 |
| networkx | 3.2.1 | 图算法（知识图谱） |
| sentence-transformers | 2.2.2 | 文本嵌入 |
| PyQt6 | 6.6.1 | GUI 框架 |
| PyQt6-WebEngine | 6.6.0 | Web 视图组件 |
| qasync | 0.27.1 | PyQt 异步支持 |
| openai-whisper | 20231117 | 语音识别（ASR） |
| faster-whisper | 0.10.0 | 加速语音识别 |
| ctranslate2 | 3.24.0 | 推理加速引擎 |
| numpy | 1.24.3 | 数值计算 |
| pyautogui | 0.9.54 | 电脑控制 |
| pygetwindow | 0.0.9 | 窗口管理 |
| browser-use | 0.1.40 | 浏览器自动化 |
| playwright | 1.40.0 | 浏览器驱动 |
| tenacity | 8.2.3 | 重试机制 |
| structlog | 23.2.0 | 结构化日志 |
| loguru | 0.7.2 | 日志库 |
| tiktoken | 0.5.1 | Token 计数 |
| aiofiles | 23.2.1 | 异步文件操作 |
| colorama | 0.4.6 | 终端颜色 |
| fastapi | 0.104.1 | Web 框架（微服务） |
| uvicorn | 0.24.0 | ASGI 服务器 |
| html2text | 2020.1.16 | HTML 转文本 |
| googlesearch-python | 1.2.3 | Google 搜索 |
| baidusearch | 1.0.3 | 百度搜索 |
| duckduckgo_search | 3.9.6 | DuckDuckGo 搜索 |
| tomli | 2.0.1 | TOML 解析 |
| beautifulsoup4 | 4.12.2 | HTML 解析 |
| pytesseract | 0.3.10 | OCR 文字识别 |
| tqdm | 4.66.1 | 进度条 |

### GPT-SoVITS 语音合成依赖（可选）

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| torch | >=2.6.0 | PyTorch 核心框架（CVE-2025-32434 安全要求） |
| torchaudio | >=2.6.0 | 音频处理 |
| torchvision | >=0.21.0 | 视觉处理 |
| transformers | >=4.38.0 | HuggingFace 预训练模型 |
| huggingface_hub | >=0.19.0 | 模型下载 |
| peft | >=0.7.0 | 参数高效微调（LoRA） |
| pytorch-lightning | >=2.1.0 | 训练框架 |
| torchmetrics | >=1.2.0 | 指标计算 |
| einops | >=0.7.0 | 张量操作 |
| x-transformers | >=1.27.0 | Transformer 组件 |
| librosa | >=0.10.0 | 音频特征提取 |
| soundfile | >=0.12.0 | 音频文件 I/O |
| ffmpeg-python | >=0.2.0 | FFmpeg 绑定 |
| onnxruntime | >=1.16.0 | ONNX 推理 |
| pypinyin | >=0.49.0 | 拼音转换 |
| cn2an | >=0.5.22 | 中文数字转换 |
| nltk | >=3.8.0 | NLP 工具 |
| matplotlib | >=3.7.0 | 绘图 |

### OpenManus Agent 依赖（可选）

| 包名 | 版本要求 | 用途 | 备注 |
|------|----------|------|------|
| mcp | >=1.0.0 | Model Context Protocol | 核心功能 |
| docker | >=7.0.0 | Docker 沙箱 | try/except 保护 |
| boto3 | >=1.34.0 | AWS Bedrock 集成 | try/except 保护 |
| crawl4ai | >=0.2.0 | 网页爬取 | 动态导入 |

### 语言特定依赖（可选）

| 包名 | 用途 | 语言 |
|------|------|------|
| pyopenjtalk | 日语 TTS 前端 | 日语 |
| jamo | 韩语 Jamo 处理 | 韩语 |
| ko_pron | 韩语发音 | 韩语 |
| g2pk2 | 韩语 G2P | 韩语 |
| g2p_en | 英语 G2P | 英语 |
| wordsegment | 英语分词 | 英语 |

### 开发依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| pytest | 7.4.3 | 测试框架 |
| pytest-cov | 4.1.0 | 覆盖率 |
| pytest-asyncio | 0.21.1 | 异步测试 |
| pytest-mock | 3.12.0 | Mock 工具 |
| pytest-xdist | 3.5.0 | 并行测试 |
| black | 23.11.0 | 代码格式化 |
| isort | 5.12.0 | Import 排序 |
| ruff | 0.1.6 | Lint 工具 |
| mypy | 1.7.1 | 类型检查 |
| pre-commit | 3.6.0 | Git 钩子 |
| types-requests | 2.31.0.10 | 类型存根 |
| types-pyyaml | 6.0.12.12 | 类型存根 |

## 安装方式

### 方式一：Windows 批处理脚本（推荐）

```batch
# 安装核心依赖
install_dependencies.bat

# 安装核心 + PyTorch + GPT-SoVITS
install_dependencies.bat -Torch -GptSovits

# 安装所有依赖（含开发工具）
install_dependencies.bat -All

# 使用清华镜像源加速
install_dependencies.bat -Mirror -All
```

### 方式二：pip 直接安装

```powershell
# 核心依赖
python -m pip install -r requirements.txt

# PyTorch (CUDA 12.1, 要求 >=2.6.0)
python -m pip install "torch>=2.6.0" "torchaudio>=2.6.0" "torchvision>=0.21.0" --index-url https://download.pytorch.org/whl/cu121

# GPT-SoVITS 依赖
python -m pip install transformers huggingface_hub peft pytorch-lightning torchmetrics einops x-transformers librosa soundfile ffmpeg-python onnxruntime pypinyin cn2an nltk matplotlib

# 可选依赖
python -m pip install docker boto3 crawl4ai mcp
```

### 方式三：Poetry

```powershell
poetry install
```

## 重要说明

### PyTorch 版本要求

由于安全漏洞 [CVE-2025-32434](https://nvd.nist.gov/vuln/detail/CVE-2025-32434)，`transformers>=4.38` 要求 `torch>=2.6.0`。请确保安装正确版本的 PyTorch。

### HTTP/2 支持

微服务间通信使用 HTTP/2 协议，需要安装 `h2` 包。如果遇到 "Using http2=True, but the 'h2' package is not installed" 错误，请运行：

```powershell
pip install "httpx[http2]" h2
```

## 维护流程

1. **修改依赖时**：先更新 `requirements.txt` 中的钉死版本，再将 `pyproject.toml` 里 `[tool.poetry.dependencies]` 对齐到相同版本。
2. **CI**：Lint 使用与 `requirements.txt` 中一致的 Black / isort / Ruff / mypy 版本；测试类 job 使用 `pip install -r requirements.txt`，确保与本地「全量安装」一致。
3. **不使用 Poetry 的开发者**：仅需 `python -m pip install -r requirements.txt`。

## 常见问题

### Q: 为什么 PyTorch 不在 requirements.txt 中？

A: PyTorch 的安装命令因 CUDA 版本而异，无法用简单的 `pip install torch` 完成。请使用 `install_dependencies.bat -Torch` 或参考上述说明手动安装。

### Q: 安装时出现版本冲突怎么办？

A: 项目要求 Python >=3.10 且 <3.12。请确保使用正确的 Python 版本。如遇冲突，可尝试：

```powershell
pip install --force-reinstall -r requirements.txt
```

### Q: 出现 "h2 package is not installed" 错误？

A: 微服务使用 HTTP/2 通信，需要安装 h2：

```powershell
pip install "httpx[http2]" h2
```

### Q: 出现 torch.load 安全漏洞错误？

A: transformers>=4.38 要求 torch>=2.6.0。请升级 PyTorch：

```powershell
pip install "torch>=2.6.0" "torchaudio>=2.6.0" "torchvision>=0.21.0" --index-url https://download.pytorch.org/whl/cpu
```
