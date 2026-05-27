---
allowed-tools: Bash(gh issue create:*), Bash(gh issue view:*), Bash(gh issue list:*), Bash(gh issue edit:*), Bash(gh label list:*), Bash(gh project:*), Bash(gh api:*), Bash(gh pr create:*), Bash(gh repo view:*), Bash(git checkout:*), Bash(git switch:*), Bash(git push:*), Bash(git add:*), Bash(git commit:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(date:*), Bash(cat:*)
argument-hint: "[Issue 番号 or URL] [--repo <owner/repo>]"
description: "Issue を作成（または既存 Issue を指定）し、実装して PR を作成する"
---

# Solve Issue

会話のコンテキストや既存の Issue に基づいて、ブランチ作成 → 実装 → PR 作成を一連で行います。

## デフォルト設定

以下は設定ファイルから読み込まれたデフォルト値です。
引数で上書きされない場合、この値を使用してください。

```json
!`cat ~/.claude/custom-config/create-issue-config.json 2>/dev/null || echo '{"repo":"","project":{"owner":"","number":0,"status":"","done_status":"Done","start_date":"today"},"labels":[],"assignee":""}'`
```

repo の指定がない場合、カレントリポジトリを対象とします。

`custom-config/create-issue-config.json` が存在しない場合は、ユーザーに以下の内容でファイルを作成するよう促してください。

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
  "assignee": ""
}
```

- `repo`: Issue を起票するリポジトリ（形式: `owner/repo`）
- `project.owner`: GitHub Projects のオーナー（Organization 名またはユーザー名）
- `project.number`: GitHub Projects の番号
- `project.status`: Issue 起票時に設定する Status の値
- `project.done_status`: Issue クローズ時に設定する Status の値
- `project.start_date`: `"today"` の場合、起票時に今日の日付を Start Date に設定

## 引数のパースルール

```text
/solve-issue [Issue 番号 or URL] [--repo <owner/repo>]
```

- 引数なし → **パターン A**（会話コンテキストから新規 Issue を作成）
- 引数が数字または GitHub Issue URL → **パターン B**（既存 Issue を解決）
- `--repo`: 対象リポジトリを指定（省略時はデフォルト設定 → カレントリポジトリの順で決定）

### 例

```text
/solve-issue
→ 会話のコンテキストから Issue を新規作成し、実装、PR 作成まで行う

/solve-issue 42
→ Issue #42 の内容を取得し、ブランチ作成 → 実装 → PR 作成

/solve-issue 42 --repo other-org/other-repo
→ other-org/other-repo の Issue #42 を解決
```

---

## Step 1: 計画立案

1. 会話のコンテキストからタイトル・概要・完了条件を整理する
2. 情報が不足している場合はユーザーに質問する

### 計画に含めるべき項目

- 完了条件とそれを満たすために必要な具体的なタスク
- 課題を達成したことをどのように確認するか（例: 追加するテストケースの内容や、動作確認の手順）
- ユニットテストや統合テスト・E2Eテストの追加が必要な場合は、その内容を計画に含める

## Step 2: Issue の準備

Step 1 で整理した内容をもとに、Issue を作成するか既存 Issue を指定するかユーザーに確認する
新規 Issue を作成する場合は、タイトル・概要・完了条件をユーザーに提示して確認を取る

### Issue を書くときのガイドライン

Issue 内に他の Issue やプルリクエストへのリンクを記載する場合は、以下の形式で記述してください。
以下のようにリスト形式で URL を記載することで、GitHub が自動的にリンクを変換して表示します。
同じ行内に他の文字を混ぜるとリンクが正しく認識されない可能性があるため、URL は行を分けて記載してください。

```markdown
- <完全なURL>
```

`#123` のようにリポジトリ内の Issue やプルリクエスト番号だけを記載する方法もありますが、
複数のリポジトリを横断している場合に間違ったリポジトリの Issue を参照してしまう可能性があるため、完全な URL を記載してください。

### パターン A: 新規 Issue 作成

以下のコマンドで Issue を起票する

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
3. Issue の内容をユーザーに提示し、解決方針を確認する
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
   - 例: `feature/42-add-login-feature`

4. ブランチを作成する

   ```bash
   git switch -c feature/{issue-number}-{slug}
   ```

---

## Step 4: 実装

1. Issue の概要と完了条件に基づいて、実装方針をユーザーに提示する
2. ユーザーの承認を得てから実装に着手する
3. 通常の実装能力をフル活用してコードを実装する

### 実装後の確認ポイント

- 完了条件をすべて満たしているか
- 追加したコードに対して適切なテストが書かれているか
- コードの品質やスタイルがプロジェクトの基準を満たしているか

特に mise.toml などのタスクランナーにはコードフォーマット・リンティング・ユニットテストのタスクが含まれていることが多いので、これらを活用してコード品質を担保してください。

#### MarkDown を生成・編集した場合

mise.toml に Markdown 用のフォーマットタスクが定義されている場合は、生成・編集した Markdown ファイルをそのタスクで整形してください。
存在しない場合は、一般的な Markdown フォーマッタ（例: Prettier）を使用して整形してください。その際に .markdownlint.json などの設定ファイルが存在する場合は、それに従って整形してください。

#### Shell Script を生成・編集した場合

mise.toml に Shell Script 用のフォーマットタスクが定義されている場合は、生成・編集した Shell Script ファイルをそのタスクで整形してください。
存在しない場合は、一般的な Shell Script フォーマッタ（例: shfmt）を使用して整形してください。

#### YAML を生成・編集した場合

mise.toml に YAML 用のフォーマットタスクが定義されている場合は、生成・編集した YAML ファイルをそのタスクで整形してください。
存在しない場合は、yamllint を使用して整形してください。その際に .yamllint.yml などの設定ファイルが存在する場合は、それに従って整形してください。

---

## Step 5: Commit & Push & PR 作成

実装完了後、変更内容をコミットする

```bash
git add <適切なファイルパス>
git commit -m "{コミットメッセージ}"
```

- コミットメッセージはコミット規約に従う（リポジトリに規約がある場合はそれに従う）
- 変更が大きい場合は適宜複数コミットに分割する
- 実装と関係ないファイルの変更が含まれている場合は、それがコミットに含まれないように注意する

ブランチをリモートにプッシュする

```bash
git push -u origin feature/{issue-number}-{slug}
```

PR を作成する

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
