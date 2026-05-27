---
name: codex-review
description: the agent が書いたコードを Codex CLI (`codex review` / `codex exec`) にレビューさせ、指摘を反映するサイクルを回す必要があるときに使用する。diff レビュー・コミットレビュー・ブランチレビュー・特定ファイルの深いレビューに対応。
---

# Codex Review - the agent が書いたコードを Codex にレビューさせる

the agent がコードを編集した後、Codex CLI (`codex review` / `codex exec`) を使ってレビューを実行し、指摘があれば修正するサイクルを回す skill。

## 前提条件

- Codex CLI がインストール済み (`@openai/codex`, volta 経由)
- OpenAI API キーが設定済み
- 対象ディレクトリが Git リポジトリであること

## レビューモード

ユーザーの指示やコンテキストに応じて、最適なモードを選択する。

### Mode A: diff レビュー（デフォルト）

the agent がコードを編集した後、未コミットの変更差分をレビューする。

```bash
cd <対象リポジトリのパス>
codex review --uncommitted
```

- **用途**: 編集直後のレビュー
- **注意**: `--uncommitted` とカスタムプロンプトは同時に使えない
- **タイムアウト**: 120秒を推奨

### Mode B: コミットレビュー

コミット後に、そのコミットの変更をレビューする。

```bash
cd <対象リポジトリのパス>
codex review --commit HEAD
```

- **用途**: コミット単位でのレビュー

### Mode C: ブランチレビュー

ベースブランチとの差分全体をレビューする。

```bash
cd <対象リポジトリのパス>
codex review --base main
```

- **用途**: PR 作成前の最終レビュー

### Mode D: カスタムレビュー（特定ファイル・特定観点）

`codex exec` で自由なプロンプトを使い、特定ファイルや特定の観点でレビューする。

```bash
cd <対象リポジトリのパス>
codex exec --full-auto --ephemeral "<レビュー指示>"
```

- **用途**: セキュリティ、パフォーマンス、特定ファイルなど焦点を絞ったレビュー
- `--full-auto`: サンドボックス内で自動実行（read-only）
- `--ephemeral`: セッションファイルを残さない

#### カスタムレビューのプロンプト例

```plain
# セキュリティレビュー
codex exec --full-auto --ephemeral \
  "app/routers/messages.py を読んで、セキュリティの観点からレビューしてください。重要度付きで指摘をリスト形式で出力してください。"

# テストカバレッジレビュー
codex exec --full-auto --ephemeral \
  "tests/ と src/ を比較し、テストが不足している箇所を指摘してください。"
```

## 標準ワークフロー（MUST FOLLOW）

この skill がトリガーされたら、以下のサイクルを実行する。

### Step 1: the agent がコードを編集

ユーザーの要求に基づいてコードを編集・実装する。

### Step 2: Codex にレビューを依頼

編集完了後、適切なモードで `codex review` または `codex exec` を実行する。
Bash ツールの `timeout` は `120000`（120秒）に設定する。

```bash
# 例: diff レビュー
cd /path/to/repo
codex review --uncommitted
```

### Step 3: レビュー結果を分析・報告

Codex の出力を読み、以下の形式でユーザーに報告する:

```markdown
## Codex レビュー結果

### 指摘事項

- **[重要度]** 内容 (ファイル:行番号)
  - Codex の対応方針: ...

### 対応予定

- [ ] 指摘1: 修正する / しない（理由）
- [ ] 指摘2: 修正する / しない（理由）
```

### Step 4: 指摘を反映

正当な指摘に対してコードを修正する。
ただし、以下の場合は修正しない（理由をユーザーに説明する）:

- プロジェクトの方針と矛盾する指摘
- 過剰な変更を要求する指摘（YAGNI 違反）
- 既存のテストやリンターで担保されている内容

### Step 5: 再レビュー（必要な場合のみ）

重大な指摘（P0/P1 相当）を修正した場合は、再度 Step 2 に戻る。
軽微な指摘のみの場合は、サイクルを終了する。

## Bash ツール呼び出し時の注意

```plain
- timeout: 120000 を必ず指定する（Codex は大きな diff で時間がかかる）
- cd で対象リポジトリに移動してから実行する
- 出力が長い場合は tail で末尾を取得する
```

## モデル指定（オプション）

特定のモデルを使いたい場合:

```bash
codex review --uncommitted -c model="o3"
codex exec --full-auto --ephemeral -m o3 "..."
```
