# 開発者ガイド

**Language / 語言 / 言語:**

- [中文](./CONTRIBUTING.md)
- [English](./CONTRIBUTING_EN.md)
- [日本語](./CONTRIBUTING_JA.md)

このドキュメントでは、開発環境のセットアップ、テストの実行、および Local-project へのコード貢献方法について説明します。

## 目次

- [開発環境のセットアップ](#開発環境のセットアップ)
- [プロジェクト構造](#プロジェクト構造)
- [コード規約](#コード規約)
- [テスト](#テスト)
- [CI/CD](#cicd)
- [モジュール説明](#モジュール説明)

## 開発環境のセットアップ

### 前提条件

- Python 3.9 - 3.11
- pip または Poetry
- Git

### クイックスタート

```powershell
# 1. リポジトリをクローンする
git clone https://github.com/your-org/local-project.git
cd local-project

# 2. 仮想環境を作成する
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. 依存関係をインストールする
.\scripts\dev.ps1 setup

# 4. pre-commit フックをセットアップする
.\scripts\dev.ps1 pre-commit
```

### Poetry を使用する（推奨）

```powershell
# Poetry をインストールする
pip install poetry

# すべての依存関係をインストールする
poetry install

# 仮想環境を有効化する
poetry shell
```

## プロジェクト構造

```
Local-project/
├── modules/              # コアモジュール
│   ├── agent/           # AI Agent モジュール
│   ├── avatar/          # アバターモジュール
│   ├── memory/          # メモリシステム
│   ├── config.py        # 設定管理
│   ├── health.py        # ヘルスチェック
│   ├── launcher.py      # アプリケーション起動器
│   ├── llm.py           # LLM 呼び出し
│   ├── resilience.py    # エラーハンドリングとリトライ
│   ├── utils.py         # ユーティリティ関数
│   └── voice.py         # 音声合成
├── tests/               # テストファイル
├── assets/              # 静的アセット
├── data/                # データディレクトリ
├── scripts/             # 開発スクリプト
├── .github/workflows/   # CI/CD 設定
├── main.py              # メインエントリーポイント
├── pyproject.toml       # プロジェクト設定
└── requirements.txt     # 依存関係リスト
```

## コード規約

### フォーマッティング

プロジェクトは一貫したコードスタイルを維持するために、以下のツールを使用しています：

- **Black**: コード フォーマッティング（行幅 120）
- **isort**: インポート並べ替え
- **Ruff**: 高速 Python リンター

```powershell
# コードをフォーマットする
.\scripts\dev.ps1 format

# または手動で実行する
black modules/ tests/ main.py
isort modules/ tests/ main.py
```

### 型ヒント

型ヒント の使用が推奨され、mypy で検査されます：

```python
def process_text(text: str, max_length: int = 100) -> Optional[str]:
    """テキストを処理して結果を返す"""
    if not text:
        return None
    return text[:max_length]
```

```powershell
# 型チェック
mypy modules/ --ignore-missing-imports
```

### Pre-commit フック

コミット前に自動的にチェックが実行されます：

```powershell
# フックをインストールする
pre-commit install

# すべてのチェックを手動で実行する
pre-commit run --all-files
```

## テスト

### テストの実行

```powershell
# すべてのテストを実行する
.\scripts\dev.ps1 test

# または pytest で直接実行する
pytest tests/ -v

# 特定のテストファイルを実行する
pytest tests/test_utils.py -v

# 特定のテストを実行する
pytest tests/test_utils.py::TestCleanText::test_clean_text -v
```

### テストカバレッジ

```powershell
# カバレッジレポートを生成する
.\scripts\dev.ps1 test-cov

# HTML レポートを表示する
start htmlcov/index.html
```

### テストの作成

テストファイルは `tests/` ディレクトリに配置され、命名形式は `test_<module>.py` です：

```python
# tests/test_example.py
import pytest
from modules.example import my_function

class TestMyFunction:
    """my_function のテスト"""
    
    def test_basic_case(self):
        """基本的な機能をテストする"""
        result = my_function("input")
        assert result == "expected"
    
    @pytest.mark.slow
    def test_slow_operation(self):
        """時間がかかるテスト"""
        # スロー としてマーク、デフォルトはスキップ
        pass
```

### テストマーカー

- `@pytest.mark.slow` - 遅いテスト（`--runslow` で実行）
- `@pytest.mark.integration` - 統合テスト（`--runintegration` で実行）
- `@pytest.mark.unit` - ユニットテスト

## CI/CD

プロジェクトは GitHub Actions を使用して継続的インテグレーションを実行します：

### CI パイプライン

1. **コード品質チェック** - Black, isort, Ruff, mypy
2. **ユニットテスト** - 複数の Python バージョンと OS で実行
3. **カバレッジレポート** - Codecov にアップロード
4. **セキュリティスキャン** - Bandit, pip-audit

### ローカル検証

コミット前に完全なチェックを実行します：

```powershell
.\scripts\dev.ps1 check
```

## モジュール説明

### resilience.py - エラーハンドリングとリトライ

統一されたエラーハンドリングメカニズムを提供します：

```python
from modules.resilience import retry, RetryStrategy, CircuitBreaker

# リトライデコレーターを使用する
@retry(max_retries=3, strategy=RetryStrategy.EXPONENTIAL)
def call_external_api():
    # API 呼び出し
    pass

# サーキットブレーカーを使用する
breaker = CircuitBreaker(failure_threshold=5)

@breaker
def risky_operation():
    # 失敗する可能性のある操作
    pass
```

### health.py - ヘルスチェック

重要なサービスのステータスを監視します：

```python
from modules.health import health_checker, check_sovits_health

# ヘルスチェックを登録する
health_checker.register("sovits", check_sovits_health)

# チェックを実行する
result = health_checker.check("sovits")
print(f"Status: {result.status}")

# すべてのサービスをチェックする
health = health_checker.check_all()
print(f"Overall: {health.overall_status}")
```

### launcher.py - アプリケーション起動器

アプリケーションのライフサイクルを管理します：

```python
from modules.launcher import initialize_core_services, app_context

# すべてのサービスを初期化する
services = initialize_core_services(
    enable_sovits=True,
    enable_agent=True,
)

# サービスインスタンスを取得する
memory_manager = app_context.get_service("memory_manager")

# リソースをクリーンアップする（atexitに自動登録）
app_context.cleanup()
```

## 貢献ガイドライン

1. リポジトリをフォークする
2. フィーチャーブランチを作成する (`git checkout -b feature/amazing-feature`)
3. 変更をコミットする (`git commit -m 'Add amazing feature'`)
4. ブランチにプッシュする (`git push origin feature/amazing-feature`)
5. Pull Request を作成する

### コミットメッセージ規約

```
<type>: <description>

[optional body]
```

タイプ：
- `feat`: 新機能
- `fix`: バグ修正
- `docs`: ドキュメント更新
- `style`: コードフォーマッティング（機能に影響なし）
- `refactor`: リファクタリング
- `test`: テスト関連
- `chore`: ビルド/ツール関連
