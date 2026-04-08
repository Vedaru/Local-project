# 開発者向け貢献ガイド

**Language / 言語 / 语言:**

- [中文](./CONTRIBUTING.md)
- [English](./CONTRIBUTING_EN.md)
- [日本語](./CONTRIBUTING_JA.md)

このドキュメントは、推奨される開発・テスト・貢献フローをまとめたものです。

## 1. 開発環境

### 前提条件

- Python 3.10 - 3.11（推奨）
- Git
- Rust ツールチェーン（`rust_modules/web_fetcher_rs` を変更する場合のみ必須）
- C++/CMake ツールチェーン（`cpp_modules/voice_cpp_engine` を変更する場合のみ必須）

### セットアップ

```powershell
git clone https://github.com/your-org/local-project.git
cd local-project

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2. ローカル実行とテスト

```powershell
python main.py
```

```powershell
python -m pytest -q
```

OpenManus のツールチェーンを変更した場合は、少なくとも次を実行してください：

```powershell
python -m pytest tests/test_openmanus_web_search_fetcher.py -q
python -m pytest tests/test_openmanus_browser_enhancements.py -q
python -m pytest tests/test_voice_tts_chain.py -q
```

## 3. Rust 取得拡張の開発フロー

次のファイルを変更した場合：

- `rust_modules/web_fetcher_rs`
- `modules/openmanus/app/tool/web_search.py`

拡張のビルドと検証を実行してください：

```powershell
python -m pip install maturin
python -m maturin develop --manifest-path rust_modules/web_fetcher_rs/Cargo.toml
python -m pytest tests/test_openmanus_web_search_fetcher.py -q
```

任意のネイティブチェック：

```powershell
cargo check --manifest-path rust_modules/web_fetcher_rs/Cargo.toml
```

## 4. C++ 音声アクセラレーション開発フロー

次のファイルを変更した場合：

- `cpp_modules/voice_cpp_engine`
- `modules/voice.py`
- `modules/voice_cpp_accel.py`

C++ ライブラリのビルドと音声回帰テストを実行してください：

```powershell
cmake -S cpp_modules/voice_cpp_engine -B build/voice_cpp_engine -DCMAKE_BUILD_TYPE=Release
cmake --build build/voice_cpp_engine --config Release
python -m pytest tests/test_voice_tts_chain.py -q
python -m pytest tests/test_voice_service_wav_cleanup.py -q
```

## 5. Tool 並列実行ポリシー

`ToolCollection` は `execute_many` によりバッチ/並列実行をサポートします。

安全性のため、以下は既定で直列実行です：

- `python_execute`
- `str_replace_editor`
- `file_operator`
- `terminate`
- `browser_use`
- `tool_selector`

副作用のある新規ツールを追加する際は、直列実行対象にすべきかを必ず評価してください。

関連環境変数：

- `OPENMANUS_TOOL_PARALLEL_ENABLED`：並列実行の有効/無効
- `OPENMANUS_TOOL_PARALLEL_MAX`：最大同時実行数

## 6. ドキュメント同期要件

アーキテクチャ、実行方式、性能仕様を変更した場合は、次の 6 ファイルを同期更新してください：

- `docs/README.md`
- `docs/README_EN.md`
- `docs/README_JA.md`
- `docs/CONTRIBUTING.md`
- `docs/CONTRIBUTING_EN.md`
- `docs/CONTRIBUTING_JA.md`

## 7. 貢献フロー

1. ブランチ作成：`git checkout -b feat/your-topic`
2. 実装とコミット
3. テスト成功を確認
4. Pull Request を作成

コミットメッセージ形式：

```text
<type>: <summary>
```

よく使う `type`：

- `feat`
- `fix`
- `refactor`
- `test`
- `docs`
- `chore`

## 8. PR チェックリスト

- [ ] 変更範囲が目的に一致している
- [ ] 関連する回帰テストを実行した
- [ ] 明らかな性能劣化を導入していない
- [ ] 必要時に CN/EN/JA 文書を同期更新した
- [ ] コミットメッセージが明確である
