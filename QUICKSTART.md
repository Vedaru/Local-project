# 快速启动指南 - Project Local

本指南帮助你快速设置和启动 Project Local。

## 📋 前置准备

### 选项 A：使用独立 Runtime（推荐，Windows 用户）

✅ **无需安装 Python**，项目自带完整的 Python 3.9 运行环境

### 选项 B：使用系统 Python

✅ 需要安装 **Python 3.9 - 3.11**
✅ 推荐使用虚拟环境

---

## 🚀 快速启动流程

### ✨ 选项 A：使用独立 Runtime（5 分钟）

```powershell
# 1️⃣ 检查 Runtime 配置（可选但推荐）
.\check_runtime.ps1

# 2️⃣ 安装依赖
.\install_dependencies.ps1

# 如果需要开发工具（测试、格式化等）
.\install_dependencies.ps1 -Dev

# 如果在中国大陆，使用镜像加速
.\install_dependencies.ps1 -Mirror

# 3️⃣ 配置环境变量
copy .env.example .env
# 用记事本或其他编辑器打开 .env，填写 API 密钥

# 4️⃣ 启动项目
.\run_with_runtime.ps1
```

### 🐍 选项 B：使用系统 Python

```bash
# 1️⃣ 创建虚拟环境
python -m venv venv

# Windows 激活：
.\venv\Scripts\activate
# Linux/macOS 激活：
source venv/bin/activate

# 2️⃣ 安装依赖
pip install -r requirements.txt

# 3️⃣ 配置环境变量
# Windows:
copy .env.example .env
# Linux/macOS:
cp .env.example .env
# 编辑 .env 填写 API 密钥

# 4️⃣ 启动项目
python main.py
```

---

## ⚙️ 环境变量配置

打开 `.env` 文件，**至少配置以下必填项**：

```ini
# 必填：大语言模型 API
ARK_API_KEY=你的API密钥
MODEL_NAME=模型名称

# 可选：语音合成服务
SOVITS_URL=http://127.0.0.1:9880
```

其他配置项参见 [.env.example](.env.example) 文件内的注释。

---

## 🎯 功能配置

### 启用/禁用功能模块

编辑 `config.yaml`：

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

**祝使用愉快！** 🚀
