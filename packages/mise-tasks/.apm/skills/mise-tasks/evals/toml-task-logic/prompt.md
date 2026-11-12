次の初期状態を用意した、分離されたリポジトリで作業してください。

- `mise.toml` には `[tasks.ready]` のみがあり、`run = "echo ready"` と `description = "Print ready"` が設定されています。
- `VERSION` の内容は `1.2.3` です。
- 最新の Git タグは `v1.2.2` です。そのタグ以降の最初の親コミットの履歴には、件名が `Merge pull request #12 from demo/add-login` と `Merge pull request #13 from demo/fix-cache` のマージコミットが、この順で2件あります。
- `mise/` の下にはファイルがなく、`build/` ディレクトリもありません。

バージョンと2件のマージされたプルリクエストの件名を履歴順に `build/release-notes.md` へ書き込む `release-notes` タスクを追加してください。既存の `ready` タスクも動作する状態にしてください。ローカルの Git 履歴だけを使い、GitHub やほかのネットワークサービスには接続しないでください。このリポジトリの mise の規約に従い、タスクの実行方法と確認方法も説明してください。
