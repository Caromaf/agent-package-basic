---
name: delegate-worktrees
description: main agent を master/coordinator として動かし、実作業を複数の subagent/worker に git worktree 単位で委任して個別 PR を作らせる必要があるときに使用する。ユーザーが「subagent を使って」「$worktree と subagent で」「master agent として取りまとめて」「複数 worker に分けて PR を作って」などを求めた場合に発火する。loop engineering で Ready Issue キューから複数 worker を起動し、PR 単位で進捗管理する場合にも使用する。
---

# Delegate Worktrees

main agent は実装を抱え込まず、作業分解・優先順位付け・worker 管理・PR 判断に集中する。実作業は worker subagent が専用 worktree で行い、個別に commit/push/PR を作成して報告する。

この skill は委任の段取り (分解・並列化・PR 統合) を扱い、worktree の隔離そのものの実装は同梱の `worktree` skill に委ねる関係にある。重複ではなく `delegate-worktrees` が `worktree` を内包して使う。

## Loop Coordinator モード

GitHub Project / Issue キューから継続的に worker を起動する場合は、coordinator が以下を先に決める。

- 取得対象は `ai-auto` と `loop-approved` の両方があり、Status が `Ready` の Issue に限定する。
- 同時 worker は最大 3 件を初期値にする。過去に安定している repo でも 5 件を超えない。
- 1 回の loop run で扱う上限、コスト上限、停止条件を決める。
- shared config、lockfile、migration、public API、認証認可、課金、データ削除を含む Issue は自動 worker から除外する。
- 状態は GitHub Project / Issue / PR / CI / 最終報告に集約する。作業ログ・ロードマップ・タスクリストのような状態記録ファイルを repository 内に作成しない。

worker に渡す実行 skill は原則 `solve-issue <issue> --loop` とし、PR 作成前 checker として `codex-review` を使う。レビューコメント対応は worker に抱え込ませず、PR 作成後に `respond-pr` へ渡す。

## Coordinator の責務

1. 目的、完了条件、制約、対象 repo を整理し、独立可能な作業単位に分解する。
2. critical path と依存関係を判断し、並列化できる作業だけ worker に委任する。
3. 各 worker に branch/worktree/path/ownership/期待成果/検証/PR 作成方針を明確に渡す。
4. 進捗、PR URL、検証結果、残件を一覧で管理する。
5. PR 後は必要に応じて `codex-review` / `review-pr` / `respond-pr` などの review skill を実行し、merge 可否と順序を判断する。
6. durable docs が必要な場合だけ、coordinator が「開発者・一般ユーザーに必要な導入/利用情報」または「ソースコードや git log から得られない ADR/意思決定」に該当するか判断する。

Coordinator は原則として実装ファイルを編集しない。設計上の追加問題を見つけた場合も、勝手に実装範囲を広げず、後続 Issue/PR の候補として報告する。

## Worker の責務

1. 専用 worktree で作業する。Claude Code では `isolation: worktree` で起動済みなのでそれを使い、手動運用のランタイムでは main worktree が clean であることを確認して新規 git worktree と branch を作成する (「Worktree ルール」参照)。
2. main worktree には書き込まず、専用 worktree 内だけで実装・テスト・修正を行う。
3. 他者や別 worker の変更を revert しない。競合や dirty 状態が作業に影響する場合は coordinator に報告する。
4. ownership 範囲に収まる変更だけを行い、必要な commit を作成して push する。
5. PR を作成し、変更ファイル、検証コマンド、PR URL、残件を coordinator に報告する。

## Worktree ルール

worktree の作り方は実行ランタイムによって 2 系統に分ける。同梱の `worktree` skill と同じ方針で、native 機能を優先しつつ非対応ランタイムにフォールバックする。

- **Claude Code ランタイム (優先)**: worker を `isolation: worktree` で起動し、worktree の生成と後片付けをランタイムに委ねる。手動 `git worktree add` は書かない。native worktree は parent session の `HEAD` ではなく **default branch から分岐**し、変更が無ければ自動でクリーンアップされる点に注意する。直前の未マージ作業の上に積みたい場合はこの分岐起点が合わないので、その作業は直列化して扱う。
- **native isolation 非対応ランタイム (Codex 等)**: worker prompt 内で手動 `git worktree` を使う。worktree は元 repo の親ディレクトリ配下に置く。例: `<repo>-worktrees/<branch-name>`。worker 中断時に orphan worktree が残りうるので、coordinator が掃除責務を持つ。

共通ルール:

- 作業前に `git status --porcelain` と現在 branch を確認する。
- branch 名は作業内容が分かる hyphen-case にする。
- worker 間で write scope を分離する。共有ファイルや衝突しやすいファイルは同時編集しない。
- dirty な main worktree から作業を始める必要がある場合は、coordinator に状態を報告してから判断する。

## 並列化ルール

- 独立しており、write scope が分離でき、片方の結果を待たずに検証できる作業だけを複数 worker に委任する。
- 同時稼働 worker は 3〜5 を上限の目安にする。これを超えると、結果の統合と複数 worktree 管理のオーバーヘッドが並列化の利益を上回りやすい。多い場合は phase で区切って順に流す。
- 依存マッピングをしてから phase に分ける。依存タスクは直列化し、独立タスクだけ並列化する。例: Phase 1 (並列) で schema 設計と project 雛形を別 worker に出し、Phase 2 (Phase 1 依存) で auth route と todo route を別 worker に出し、Phase 3 で test と docs を出す。
- shared config、lockfile、migration、共通 API contract など衝突しやすい変更は coordinator が PR 順序、rebase、統合方針を管理する。
- CI 待ちがボトルネックになる場合は、小さな commit と bundled PR を許容する。ただし責務と検証結果が追える単位に保つ。

## Subagent Prompt Template

```text
あなたは worker subagent です。main agent は coordinator として全体管理します。

Repo: {repo_path}
Base branch: {main_branch}
Worktree: 専用 worktree 内だけで作業し、main worktree には書き込まない (Claude Code では isolation: worktree で起動済み。手動運用時は新規 git worktree を作成する)
Branch: {branch_name}
Ownership: {変更してよい範囲。触らない範囲も明記}
Task: {実装内容と完了条件}
Verification: {実行すべきテスト/lint/手動確認}
PR: commit/push して PR を作成する。PR 本文には変更内容、検証、残件を書く
Report: PR URL、変更ファイル、検証結果、残件を日本語で報告する

注意:
- 他者の変更を revert しない
- 追加で見つけた設計課題は勝手に実装せず、後続 Issue/PR 候補として報告する
- 競合、dirty 状態、ownership 外の変更が必要な場合は作業を広げず coordinator に報告する
- loop 実行では `solve-issue {issue} --loop` の安全条件を満たさない場合、実装せず停止理由を報告する
```

## PR 後

統合は coordinator の責務とする。worker に自分たちの成果を統合させない。worker に統合を求めると、重複実装と衝突が発生する。merge/rebase の順序判断は coordinator が単独で握る。

1. coordinator は PR 一覧、依存関係、CI 状態、レビュー状況を更新する。
2. merge 前に必要な review skill (`review-pr` など) を実行する。
3. 競合しやすい PR は順序を決め、必要なら worker に rebase/修正を依頼する。
4. merge 後に durable docs の更新が必要なら、coordinator が全体の整合性を見て別 PR または後続 worker に委任する。作業ログ・ロードマップ・タスクリスト目的の Markdown は作成しない。

## 参照

委任パターンや並列化の前提を更新するときは [references/orchestration-references.md](references/orchestration-references.md) を読む。公式ドキュメント (sub-agents / worktrees / agent-teams) の URL と、`isolation: worktree` の挙動など確定事実をまとめてある。
