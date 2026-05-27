---
name: gh-unlink-subissue
description: GitHub Issue から Sub-issue の紐付けを解除する必要があるときに使用する。親 Issue と子 Issue の URL/番号を指定すると `removeSubIssue` mutation で関係のみを解除し、Issue 自体は削除しない。
---

# GitHub Sub-issue 紐付け解除スキル

親 Issue から子 Issue の Sub-issue 紐付けを解除します。

## 前提条件

- `gh` CLI がインストール・認証済みであること
- 対象リポジトリへのアクセス権があること

## 入力

ユーザーから以下の情報を収集してください：

- **親 Issue**: `owner/repo#number` 形式または GitHub URL
- **子 Issue**: `owner/repo#number` 形式または GitHub URL

## 手順

### Step 1: Issue の Node ID を取得

```bash
# 親 Issue
PARENT_ID=$(gh api graphql -f query='
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) { id }
  }
}' -f owner="OWNER" -f repo="REPO" -F number=NUMBER \
  -q '.data.repository.issue.id')

# 子 Issue
CHILD_ID=$(gh api graphql -f query='
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) { id }
  }
}' -f owner="OWNER" -f repo="REPO" -F number=NUMBER \
  -q '.data.repository.issue.id')
```

### Step 2: removeSubIssue mutation で紐付け解除

```bash
gh api graphql -f query='
mutation($parent: ID!, $child: ID!) {
  removeSubIssue(input: {issueId: $parent, subIssueId: $child}) {
    issue { id title }
    subIssue { id title }
  }
}' -f parent="$PARENT_ID" -f child="$CHILD_ID"
```

### Step 3: 結果の確認

解除が成功したら、親 Issue と子 Issue のタイトルを表示して結果を報告してください。

## 注意事項

- 紐付けが存在しない場合はエラーが返る
- 解除しても Issue 自体は削除されない（紐付け関係のみ解除）
