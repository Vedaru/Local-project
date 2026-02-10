# Project Local

一个本地运行的AI助手项目，结合大语言模型（LLM）、语音合成技术和电脑控制功能，提供智能对话、语音输入输出、人类化记忆管理和电脑操作自动化。采用模块化设计，支持多层次记忆系统，能够像人类一样自然地更新偏好和记忆。

## 功能特性

- **智能对话**：基于大语言模型的文本对话
- **语音交互**：集成语音识别和语音合成，支持语音输入输出
- **语音合成**：集成GPT-SoVITS实现高质量语音输出
- **电脑控制**：支持自动化电脑操作，如打开应用、输入文字、保存笔记、访问浏览器等
- **Avatar显示**：基于WebGL的3D虚拟形象，支持表情和口型同步
- **人类化记忆系统**：使用向量数据库存储和检索对话记忆
  - 多层次记忆（短期、工作、长期、情感记忆）
  - **智能冲突检测与偏好更新**（四步流程：定位→检索→判定→覆盖）
    - 实体定位：提取对话中的核心关键词
    - 冲突检索：基于实体和语义检索相关记忆
    - 智能判定：应用规则判断是否存在冲突
    - 自动覆盖：物理删除旧记忆，插入新记录
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
- **电脑控制配置**：
  - `whitelist`: 允许启动的应用程序白名单
  - `browser_path`: 默认浏览器路径
  - `notes_path`: 笔记保存目录
  - `safety_enabled`: 是否启用安全检查

## 使用方法

启动程序后，可以通过文本输入或语音输入与AI对话。AI将生成智能响应并可选输出语音。

### 基本命令
- 输入 `exit` 或 `quit` 退出程序
- 输入 `status` 查看记忆系统状态
- 程序会自动管理对话记忆，提供连续的对话体验
- 记忆系统支持偏好更新，如"我现在喜欢吃香蕉"会自动覆盖之前的"喜欢吃苹果"

### 电脑控制功能
AI可以执行以下电脑操作命令：
- **打开应用**：如"打开QQ"、"打开浏览器"等（需在白名单内）
- **访问网页**：如"打开百度"、"搜索Python教程"等
- **保存笔记**：如"保存笔记：今天的学习内容"等
- **输入文本**：AI可以模拟键盘输入中文和英文文本

### 语音交互
- 支持实时语音输入（需要麦克风权限）
- 语音合成输出高质量语音
- 自动过滤语音中的情感标签（如[开心]、[生气]等）

### Avatar显示
- 启动后会显示3D虚拟形象
- 支持表情同步和口型动画
- 可以调整窗口大小和透明度

api服务的终端输出会存放在Local-project\GPT-SoVITS-v2pro-20250604-nvidia50\gpt_sovits.log中

## 项目结构

```
Local-project/
├── .env                        # 环境变量配置
├── .gitattributes             # Git 配置
├── .gitignore                 # Git 忽略规则
├── assets/                    # 资源文件
│   ├── audio_ref/             # 参考音频文件
│   │   ├── ref_text.txt       # 参考文本
│   └── web/                   # 前端资源
│       ├── viewer.html        # Avatar 查看器
│       ├── js/                # JavaScript 文件
│       └── models/            # 3D 模型文件
├── config.yaml                # 配置文件
├── data/                      # 数据存储
│   ├── chroma_db/             # 向量数据库
│   │   ├── chroma.sqlite3     # ChromaDB 数据库文件
│   │   └── [collection_dirs]/ # 集合数据目录
│   ├── logs/                  # 日志文件
│   └── temp/                  # 运行时临时文件
├── GPT-SoVITS-v2pro-20250604-nvidia50/ # GPT-SoVITS 模型目录
│   ├── api_v2.py              # API 接口
│   ├── GPT_SoVITS/            # 核心模块
│   ├── GPT_weights*/          # GPT 模型权重
│   ├── SoVITS_weights*/       # SoVITS 模型权重
│   ├── runtime/               # Python 运行时环境
│   ├── tools/                 # 工具脚本
│   └── logs/                  # GPT-SoVITS 日志
├── main.py                    # 主入口文件
├── main copy.py               # 主入口文件副本（带语音识别）
├── modules/                   # 核心模块
│   ├── __init__.py            # 模块初始化
│   ├── _patch_ctranslate2.py  # CTranslate2 补丁
│   ├── avatar/                # Avatar 子模块
│   │   ├── __init__.py
│   │   ├── click_through.py   # 点击穿透
│   │   ├── expression.py      # 表情管理
│   │   ├── js_communication.py # JS 通信
│   │   ├── lip_sync.py        # 口型同步
│   │   ├── logger.py          # 日志
│   │   ├── manager.py         # Avatar 管理器
│   │   ├── resize.py          # 窗口调整
│   │   ├── tray.py            # 系统托盘
│   │   ├── webengine.py       # WebEngine 集成
│   │   └── widget.py          # 主窗口组件
│   ├── config.py              # 配置加载
│   ├── controller/            # 电脑控制模块
│   │   ├── __init__.py
│   │   ├── core.py            # 控制核心
│   │   ├── executor.py        # 动作执行器
│   │   └── safety.py          # 安全守卫
│   ├── ear.py                 # 语音识别模块
│   ├── llm.py                 # LLM 接口
│   ├── logging_config.py      # 日志配置
│   ├── memory/                # 记忆管理子模块
│   │   ├── __init__.py        # 记忆模块初始化
│   │   ├── analyzers.py       # 文本分析器
│   │   ├── config.py          # 记忆配置参数
│   │   ├── conflict/          # 冲突检测与覆盖模块
│   │   │   ├── __init__.py
│   │   │   ├── constants.py
│   │   │   ├── detector.py
│   │   │   ├── locator.py
│   │   │   ├── models.py
│   │   │   ├── resolver.py
│   │   │   └── utils.py
│   │   ├── core.py            # 核心记忆管理类
│   │   ├── logger.py          # 日志配置
│   │   ├── retrieval.py       # 记忆检索与去重
│   │   └── storage.py         # 存储层
│   ├── utils.py               # 工具函数
│   └── voice.py               # 语音管理
├── requirements.txt           # Python 依赖
├── temp/                      # 临时文件目录
└── README.md                  # 项目说明文档
```

## 故障排除

### 常见问题

**Q: 语音功能无法使用**
- 检查GPT-SoVITS服务是否正常启动
- 确认模型文件是否正确放置在指定目录
- 查看日志文件 `gpt_sovits.log` 获取详细错误信息

**Q: 电脑控制功能无法启动应用程序**
- 检查应用程序路径是否在 `config.yaml` 的白名单中
- 确认应用程序路径正确（使用双斜杠 `\\` 或原始字符串）
- 查看日志确认安全检查是否通过

**Q: 中文输入显示为乱码**
- 程序使用剪贴板方式输入中文文本
- 确保目标应用程序支持剪贴板粘贴操作

**Q: Avatar窗口无法显示**
- 检查WebGL支持和显卡驱动
- 确认前端资源文件完整
- 查看浏览器控制台错误信息

**Q: 记忆系统响应慢**
- 检查ChromaDB数据库文件大小
- 考虑清理过期记忆数据
- 调整相似度阈值参数

**Q: 语音识别不准确**
- 检查麦克风权限和设置
- 减少环境噪音
- 使用带语音识别的主入口文件 `main copy.py`

## 注意事项

- 首次运行需要下载模型文件，可能需要较长时间
- 确保GPT-SoVITS服务正常启动，否则语音功能将不可用
- 建议使用GPU加速以获得更好的性能
- 记忆系统会在 `data/chroma_db/` 目录存储向量数据，重启程序后记忆会保持
- **冲突检测系统**采用模块化设计，支持四种冲突类型：
  - 重复记忆：极高相似度（<0.15）的完全重复内容
  - 信息更新：包含更新意图 + 共同实体的更正信息
  - 偏好矛盾：同一对象的正反偏好冲突（如喜欢→不喜欢）
  - 同类偏好更新：同一类别偏好的更新（如食物偏好）
- 偏好更新功能会自动处理同类偏好冲突，如食物偏好、音乐偏好等

## 许可证

本项目采用MIT许可证。详见LICENSE文件。

## 贡献

欢迎提交Issue和Pull Request来改进项目。