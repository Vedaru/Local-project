# Project Local

一个本地运行的AI助手项目，结合大语言模型（LLM）和语音合成技术，提供智能对话、语音输出和人类化记忆管理功能。采用模块化设计，支持多层次记忆系统，能够像人类一样自然地更新偏好和记忆。

## 功能特性

- **智能对话**：基于大语言模型的文本对话
- **语音合成**：集成GPT-SoVITS实现高质量语音输出
- **人类化记忆系统**：使用向量数据库存储和检索对话记忆
  - 多层次记忆（短期、工作、长期、情感记忆）
  - 智能冲突检测与偏好更新
  - 同类偏好自动覆盖（如食物偏好更新）
  - 并行检索与低延迟响应
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

   SYSTEM_PROMPT=example

   GPT_SOVITS_PATH=example

   MODEL_NAME=example
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
- **记忆配置**：向量数据库路径、集合名称、相似度阈值、遗忘参数
- **日志配置**：日志文件存储目录

## 使用方法

启动程序后，在命令行中输入文本，AI将生成响应并可选输出语音。

- 输入 `exit` 或 `quit` 退出程序
- 输入 `status` 查看记忆系统状态
- 程序会自动管理对话记忆，提供连续的对话体验
- 记忆系统支持偏好更新，如"我现在喜欢吃香蕉"会自动覆盖之前的"喜欢吃苹果"

api服务的终端输出会存放在Local-project\GPT-SoVITS-v2pro-20250604-nvidia50\gpt_sovits.log中

## 项目结构

```
Local-project/
├── main.py                 # 主入口文件
├── config.yaml            # 配置文件
├── requirements.txt       # Python依赖
├── .env                   # 环境变量配置
├── modules/               # 核心模块
│   ├── __init__.py        # 模块初始化
│   ├── config.py          # 配置加载
│   ├── llm.py            # LLM接口
│   ├── memory/           # 记忆管理子模块
│   │   ├── __init__.py   # 记忆模块初始化
│   │   ├── analyzers.py  # 文本分析器
│   │   ├── config.py     # 记忆配置参数
│   │   ├── conflict.py   # 冲突检测与覆盖
│   │   ├── core.py       # 核心记忆管理类
│   │   ├── logger.py     # 日志配置
│   │   ├── retrieval.py  # 记忆检索与去重
│   │   └── storage.py    # 存储层
│   ├── utils.py          # 工具函数
│   └── voice.py          # 语音管理
├── assets/                # 资源文件
│   ├── audio_ref/        # 参考音频
├── data/                  # 数据存储
│   ├── chroma_db/        # 向量数据库
│   └── logs/             # 日志文件
├── temp/                  # 临时文件
├── GPT-SoVITS-v2pro-.../ # GPT-SoVITS模型目录
└── README.md             # 项目说明文档
```

## 注意事项

- 首次运行需要下载模型文件，可能需要较长时间
- 确保GPT-SoVITS服务正常启动，否则语音功能将不可用
- 建议使用GPU加速以获得更好的性能
- 记忆系统会在 `data/chroma_db/` 目录存储向量数据，重启程序后记忆会保持
- 偏好更新功能会自动处理同类偏好冲突，如食物偏好、音乐偏好等

## 许可证

本项目采用MIT许可证。详见LICENSE文件。

## 贡献

欢迎提交Issue和Pull Request来改进项目。