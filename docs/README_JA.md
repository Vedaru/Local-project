<div align="center">

**🌐 Language / 语言 / 言語**

[![中文](https://img.shields.io/badge/中文-简体-red?style=flat-square)](README.md)
[![English](https://img.shields.io/badge/English-blue?style=flat-square)](README_EN.md)
[![日本語](https://img.shields.io/badge/日本語-green?style=flat-square)](README_JA.md)

---

# 🤖 Project Local

[![Python](https://img.shields.io/badge/Python-3.10--3.11-blue?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://img.shields.io/badge/CI-GitHub_Actions-orange?logo=github-actions&logoColor=white)](.github/workflows/ci.yml)
[![Code Style](https://img.shields.io/badge/Code%20Style-Black-black)](https://github.com/psf/black)

**バーチャルアバター付きローカルAIデスクトップアシスタント**

音声対話 · スマートメモリ · PC制御 · 3Dアバター

[機能](#-機能) •
[クイックスタート](#-クイックスタート) •
[ランタイム設定](#-ランタイム設定) •
[設定](#%EF%B8%8F-設定) •
[プロジェクト構成](#-プロジェクト構成) •
[開発ガイド](#-開発ガイド)

</div>

---

## ✨ 機能

<table>
<tr>
<td width="50%">

### 🎯 コア機能

- **💬 スマート会話** - LLMによる自然な対話
- **🎙️ 音声対話** - リアルタイム音声認識 + 高品質音声合成
- **🧠 人間らしい記憶** - 多層記憶システム、好み更新対応
- **🖥️ PC制御** - 自動化：アプリ起動、ウェブ閲覧など
- **👤 3Dアバター** - WebGLバーチャルキャラクター、表情・リップシンク

</td>
<td width="50%">

### 🧠 記憶システムのハイライト

- 📊 **多層記憶** - 短期/作業/長期/感情記憶
- 🔄 **スマート競合検出** - 4ステップ自動処理
- 🎯 **自動好み更新** - 「りんごが好き」→「バナナが好き」
- ⚡ **並列検索** - 低レイテンシ応答
- 🔒 **完全ローカル** - クラウドサービス不要

</td>
</tr>
</table>

---

## 🚀 クイックスタート

### 必要要件

| 要件 | バージョン |
|------|----------|
| Python | 3.10 - 3.11 |
| OS | Windows / Linux / macOS |
| GPU | 推奨（音声合成の高速化用） |
オプション 1: 組み込みランタイムを使用（Windows推奨）

プロジェクトにはスタンドアロンの Python 3.9 ランタイムが付属しており、システム Python のインストールは不要です：

```batch
# 1. プロジェクトをクローン
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. PowerShell で依存関係をインストール（推奨）
.\install_dependencies.ps1

# 3. 環境変数を設定（.env ファイルを作成）
copy .env.example .env
# .env を編集して API キーを記入

# 4. プロジェクトを実行
.\run_with_runtime.ps1
# または唯一のワンクリックバッチ: .\run_with_runtime.bat
```

### オプション 2: システム Python または仮想環境を使用

既に Python 3.10-3.11 がある場合：

```bash
# 1. プロジェクトをクローン
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. 仮想環境を作成（推奨）
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 3. 依存関係をインストール
pip install -r requirements.txt

# 4. 環境変数を設定（.env ファイルを作成）
cp .env.example .env
# .env を編集して API キーを記入v
# .envを編集してAPIキーを入力

# 5. 実行
python main.py
```

### 環境変数の設定

`.env`ファイルを作成：

```ini
# LLM API設定
ARK_API_KEY=your_api_key_here
MODEL_NAME=your_model_name

# システムプロンプト（オプション、ファイルパス対応）
SYSTEM_PROMPT_FILE=SYSTEM_PROMPT.txt

# ブラウザエージェント（オプション）
OPENAI_API_KEY=sk-xxxxxx
```

### 🎯 機能設定

`config.yaml` を編集して機能モジュールを有効/無効にします：

```yaml
# PC制御機能
controller:
  enabled: true          # false に変更して無効化

# 音声認識機能
ear:
  enabled: false         # true に変更して有効化
  model_size: "base"     # モデルサイズ: tiny, base, small, medium
```

---

## 🐛 よくある質問

### ❌ python.exe が見つかりません

**症状**: `Cannot find Python Runtime: runtime\python.exe`

**解決方法**:
1. `runtime` ディレクトリに完全な Python 3.9 ランタイムが含まれていることを確認
2. ヘルスチェックを実行: `.\check_runtime.ps1`
3. [RUNTIME.md](RUNTIME.md) を参照して再設定

### ❌ モジュールのインポートに失敗

**症状**: `ModuleNotFoundError: No module named 'xxx'`

**解決方法**:
```powershell
# ランタイムの使用:
.\install_dependencies.ps1

# システム Python を使用:
pip install -r requirements.txt
```

### ❌ 起動直後に終了

**チェックステップ**:
1. ログファイルを確認: `data/logs/project_local.log`
2. `.env` 設定が正しいことを確認（API キーなど）
3. ヘルスチェックを実行: `.\check_runtime.ps1`

### ❌ ctranslate2 エラー

**症状**: `ctranslate2` に関連する DLL ロードエラー

**解決方法**:
- スタートアップスクリプトは自動的に `CT2_USE_CUDA=0` を設定
- 問題が続く場合は、環境変数が正しいことを確認

### ❌ 音声機能が機能しない

**症状**: `GPT-SoVITS service not found`

**解決方法**:
- GPT-SoVITS サービスが正常に実行されているか確認
- モデルファイルが正しく配置されているか確認
- ログを確認: `modules/gpt_sovits/gpt_sovits.log`

### ❌ PC制御がアプリを起動できない

**症状**: アプリが開かないか権限エラー

**解決方法**:
- アプリパスが `config.yaml` のホワイトリストに含まれているか確認
- パスが正しいことを確認（`\\` または raw 文字列を使用）
- ログを確認してセキュリティチェックが通ったか確認

---

## 📚 さらに詳しく

- **完全なドキュメント**: [README.md](README.md)
- **ランタイム詳細ガイド**: [RUNTIME.md](RUNTIME.md)
- **貢献ガイド**: [CONTRIBUTING_JA.md](CONTRIBUTING_JA.md)
- **開発スクリプト**: [dev.ps1](dev.ps1)

---

## 🆘 ヘルプを求める

1. **ログを確認**: `data/logs/project_local.log`
2. **診断を実行**: `.\check_runtime.ps1`
3. **ドキュメントを参照**: 上記のリンクを参照
4. **Issue を提出**: [GitHub Issues](https://github.com/your-org/local-project/issues)

---

## ✅ インストールの確認

起動に成功すると、以下が表示されます：

```
============================================
Project Local - 組み込みランタイムを使用
============================================
Python: d:\...\Local-project\runtime\python.exe
プロジェクトディレクトリ: d:\...\Local-project
============================================

Project Local を起動中...
[INFO] 設定ファイルを読み込んでいます...
[INFO] モジュールを初期化しています...
[INFO] アバターウィンドウが起動しました
```

アバターウィンドウが表示されてエラーがなければ、Project Local の起動に成功しました！🎉

---

## ⚙️ ランタイム設定

### 📦 概要

プロジェクトはスタンドアロンの Python 3.9 ランタイム環境（`runtime` に配置）を提供し、システム Python から隔離されており、依存関係の一貫性と移植性を確保します。

### 📁 ランタイム構造

```
runtime/
├── python.exe              # Python 3.9 インタプリタ
├── python39.dll            # Python コアライブラリ
├── python39._pth           # Python パス設定
├── python39.zip            # 標準ライブラリ（圧縮）
├── Lib/                    # Python 標準ライブラリ
│   └── site-packages/      # サードパーティパッケージディレクトリ
├── Scripts/                # 実行可能スクリプトディレクトリ
│   ├── pip.exe             # pip パッケージマネージャー
│   └── ...
├── include/                # C/C++ ヘッダーファイル
└── libs/                   # リンクライブラリ
```

### ⚙️ モジュール検索パス (python39._pth)

`python39._pth` ファイルは Python モジュール検索パスを定義：

```
python39.zip                # 圧縮標準ライブラリ
.                           # ランタイムディレクトリ自体
Lib                         # 標準ライブラリディレクトリ
Lib\site-packages           # サードパーティパッケージディレクトリ
..                          # プロジェクトルートディレクトリ
..\..\modules               # modules パッケージ

import site                 # site-packages を有効化
```

### 🚀 ランタイムスクリプト

#### 依存関係のインストール

```powershell
# 本番依存関係のみをインストール
.\install_dependencies.ps1

# 本番 + 開発依存関係をインストール
.\install_dependencies.ps1 -Dev

# ミラーを使用してダウンロード高速化
.\install_dependencies.ps1 -Mirror
```

#### プロジェクトを開始

```powershell
# PowerShell（推奨）
.\run_with_runtime.ps1

# またはバッチスクリプト
.\run_with_runtime.bat
```

#### ヘルスチェック

```powershell
# ランタイム設定を診断
.\check_runtime.ps1
```

#### 手動使用

```batch
# Python を直接実行
runtime\python.exe script.py

# pip を使用
runtime\Scripts\pip.exe install package-name
```

### 🔧 自動設定される環境変数

| 変数 | 値 | 説明 |
|-----|-----|------|
| `CT2_USE_CUDA` | `0` | ctranslate2 CUDA を無効化してパス問題を回避 |
| `LOKY_MAX_CPU_COUNT` | 自動 | 中国語 Windows でのエンコード問題を修正 |

### 🐛 ランタイムトラブルシューティング

<details>
<summary><b>python.exe が見つからない</b></summary>

- `runtime/python.exe` が存在することを確認
- ランタイムディレクトリの完全性を確認
- `.\check_runtime.ps1` を実行して診断

</details>

<details>
<summary><b>モジュールインポート失敗 (ModuleNotFoundError)</b></summary>

- `python39._pth` の相対パスを確認
- 依存関係がインストール済みかを確認：`runtime\Scripts\pip.exe list`
- `.\install_dependencies.ps1` を再実行

</details>

<details>
<summary><b>DLL 読み込み失敗</b></summary>

- Visual C++ Redistributable 2015-2022 をインストール
- 依存パッケージの再インストールを試みる
- システムライブラリの欠落を確認

</details>

### 📚 高度な設定

**ランタイムを更新**:
```batch
# 現在のバージョンをバックアップ
xcopy runtime runtime_backup /E /I /H

# 新しい Python 3.9 組み込みバージョンに置き換えた後
.\install_dependencies.ps1
```

**依存関係管理**:
```batch
# インストール済みパッケージをリスト
runtime\Scripts\pip.exe list

# 依存関係をエクスポート
runtime\Scripts\pip.exe freeze > requirements.txt
```

---

## ⚙️ 設定

設定ファイル：`config.yaml`

```yaml
# API設定
api:
  sovits_url: "http://127.0.0.1:9880"

# オーディオ設定
audio:
  ref_audio_path: "assets/audio_ref/ref_audio.wav"
  sample_rate: 32000

# PC制御設定
controller:
  enabled: true
  failsafe: true
  app_whitelist:
    notepad: "C:\\Windows\\System32\\notepad.exe"
    edge: "C:\\Program Files\\Microsoft\\Edge\\msedge.exe"
```

<details>
<summary>📋 <b>ログシステム</b>（クリックで展開）</summary>

ログシステムは統一的、モジュール化、構造化された設計を採用：

- **保存場所**：`data/logs/project_local.log`（日次ローテーション）
- **ファイル形式**：JSON（検索/アラート用）
- **コンソール**：カラー出力（INFO以上）

```python
from modules.logging_config import get_logger
logger = get_logger('MyModule')
logger.info('Hello!')
```

</details>

---

## 📖 使い方

### 基本コマンド

| コマンド | 説明 |
|---------|------|
| `exit` / `quit` | プログラムを終了 |
| `status` | 記憶システムの状態を表示 |

### 🖥️ PC制御

AIが実行できる操作：

- 📂 **アプリを開く** - 「QQを開いて」、「メモ帳を開いて」
- 🌐 **ウェブサイトにアクセス** - 「Googleを開いて」、「Pythonチュートリアルを検索」
- 📝 **メモを保存** - 「メモを保存：今日の学習内容」
- ⌨️ **テキスト入力** - キーボード入力をシミュレート（多言語対応）

### 🎙️ 音声対話

- ✅ リアルタイム音声入力（マイク権限が必要）
- ✅ 高品質な音声合成出力
- ✅ 感情タグの自動フィルタ（例：`[嬉しい]`、`[怒り]`）

### 👤 アバター表示

- 🎨 3Dバーチャルキャラクター（WebGL）
- 😊 表情同期
- 👄 リップアニメーション
- 🔧 ウィンドウサイズと透明度の調整可能

---

## 📁 プロジェクト構成

```
Local-project/
├── 📄 main.py                 # エントリーポイント
├── 📄 config.yaml             # 設定ファイル
├── 📄 pyproject.toml          # プロジェクト設定（Poetry）
├── 📄 requirements.txt        # 依存関係リスト
│
├── 📂 modules/                # コアモジュール
│   ├── 📂 agent/              # AIエージェント（ReAct + ツール）
│   ├── 📂 avatar/             # アバターモジュール
│   ├── 📂 memory/             # 記憶システム
│   ├── 📄 config.py           # 設定管理
│   ├── 📄 ear.py              # 音声認識
│   ├── 📄 health.py           # ヘルスチェック
│   ├── 📄 launcher.py         # アプリランチャー
│   ├── 📄 llm.py              # LLMインターフェース
│   ├── 📄 resilience.py       # エラー処理とリトライ
│   ├── 📄 utils.py            # ユーティリティ関数
│   └── 📄 voice.py            # 音声合成
│
├── 📂 tests/                  # テストファイル
├── 📂 assets/                 # 静的リソース
│   ├── 📂 audio_ref/          # 参照音声
│   └── 📂 web/                # フロントエンドリソース
├── 📂 data/                   # データストレージ
│   ├── 📂 memoripy/           # 記愆システムデータ
│   ├── 📂 logs/               # ログファイル
│   └── 📂 temp/               # 一時ファイル
│
├── 📂 .github/workflows/      # CI/CD設定
├── 📄 dev.ps1                 # 開発スクリプトのエントリ
└── 📄 start_microservices_with_monitor.ps1  # マイクロサービス起動スクリプト
```

<details>
<summary>📋 <b>詳細なモジュール説明</b>（クリックで展開）</summary>

### Agentサブモジュール (`modules/agent/`)
| ファイル | 説明 |
|---------|------|
| `core.py` | エージェントのコアロジック（ReActループ） |
| `tools.py` | ツールラッパー（ActionExecutor含む） |
| `browser.py` | ブラウザ/ウェブ検索ツール |
| `safety.py` | SafetyGuardホワイトリスト検証 |
| `window.py` | ウィンドウ管理ヘルパー |
| `file_tools.py` | ファイル/メモアシスタント |

### Avatarサブモジュール (`modules/avatar/`)
| ファイル | 説明 |
|---------|------|
| `widget.py` | メインウィンドウコンポーネント |
| `expression.py` | 表情管理 |
| `lip_sync.py` | リップシンク |
| `click_through.py` | クリックスルー |
| `webengine.py` | WebEngine統合 |

### Memoryサブモジュール (`modules/memory/`)
| ファイル | 説明 |
|---------|------|
| `core.py` | コア記憶マネージャー |
| `storage.py` | ストレージ層 |
| `retrieval.py` | 記憶検索と重複排除 |
| `conflict/` | 競合検出と上書き |

</details>

---

## 💻 開発ガイド

### 開発環境のセットアップ

```powershell
# 開発依存関係をインストール
.\dev.ps1 setup

# pre-commitフックを設定
.\dev.ps1 pre-commit
```

### よく使うコマンド

| コマンド | 説明 |
|---------|------|
| `.\dev.ps1 test` | テストを実行 |
| `.\dev.ps1 test-cov` | テスト + カバレッジ |
| `.\dev.ps1 lint` | コードリンティング |
| `.\dev.ps1 format` | コードフォーマット |
| `.\dev.ps1 check` | すべてのチェックを実行 |

### コードスタイル

- 🎨 **Black** - コードフォーマット（行幅120）
- 📦 **isort** - インポートソート
- 🔍 **Ruff** - 高速リンティング
- 📝 **mypy** - 型チェック

詳しくは[CONTRIBUTING_JA.md](CONTRIBUTING_JA.md)を参照してください。

---

## 🧪 テストと CI

### ローカルテスト

```powershell
# すべてのテストを実行
python -m pytest tests/ -v

# 高速フェイルモードを実行（最初の失敗で停止）
python -m pytest tests/ -x

# カバレッジチェックを実行
python -m pytest tests/ --cov=modules --cov-report=html
```

### CI/CDパイプライン

プロジェクトは継続的統合に **GitHub Actions** を使用：

| チェック | 説明 | ステータス |
|----------|------|----------|
| 🧪 **テスト** | 91個のユニットテスト（Python 3.10、3.11 マトリックス） | ✅ 厳密 |
| 🎨 **フォーマット** | Black、isort、Ruff チェック | ⚠️ オプション |
| 📝 **型** | mypy 型チェック | ⚠️ オプション |
| 📊 **カバレッジ** | 最小カバレッジ 20% | ⚠️ オプション |
| 🔒 **セキュリティ** | Bandit、pip-audit スキャン | ⚠️ 情報提供 |

**注意**：コード品質チェックは警告のみで、CIは失敗しません。テスト失敗のみがマージをブロックします。

---

## ❓ トラブルシューティング

<details>
<summary><b>🔊 音声機能が動作しない</b></summary>

- GPT-SoVITSサービスが正常に起動しているか確認
- モデルファイルが正しく配置されているか確認
- ログを確認：`GPT-SoVITS-v2pro-20250604-nvidia50/gpt_sovits.log`

</details>

<details>
<summary><b>🖥️ PC制御でアプリを起動できない</b></summary>

- アプリのパスが`config.yaml`のホワイトリストに含まれているか確認
- パスが正しいか確認（`\\`または生文字列を使用）
- ログでセキュリティチェックが通過したか確認

</details>

<details>
<summary><b>👤 アバターウィンドウが表示されない</b></summary>

- WebGLのサポートとグラフィックスドライバを確認
- フロントエンドリソースファイルが完全か確認
- ブラウザコンソールのエラーを確認

</details>

<details>
<summary><b>🐢 記憶システムの応答が遅い</b></summary>

- 記愆データベースファイルのサイズを確認
- 期限切れの記憶データのクリーンアップを検討
- 類似度しきい値パラメータを調整

</details>

<details>
<summary><b>📷 OCR / Tesseractエラー</b></summary>

1. Tesseractをインストールし、言語パックをダウンロード
2. 環境変数`TESSDATA_PREFIX`を設定
3. プログラムは`eng.traineddata`の自動ダウンロードを試みます

</details>

<details>
<summary><b>⌨️ 日本語入力が文字化けする</b></summary>

- プログラムは日本語テキスト入力にクリップボード方式を使用
- 対象アプリケーションがクリップボード貼り付けをサポートしているか確認

</details>

---

## ⚠️ 注意事項

> - 初回実行時はモデルファイルのダウンロードが必要で、時間がかかる場合があります
> - GPT-SoVITSサービスが起動していることを確認してください。そうでないと音声機能は利用できません
> - より良いパフォーマンスのためにGPUアクセラレーションを推奨
> - 記愆システムは`data/memoripy/`ディレクトリに交互履歴データを保存します

### 競合検出システム

4種類の競合タイプをサポート：

| タイプ | 説明 |
|--------|------|
| 🔄 重複記憶 | 極めて高い類似度（<0.15）の完全な重複 |
| 📝 情報更新 | 更新意図 + 共通エンティティを含む修正情報 |
| ❤️ 好みの矛盾 | 同じ対象に対する肯定/否定の好み競合 |
| 🍎 同カテゴリ更新 | 同じカテゴリの好み更新（例：食べ物の好み） |

---

## 📜 ライセンス

このプロジェクトは[MITライセンス](LICENSE)の下でライセンスされています。

---

## 🤝 コントリビューション

IssueやPull Requestを歓迎します！

詳しくは[貢献ガイド](CONTRIBUTING_JA.md)をご覧ください。

---

<div align="center">

**Made with ❤️ by Local Project Team**

</div>

