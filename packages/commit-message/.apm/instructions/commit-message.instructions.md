---
description: 日本語コミットメッセージの記法ルール (Conventional Commits 不使用・絵文字なし・Subject 50字以内で動詞終止・コード参照はバッククォート)
applyTo: "**"
---

# コミットメッセージのルール

コミットメッセージは日本語で書く。

## Subject

- 50文字以内（全角約25文字目安）に収める
- Conventional Commits プレフィックス（feat:, fix:, docs: 等）は使わない
- gitmoji や絵文字は使わない
- 変更内容を直接記述する。日本語の場合は動詞で終える: 〜を追加、〜を修正、〜に変更、〜を削除など
- コード参照（クラス名・設定キー・ファイル名等）はバッククォートで囲む
- Subject の末尾にピリオド（。）を付けない

## Body

- Subject で説明が十分な場合 Body は省略する
- Subject と Body は空行で分離する
- 箇条書きは `-` を使う
- what と why を説明する（how ではない）
- 72文字に収まるように端的な文章で書く

## 良い Subject の例

```text
`Config\Database` で指定したリトライポリシーの適用漏れを修正
PHP標準のException使用箇所を `BaseException` に変更
`TlsContext` で `verify_peer` を指定可能にする
```
