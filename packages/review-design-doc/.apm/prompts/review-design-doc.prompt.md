---
allowed-tools: Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh issue view:*), Bash(gh issue list:*), Bash(gh pr checkout:*), Read(CLAUDE.md), Read(AGENTS.md), Bash(make:*), Bash(mise:*), Bash(docker:*), Bash(ripgrep:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git show:*), Bash(cat:*), Bash(ls:*), Bash(cd:*)
argument-hint: "<PR Number or URL>"
description: "Review a Pull Request About Design Docs (PR Number Required)"
---

# Review Pull Request About Design Docs

以下の手順でデザインドキュメントのプルリクエストをレビューしてください。
デザインドキュメントとは実装を伴う変更に関する設計方針や仕様を記述したドキュメントです。
適切なデザインドキュメントを作成することで、実装時の認識齟齬を防ぎ、将来的な保守性を向上させることができます。
したがって、デザインドキュメントの時点で適切な設計になっていることを確認することが重要です。

1. プルリクエストの概要を把握する
2. プルリクエストの内容確認
3. プロンプトファイルの内容確認
4. コミット内容のレビュー

## プルリクエストの概要を把握する

以下のコマンドを使用して、プルリクエストの概要を把握します。`ARGUMENT` はプルリクエスト番号または URL を指定します。

```bash
gh pr view $ARGUMENT
```

プルリクエストの説明に Issue や Pull Request のリンクがある場合はそれを確認します。
さらにそれらから派生する関連 Issue や Pull Request があればそれも確認してください。

## プルリクエストの内容確認

以下のコマンドを使用して、対象 PR の内容を確認します。`ARGUMENT` はプルリクエスト番号または URL を指定します。

```bash
gh pr diff $ARGUMENT
```

さらに、デザインドキュメントで言及されている箇所のソースコードについて現在の実装内容を確認し、デザインドキュメントによって将来的に追加される実装の追加・変更が適切であることを検証します。

## プロンプトファイルの内容確認

プロンプトファイル`CLAUDE.md`または`AGENTS.md`の内容を確認します。

## コミット内容のレビュー

以上の確認項目をもとにレビューを実施し、修正が必要であるかどうかの判断をしてください。
修正が必要ならば修正計画・コメント内容を考案します。

## レビュー終了後にやること

レビュー時に新しくチェックアウトしたブランチを削除します。
新しくチェックアウトしていない場合は削除しなくて良いです。
