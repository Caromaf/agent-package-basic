#!/usr/bin/env bash
# レビュースレッドに返信コメントを投稿する。
#
# Usage:
#   reply_to_thread.sh <pr-number> <first-comment-database-id> <body> [owner/repo]
#
# first-comment-database-id は `list_unresolved_threads.sh` の出力の
# .firstCommentId フィールド（数値 ID）。
# body は markdown 文字列。長文の場合は変数経由で渡すこと。
set -euo pipefail

PR="${1:?pr-number is required}"
COMMENT_ID="${2:?comment-database-id is required}"
BODY="${3:?body is required}"
REPO="${4:-}"
if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
fi

gh api --method POST \
  "repos/${REPO}/pulls/${PR}/comments/${COMMENT_ID}/replies" \
  -f body="$BODY" \
  --jq '{id, url, body}'
