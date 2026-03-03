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

**バーチャルアバター付きローカルAIデスクトップアシスタント**

音声対話 · スマートメモリ · PC制御 · 3Dアバター

[機能](#-機能) •
[クイックスタート](#-クイックスタート) •
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
| Python | 3.9 - 3.11 |
| OS | Windows / Linux / macOS |
| GPU | 推奨（音声合成の高速化用） |

### インストール手順

```bash
# 1. プロジェクトをクローン
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. 仮想環境を作成
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 3. 依存関係をインストール
pip install -r requirements.txt

# 4. 環境変数を設定（.envファイルを作成）
cp .env.example .env
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

# GPT-SoVITSパス
GPT_SOVITS_PATH=./GPT-SoVITS-v2pro-20250604-nvidia50

# ブラウザエージェント（オプション）
OPENAI_API_KEY=sk-xxxxxx
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
│   ├── 📂 chroma_db/          # ベクトルデータベース
│   ├── 📂 logs/               # ログファイル
│   └── 📂 temp/               # 一時ファイル
│
├── 📂 .github/workflows/      # CI/CD設定
└── 📂 scripts/                # 開発スクリプト
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
.\scripts\dev.ps1 setup

# pre-commitフックを設定
.\scripts\dev.ps1 pre-commit
```

### よく使うコマンド

| コマンド | 説明 |
|---------|------|
| `.\scripts\dev.ps1 test` | テストを実行 |
| `.\scripts\dev.ps1 test-cov` | テスト + カバレッジ |
| `.\scripts\dev.ps1 lint` | コードリンティング |
| `.\scripts\dev.ps1 format` | コードフォーマット |
| `.\scripts\dev.ps1 check` | すべてのチェックを実行 |

### コードスタイル

- 🎨 **Black** - コードフォーマット（行幅120）
- 📦 **isort** - インポートソート
- 🔍 **Ruff** - 高速リンティング
- 📝 **mypy** - 型チェック

詳しくは[CONTRIBUTING_JA.md](CONTRIBUTING_JA.md)を参照してください。

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

- ChromaDBデータベースファイルのサイズを確認
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
> - 記憶システムは`data/chroma_db/`ディレクトリにベクトルデータを保存します

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
