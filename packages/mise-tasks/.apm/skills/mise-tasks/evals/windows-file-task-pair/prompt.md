次の初期状態を用意した、OS を問わず動作する分離されたリポジトリで作業してください。

- `mise.toml` には `[tasks.ready]` のみがあり、`run = "echo ready"` と `description = "Print ready"` が設定されています。
- `mise/` の下にはファイルがありません。
- このリポジトリは Windows、Linux、macOS に対応しています。

`machine-name` タスクを追加してください。Windows では PowerShell を使い、`HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion` から `ProductName` の値を表示します。Linux と macOS では、利用できないことが分かるメッセージを表示して、0以外の終了コードを返します。どちらのプラットフォームでも `mise run machine-name` で実行できるようにしてください。既存の `ready` タスクも動作する状態にしてください。

評価ホスト上でタスクを実行したり、実際のレジストリを読んだりしないでください。ソースとプラットフォームごとのファイル配置だけを確認し、確認した内容を説明してください。
