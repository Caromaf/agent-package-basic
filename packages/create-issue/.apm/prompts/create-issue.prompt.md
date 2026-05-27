---
allowed-tools: Bash(gh issue create:*), Bash(gh issue view:*), Bash(gh issue list:*), Bash(gh label list:*), Bash(gh project:*), Bash(gh api:*), Bash(date:*), Bash(cat:*)
argument-hint: "<Issue タイトル> [--repo <owner/repo>] [--label <label>] [--assignee <user>] [--status <status>]"
description: "Issue を起票する"
---

# Issue 起票スキル

## デフォルト設定

以下は設定ファイルから読み込まれたデフォルト値です。
引数で上書きされない場合、この値を使用してください。

```json
!`cat ~/.claude/custom-config/create-issue-config.json 2>/dev/null || echo '{"repo":"org/repo","project":{"owner":"","number":0,"status":"","done_status":"Done","start_date":"today"},"labels":[],"assignee":""}'`
```

もし `custom-config/create-issue-config.json` が存在しない場合は、ユーザーに以下の内容でファイルを作成するよう促してください。

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

`$ARGUMENTS` には以下の形式で値が渡されます。

```text
<Issue タイトル> [--repo <owner/repo>] [--label <label>] [--assignee <user>] [--status <status>]
```

- `--` で始まるフラグとその直後の値はオプションとして取り出す
- フラグに該当しない部分が Issue タイトルになる
- 指定されなかったオプションはデフォルト設定の値を使用する
- `--label` は複数回指定可能。1つでも指定された場合、デフォルトの labels は上書きされる

### 例

```text
/create-issue S3連携の配線を接続する
→ タイトル: "S3連携の配線を接続する", その他はデフォルト値

/create-issue バグ修正 --repo other/repo --label bug --label urgent
→ タイトル: "バグ修正", repo: "other/repo", labels: ["bug", "urgent"]

/create-issue 新機能追加 --assignee another-user --status Todo
→ タイトル: "新機能追加", assignee: "another-user", status: "Todo"
```

## Issue テンプレート

以下のテンプレートに従って Issue 本文を作成してください。

```markdown
## 概要

{ユーザーの指示内容や会話コンテキストに基づいて概要を記述}

## 完了条件

{ユーザーの指示内容に基づいて完了条件を記述}

## プルリク

（なし）

## 依頼元

（なし）
```

### Issue を書くときのガイドライン

Issue 内に他の Issue やプルリクエストへのリンクを記載する場合は、以下の形式で記述してください。
以下のようにリスト形式で URL を記載することで、GitHub が自動的にリンクを変換して表示します。
同じ行内に他の文字を混ぜるとリンクが正しく認識されない可能性があるため、URL は行を分けて記載してください。

```markdown
- <完全なURL>
```

`#123` のようにリポジトリ内の Issue やプルリクエスト番号だけを記載する方法もありますが、
複数のリポジトリを横断している場合に間違ったリポジトリの Issue を参照してしまう可能性があるため、完全な URL を記載してください。

## 起票手順

1. `$ARGUMENTS` をパースし、タイトルとオプションを取り出す
2. デフォルト設定とマージする（引数で指定された値が優先）
3. ユーザーに概要と完了条件の内容を確認する。情報が不足している場合は質問する
4. 以下のコマンドで Issue を起票する

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

3. 起票した Issue の URL をユーザーに報告する
