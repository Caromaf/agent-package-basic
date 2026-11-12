次の初期状態を用意した、クリーンなリポジトリで作業してください。

- `mise.toml` には `[tasks.ready]` のみがあり、`run = "echo ready"` と `description = "Print ready"` が設定されています。
- `mise/` の下にはファイルがありません。
- `data/users.csv` の内容は、別々の行にある `id,email`、`1,hana@example.test`、`2,ken@example.test` の3行だけです。
- `data/one-user.csv` の内容は、別々の行にある `id,email`、`3,mei@example.test` の2行だけです。

任意の `--csv <csv>` フラグを受け取る `mise/tasks/preview-users.sh` を作成してください。指定された CSV を読み取り、データ行数を N として `Would import N users from PATH` と表示します。フラグを指定しない場合は `data/users.csv` を使い、`--csv data/one-user.csv` を指定した場合はユーザーが1人だと表示してください。このタスクは読み取り専用のプレビューです。データベースやサービスに接続せず、ファイルも変更しないでください。オプションは `#USAGE` で宣言し、リポジトリの厳格な Bash 設定を使ってください。また、`mise run preview-users --help` でフラグの説明が表示されるようにしてください。既存の `ready` タスクも動作する状態にしてください。
