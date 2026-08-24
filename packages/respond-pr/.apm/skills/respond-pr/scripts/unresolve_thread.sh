#!/usr/bin/env bash
# レビュースレッドを unresolved に戻す（GitHub GraphQL）。
#
# Usage:
#   unresolve_thread.sh <thread-node-id>
#
# 成功時: { "isResolved": false } を stdout に出す
set -euo pipefail

THREAD_ID="${1:?thread-node-id is required}"

# shellcheck disable=SC2016  # GraphQL 変数はシェル展開させない
gh api graphql -f threadId="$THREAD_ID" -f query='
mutation($threadId: ID!) {
  unresolveReviewThread(input: {threadId: $threadId}) {
    thread { isResolved }
  }
}' | jq '.data.unresolveReviewThread.thread'
