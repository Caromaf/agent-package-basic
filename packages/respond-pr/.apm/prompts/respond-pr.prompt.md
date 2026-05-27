---
allowed-tools: Bash(gh pr view:*), Bash(gh pr checks:*), Bash(gh pr diff:*), Bash(gh api:*), Bash(git status:*), Bash(git log:*), Bash(git diff:*), Bash(git fetch:*), Bash(git pull:*), Bash(git push:*), Bash(git switch:*), Bash(git checkout:*), Bash(git add:*), Bash(git commit:*), Bash(git rev-parse:*), Bash(git merge-base:*), Bash(make:*), Bash(mise:*), Bash(date:*), Bash(cat:*), Bash(ls:*), Bash(cd:*), Bash(bash ~/.claude/skills/respond-pr/scripts/*.sh), Bash(~/.claude/skills/respond-pr/scripts/*.sh), Bash(bash ~/.agents/skills/respond-pr/scripts/*.sh), Bash(~/.agents/skills/respond-pr/scripts/*.sh)
argument-hint: "[<PR Number or URL>] — 省略時はカレントブランチの PR"
description: "PR のレビューコメントに対して、妥当性判断・修正・返信・resolveReviewThread まで完走させる"
---

# Respond to PR Reviews

Pull Request のレビュースレッドを順番に捌き、**返信コメント投稿 + `resolveReviewThread` GraphQL mutation** まで完走させるコマンド。

このコマンドは `respond-pr` skill のエントリーポイント。**必ずスキルの `SKILL.md` を最初に読み、その手順に従う**。ここで手順を重複記載しない（スキル本体の更新が常に真実）。

## 引数

- 第 1 引数（省略可）: PR 番号 or URL。例: `42` / `https://github.com/org/repo/pull/42`
- 省略時: `gh pr view --json number --jq '.number'` でカレントブランチの PR を取得

## 必ず守る原則（`SKILL.md` のエッセンス）

1. **`reviewThreads` GraphQL で未 resolve を取得**する（`gh pr view --comments` では `isResolved` が取れない）
2. **bot の指摘を鵜呑みにしない**。`npm view` などで現行版を独立検証してから判断する
3. **完走条件**: 各スレッドに対して
   - 妥当性判断（Major は原則ユーザー確認、Minor は自律判断）
   - 修正 or 明示的な「修正不要」の理由付き返信
   - **返信コメント（`reply_to_thread.sh`）** ← 忘れやすい
   - **`resolveReviewThread`（`resolve_thread.sh`）** ← 忘れやすい
4. push 後に新レビューが入ったら再取得してループ
5. レビューに無い別問題（CI failure 等）を見つけた場合、PR スコープに直接関係するものだけバンドルし、関係ないものはユーザーに報告のみ

## スクリプト

スキルに 3 つのラッパーあり（claude では `~/.claude/skills/respond-pr/scripts/`、codex では `~/.agents/skills/respond-pr/scripts/` に deploy される）：

- `list_unresolved_threads.sh <pr> [repo]`
- `reply_to_thread.sh <pr> <comment-db-id> <body> [repo]`
- `resolve_thread.sh <thread-node-id>`

## 実行手順

1. `ARGUMENT` から PR 番号を決定（省略時はカレントブランチから）
2. `SKILL.md` を `Read` で読み込む
3. スキルのワークフロー（対象 PR 特定 → 未 resolve 列挙 → 各スレッド処理 → 再取得ループ）に従う
4. 完了後、「処理したスレッド / 追加コミット / 未 resolve 残 / CI 状況」を報告

**注意**: このコマンドは skill へのエントリであり、実際の判断は skill の本体に委ねる。skill を改善したら自動的にコマンドの挙動も追従する。
