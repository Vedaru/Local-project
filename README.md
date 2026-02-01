# Project Local

一个本地运行的AI助手项目，结合大语言模型（LLM）和语音合成技术，提供智能对话和语音输出功能。

## 功能特性

- **智能对话**：基于大语言模型的文本对话
- **语音合成**：集成GPT-SoVITS实现高质量语音输出
- **记忆管理**：使用向量数据库存储和检索对话记忆
- **本地运行**：完全本地化，无需依赖云服务

## 环境要求

- Python 3.8+
- Windows/Linux/MacOS
- 足够的磁盘空间用于模型文件

## 安装步骤

1. **克隆项目**
   ```bash
   git clone <repository-url>
   cd Local-project
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **配置环境变量**

   创建 `.env` 文件并设置以下变量：
   ```
   ARK_API_KEY=your_api_key_here
   ```

4. **下载并配置GPT-SoVITS**

   - 下载GPT-SoVITS模型文件到 `GPT-SoVITS-v2pro-20250604-nvidia50/` 目录
   - 确保参考音频文件位于 `assets/audio_ref/ref_audio.wav`
   - 根据需要修改 `config.yaml` 中的配置

5. **运行项目**
   ```bash
   python main.py
   ```

## 配置说明

项目配置文件为 `config.yaml`，包含以下主要配置项：

- **API配置**：LLM API密钥、GPT-SoVITS服务地址
- **音频配置**：参考音频路径、提示文本、采样率
- **记忆配置**：向量数据库路径、集合名称
- **日志配置**：日志文件存储目录

## 使用方法

启动程序后，在命令行中输入文本，AI将生成响应并可选输出语音。

- 输入 `exit` 或 `quit` 退出程序
- 程序会自动管理对话记忆，提供连续的对话体验

## 项目结构

```
Local-project/
├── main.py                 # 主入口文件
├── config.yaml            # 配置文件
├── requirements.txt       # Python依赖
├── modules/               # 核心模块
│   ├── memory.py         # 记忆管理
│   ├── voice.py          # 语音管理
│   ├── llm.py            # LLM接口
│   ├── config.py         # 配置加载
│   └── utils.py          # 工具函数
├── assets/                # 资源文件
│   └── audio_ref/        # 参考音频
├── data/                  # 数据存储
│   ├── chroma_db/        # 向量数据库
│   └── logs/             # 日志文件
├── GPT-SoVITS-v2pro-.../ # GPT-SoVITS模型目录
└── temp/                 # 临时文件
```

## 注意事项

- 首次运行需要下载模型文件，可能需要较长时间
- 确保GPT-SoVITS服务正常启动，否则语音功能将不可用
- 建议使用GPU加速以获得更好的性能

## 许可证

本项目采用MIT许可证。详见LICENSE文件。

## 贡献

欢迎提交Issue和Pull Request来改进项目。