---
name: mise-tasks
description: mise の task / config を扱う際に守るべき構造ルールと参照ドキュメントを確認する必要があるときに使用する。`mise.toml` の追加・編集、`mise/tasks/*.sh` や `mise/scripts/*.sh` の追加・修正、`mise run <task>` の動作変更、`#MISE` / `#USAGE` コメントの解釈・実装、新しい mise タスクの作成、mise の flag 引数渡し、env/tools セクションの設定など、mise が関与する全ての作業で適用する。
---

# mise タスクのルール

mise の task / 設定を扱うときは以下を必ず守ること。

## 1. ドキュメントを先に読む

実装に着手する前に、関連する公式ドキュメントを確認する。記憶や推測で書かない。

主要ページ:

- Tasks 全般: <https://mise.jdx.dev/tasks/>
- File tasks (`mise/tasks/*.sh` 形式): <https://mise.jdx.dev/tasks/file-tasks.html>
- Task arguments (`#USAGE` コメントによる flag 宣言): <https://mise.jdx.dev/tasks/task-arguments.html>
- TOML tasks (`mise.toml` 内記述): <https://mise.jdx.dev/tasks/toml-tasks.html>
- Running tasks: <https://mise.jdx.dev/tasks/running-tasks.html>
- 環境変数 / tools: <https://mise.jdx.dev/configuration/>

不明な挙動（例: `#USAGE flag` の `<value>` 引数の shell 変数展開、`depends` の動作、`quiet` / `hide` の効果など）に遭遇したら、コードを書く前に該当ページを `WebFetch` で読むこと。

## 2. `mise.toml` を肥大化させない

`mise.toml` は宣言的なメタデータの記述に留め、ロジックを書かない。

- **`mise.toml` に書いてよいもの**:
  - `[tools]` セクション（依存ツールのバージョン）
  - `[env]` セクション（環境変数定義）
  - 1〜2 行で済む簡単な task 宣言（`alias`, `description`, `depends` のみのもの）
  - 共通設定（`[settings]` 等）
- **`mise.toml` に書かないもの**:
  - 複数行の shell スクリプト
  - 条件分岐や loop を含むロジック
  - `printf` / `echo` 以外の副作用を持つ処理

## 3. ロジックは `mise/tasks/*.sh` または `mise/scripts/*.sh` に置く

shell ロジックは独立したファイルに分離する。これにより:

- `shellcheck` / `shfmt` が個別ファイルに対して効く
- エディタの bash 構文ハイライトが効く
- task の再利用やテストがしやすくなる

ファイル配置の使い分け:

- `mise/tasks/*.sh`: `mise run <task>` で直接呼ばれるエントリポイント。先頭に `#MISE description=...` コメントを置く
- `mise/scripts/*.sh`: tasks から `bash mise/scripts/foo.sh` で呼ばれるヘルパー。共通処理を切り出す
- `mise/common.sh`: 複数 script で再利用される関数（`print_red`, `select_one` 等）

### `#MISE` / `#USAGE` コメントの基本形

```bash
#!/usr/bin/env bash

#MISE description="何をするタスクか日本語で簡潔に"
#MISE depends=["init"]
#USAGE flag "-p --profile <profile>" {
#USAGE   help "何の flag か"
#USAGE   default "dev"
#USAGE   choices "dev" "prd"
#USAGE }

set -euo pipefail
# flag の値は ${usage_<name>} という shell 変数で参照できる
echo "${usage_profile:?}"
```

flag 値が空の場合のフォールバックは `${usage_csv:-}` のように明示的に書く（`set -u` と組み合わせるため）。

## 4. shell スクリプトの書き方

`mise/tasks/*.sh` および `mise/scripts/*.sh` は次のテンプレに従う:

```bash
#!/usr/bin/env bash

#MISE description="..."

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source "${ROOT_DIR}/mise/common.sh"

# 本体処理
```

- `set -euo pipefail` を必ず付ける
- `ROOT_DIR` 経由でプロジェクトルートに `cd` してから処理する
- 共通関数は `mise/common.sh` から source する
- `shellcheck` を通す（pre-commit hook が走る前提）

## 5. 編集後のチェック

実装後に必ず以下を確認:

- `bash -n <file>`: 構文エラー検出
- `shellcheck <file>`: lint
- `mise tasks` または `mise run <task> --help`: task 認識と `#USAGE` 反映の確認
- 必要なら実際に `mise run <task>` を実行して動作確認
