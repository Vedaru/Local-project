<div align="center">

**🌐 Language / 语言 / 言語**

[![中文](https://img.shields.io/badge/中文-简体-red?style=flat-square)](README.md)
[![English](https://img.shields.io/badge/English-blue?style=flat-square)](README_EN.md)
[![日本語](https://img.shields.io/badge/日本語-green?style=flat-square)](README_JA.md)

---

# 🤖 Project Local

**バーチャルアバター対応のローカル AI デスクトップアシスタント**

音声対話 · メモリシステム · ツール実行 · 3D Avatar · マイクロサービス連携

</div>

---

## 概要

Project Local は、LLM 対話、音声パイプライン、記憶管理、PC 操作、アバター表示をローカル優先で統合したプロジェクトです。
現在の既定実行形態は microservices-only で、GUI は gateway 経由で orchestrator と各バックエンドサービスを呼び出します。

## 主な機能

- マルチターン文脈を扱うスマート対話。
- ASR + TTS による音声チェーン。
- 好み更新を含む多層メモリ。
- アバターの表情・リップシンク。
- 拡張可能なツール群（ファイル操作、Web 検索/取得、Python 実行）。

## 性能最適化（今回の更新）

### 1) Rust Web 取得アクセラレーション

- パス: `rust_modules/web_fetcher_rs`
- 追加 API: `fetch_content_batch(urls, timeout, max_chars)`
- Python 統合: `WebContentFetcher` は Rust のバッチ取得を優先し、従来のフォールバックも維持。
- 最適化ポイント: Rust 側で共有 HTTP Client を再利用し、リクエストごとの初期化コストを削減。

### 2) Agent Tool のグローバル実行最適化

- パス: `modules/openmanus/app/tool/tool_collection.py`
- 追加機能:
  - `to_params()` のキャッシュ
  - `execute_many()` によるバッチ実行
  - 上限制御付き並列実行
  - `get_stats()` による実行統計
- Agent 統合: `modules/openmanus/app/agent/toolcall.py` がバッチ実行フローを利用。

### 3) C++ 音声生成パイプラインのアクセラレーション

- パス: `cpp_modules/voice_cpp_engine`、`modules/voice.py`、`modules/voice_cpp_accel.py`
- 追加機能:
  - C++ 音声チャンク索引 API: `build_chunk_index_cpp(total_size, chunk_size, ...)`
  - `tts_worker` はキャッシュヒット時とバッファフォールバック時に C++ 分割を優先
  - 旧版互換性と耐障害性のため Python 分割フォールバックを維持
- メトリクス: `cpp_chunk_accel_success` と `cpp_chunk_accel_errors` を追加し、加速の命中率を観測。

### 並列実行の設定

| 環境変数 | 既定値 | 説明 |
|---|---|---|
| `OPENMANUS_TOOL_PARALLEL_ENABLED` | `1` | ツール並列実行を有効化 |
| `OPENMANUS_TOOL_PARALLEL_MAX` | `4` | 最大同時実行数 |
| `WEB_FETCHER_RS_PY_EXT` | 空 | Rust 拡張 `.pyd/.so` の明示パス（任意） |

安全性のため、次のツールは既定で直列実行です:
`python_execute`, `str_replace_editor`, `file_operator`, `terminate`, `browser_use`, `tool_selector`。

## クイックスタート

### 方法 1: Windows 組み込み Runtime（推奨）

```batch
git clone https://github.com/Vedaru/Local-project.git
cd local-project

install_dependencies.bat
run_with_runtime.bat
```

実行前チェック:

```batch
check_runtime.bat
```

### 方法 2: システム Python / 仮想環境

```powershell
git clone https://github.com/Vedaru/Local-project.git
cd local-project

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## 任意: Rust 拡張のビルド

```powershell
python -m pip install maturin
python -m maturin develop --manifest-path rust_modules/web_fetcher_rs/Cargo.toml
```

独自ツールチェーンを使う場合は、Rust/Cargo と Python ABI の整合性を確認してください。

## 任意: C++ 音声アクセラレーションライブラリのビルド

```powershell
cmake -S cpp_modules/voice_cpp_engine -B build/voice_cpp_engine -DCMAKE_BUILD_TYPE=Release
cmake --build build/voice_cpp_engine --config Release
```

## テスト

```powershell
python -m pytest -q
```

主要な回帰テスト:

```powershell
python -m pytest tests/test_openmanus_web_search_fetcher.py -q
python -m pytest tests/test_openmanus_browser_enhancements.py -q
python -m pytest tests/test_voice_tts_chain.py -q
```

## リポジトリ構成（抜粋）

```text
Local-project/
├── modules/                     # 主要機能モジュール
├── microservices/               # gateway / orchestrator / backend services
├── rust_modules/web_fetcher_rs/ # Rust Web 取得拡張
├── tests/                       # テスト
└── docs/                        # 多言語ドキュメント
```

## 関連ドキュメント

- 中文开发指南: `CONTRIBUTING.md`
- English Developer Guide: `CONTRIBUTING_EN.md`
- 日本語開発ガイド: `CONTRIBUTING_JA.md`

## ライセンス

MIT。詳細は `../LICENSE` を参照してください。
