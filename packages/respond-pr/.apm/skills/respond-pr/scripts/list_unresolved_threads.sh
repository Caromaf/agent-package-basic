#!/usr/bin/env bash
# 未 resolve のレビュースレッドを JSON で出力する。
#
# Usage:
#   list_unresolved_threads.sh <pr-number> [owner/repo]
#
# owner/repo を省略した場合は `gh repo view` でカレントリポジトリを使う。
# 出力: 各スレッドが 1 オブジェクトの JSON 配列
#   [
#     {
#       "threadId": "...",
#       "path": "...",
#       "line": 123,
#       "isOutdated": true,
#       "firstCommentId": "...",
#       "firstCommentUrl": "...",
#       "author": "coderabbitai",
#       "body": "..."
#     },
#     ...
#   ]
set -euo pipefail

PR="${1:?pr-number is required}"
REPO="${2:-}"
if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
fi
OWNER="${REPO%%/*}"
NAME="${REPO##*/}"

# shellcheck disable=SC2016  # GraphQL 変数はシェル展開させない
gh api graphql -F owner="$OWNER" -F name="$NAME" -F pr="$PR" -f query='
query($owner:String!, $name:String!, $pr:Int!) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$pr) {
      reviewThreads(first:100) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first:1) {
            nodes {
              databaseId
              url
              author { login }
              body
            }
          }
        }
      }
    }
  }
}' | jq '[
  .data.repository.pullRequest.reviewThreads.nodes[]
  | select(.isResolved == false)
  | {
      threadId: .id,
      path: .path,
      line: .line,
      isOutdated: .isOutdated,
      firstCommentId: .comments.nodes[0].databaseId,
      firstCommentUrl: .comments.nodes[0].url,
      author: .comments.nodes[0].author.login,
      body: .comments.nodes[0].body
    }
]'
