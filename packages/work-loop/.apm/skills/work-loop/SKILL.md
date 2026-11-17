---
name: work-loop
description: GitHub の ai-work / ai-decision Issue の依存、Decision revision、再計画ゲートを read-only CLI で確認する必要があるときに使用する。常駐 runner や Issue 変更は行わない。
argument-hint: "<status | explain> [Issue 番号 or URL] --repo <owner/repo>"
allowed-tools: Bash(gh issue list:*), Bash(gh issue view:*), Bash(gh repo view:*)
---

# Work Loop

`ai-work` Issue の依存と Decision の再計画状態を確認する読み取り専用 skill。Issue の本文・ラベルは変更しない。Issue を作成・編集する場合は既存の `create-issue` / `solve-issue` skill を使い、Work と Decision の本文・ラベルには [Issue contract](references/issue-contract.md) を適用する。

## CLI の場所と実行

CLI はこの skill に同梱された `scripts/work_queue.py` である。skill が読み込まれたランタイムから `work-loop/SKILL.md` のインストール先ディレクトリを特定し、そのディレクトリの `scripts/work_queue.py` を実行する。リポジトリのカレントディレクトリを基準に相対パスを推測しない。複数のインストールがある場合は、現在のランタイムが読み込んだ `work-loop` skill と同じ APM インストールのファイルを使う。インストール先を特定できない場合は停止する。

Python 3.12 以上で次のように実行する。`uv` がある場合は PEP 723 の環境を使い、なければ Python で直接実行してよい。スクリプトには外部 Python 依存がない。

Python / `uv` の実行は、実際の同梱スクリプトへのパスを含むコマンドをランタイムの標準コマンド承認フローで実行する。`Bash(python:*)` などの包括的な実行許可は追加しない。承認されない、または実行できない場合は `unknown` として停止する。

```bash
uv run --script "<work-loop skill directory>/scripts/work_queue.py" status --repo OWNER/REPO --json
uv run --script "<work-loop skill directory>/scripts/work_queue.py" explain 123 --repo OWNER/REPO --json
```

`explain` は `ready` の場合だけ終了コード 0 を返す。`blocked` / `needs-replan` は終了コード 1、取得不能・形式不明・依存不完全は JSON の `state: "unknown"` を含め終了コード 2 を返す。終了コードだけでなく JSON の `state` と `reason` を確認する。エラー出力や不正 JSON、CLI 不在も `unknown` と同様に扱い、worker を停止する。

## Coordinator / Worker の使い方

- キュー全体を見るには `status --repo OWNER/REPO --json` を使う。`issues` の各項目に `state` と `reason` がある。worker 候補にできるのは `ready` の Work Issue だけ。
- Issue の着手直前には `explain <Issue 番号 or URL> --repo OWNER/REPO --json` を使う。`ai-work` 以外の Issue や `ai-decision` Issue は worker 実装へ渡さない。
- `blocked` は blocking Decision が open / pending、または決定記録が不完全であることを表す。人間の判断や記録を待ち、Decision Issue を閉じただけで再開しない。
- `needs-replan` は、Work に記録された applied revision / closed-at と閉じた Decision の現 revision / `closedAt` が一致しない、記録がない、または Work に `needs-replan` が付いていることを表す。coordinator は Work の内容・完了条件を再確認し、[契約](references/issue-contract.md)に従って Decision URL / revision / `closedAt` を記録し、再計画完了後にラベルを外す。
- `ready` は依存・再計画ゲートのみの通過を示す。自動 Worker を開始するときは `ai-auto`、`loop-approved`、Project の `Ready`、リスク等の既存条件も別途確認する。
- `unknown`、CLI 不在、JSON parse error、Issue に `ai-work` と `ai-decision` の両方が付いている場合、またはどの判定エラーでも fail closed とする。Issue の情報を推測して worker に渡さない。

## CLI コマンド

```text
work_queue.py status --repo OWNER/REPO [--json]
work_queue.py explain <Issue 番号 or URL> --repo OWNER/REPO [--json]
```

`explain` は正の Issue 番号か canonical HTTPS Issue URL だけを受け付ける。URL を `gh` の引数としては使わず、検証後の番号だけを渡す。`gh repo view --json url` が返すcanonical URLとhost / owner / repoを比較するため、GitHub Enterprise hostも照合される。

`status` と `explain` は GitHub CLI の `gh issue list/view --json` で Issue 情報を取得する。`blockedBy` 接続の `nodes` と `totalCount` が一致すること、各 Decision 詳細が依存 URL と一致することを確認する。不完全な接続、未知の形式、非 Decision の blocker は `unknown` として停止する。
