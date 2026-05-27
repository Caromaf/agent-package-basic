---
name: ux-review
description: AI ペルソナを与えて Playwright MCP で対象サービスを実際に触らせ、タスク実施時の詰まりや気づきを構造化レポートとしてまとめる必要があるときに使用する。`init` サブコマンドで雛形展開、本実行でレビューセッションを行う 2 モード構成。
---

# UX Review

AI にペルソナを与え、Playwright MCP で対象サービスを実際に触らせて
UI/UX の詰まりどころをレポートする仕組み。

## 全体フロー（必ずこの順序で進める）

1. **初回のみ**: `codex mcp add playwright -- npx '@playwright/mcp@latest'` を実行して Codex を再起動
2. **プロジェクトごとのセットアップ**: `~/dotfiles/codex/ux-review/templates/` をプロジェクトの `evaluation/ux_review/` などにコピー
3. **雛形の編集**: コピーした `service.md`（URL・ログイン）と `tasks/<persona>.md`（典型タスク）を対象サービス用に書き換える
4. **レビュー実行**: `ux-review <service-path> <persona>` で Playwright MCP が起動し、AI がペルソナに成り切って操作
5. **人間レビュー**: 生成されたレポート末尾の `## 人間レビューメモ` 欄を埋め、Issue 化する改善案を選ぶ

2〜3 は `ux-review init <target-path>` サブコマンドでも実行できる（後述）。
**詳しい使い方ドキュメント**: `~/dotfiles/codex/ux-review/Introduction.md`

## 引数

### 通常実行

```text
ux-review <service-path> <persona> [scenario]
```

- `service-path`: `service.md` と `personas/` `tasks/` `scenarios/` `reports/` を持つディレクトリのパス
- `persona`: `<service-path>/personas/<persona>.md` のファイル名（拡張子なし）
- `scenario`: 既定 `free_exploration`。`<service-path>/scenarios/<scenario>.md` を読む

例:

```text
ux-review org/evaluation/ux_review newcomer
ux-review org/evaluation/ux_review ip_veteran free_exploration
```

### 初期化

```text
ux-review init <target-path>
```

新サービスに骨格を展開する。`~/dotfiles/codex/ux-review/templates/` の内容を
`<target-path>` にコピーする。

例:

```text
ux-review init some-repo/evaluation/ux_review
```

## 前提条件チェック

コマンド起動時、まず以下を確認してください:

1. **Playwright MCP が接続されているか**
   - 期待ツール名: `mcp__playwright__browser_navigate` 等
   - 未接続の場合はユーザーにこう案内して停止:
     > Playwright MCP が接続されていません。以下を実行してから Codex を再起動してください:
     >
     > ```bash
     > codex mcp add playwright -- npx '@playwright/mcp@latest'
     > ```

2. **引数が `init` か通常実行か** を判断し、以下のいずれかに進む

## モード 1: init（雛形展開）

プロジェクトに UX Review 資産を配置する。手動で
`cp -R ~/dotfiles/codex/ux-review/templates/. <target-path>/` しても同じ結果になるが、
このサブコマンドを使うと編集ポイントの案内までセットで実行される。

1. `<target-path>` が既存なら「既に存在します。上書きを避けるため中断します。」と伝えて停止
2. `mkdir -p <target-path>` でディレクトリ作成
3. `cp -R ~/dotfiles/codex/ux-review/templates/. <target-path>/` でコピー（この dotfiles ディレクトリが雛形の正本。更新はここを直接編集する）
4. コピー後、ユーザーに以下を **編集必須** として案内:
   - `<target-path>/service.md` — URL・ログイン手順・プレフィックス規約・レート制約
   - `<target-path>/tasks/<persona>.md` — そのサービス固有の典型タスク
   - `<target-path>/README.md` — プロジェクト固有の補足（任意）
5. 編集が終わったら `ux-review <target-path> <persona>` で実行可能であることを伝える

## モード 2: 通常実行（レビューセッション）

### Step 1: 資産の読み込み

以下のファイルを順に Read ツールで読む:

1. `<service-path>/service.md` — サービス情報（URL、ログイン、規約、レート制約）
2. `<service-path>/personas/<persona>.md` — ペルソナ定義
3. `<service-path>/tasks/<persona>.md` — このペルソナ向けのタスクセット
4. `<service-path>/scenarios/<scenario>.md` — シナリオ（free_exploration 等）
5. `<service-path>/reports/_template/report.md` — レポート雛形

どれかが欠けていたら、欠けているファイル名を明示してユーザーに作成を促し停止する。

### Step 2: 実行計画の提示

読み込んだ内容を踏まえ、以下をユーザーに 1 メッセージで提示してから開始:

- 対象サービスと URL
- 使用ペルソナと主要な属性 1 行
- 実施するタスク一覧（tasks/<persona>.md から）
- レポート出力先: `<service-path>/reports/<YYYY-MM-DD>_<persona>_<scenario>/`
- 推定所要時間

### Step 3: ペルソナ演技とブラウザ操作

**重要: ペルソナ逸脱を防ぐため、以下を守る**

- 操作前に「ペルソナならどう見えるか／どう反応するか」を 1 行書く
- 開発者用語（コンポーネント名、内部 API 等）を口に出さない
- 自分の属性を超えた知識を使わない
- scenario で指定された制約（プレフィックス、レート制約、禁止事項）を必ず守る

Playwright MCP ツールで操作:

- `mcp__playwright__browser_navigate` で画面遷移
- `mcp__playwright__browser_snapshot` で画面状態を取得（ARIA 情報ベース）
- `mcp__playwright__browser_take_screenshot` で重要な画面を保存
- `mcp__playwright__browser_click` / `browser_type` / `browser_press_key` で操作

スクリーンショットは
`<service-path>/reports/<YYYY-MM-DD>_<persona>_<scenario>/screenshots/NN_<tN>_<short>.png`
のパス指定で保存（NN は連番、tN はタスク番号）。

### Step 4: タスク実施

`tasks/<persona>.md` の t1 → t2 → t3 を順に実施。

- 各タスクの目安時間を超えそうなら「詰まった」と記録して次のタスクへ
- タスクの境目で「タスク N 終了 / タスク N+1 開始」を明示
- タスク間では記憶をリセットしない（学習曲線を記録するため）

### Step 5: レポート生成

`<service-path>/reports/<YYYY-MM-DD>_<persona>_<scenario>/report.md` を
`reports/_template/report.md` の構造に従って書く。

必須項目:

- 基本情報（実行日、ペルソナ、シナリオ、エンジン、セッション時間、AI モデル、ログインユーザー名、stg URL）
- タスク一覧（達成/部分達成/未達）
- 行動ログ(タスクごとに時刻・画面・操作・観察)
- 気づき（詰まり・違和感。スクショ参照付き）
- サマリ（達成数、詰まり件数、学習曲線メモ）
- 改善提案（優先度付き）
- 人間レビューメモ（**空欄で残す。人間が後で埋める欄**）

### Step 6: 実行後の必須フォロー

レポート生成後、以下をユーザーに **必ず** 案内する:

1. レポートパスを明示: `<絶対パス>/report.md`
2. **このレポートは人間レビューが必須です** と伝える:
   - ペルソナ設定からの逸脱チェック
   - Issue 化する改善提案の選定
   - レポート末尾の `## 人間レビューメモ` 欄を埋める
3. レポート内容の簡易サマリ（3 行程度）を提示

## 運用上の注意

- このコマンドは **ブラウザを実際に操作する** ため、MCP 接続済みセッション前提
- stg 環境のみ対象（service.md で明示されている場合）。本番には絶対にアクセスしない
- 副作用が残る場合のプレフィックス規約（`[ux-review/<persona>/<date>]` 等）を必ず遵守
- レート制約（service.md 記載）を超えない
- 1 セッション 20 分を目安に切り上げる

## 失敗時の扱い

- MCP 未接続: セットアップコマンドを案内して停止
- 資産ファイル欠落: 欠落ファイル名を明示して停止
- ログイン失敗: スクリーンショットを撮って行動ログに記録、以降のタスクを「未達」として扱い、気づきとして記述する（失敗そのものが価値）
- タイムアウト: 詰まった状態として記録し、次タスクへ進む
