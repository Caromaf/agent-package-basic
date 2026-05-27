---
allowed-tools: Bash(git worktree:*), Bash(git switch:*), Bash(git checkout:*), Bash(git merge:*), Bash(git branch:*), Bash(git log:*), Bash(git status:*), Bash(git diff:*), Bash(git push:*), Bash(git pull:*), Bash(git add:*), Bash(git commit:*), Bash(git stash:*), Bash(rm -rf:*), EnterWorktree, ExitWorktree
argument-hint: "[worktree 名] [--exit] [--exit-remove]"
description: "git worktree で隔離された作業環境を作成する"
---

# Worktree — git worktree を使って作業ディレクトリを分離する

git worktree を使って作業ディレクトリを分離し、未コミットの変更の競合を防止します。

## 引数のパースルール

```text
/worktree [worktree 名] [--exit] [--exit-remove]
```

- 引数なし → 新しい git worktree を作成する
- `worktree 名` → 指定した名前で git worktree を作成する（例: `/worktree fix-auth-bug`）
- `--exit` → 現在の git worktree を保持したまま元のディレクトリに戻る
- `--exit-remove` → 現在の git worktree を削除して元のディレクトリに戻る

## パターン A: Worktree に入る（デフォルト）

### Step 1: 事前チェック

1. 現在のディレクトリが git リポジトリであることを確認する
2. 未コミットの変更がある場合はユーザーに警告し、続行するか確認する

### Step 2: Worktree の作成

`EnterWorktree` ツールを使用して git worktree を作成する。

- 引数に名前が指定されている場合はその名前を使用する
- 指定されていない場合は `EnterWorktree` が自動生成する

### Step 3: 状況の報告

以下の情報をユーザーに報告する。

```text
🌳 Worktree を作成しました。

- 作業ディレクトリ: {worktree のパス}
- ブランチ: {作成されたブランチ名}
- ベース: {元のブランチ名}

作業が終わったら:
- /worktree --exit         → git worktree を保持して戻る
- /worktree --exit-remove  → git worktree を削除して戻る
```

### Step 4: 以降の作業

worktree 内で通常どおりファイルの編集・コミットを行う。
ユーザーの指示に従って実装を進める。

## パターン B: Worktree から出る（--exit）

1. 未コミットの変更がある場合はユーザーに警告する
2. `ExitWorktree` を `action: "keep"` で呼び出す
3. 元のディレクトリに戻ったことを報告する

```text
🌳 Worktree を保持したまま元のディレクトリに戻りました。

- 保持された worktree: {パス}
- 保持されたブランチ: {ブランチ名}

worktree 内の変更をメインブランチに取り込むには:
  git merge {ブランチ名}
```

## パターン C: Worktree を削除して出る（--exit-remove）

1. 未コミットの変更やマージされていないコミットがある場合は警告し、確認する
2. `ExitWorktree` を呼び出す前に、worktree のパスを変数として記録しておく
3. `ExitWorktree` を `action: "remove"` で呼び出す
   - 変更がある場合は `discard_changes: true` を設定する前にユーザーの確認を取る
4. **ディレクトリ残存チェックと削除**: `ExitWorktree` は git worktree の登録解除を行うが、サンドボックスの制限によりディレクトリが物理的に残る場合がある。以下の手順で対処する:
   a. `ls {worktree のパス}` でディレクトリが残っているか確認する
   b. 残っている場合は `rm -rf {worktree のパス}` で削除を試みる
   c. `rm -rf` が権限エラーで失敗した場合は、ユーザーに手動削除コマンドを案内する
5. 結果を報告する

削除成功時:

```text
🌳 Worktree を削除して元のディレクトリに戻りました。
```

ディレクトリの手動削除が必要な場合:

```text
🌳 Worktree の git 登録を解除して元のディレクトリに戻りました。

⚠️ ディレクトリが残っています。以下のコマンドで手動削除してください:
  rm -rf {worktree のパス}
```

## 運用のベストプラクティス

ユーザーに求められた場合は以下のガイダンスを提供する。

- 既に別の変更がある状態で作業を開始する場合は、まず `/worktree` を実行してから作業を開始する
- worktree 名に作業内容を反映させる（例: `/worktree fix-login`, `/worktree add-api`）
- 作業完了後は PR を作成してマージするのが最も安全
- 直接マージする場合は `git merge` でブランチを統合する
