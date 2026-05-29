---
name: audit-memory
description: CLAUDE.md / AGENTS.md / `~/.claude/rules/*.md` / `.cursor/rules/*.md` といったメモリファイルを 1 ルールずつ評価し、冗長・重複・言語の常識被り・機械強制可能・証拠なしの観点で削除/統合/skill 化/hook 化への移行を提案する診断 skill。新規ルール追加は `triage-improvements` の責務、本 skill は「何を捨てるか・どこへ逃がすか」を担当する。
---

# audit-memory

メモリ系ファイルの健康診断 skill。`triage-improvements` (追加担当) と対をなす **削除/移行担当**。

## 設計の根拠

Anthropic 公式 [Claude Code ベストプラクティス](https://code.claude.com/docs/ja/best-practices) は以下を推奨:

- **300 行 / 200 ルール程度を上限の目安に**。膨らんだ CLAUDE.md は重要なルールがノイズに失われる。
- **「削除すると Claude が間違いを犯すか?」を 1 行ごとに問う**。No なら削除。
- **CLAUDE.md には広く適用されるもののみ**。ドメイン知識・たまに必要なワークフローは **skill** に逃がす。
- **lint/format/test 等の機械強制可能ルールは hook (`settings.json`) や CI で守る**。CLAUDE.md に書かない。

本 skill はこの方針を運用に落とし込む。**追加だけの運用は 100% 肥大する** ため、定期的 (月 1〜四半期に 1) に走らせて整理する。

## スコープ

**この skill が行うこと**:

1. メモリファイルの **客観指標を取得** (行数 / ルール数 / 重複検出 / セクション一覧) — Python スクリプト
2. **意味判断** を加えて 1 ルールごとに 5 観点で評価 (冗長・重複・常識・機械強制可能・証拠なし) — Claude
3. 反映先候補を提示 (削除 / 統合 / skill 化 / hook 化)
4. ユーザー承認後、対象ファイルを `Edit` で編集し、必要なら hook テンプレを `~/.claude/settings.json` に追記
5. `git add` まで実行し停止

**この skill が行わないこと** (別途実行する):

- `git commit` (`commit-commands` plugin か手動)
- `git push` / `gh pr create`
- 新規ルールの追加 (← `triage-improvements` の責務)
- 内容の品質評価 (日本語が稚拙、等) — **量と配置の問題に集中**

## 前提

- [`uv`](https://docs.astral.sh/uv/) が PATH に存在する (同梱スクリプトは PEP 723 inline script)
- 編集対象のメモリファイルがローカルに存在する。dotfiles 派なら symlink 越しでも問題ない (`Edit` ツールが symlink を辿る)

## 入力

```text
audit-memory [--target <path> ...] [--auto] [--max-lines N] [--max-rules N] [--apply-deletions]
```

- `--target <path>`: 監査対象。複数指定可。省略時は `--auto` と同じ標準位置探索を行う
- `--auto`: 標準位置を全部スキャン (デフォルト動作)
  - `~/.claude/CLAUDE.md`
  - `$(pwd)/CLAUDE.md`, `$(pwd)/CLAUDE.local.md`, `$(pwd)/AGENTS.md`
  - `~/.claude/rules/*.md`
  - `$(pwd)/.claude/rules/*.md`
  - `$(pwd)/.cursor/rules/*.md`
- `--max-lines N`: 警告閾値 (デフォルト 300)
- `--max-rules N`: ルール数の警告閾値 (デフォルト 200)
- `--apply-deletions`: ユーザー対話を省略して全採用 (CI / 定期実行用)

## フロー

### Step 1: 機械指標の取得

skill 同梱のスクリプトを実行し、診断 JSON を `.triage/audit-<date>-<hhmm>.json` に書き出す:

```bash
uv run --script "<skill-dir>/scripts/audit_memory.py" --auto
```

`<skill-dir>` はこの SKILL.md があるディレクトリ。Claude Code 環境では `~/.claude/skills/audit-memory`。

スクリプトは以下を出力する (Claude が後の Step で読み込む):

- ファイルごとの行数 / ルール数 / 上限に対する % (lines_pct, rules_pct)
- セクション一覧 (level / title / start_line / end_line / line_count / body_excerpt)
- bullet 単位のルール一覧 (line / rule_head / raw / is_bold)
- 同一ファイル内重複 (`duplicates_within_file`) — 完全一致の rule_head が 2 回以上
- ファイル間重複 (`duplicates_across_files`) — 同じ rule_head が複数ファイルに登場

**意味判断はスクリプトでは行わない**。次の Step で Claude が補う。

### Step 2: 1 ルールごとに 5 観点で評価

Step 1 の JSON を読み、各 `bullet_rules[]` を以下の観点で評価する。**1 つでも該当するなら整理候補**。

| 観点 | 判断基準 |
| --- | --- |
| **冗長** | Claude のデフォルト挙動と被る (例: 「不明瞭なら質問する」) |
| **重複** | スクリプトが検出済み (`duplicates_within_file` / `duplicates_across_files`) |
| **言語/ツール常識** | プロジェクトのコードを読めば推測できる (例: 「Python では PEP 8」「ES modules を使う」) |
| **機械強制可能** | lint / formatter / hook / pre-commit / CI に逃がせる (例: 「lint and format while editing」) |
| **証拠なし** | 「削除すると Claude が間違える」具体根拠が思い当たらない (= 念のため書かれているだけ) |

**残すべきルール** = 5 観点いずれにも該当しない、つまり「具体的なインシデントから生まれた / Claude が知らない / 自動化できない」もの。

例 (現 CLAUDE.md の `## 推論スタイル`):

```markdown
- **deprecated な CLI コマンド・設定キーをユーザーに案内しない**。
  - 理由: 過去のドキュメントに残った旧機能 (例: `/output-style`) を勧めるとユーザーの環境で実行できず混乱を招く。
  - 対処: `/help` 出力・現行ドキュメントで存在確認する。
```

これは **冗長でも重複でも常識でもない / 機械強制不可 / 具体インシデント由来** で全観点クリア。残す。

### Step 3: 反映先の判定 (5 階層)

整理候補と判定したルールをどこへ移すか決める。

| 移行先 | 適合する内容 | 例 |
| --- | --- | --- |
| **削除** | 冗長 / 常識 / 証拠なし | 「不明瞭なら質問」「機密をコードに書かない」 |
| **統合** | 既存の同趣旨ルールに併合 (新規追加しない) | 同じファイル内に類似ルール / クロスファイル重複 |
| **skill 化** | ドメイン固有 / 特定ワークフローでのみ必要 | 「PHP/CakePHP プロジェクトで〜」「PR レビュー時に〜」 |
| **hook 化** | edit/write 等のイベントで機械強制可能 | 「lint and format while editing」 → `PostToolUse` hook |
| **CI/lint 化** | プロジェクトの test/lint で守れる | 「import 順は isort」 → `ruff check` で強制 |

判定に迷ったら **削除を優先**。「ルールを足すより捨てる方が CLAUDE.md は健康になる」(公式ベストプラクティスの基本姿勢)。

hook 化候補は本 skill 同梱のテンプレを参照:

- `<skill-dir>/templates/lint-after-edit.json`: `PostToolUse` で `mise run format` を走らせるひな形

### Step 4: ユーザーへの提示

ファイルごとにまとめて提示する:

```text
📋 audit-memory 診断結果

対象: ~/.claude/CLAUDE.md
サイズ: 83 行 / 4576 bytes (上限 300 行に対し 27.7%)
ルール数: 23 (上限 200 に対し 11.5%)
ヘッドルーム: 余裕あり (削除候補なくても急務ではない)

検出済み重複:
- "Python: uv, ruff" (L18, L27)
- "JavaScript: eslint, prettier" (L19, L28)

────────────────────────────────────────────────────
[診断 1/N] L5: "Ask questions if the instructions are unclear."
  種別: 冗長
  根拠: Claude のデフォルト動作。明示しなくても不明瞭時は質問する
  推奨: 削除

[診断 2/N] L13-19 + L21-28: "## Preferred Tools and Libraries" と "## Code Style Guidelines"
  種別: 重複 (スクリプト検出) + 機械強制可能
  根拠: ツール列挙が 2 セクションに完全重複。"Lint and Format while editing" は hook 化推奨
  推奨: "## Code Style Guidelines" セクション削除 + PostToolUse hook 追加
  hook テンプレ: <skill-dir>/templates/lint-after-edit.json

採否を選んでください:
- 全採用: all
- 個別採用: 1,2,5  (採用する診断番号)
- 文面修正: edit 1
- 全見送り: skip
```

**ヘッドルームに余裕があっても整理は推奨**。今足りていなくても放置すると 6 ヶ月で破綻する。

### Step 5: 採用分の編集

ユーザー承認に基づき:

1. 対象メモリファイルを `Edit` で編集 (削除 / 統合)
2. hook 化採用なら `~/.claude/settings.json` の `hooks` キーにテンプレ JSON を merge
3. skill 化採用なら、新 skill のディレクトリを scaffold する案内のみ (実装はユーザー)

同一ファイルに複数の編集があるときは **1 ファイル = 1 Edit にまとめる** (失敗時のロールバックが楽)。

### Step 6: `git add`

編集したファイルが git 管理下なら `git add`。**commit はしない**。

```bash
target_dir=$(dirname "$TARGET_FILE")
if git -C "$target_dir" rev-parse --git-dir > /dev/null 2>&1; then
  git -C "$target_dir" add "$TARGET_FILE"
fi
```

`~/.claude/settings.json` は通常 git 管理外なので、編集したことだけ報告する (add はしない)。

### Step 7: 報告

```text
📋 audit-memory 完了

対象: 2 ファイル / 採用: 4 件 / 見送り: 6 件

ファイル変更 (staged):
  ~/.claude/CLAUDE.md  (-23 行 / 83 → 60 行)
  ~/dotfiles/claude/profiles/wsl-ubuntu/CLAUDE.md  (同上)

未 staged (git 管理外):
  ~/.claude/settings.json  (+1 hook: PostToolUse → mise run format)

スキップ (skill 化候補は手動):
  - L33-41 "## Restrictions" → security-related skill 新設を検討

次のステップ:
- 差分確認: git -C ~/dotfiles diff --cached
- コミット: /commit または手動 `git commit`
```

## 重要な注意事項

### 1. 勝手にコミット・push しない

- 編集と `git add` で停止する
- `~/.claude/settings.json` への hook 追記は実行するが、これは git 管理外のことが多いので「編集したこと」だけ報告

### 2. 削除を恐れない

公式ベストプラクティスの原則: **「削除すると Claude が間違いを犯すか? No なら削除」**。

ユーザーが「迷ったら残す」を選びがちだが、肥大化したファイルは Claude にとって最終的に **半分無視される** 状態になる。具体根拠 (失敗インシデント / 公式と異なる挙動) のないルールは削除候補。

### 3. ルール本体と "理由 / 対処" のサブ bullet をペアで扱う

```markdown
- **rule head**
  - 理由: ...
  - 対処: ...
```

このフォーマットの bullet を編集するときは **3 行 (or 4 行) 全体を 1 ユニット**として削除/編集する。`rule_head` だけ消して `理由:` `対処:` が孤児になる事故を防ぐ。

### 4. 重複の解決方針

- **同一ファイル内重複** (`duplicates_within_file`): 後の方を削除し、前のセクションに統合
- **クロスファイル重複** (`duplicates_across_files`): **役割が違う 2 ファイルに同じことを書いている** = 責務が不明確。どちらか 1 箇所に寄せる:
  - rules ファイル (`~/.claude/rules/*.md`) は `paths` 指定で読まれるので、**特定パスでだけ効くルール**を置く
  - CLAUDE.md は **常時読まれるルール**を置く
  - 同じルールが両方にあるなら、CLAUDE.md 側を削除して rules を残すか、その逆かを選ぶ

### 5. AGENTS.md / `.cursor/rules/` を扱うとき

APM は claude / codex / cursor の 5 ターゲットを持つ。それぞれ独自のメモリファイル形式があるが、**整理の観点 (冗長/重複/常識/機械強制/証拠なし) は同一**。本 skill は形式の違いを意識せず、Markdown の bullet 単位で評価する。

ただし `.cursor/rules/*.md` は frontmatter の `globs` フィールドで適用範囲を絞る仕組みがあるので、**「常時読まれるか / 特定パスのみか」を frontmatter で確認**してから整理する。

## 既存資産との連携

- `triage-improvements`: 新規ルール追加担当。本 skill は逆方向 (削除担当)。両者を交互に回すと CLAUDE.md は健康な状態を保つ
- `commit-commands` plugin の `/commit`: 編集後のコミット作成
- `discover-signals`: 自己改善シグナル抽出。本 skill は不要 (機械指標で完結)

## このフローを動かさない時

- 全ファイルが上限の 50% 未満 + 重複ゼロ = 整理候補がまず無い → 軽くだけ報告して終了
- 採用候補があっても全 skip = 何もしない (Step 7 の報告だけ)
