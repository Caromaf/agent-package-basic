#!/usr/bin/env bash
# レビュースレッドを resolve する（GitHub GraphQL）。
#
# Usage:
#   resolve_thread.sh <thread-node-id>
#
# thread-node-id は `list_unresolved_threads.sh` の出力の .threadId フィールド
# （例: "PRRT_kwDOSBt7bM58mNgA"）。
#
# 成功時: { "isResolved": true } を stdout に出す
set -euo pipefail

THREAD_ID="${1:?thread-node-id is required}"

# shellcheck disable=SC2016  # GraphQL 変数はシェル展開させない
gh api graphql -f threadId="$THREAD_ID" -f query='
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { isResolved }
  }
}' | jq '.data.resolveReviewThread.thread'
