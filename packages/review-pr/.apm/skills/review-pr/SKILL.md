---
name: review-pr
description: プルリクエストを、PR本文・diff・関連Issue・テスト・動作確認・コミット履歴からレビューする必要があるときに使用する。public API、設定、DI、factory、adapter、protocol、migration、security、error contract など設計リスクを含む変更では architecture-review と連携して深掘りする。loop engineering の checker として、solve-issue / delegate-worktrees が作った PR を独立レビューする場合にも使用する。
---

# Review Pull Request

プルリクエストを end-to-end にレビューする。通常レビューを先に行い、設計リスクの兆候がある場合だけ `architecture-review` を併用して深掘りする。

## Output Policy

- デフォルトのレビュー出力先はチャットである。GitHub へ投稿しない。
- ユーザーが明示的に「PR に投稿して」「コメントして」と依頼した場合だけ、投稿用本文を作る。
- 投稿前にユーザー確認が必要な文脈では、まず **PR comment draft** として本文を提示する。
- 投稿する場合は `gh pr comment` を使い、review comment や review thread の既存内容は読まない。

## Evidence Policy

レビューでは次を分ける。

- **Direct fact**: PR 本文、diff、関連 issue 本文、既存コード、docs、tests、一次情報から直接言えること。
- **Inference**: direct fact から導けるバグリスク、設計リスク、保守性への影響。
- **Open question**: 現状の diff だけでは判断できない前提。

既存の PR review、review comment、approval、changes requested、discussion thread は取得・閲覧・要約しない。レビューは PR 本文、diff、関連 issue 本文、既存コード、docs、tests、外部一次情報から独立に構成する。

## Loop Checker Policy

loop で生成された PR をレビューする場合も、通常の code review と同じく findings-first で判定する。

- `ai-auto` / `loop-approved` 由来の PR では、Issue の完了条件、PR 本文、実際の diff が一致しているかを最初に確認する。
- blocking finding がある場合は merge 可にしない。`respond-pr` または修正 worker に渡すため、具体的な修正要求を書く。
- non-blocking finding は follow-up Issue 候補として分ける。PR の目的を超える改善要求を混ぜない。
- PR が自動生成であることを理由に検証を甘くしない。むしろ comprehension debt を抑えるため、変更理由と検証根拠が PR 本文から追えるかを見る。
- レビュー結果の末尾に `Loop verdict: mergeable / needs-fix / human-review-required` を付ける。

## Standard Workflow

1. PR の概要を把握する。
2. diff と変更ファイルを確認する。
3. AGENTS.md / CLAUDE.md などのプロンプトファイルを確認する。
4. architecture review gate を判定する。
5. 必要なテスト・lint・動作確認を実行する。
6. コミット履歴を確認する。
7. findings-first でレビューを書く。

## PR Overview

`ARGUMENT` は PR 番号または URL を指定する。

```bash
gh pr view "$ARGUMENT" --json title,body,url,author,baseRefName,headRefName,changedFiles,additions,deletions,files,commits
```

確認すること:

- PR の目的、スコープ、非スコープ。
- 関連 Issue や design doc のリンク。
- 変更規模と変更ファイルの分布。
- base/head branch と checkout 対象。

関連 Issue は本文を確認する。Issue comments は、ユーザーが明示的に必要とした場合を除いて読まない。

```bash
gh issue view "$ISSUE" --json title,body,url,labels,state
```

## Diff Review

```bash
gh pr diff "$ARGUMENT"
```

見る観点:

- バグ、回帰、境界条件、例外処理。
- 入力 validation、認可、秘密情報、ログ、外部入力。
- 変更に対応する tests/docs/changelog。
- diff に含まれるコメントの質。
- public API や observable behavior の変更。

## Prompt Files

リポジトリの指示ファイルを確認する。

- `AGENTS.md`
- `CLAUDE.md`
- package/subdirectory 固有の指示ファイル

## Architecture Review Gate

以下のいずれかに該当する場合は architecture review を実行する。

- public API、exported type/function、CLI、HTTP API、イベント、wire format、DB schema を変える。
- config、environment variable、DI container、module registration、provider registry、factory、adapter、plugin/extension point を変える。
- routing、dispatch、lifecycle、transaction、cache、queue、job、scheduler、cleanup の owner を変える。
- auth、permission、secret、unsafe option、external input、logging、error contract を変える。
- deprecation、compatibility layer、migration path、fallback behavior を変える。
- 複数層にまたがる責務移動、抽象追加、境界の再配置がある。
- ライブラリ、SDK、framework、shared package など他プロジェクトから利用されるコードを変える。

実行方法:

- `architecture-review` skill が利用できる場合は、その skill を使い、同じ PR evidence packet を渡す。
- 利用できない場合は、この gate の観点で軽量 fallback を行う。
- architecture finding は通常レビュー finding と重複させず、同じ根本原因は1つに統合する。

軽量 fallback では次だけ確認する。

- 変更後の owner map: 生成、変換、validation、実行、cleanup をどの型・層が持つか。
- public contract: 利用者が覚える API/config/docs/tests は増えた価値に見合うか。
- dependency direction: 上位 policy が下位 detail、内部 shape、secret value を知りすぎていないか。
- compatibility: 既存利用者が予測可能に移行できるか。

## Tests And Verification

PR のブランチを checkout して確認する。

```bash
gh pr checkout "$ARGUMENT"
git status --short
```

作業ツリーにユーザーの未コミット変更がある場合は上書きしない。必要なら確認してから進める。

テストや lint は、直接 `composer.json` や `package.json` を叩くよりも、既存のタスクランナーや docs を優先する。

優先順:

1. PR 本文や docs に記載された検証手順。
2. `mise.toml`、`Makefile`、`justfile`、`Taskfile.yml` などのタスク。
3. Docker / Docker Compose / DevContainer の既存手順。
4. 変更範囲に最も近い unit/integration test。

テストを実行できない場合は、理由を明示する。未実行の検証を成功扱いしない。

## Commit Review

base branch との差分コミットを確認する。

```bash
git log --oneline --decorate "$BASE..HEAD"
git show --stat --oneline --decorate HEAD
```

見る観点:

- コミットがレビュー可能な粒度か。
- 途中コミットに不要なファイル、生成物、秘密情報が混ざっていないか。
- PR の説明とコミット内容が一致しているか。

## Comment Audit

diff に追加・変更されたコメントだけを対象にする。既存コメントは、今回の変更で不整合が生じた場合だけ扱う。

記載すべきコメント:

- 非自明なロジックの補足。
- 複雑なアルゴリズムの意図。
- 設計上の方針、背景、避けた選択肢。
- 外部サービス、ライブラリ、protocol、runtime 仕様への依存。
- TODO / FIXME として残す理由と解消条件。

削除・修正すべきコメント:

- コードを読めば分かる実行内容の説明。
- 更新されにくく、コードと不一致になりやすい説明。
- 命名改善で解決できる変数・関数説明。
- 誤字脱字、曖昧な表現、根拠のない断定。

## Final Review Format

レビューは findings-first で書く。重要度順に並べ、ファイル・行が分かる場合は必ず示す。

```markdown
## Findings

- **[Critical|High|Medium|Low]** `path/to/file.ext:123` <短い結論>
  - Direct fact: <diff/docs/testsから直接言える事実>
  - Impact: <利用者・運用・保守・セキュリティへの影響>
  - Request: <具体的に変えてほしいこと>

## Verification

- 成功/失敗/未実行: <command or manual check>

## Residual Risk / Open Questions

- <未確認事項。findingではないもの>

## Loop Verdict

- mergeable / needs-fix / human-review-required
```

architecture-review を実行した場合は、設計 finding も `Findings` に統合する。別ログとして貼らない。

問題がない場合は、以下を明確に書く。

```markdown
指摘すべき blocking / non-blocking finding は見つかりませんでした。

Verification:

- <実行した検証>

Residual risk:

- <未実行または残る確認事項。なければ「特になし」>

Loop verdict:

- mergeable
```

## Cleanup

レビュー時に新しく checkout したブランチがあり、ユーザー作業を含まない場合だけ削除してよい。既存ブランチや未コミット変更は削除・巻き戻ししない。
