---
name: solve-issue
description: 会話のコンテキストや既存 Issue から、Issue 起票（または特定）→ ブランチ作成 → 実装 → 検証 → PR 作成までを一連のワークフローで実行する必要があるときに使用する。GitHub Projects のフィールド (Status / Start Date) や親子 Issue の自動設定にも対応する。loop engineering の Worker として、ai-auto と loop-approved が付いた低リスク Issue を自動処理する場合にも使用する。
---

# Solve Issue

会話のコンテキストや既存の Issue に基づいて、ブランチ作成 → 実装 → PR 作成を一連で行う。

## デフォルト設定

以下は設定ファイルから読み込まれたデフォルト値である。
引数で上書きされない場合、この値を使用する。

```bash
cat ~/.claude/custom-config/create-issue-config.json 2>/dev/null \
  || cat ~/.codex/custom-config/create-issue-config.json 2>/dev/null \
  || echo '{"repo":"","project":{"owner":"","number":0,"status":"","done_status":"Done","start_date":"today"},"labels":[],"loop":{"auto_label":"ai-auto","approved_label":"loop-approved","ready_status":"Ready","in_progress_status":"In progress","waiting_status":"Waiting"},"assignee":""}'
```

repo の指定がない場合、カレントリポジトリを対象とする。

`custom-config/create-issue-config.json` が存在しない場合は、ユーザーに以下の内容でファイルを作成するよう促す。

```json
{
  "repo": "org/repo",
  "project": {
    "owner": "org-or-user-name",
    "number": 1,
    "status": "",
    "done_status": "Done",
    "start_date": "today"
  },
  "labels": [],
  "loop": {
    "auto_label": "ai-auto",
    "approved_label": "loop-approved",
    "ready_status": "Ready",
    "in_progress_status": "In progress",
    "waiting_status": "Waiting"
  },
  "assignee": ""
}
```

- `repo`: Issue を起票するリポジトリ（形式: `owner/repo`）
- `project.owner`: GitHub Projects のオーナー（Organization 名またはユーザー名）
- `project.number`: GitHub Projects の番号
- `project.status`: Issue 起票時に設定する Status の値
- `project.done_status`: Issue クローズ時に設定する Status の値
- `project.start_date`: `"today"` の場合、起票時に今日の日付を Start Date に設定
- `loop.auto_label`: 自動実装 Worker の対象にしてよい Issue を表すラベル
- `loop.approved_label`: 人間が loop 実行を承認済みであることを表すラベル
- `loop.ready_status`: Worker が取得してよい Project Status
- `loop.in_progress_status`: Worker が処理開始時に設定する Status
- `loop.waiting_status`: PR 作成後に設定する Status

## 引数のパースルール

```text
solve-issue [Issue 番号 or URL] [--repo <owner/repo>] [--loop] [--no-pr]
```

- 引数なし → **パターン A**（会話コンテキストから新規 Issue を作成）
- 引数が数字または GitHub Issue URL → **パターン B**（既存 Issue を解決）
- `--repo`: 対象リポジトリを指定（省略時はデフォルト設定 → カレントリポジトリの順で決定）
- `--loop`: 自動 Worker として実行。対象 Issue が安全条件を満たす場合だけユーザー確認を省略する
- `--no-pr`: PR は作成せず、実装・検証・commit までで停止する

### 例

```text
solve-issue
→ 会話のコンテキストから Issue を新規作成し、実装、PR 作成まで行う

solve-issue 42
→ Issue #42 の内容を取得し、ブランチ作成 → 実装 → PR 作成

solve-issue 42 --repo other-org/other-repo
→ other-org/other-repo の Issue #42 を解決

solve-issue 42 --loop
→ ai-auto + loop-approved の付いた低リスク Issue だけを自動処理
```

---

## Loop Worker モード

`--loop` が指定された場合、または `/loop` / cron / GitHub Actions / `delegate-worktrees` から Worker として呼ばれた場合は、以下を守る。

### 取得してよい Issue

既存 Issue を処理する場合だけ自動実行する。引数なしの新規 Issue 作成は loop Worker では行わない。

自動実行してよい条件:

- `ai-auto` と `loop-approved` の両方のラベルが付いている
- Project Status が `Ready` または設定ファイルの `loop.ready_status`
- 工数が XS/S 相当、または本文・ラベルから低リスクと判断できる
- 完了条件と検証方法が本文に書かれている
- secret、権限、課金、データ削除、migration、本番 deploy、public API 破壊を含まない

条件を満たさない場合は実装せず、理由を報告して終了する。ラベルや Project Status を勝手に昇格しない。

### 自動実行時の確認省略

上記条件を満たす場合のみ、以下のユーザー確認を省略してよい。

- Step 2 の既存 Issue 内容確認
- Step 4 の実装方針確認
- PR 作成の確認

ただし、作業中にスコープ拡大・設計判断・破壊的変更・追加権限・未定義の外部サービス連携が必要になったら停止し、Issue に状況をコメントするかユーザーへ報告する。

### 状態更新

Project 設定がある場合は、処理開始時に Status を `In progress`、PR 作成後に `Waiting` へ更新する。該当 option が無い場合は更新をスキップし、報告に残す。

可能なら `.ai/loop-state.md` に「Issue、branch、commit、PR、検証結果、停止理由」を追記する。既存の state ファイルがあればそれを優先する。

### 検証ゲート

PR 作成前に、リポジトリの標準 test / lint / format を実行する。実行できない場合は PR 本文の Test Plan に未実行理由を明記する。`codex-review` skill が利用可能なら、commit 前または PR 作成前に diff レビューを 1 回実行し、妥当な指摘を反映する。

---

## Step 1: 計画立案

1. 会話のコンテキストからタイトル・概要・完了条件を整理する
2. 情報が不足している場合はユーザーに質問する。`--loop` の場合は質問せず停止理由として報告する

### 計画に含めるべき項目

- 完了条件とそれを満たすために必要な具体的なタスク
- 課題を達成したことをどのように確認するか（例: 追加するテストケースの内容や、動作確認の手順）
- ユニットテストや統合テスト・E2Eテストの追加が必要な場合は、その内容を計画に含める

## Step 2: Issue の準備

Step 1 で整理した内容をもとに、Issue を作成するか既存 Issue を指定するかユーザーに確認する。
新規 Issue を作成する場合は、タイトル・概要・完了条件をユーザーに提示して確認を取る。

`--loop` の場合は新規 Issue を作成しない。既存 Issue 番号または URL が無い場合は停止する。

### Issue を書くときのガイドライン

Issue 内に他の Issue やプルリクエストへのリンクを記載する場合は、以下の形式で記述する。
以下のようにリスト形式で URL を記載することで、GitHub が自動的にリンクを変換して表示する。
同じ行内に他の文字を混ぜるとリンクが正しく認識されない可能性があるため、URL は行を分けて記載する。

```markdown
- <完全なURL>
```

`#123` のようにリポジトリ内の Issue やプルリクエスト番号だけを記載する方法もあるが、
複数のリポジトリを横断している場合に間違ったリポジトリの Issue を参照してしまう可能性があるため、完全な URL を記載する。

### パターン A: 新規 Issue 作成

以下のコマンドで Issue を起票する。

```bash
gh issue create \
  --repo {repo} \
  --title "{タイトル}" \
  --label "{label1}" --label "{label2}" \
  --assignee {assignee} \
  --body "$(cat <<'EOF'
## 概要

{概要}

## 完了条件

{完了条件}

## プルリク

（なし）

## 依頼元

（なし）
EOF
)"
```

1. 起票後、`project` 設定が存在する場合は GitHub Projects のフィールドを設定する
   - `project.owner` と `project.number` で対象の GitHub Project を特定する
   - **Status**: `project.status` の値に設定
   - **Start Date**: `project.start_date` が `today` の場合は `date +%Y-%m-%d` で今日の日付を取得して設定

   GitHub Projects のフィールド設定には以下の手順で行う。

   a. Issue 側から `projectItems` でプロジェクトアイテムを取得する。Issue がまだプロジェクトに追加されていない場合は `gh project item-add` で追加する。

   ```bash
   # Issue がプロジェクトに追加されていない場合
   gh project item-add {project.number} --owner {project.owner} --url {IssueのURL}
   ```

   b. Issue の `projectItems` から対象プロジェクトのアイテム ID とフィールド情報を取得する。

   ```bash
   gh api graphql -f query='
   {
     repository(owner: "{owner}", name: "{repo}") {
       issue(number: {番号}) {
         projectItems(first: 10) {
           nodes {
             id
             project { id number title }
             fieldValues(first: 20) {
               nodes {
                 ... on ProjectV2ItemFieldSingleSelectValue {
                   name
                   field { ... on ProjectV2SingleSelectField { id name options { id name } } }
                 }
                 ... on ProjectV2ItemFieldDateValue {
                   date
                   field { ... on ProjectV2Field { id name } }
                 }
               }
             }
           }
         }
       }
     }
   }'
   ```

   c. **フィールド ID のフォールバック**: 新規 Issue では Start Date 等の Date フィールドは未設定のため `fieldValues` に含まれない。その場合はプロジェクト自体の `fields` を別途クエリして field ID を取得する。

   ```bash
   gh api graphql -f query='
   {
     node(id: "{project-id}") {
       ... on ProjectV2 {
         fields(first: 30) {
           nodes {
             ... on ProjectV2Field {
               id
               name
               dataType
             }
             ... on ProjectV2SingleSelectField {
               id
               name
               options { id name }
             }
           }
         }
       }
     }
   }'
   ```

   d. 取得したフィールド ID を使って Status と Start Date を更新する。

   ```bash
   # Status の更新
   gh project item-edit --project-id {project-id} --id {item-id} --field-id {status-field-id} --single-select-option-id {option-id}

   # Start Date の更新（未設定の場合のみ）
   gh project item-edit --project-id {project-id} --id {item-id} --field-id {start-date-field-id} --date "$(date +%Y-%m-%d)"
   ```

   **注意**: Start Date は b. で取得した `fieldValues` 内の `ProjectV2ItemFieldDateValue` を確認し、`date` が既に設定されている場合は更新をスキップする。Start Date の上書きは行わない。

2. 会話のコンテキストから親 Issue が特定できる場合は、ユーザーに確認の上、親子関係を設定する

   ```bash
   # 親 Issue の node ID を取得
   gh issue view {親Issue番号} --repo {repo} --json id --jq '.id'

   # 子 Issue（今起票した Issue）を親に紐づけ
   gh api graphql -f query='
   mutation {
     addSubIssue(input: {
       issueId: "{親IssueのnodeID}"
       subIssueUrl: "{起票したIssueのURL}"
     }) {
       issue { number title }
       subIssue { number title }
     }
   }'
   ```

### パターン B: 既存 Issue の取得

1. `gh issue view {番号} --repo {repo}` で Issue の内容を取得する
2. Issue のタイトル・本文・ラベル・担当者を確認する
3. Issue の内容をユーザーに提示し、解決方針を確認する。`--loop` で Loop Worker モードの条件を満たす場合は確認を省略する
4. `project` 設定が存在する場合は GitHub Projects のフィールドを設定する（パターン A の手順 1 と同様）
   - **Start Date の決定方法**: `project.start_date` が `"today"` の場合でも、既存 Issue では Issue の作成日（`createdAt`）を使用する。`gh issue view {番号} --repo {repo} --json createdAt --jq '.createdAt[:10]'` で取得する

---

## Step 3: ブランチ作成

1. デフォルトブランチを自動検出する

   ```bash
   gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'
   ```

2. デフォルトブランチの最新状態を取得する

   ```bash
   git switch {デフォルトブランチ}
   git pull
   ```

3. Issue 番号とタイトルからブランチ名を生成する（すでにブランチが存在する場合はそのブランチを使用する）
   - 形式: `feature/{issue-number}-{slug}`
   - slug: Issue タイトルを英数字小文字+ハイフンに変換（日本語はローマ字化せず省略し、英単語のみ抽出。適切な英語の slug がない場合はユーザーに確認する）
   - `--loop` で適切な slug が無い場合は `feature/{issue-number}-loop-worker` を使い、確認待ちで停止しない
   - 例: `feature/42-add-login-feature`

4. ブランチを作成する

   ```bash
   git switch -c feature/{issue-number}-{slug}
   ```

---

## Step 4: 実装

1. Issue の概要と完了条件に基づいて、実装方針をユーザーに提示する
2. ユーザーの承認を得てから実装に着手する。`--loop` で Loop Worker モードの条件を満たす場合は承認済みとして扱う
3. the agent の実装能力をフル活用してコードを実装する

### 実装後の確認ポイント

- 完了条件をすべて満たしているか
- 追加したコードに対して適切なテストが書かれているか
- コードの品質やスタイルがプロジェクトの基準を満たしているか
- `--loop` の場合、完了条件を満たせないまま PR を作らない。途中 commit が必要なら `--no-pr` 相当で停止し、理由を報告する

特に mise.toml などのタスクランナーにはコードフォーマット・リンティング・ユニットテストのタスクが含まれていることが多いので、これらを活用してコード品質を担保する。

#### MarkDown を生成・編集した場合

mise.toml に Markdown 用のフォーマットタスクが定義されている場合は、生成・編集した Markdown ファイルをそのタスクで整形する。
存在しない場合は、一般的な Markdown フォーマッタ（例: Prettier）を使用して整形する。その際に .markdownlint.json などの設定ファイルが存在する場合は、それに従って整形する。

#### Shell Script を生成・編集した場合

mise.toml に Shell Script 用のフォーマットタスクが定義されている場合は、生成・編集した Shell Script ファイルをそのタスクで整形する。
存在しない場合は、一般的な Shell Script フォーマッタ（例: shfmt）を使用して整形する。

#### YAML を生成・編集した場合

mise.toml に YAML 用のフォーマットタスクが定義されている場合は、生成・編集した YAML ファイルをそのタスクで整形する。
存在しない場合は、yamllint を使用して整形する。その際に .yamllint.yml などの設定ファイルが存在する場合は、それに従って整形する。

---

## Step 5: Commit & Push & PR 作成

実装完了後、変更内容をコミットする。

```bash
git add <適切なファイルパス>
git commit -m "{コミットメッセージ}"
```

- コミットメッセージはコミット規約に従う（リポジトリに規約がある場合はそれに従う）
- 変更が大きい場合は適宜複数コミットに分割する
- 実装と関係ないファイルの変更が含まれている場合は、それがコミットに含まれないように注意する
- `codex-review` を実行した場合は、PR 本文にレビュー結果の要約と対応有無を書く

`--no-pr` の場合はここで停止し、branch、commit、検証結果、PR 未作成理由を報告する。

ブランチをリモートにプッシュする。

```bash
git push -u origin feature/{issue-number}-{slug}
```

PR を作成する。

```bash
gh pr create \
  --repo {repo} \
  --base {デフォルトブランチ} \
  --title "{PR タイトル}" \
  --body "$(cat <<'EOF'
## Summary

{Issue の内容と実際の変更内容に基づく要約}

## Related Issues

- <issue-url-1>
- <issue-url-2>
- ...

## Changes

{変更内容の箇条書き}

## Test Plan

{テスト手順}
EOF
)"
```

- PR タイトルは Issue タイトルを元に作成する
- `Closes <issue-url>` 形式で Issue を自動クローズ可能にする（クロスリポジトリでも機能する）
- Issue と PR が同じリポジトリの場合でも `<issue-url>` 形式を使用する（一貫性のため）

---

## Step 6: 報告

実行結果をユーザーに報告する。

```text
✅ Issue → 実装 → PR の一連のワークフローが完了しました。

- Issue: {Issue URL}
- Branch: feature/{issue-number}-{slug}
- PR: {PR URL}
```
