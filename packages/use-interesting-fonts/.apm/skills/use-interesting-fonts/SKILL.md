---
name: use-interesting-fonts
description: 汎用フォント (Inter, Roboto, Arial 等) を避け、意図のあるタイポグラフィでフロントエンドの質を上げる必要があるときに使用する。UI 制作や LP 作成時に Display / Editorial / Technical / Distinctive の各カテゴリから決定的な選択を行い、Google Fonts からロードする。
---

# High-End Typography Skill

あなたはフロントエンドデザインにおいて、ありきたりなデザイン（Distributional convergence）を避け、高品質で意図のあるタイポグラフィを選択する必要があります。

## 基本原則

タイポグラフィは品質を瞬時に伝えます。退屈で汎用的なフォントの使用は避けてください。

### 絶対に使用しないフォント

- Inter, Roboto, Open Sans, Lato
- デフォルトのシステムフォント（sans-serif, Arialなど）

### 推奨されるインパクトのある選択肢

- **Code aesthetic:** JetBrains Mono, Fira Code, Space Grotesk
- **Editorial:** Playfair Display, Crimson Pro
- **Technical:** IBM Plex family, Source Sans 3
- **Distinctive:** Bricolage Grotesque, Newsreader

## スタイリングの指針

- **ペアリング原則:**「高コントラスト ＝ 面白い」。Display + Monospace、Serif + Geometric Sans、異なるウェイトのバリアブルフォントなどを組み合わせる。
- **極端な値の使用:** ウェイトは 400 vs 600 ではなく、100/200 vs 800/900 のように差をつける。サイズも 1.5倍ではなく 3倍以上のジャンプを意識する。
- **決定的な選択:** 特徴的なフォントを1つ選び、それを断固として使用する。

## 実装

- フォントは常に **Google Fonts** からロードするようにコードを生成してください。
