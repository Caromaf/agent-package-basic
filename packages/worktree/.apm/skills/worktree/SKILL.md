---
name: worktree
description: git worktree で作業ディレクトリを分離し、未コミット変更の競合を防ぎながら別ブランチで作業する必要があるときに使用する。`EnterWorktree` / `ExitWorktree` 専用ツールが利用できないランタイムでも、素の `git worktree` コマンドで作成・保持・削除を一貫して扱える。
---

# Worktree

git worktree を使って作業ディレクトリを分離し、未コミットの変更の競合を防止します。
the agent に `EnterWorktree` / `ExitWorktree` 相当の専用ツールがない場合は、通常の `git worktree` コマンドで作成・削除し、以降の操作では作成した worktree のパスを明示的に作業対象として扱います。

## 引数のパースルール

```text
worktree [worktree 名] [--exit] [--exit-remove]
```

- 引数なし: 新しい git worktree を作成する。名前は現在のブランチ名と時刻から生成する
- `worktree 名`: 指定した名前で git worktree を作成する。例: `worktree fix-auth-bug`
- `--exit`: 現在記録している worktree を保持したまま、以降の作業対象を元のリポジトリに戻す
- `--exit-remove`: 現在記録している worktree を削除して、以降の作業対象を元のリポジトリに戻す

## パターン A: Worktree を作成する

### Step 1: 事前チェック

1. 現在のディレクトリが git リポジトリであることを確認する
2. `git rev-parse --show-toplevel` で元リポジトリのルートを取得する
3. `git branch --show-current` でベースブランチを取得する
4. `git status --porcelain` で未コミット変更を確認する。未コミット変更がある場合はユーザーに警告し、続行確認を取る

### Step 2: Worktree 名とパスを決める

`worktree 名` が指定されていればそれを使う。指定がなければ、以下のように生成する。

```bash
BASE_BRANCH=$(git branch --show-current)
WORKTREE_NAME="${BASE_BRANCH:-worktree}-$(date +%Y%m%d-%H%M%S)"
```

worktree は元リポジトリの親ディレクトリに置く。

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
REPO_NAME=$(basename "$REPO_ROOT")
WORKTREE_PARENT="$(dirname "$REPO_ROOT")/${REPO_NAME}-worktrees"
WORKTREE_PATH="${WORKTREE_PARENT}/${WORKTREE_NAME}"
BRANCH_NAME="${WORKTREE_NAME}"
```

### Step 3: Worktree を作成する

```bash
mkdir -p "$WORKTREE_PARENT"
git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" HEAD
```

ブランチが既に存在する場合は、ユーザーに確認してから既存ブランチを使う。

```bash
git worktree add "$WORKTREE_PATH" "$BRANCH_NAME"
```

### Step 4: 状況を報告する

以下をユーザーに報告し、このセッションでは `WORKTREE_PATH` を以降の作業対象として扱う。

```text
Worktree を作成しました。

- 作業ディレクトリ: {worktree のパス}
- ブランチ: {作成されたブランチ名}
- ベース: {元のブランチ名}

作業が終わったら:
- worktree --exit         -> worktree を保持して元のリポジトリに戻る
- worktree --exit-remove  -> worktree を削除して元のリポジトリに戻る
```

## パターン B: Worktree から出る（--exit）

1. 現在記録している worktree パスを確認する
2. worktree 内の `git status --porcelain` を確認し、未コミット変更がある場合はユーザーに警告する
3. worktree は削除せず、以降の作業対象を元のリポジトリのルートに戻す
4. 保持された worktree パスとブランチ名を報告する

```text
Worktree を保持したまま元のリポジトリに戻りました。

- 保持された worktree: {パス}
- 保持されたブランチ: {ブランチ名}
```

## パターン C: Worktree を削除して出る（--exit-remove）

1. 現在記録している worktree パスを確認する
2. worktree 内の `git status --porcelain` を確認する
3. 未コミット変更や未 push のコミットがある場合は、削除前にユーザー確認を取る
4. 元リポジトリのルートで `git worktree remove {worktree のパス}` を実行する
5. ディレクトリが残っている場合のみ、ユーザー確認後に `rm -rf {worktree のパス}` を実行する

削除成功時:

```text
Worktree を削除して元のリポジトリに戻りました。
```

## 運用のベストプラクティス

- 既に別の変更がある状態で作業を開始する場合は、まず `worktree` を実行してから作業を開始する
- worktree 名に作業内容を反映させる。例: `worktree fix-login`, `worktree add-api`
- 作業完了後は PR を作成してマージする
- 直接取り込む場合は元リポジトリで `git merge {ブランチ名}` を実行する
