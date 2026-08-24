#!/usr/bin/env bash
# shellcheck disable=SC2016
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
#       "body": "...",
#       "lastCommentAuthor": "coderabbitai",
#       "lastCommentBody": "...",
#       "lastCommentCreatedAt": "2026-08-24T00:00:00Z"
#     },
#     ...
#   ]
set -euo pipefail
# GraphQL query はシェル展開させない。

PR="${1:?pr-number is required}"
REPO="${2:-}"
if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
fi
OWNER="${REPO%%/*}"
NAME="${REPO##*/}"

# GraphQL の cursor pagination で全 review thread を取得し、各 thread の comments も
# 最後まで走査する。ページ上限を検知して停止していた旧実装と異なり、見落としなく
# last comment を返す。
THREAD_CURSOR=""
THREADS='[]'
while :; do
  CURSOR_VALUE="${THREAD_CURSOR:-null}"
  RESPONSE="$(gh api graphql -F owner="$OWNER" -F name="$NAME" -F pr="$PR" -F cursor="$CURSOR_VALUE" -f query='
query($owner:String!, $name:String!, $pr:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$pr) {
      reviewThreads(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first:100) {
            pageInfo { hasNextPage endCursor }
            nodes {
              databaseId
              url
              author { login }
              body
              createdAt
            }
          }
        }
      }
    }
  }
}')"
  THREAD_PAGE="$(jq -c '.data.repository.pullRequest.reviewThreads' <<<"$RESPONSE")"
  THREADS="$(jq -c --argjson old "$THREADS" --argjson new "$(jq -c '.nodes' <<<"$THREAD_PAGE")" '$old + $new')"
  if [[ "$(jq -r '.pageInfo.hasNextPage' <<<"$THREAD_PAGE")" != true ]]; then
    break
  fi
  THREAD_CURSOR="$(jq -r '.pageInfo.endCursor' <<<"$THREAD_PAGE")"
done

RESULTS='[]'
while IFS= read -r THREAD; do
  COMMENTS="$(jq -c '.comments.nodes' <<<"$THREAD")"
  COMMENT_CURSOR="$(jq -r '.comments.pageInfo.endCursor // empty' <<<"$THREAD")"
  while [[ "$(jq -r '.comments.pageInfo.hasNextPage' <<<"$THREAD")" == true ]]; do
    CURSOR_VALUE="${COMMENT_CURSOR:-null}"
    COMMENT_PAGE="$(gh api graphql -F threadId="$(jq -r '.id' <<<"$THREAD")" -F cursor="$CURSOR_VALUE" -f query='
query($threadId:ID!, $cursor:String) {
  node(id:$threadId) {
    ... on PullRequestReviewThread {
      comments(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          databaseId
          url
          author { login }
          body
          createdAt
        }
      }
    }
  }
}')"
    COMMENT_CONNECTION="$(jq -c '.data.node.comments' <<<"$COMMENT_PAGE")"
    COMMENTS="$(jq -c --argjson old "$COMMENTS" --argjson new "$(jq -c '.nodes' <<<"$COMMENT_CONNECTION")" '$old + $new')"
    THREAD="$(jq -c --argjson comments "$COMMENTS" --argjson pageInfo "$(jq -c '.pageInfo' <<<"$COMMENT_CONNECTION")" '.comments.nodes = $comments | .comments.pageInfo = $pageInfo' <<<"$THREAD")"
    COMMENT_CURSOR="$(jq -r '.pageInfo.endCursor // empty' <<<"$COMMENT_CONNECTION")"
  done
  if [[ "$(jq -r '.isResolved' <<<"$THREAD")" == false ]]; then
    RESULT="$(jq -c --argjson comments "$COMMENTS" '
      .comments.nodes = $comments
      | ($comments[0]) as $first
      | ($comments[-1]) as $last
      | {
          threadId: .id,
          path: .path,
          line: .line,
          isOutdated: .isOutdated,
          firstCommentId: $first.databaseId,
          firstCommentUrl: $first.url,
          author: $first.author.login,
          body: $first.body,
          lastCommentAuthor: $last.author.login,
          lastCommentBody: $last.body,
          lastCommentCreatedAt: $last.createdAt
        }
    ' <<<"$THREAD")"
    RESULTS="$(jq -c --argjson old "$RESULTS" --argjson new "[$RESULT]" '$old + $new')"
  fi
done < <(jq -c '.[]' <<<"$THREADS")

printf '%s\n' "$RESULTS"
