# Work-loop Issue contract

この契約は、`work-loop` CLI と AI worker / coordinator が共有する固定形式である。CLI は GitHub Issue を読み取るだけで、ラベルや本文を変更しない。

## Labels

- `ai-work`: coordinator が実装 worker に割り当てる Work Issue。
- `ai-decision`: 人間の判断を待つ Decision Issue。Decision Issue 自体を実装 worker に割り当てない。
- `needs-replan`: Decision の決定が変わった後、Work 側の再計画記録とラベル整理が終わるまで worker を止める Work Issue。

同じ Issue に `ai-work` と `ai-decision` が付いている場合は契約違反として `unknown` で停止する。

## Decision Issue body

Decision Issue の本文に、各フィールドを一度だけ独立した行として記録する。状態値は `pending` または `decided`、revision は 1 以上の整数とする。`decided` の場合は `decision-outcome` に決定内容を一行で記録する。決定内容に影響する変更のたびに revision を増やす。

```text
decision-status: pending
decision-revision: 1
```

決定後の例:

```text
decision-status: decided
decision-revision: 2
decision-outcome: Keep the current API and defer the migration.
```

`decision-status` / `decision-revision` がない、重複している、値が契約外、または `decided` に決定内容がない Decision は未解決として扱う。Issue が open の間も、本文に `decided` と記録されていても未解決である。

## Work Issue body

Work Issue は、依存する各 Decision が close され、その内容を Work の計画に反映した後、本文に Decision の正規 URL、適用した revision、GitHub の `closedAt` を一行で記録する。`closedAt` を含めることで、Decision を close しただけでは既存の Work 記録と一致せず、gate は再開しない。

```text
decision-applied: https://github.com/OWNER/REPO/issues/123 @ 2 ; closed-at: 2026-10-19T12:00:00Z
```

依存する Decision ごとに一行を置く。Decision の内容が変わった場合は、この記録を新しい revision と最新の `closedAt` に更新し、Work の作業計画と完了条件を再確認する。再計画が完了したら `needs-replan` ラベルを外す。ラベルを外すだけでは再計画の記録にならない。

## Gate states

- `blocked`: Decision が open / `pending`、または Decision の決定記録が不完全。
- `needs-replan`: closed / `decided` Decision の revision または `closedAt` と Work の `decision-applied` が一致しない、記録がない、または Work に `needs-replan` ラベルが付いている。
- `ready`: すべての blocking Decision が closed / `decided` で、Work の適用記録にある revision と `closedAt` が両方一致し、Work に `needs-replan` ラベルがない。
- `unknown`: Issue の形式、GitHub CLI 出力、依存情報の完全性を確認できない。worker は停止する。

`ready` は依存関係と再計画ゲートだけを通過したことを示す。`ai-auto` / `loop-approved` / Project の `Ready` など既存 Worker 条件を置き換えない。Decision Issue を close しただけでは Work は再開しない。

## Dependency completeness

GitHub の `blockedBy` は `{ "nodes": [...], "totalCount": N }` 形式で取得し、`nodes` の件数と `totalCount` が一致することを確認する。不足、未知の形、非 Decision の blocking Issue、詳細取得の不一致があれば `unknown` として停止する。部分的な依存一覧から `ready` を判定してはならない。
