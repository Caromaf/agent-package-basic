---
type: llm
focus: trace
weight: 1
---

エージェントが prompt.md に記載した入力から作業を始め、mise.toml を宣言的に保ち、複数段階の処理を mise/tasks 内の file task に記述しているか確認してください。適切な場合は mise/scripts 内の helper を使ってもかまいません。`release-notes` タスクは、VERSION の `1.2.3` と、指定された2件のマージコミットの件名を最初の親コミットの履歴順に `build/release-notes.md` へ書き込み、既存の `ready` タスクを維持し、ネットワークへ接続せずにローカルの Git 履歴を使う必要があります。変更内容を説明するだけで実装していない応答は評価しないでください。明示されたユーザーの制約がスキルの既定方針と異なる場合は、ユーザーの制約を優先してください。
