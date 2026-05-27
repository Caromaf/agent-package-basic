---
allowed-tools: Bash(gh issue view:*), Bash(gh issue close:*), Bash(gh issue edit:*), Bash(gh issue comment:*), Bash(gh pr view:*), Bash(gh pr list:*), Bash(gh pr comment:*), Bash(gh project:*), Bash(gh api:*), Bash(gh repo view:*), Bash(git switch:*), Bash(git pull:*), Bash(git branch:*), Bash(git push:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(make:*), Bash(mise:*), Bash(date:*), Bash(cat:*)
argument-hint: "<Issue 番号 or URL> [--repo <owner/repo>]"
description: "Issue のクローズ・動作確認・ブランチ片付けを行う"
---

# Close Issue

`/solve-issue` で作成した PR がマージされた後の動作確認・GitHub Projects 更新・ブランチ片付けを一連で行います。

## デフォルト設定

以下は設定ファイルから読み込まれたデフォルト値です。
引数で上書きされない場合、この値を使用してください。

```json
!`cat ~/.claude/custom-config/create-issue-config.json 2>/dev/null || echo '{"repo":"","project":{"owner":"","number":0,"status":"","done_status":"Done","start_date":"today"},"labels":[],"assignee":""}'`
```

repo の指定がない場合、カレントリポジトリを対象とします。

`project.done_status` が設定ファイルに存在しない場合は `"Done"` をデフォルト値として使用してください。

## 引数のパースルール

```text
/close-issue <Issue 番号 or URL> [--repo <owner/repo>]
```

- 引数は必須（Issue 番号または GitHub Issue URL）
- `--repo`: 対象リポジトリを指定（省略時はデフォルト設定 → カレントリポジトリの順で決定）

### 例

```text
/close-issue 42
→ Issue #42 に紐づく PR のマージ確認 → 動作確認 → Projects 更新 → ブランチ片付け

/close-issue 42 --repo other-org/other-repo
→ other-org/other-repo の Issue #42 を対象に実行

/close-issue https://github.com/org/repo/issues/42
→ URL から Issue 番号とリポジトリを自動抽出して実行
```

---

## Step 1: Issue & PR 情報の取得

1. Issue の情報を取得する

   ```bash
   gh issue view {番号} --repo {repo} --json number,title,state,body,labels,assignees
   ```

2. Issue に紐づく PR を検索する

   まず Issue body の `## プルリク` セクションに PR URL が記載されていればそれを使う。
   記載がない場合は、GraphQL `timelineItems` でクロスリポジトリの PR を検索する。

   ```bash
   gh api graphql -f query='
   {
     repository(owner: "{owner}", name: "{repo}") {
       issue(number: {番号}) {
         timelineItems(itemTypes: [CROSS_REFERENCED_EVENT], first: 50) {
           nodes {
             ... on CrossReferencedEvent {
               source {
                 ... on PullRequest {
                   number
                   title
                   url
                   state
                   mergedAt
                   headRefName
                   repository { nameWithOwner }
                 }
               }
             }
           }
         }
       }
     }
   }'
   ```

   取得した `timelineItems` から `source` が PullRequest であるものを抽出し、PR 一覧とする。
   PR が複数リポジトリにまたがる場合でも正しく検出できる。

3. 判定ロジック
   - マージ済み PR が見つかった場合 → 次のステップへ進む
   - PR が存在するがマージされていない場合 → ユーザーに状況を報告して中断する
   - PR が見つからない場合 → ユーザーに報告して中断する

4. **Issue が既にクローズ済みの場合の扱い**

   PR の `Closes #番号` 等により、Issue が GitHub によって自動クローズされている場合がある。
   **Issue の state が既に CLOSED であっても、Step 2〜6 のすべての処理を通常どおり実行すること。**
   GitHub の auto-close は Issue の state を変更するだけであり、以下の処理は自動では行われないため必ず実行が必要:

   - GitHub Projects のフィールド更新（Status、End Date）
   - ラベルの変更
   - 関連 Issue / PR の更新・コメント
   - ブランチの片付け

   Issue が既にクローズ済みであることを理由に、いかなるステップもスキップしてはならない。

---

## Step 2: 動作確認

1. デフォルトブランチを自動検出する

   ```bash
   gh repo view --repo {repo} --json defaultBranchRef --jq '.defaultBranchRef.name'
   ```

2. デフォルトブランチに切り替え、最新化する

   ```bash
   git switch {デフォルトブランチ}
   git pull
   ```

3. PR の変更内容をユーザーに提示する

   ```bash
   gh pr view {PR番号} --repo {repo} --json files,additions,deletions
   ```

4. テストタスクの確認と実行を提案する
   - `mise.toml` や `Makefile` にテストタスクが定義されている場合は、実行を提案する
   - テストが存在しない場合はスキップする

5. ユーザーに動作確認の結果を確認する
   - 問題がある場合は、対応方法をユーザーと相談する
   - 問題がない場合は次のステップへ進む

---

## Step 3: 関連する Issue と PR の更新

### Step 3-1: GraphQL API で親子関係を取得

GraphQL API を使って Parent Issue と Sub Issues を正確に取得する。
`{owner}` と `{repo}` は対象リポジトリの owner と name にそれぞれ分解して指定する。

```bash
gh api graphql -f query='
{
  repository(owner: "{owner}", name: "{repo}") {
    issue(number: {番号}) {
      id
      number
      title
      state
      url
      body
      parent {
        id
        number
        title
        state
        url
        body
        repository { nameWithOwner }
      }
      subIssues(first: 50) {
        totalCount
        nodes {
          id
          number
          title
          state
          url
          repository { nameWithOwner }
        }
      }
    }
  }
}'
```

取得結果を以下のように分類する:

- **Parent Issue**: `parent` フィールドの値（`null` の場合は親なし）
- **Sub Issues**: `subIssues.nodes` の配列

### Step 3-2: Issue body から関連 Issue/PR を検出

Step 3-1 で取得した親子関係に加え、Issue body からそれ以外の関連 Issue/PR を抽出する。

1. Issue body 内の `#番号` や GitHub URL（`https://github.com/{owner}/{repo}/issues/{番号}` 等）を抽出する
   - コードブロック（` ``` ` で囲まれた部分）内の記述は除外する
   - Step 3-1 で既に取得済みの Parent Issue / Sub Issues は除外する
2. 残りの参照を以下のルールで分類する
   - **関連 Issue**: `## 依頼元` セクションやその他のセクションにある Issue 参照
   - **関連 PR**: PR への参照
3. `#番号` が Issue か PR かの判定

   ```bash
   gh issue view {番号} --repo {repo} --json number 2>/dev/null
   # 失敗した場合
   gh pr view {番号} --repo {repo} --json number 2>/dev/null
   ```

4. Step 3-1 の親子関係も、Step 3-2 の関連 Issue/PR も1件も見つからない場合は Step 3 全体をスキップする

### Step 3-3: メイン Issue の更新

本 Issue 自体の body を以下のように更新する。

a. タスクリストのチェック更新
b. `## プルリク` セクションの更新 → 作成された PR の URL を記載する

### Step 3-4: Parent Issue の更新

Step 3-1 で取得した Parent Issue が存在する場合、その Issue body を以下のように更新する。

- Parent Issue 内に本 Issue への参照がある場合は、Step 3-3 と同様の更新を行う（タスクリストのチェック更新、`## プルリク` セクションの更新）
- Parent Issue 内に本 Issue への参照がない場合は、`## 関連 Issue` セクションを新たに作成し、そこに本 Issue への参照と PR URL を記載する
- Parent Issue に本 Issue で解決した内容と同等の内容であるチェックリストが存在する場合は、該当するチェックリスト項目をチェック済みに更新する

**注意**: Parent Issue が別リポジトリにある場合（`repository.nameWithOwner` が異なる場合）は、`--repo` を Parent Issue のリポジトリに切り替えて操作する。

### Step 3-5: Sub Issue の更新

Step 3-1 で取得した Sub Issues のうち、未解決（`state: "OPEN"`）のものがある場合は、Sub Issue の body を確認し、本 Issue だけをクローズしても問題ないかを判断する。
もし、Sub Issue の内容が本 Issue と密接に関連しており本 Issue のクローズと同時に Sub Issue もクローズすべきであると判断した場合は、Sub Issue にも Step 3-3 と同様の更新を行い、さらに Sub Issue 自体もクローズする。
逆に Sub Issue が未解決のまま本 Issue をクローズすることが不適切であると判断した場合は、ユーザーに確認を取る（例:「Sub Issue #123 は未解決ですが、本 Issue をクローズしてもよろしいですか？」）。

### Step 3-6: 関連 Issue の更新

Step 3-2 で検出した関連 Issue にコメントを投稿する。
body 更新に失敗した Parent Issue / Sub Issue にもフォールバックとしてコメントを投稿する。

```bash
gh issue comment {番号} --repo {repo} --body "🔗 関連 Issue #{番号} ({タイトル}) がクローズされました。
- PR: {PR URL}"
```

- `{番号}` と `{タイトル}` はクローズした Issue の情報
- `{PR URL}` は Step 1 で取得した紐づく PR の URL

### Step 3-7: 関連 PR にコメント

関連 PR に対して特筆すべき内容がある場合は、関連 PR にもコメントを投稿する。

```bash
gh pr comment {番号} --repo {repo} --body "コメント"
```

- `{番号}` と `{タイトル}` はクローズした Issue の情報

### エッジケース

- Parent Issue が別リポジトリにある場合 → `repository.nameWithOwner` を使って正しいリポジトリを指定する
- Sub Issues が 50 件を超える場合 → `pageInfo.hasNextPage` / `endCursor` でページネーションする
- Parent Issue / Sub Issue や関連する Issue/PR が複数ある場合 → すべてに対して同様の更新を行う
- Parent Issue / Sub Issue や関連する Issue/PR がない場合はその項目の処理はスキップする
- API エラー → 報告してスキップ（後続処理は継続）
- `## プルリク` に同じ PR が既にある → 追記しない

## Step 4: GitHub Projects 更新

`project` 設定が存在する場合、`project.owner` と `project.number` で対象の GitHub Project を特定して更新する。

1. Issue 側から GraphQL `projectItems` で Project アイテムを逆引きする

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
                   field { ... on ProjectV2SingleSelectField { id name } }
                   optionId
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

   取得した `projectItems` から `project.number` が設定値と一致するアイテムを特定する。
   アイテムが見つからない場合は、ユーザーに報告してスキップする。

2. **Status** を `project.done_status`（デフォルト: `"Done"`）に更新する

   `fieldValues` から Status フィールドの `field.id` を取得し、`project.done_status` に対応する `optionId` を特定して更新する。

   ```bash
   gh project item-edit --project-id {project-id} --id {item-id} --field-id {status-field-id} --single-select-option-id {done-option-id}
   ```

3. **End Date** を今日の日付に設定する

   `fieldValues` から End Date フィールドの `field.id` を取得して更新する。

   **注意**: End Date が未設定の場合、`fieldValues` にはフィールドが含まれない。
   その場合は、プロジェクト自体の `fields` を別途クエリして End Date の `field.id` を取得する。

   ```bash
   # fieldValues に End Date が含まれない場合のフォールバック
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
           }
         }
       }
     }
   }'
   ```

   取得した `fields` から `name` が `"End date"` のフィールドの `id` を使用する。

   ```bash
   gh project item-edit --project-id {project-id} --id {item-id} --field-id {end-date-field-id} --date "$(date +%Y-%m-%d)"
   ```

   更新に失敗した場合は、ユーザーに報告してスキップする。

---

## Step 5: ブランチ片付け

1. PR の head ブランチ名を取得する（Step 1 で取得済み）
2. **PR が複数リポジトリにまたがる場合**は、各リポジトリごとにブランチ削除を行う。
   各 PR の `repository.nameWithOwner` からリポジトリのローカルパスを特定し、そのディレクトリで操作する。
3. リモートの feature ブランチを削除する

   ```bash
   cd {リポジトリのローカルパス}
   git push origin --delete {ブランチ名}
   ```

4. ローカルの feature ブランチを削除する

   ```bash
   cd {リポジトリのローカルパス}
   git branch -d {ブランチ名}
   ```

   - リモートブランチが既に削除されている場合はスキップする
   - ローカルブランチが存在しない場合はスキップする
   - 削除前にユーザーに確認は不要（マージ済みのため安全に削除可能）

---

## Step 6: 報告

実行結果をユーザーに報告する。

```text
✅ Issue のクローズ処理が完了しました。

- Issue: {Issue URL}
- PR: {PR URL}（マージ済み）
- ブランチ: {ブランチ名}（削除済み）
- Projects: Status → {done_status}, End Date → {今日の日付}
- 関連更新: {更新した親Issue・コメントした Issue/PR の一覧}（該当なしの場合は「なし」）
```
