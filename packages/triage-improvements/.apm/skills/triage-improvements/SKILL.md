---
name: triage-improvements
description: "`discover-signals` が抽出した自己改善シグナル (`.triage/signals-*.json`) を読み込み、CLAUDE.md / SKILL.md への追記提案を生成、ユーザー承認を経て対象ファイルを編集し `git add` まで行うときに使用する。完全自動化はせず、各シグナルごとに採否と文面をユーザーが確認する対話型のフロー。loop engineering の学習ループとして、失敗を skill / hook / memory に戻す場合にも使用する。コミット・push・PR 作成は本 skill の責務外 (別途実行する)。"
---

# triage-improvements

`discover-signals` が抽出したシグナルを評価し、行動規則として CLAUDE.md / SKILL.md に取り込む対話型 skill。

## スコープ

**この skill が行うこと**:

1. `.triage/signals-*.json` の読み込み
2. シグナルごとの採否判定と追記文面の提案
3. ユーザー承認の取得
4. 対象ファイルの編集 (`Edit` ツール経由)
5. 編集したファイルの `git add` まで

**この skill が行わないこと** (別途実行する):

- `git commit` (`commit-commands` plugin や手動コミットを使用)
- `git push`
- `gh pr create` / PR 本文の生成

ユーザーが staged 状態の diff を目視確認できるところで停止することで、人間レビューの介入点を確保する。

## Loop 学習ループでの扱い

自動実行で得た signal でも、採否と文面は人間が確認する。loop の失敗をそのまま CLAUDE.md に足さず、次の順序で逃がす。

1. 既存 skill の手順不足なら、その SKILL.md を更新する。
2. 機械強制できるなら hook / lint / CI に寄せる。
3. 特定 repo 固有なら repo の AGENTS.md / CLAUDE.md に寄せる。
4. 全タスクで必要な判断規則だけをグローバル memory に入れる。

loop が同じ失敗を 2 回以上繰り返した場合は、単なる追記ではなく `audit-memory` も合わせて実行し、古い・弱いルールを削る。

## 前提

- `discover-signals` で `.triage/signals-<date>-<hhmm>.json` が生成済み (旧フォーマット `signals-<date>.json` も後方互換で受ける)
- 編集対象の CLAUDE.md / SKILL.md がローカルに存在する。**作者固有のパスは前提にしない** — 引数または環境変数で指定する

## 入力

```text
triage-improvements [--signals <path>] [--target-claude-md <path>] [--skill-repo <path> ...] [--limit N]
```

- `--signals <path>`: 入力 JSON。省略時は `.triage/signals-*.json` の最新を選択
- `--target-claude-md <path>`: CLAUDE.md 系シグナルの追記先ファイル。省略時の探索順序:
  1. 環境変数 `$CLAUDE_TARGET_MD` (利用者が固定の追記先を持つ場合に設定)
  2. `~/.claude/CLAUDE.md` (Claude Code 標準のグローバル memory)
  3. 上記いずれも存在しなければユーザーに対話で尋ねる
- `--skill-repo <path>`: SKILL.md 系シグナルの追記先となる APM パッケージリポのローカル clone パス。**複数指定可** (`--skill-repo ~/repos/agent-package-basic --skill-repo ~/repos/agent-package-team`)。省略時は SKILL.md 系シグナルを「未適用」として `.triage/pending-skill-md-*.md` に書き出すのみで停止する
- `--limit N`: ユーザー提示時に最初に表示する件数 (デフォルト 10)。残りは「more」で順次表示。50 件超のシグナルで画面が溢れるのを防ぐ

## フロー

### Step 1: 入力ファイルの読み込み

最新の signals ファイルを選ぶ。`ls -t glob` はシェル alias (例: `eza`) でグロブが期待通りに展開されないことがあるので `find` ベースで取る:

```bash
find .triage -maxdepth 1 -name 'signals-*.json' -printf '%T@ %p\n' \
  | sort -nr | head -1 | cut -d' ' -f2-
```

`--signals <path>` が指定されたらそれを優先する。

JSON の `signals[]` を読み、件数とシグナル種別の内訳をユーザーに報告する。

### Step 1.5: 追記先のヘッドルーム確認 (重要)

**新規ルール追加を提案する前に**、追記先のメモリファイルが既に肥大化していないか確認する。Anthropic 公式 [ベストプラクティス](https://code.claude.com/docs/ja/best-practices) は CLAUDE.md を 300 行 / 200 ルール程度に保つことを推奨。これを超えると重要なルールがノイズに失われる。

`audit-memory` skill が同梱しているスクリプトでヘッドルームを取得する (利用可能な場合):

```bash
uv run --script ~/.claude/skills/audit-memory/scripts/audit_memory.py --target "$TARGET_CLAUDE_MD"
```

判定:

- **ヘッドルームに余裕** (lines_pct < 60% かつ重複ゼロ): そのまま Step 2 へ
- **ヘッドルームひっ迫** (lines_pct >= 60% または重複あり): ユーザーに `audit-memory` を先に走らせるよう案内し、本 skill を一時停止する選択肢を出す

```text
⚠️ 追記先 CLAUDE.md は 218 行 / 145 ルール (上限の 73%/72%)。
   重複検出: 3 件。
   新規ルール追加の前に audit-memory で整理を推奨します。

選択してください:
- audit-memory を先に実行: audit
- 整理は後回しで triage を続行: continue
- triage を中止: abort
```

`audit-memory` skill が未配備なら Step 2 へ進んで構わないが、Step 4 のユーザー提示時に `wc -l` だけ報告する。

### Step 2: シグナルの評価と提案文面の生成

各シグナルを以下の観点で評価する。

#### 2-1: 採否の方針

| シグナル種別           | 採用基準                                                                                   |
| ---------------------- | ------------------------------------------------------------------------------------------ |
| `user_correction`      | アシスタントの応答に**繰り返されそうな性質の誤り**があれば採用。1 回限りの取り違えは見送り |
| `repeated_instruction` | 3 セッション以上に登場 = 確実に行動規則化候補                                              |
| `tool_loop`            | 失敗を伴う反復 = skill / hook 化候補                                                       |

#### 2-2: 反映先の判定 (5 階層)

**重要**: CLAUDE.md は最後の手段。下記の判定順序で「より下層に逃せないか」を必ず先に問う。Anthropic 公式は CLAUDE.md について「**Claude が指示なしで既に正しく動くなら削除**」「**機械強制可能なものは hook / lint へ**」を推奨している。

判定順序 (上から順に検討、合致したらそこで決定):

| #   | 反映先                                     | 適合する内容                                                      | 例                                                                                                                  |
| --- | ------------------------------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 1   | **見送り (= 何もしない)**                  | 1 回限りの取り違え / Claude のデフォルトと被る / 検証不能な抽象論 | 「気をつけて」「丁寧に」                                                                                            |
| 2   | **既存ルールへの統合**                     | Step 3 の重複チェックで類似ルールあり                             | 同趣旨の "## 推論スタイル" 既存ルール                                                                               |
| 3   | **hook / lint / CI で機械強制**            | edit/write/commit のイベントで自動実行可能                        | "lint after edit" → `PostToolUse` hook<br>"commit message format" → `commit-msg` hook<br>"import 順" → `ruff check` |
| 4   | **skill (新規 or 既存) の SKILL.md**       | 特定ワークフロー / ドメインでだけ必要、常時不要                   | "PR レビュー時に〜" → `review-pr` SKILL.md<br>"Issue 起票時に〜" → `create-issue` SKILL.md                          |
| 5   | **CLAUDE.md (新規セクション or 末尾追加)** | 上記すべてに該当しない、常時必要な行動規則                        | 推論スタイルの全般指針                                                                                              |

**5 (CLAUDE.md 追加) を選ぶ前に、必ず 1〜4 を検討した証拠を残す**。例えば「hook 化は技術的に不可能 (動的判断が必要)」「skill 化は範囲が広すぎる (全タスクで必要)」のような理由付け。

`--skill-repo` が複数指定されている場合、対象 skill 名 (`tool_loop` シグナルの `tool` または `signatures[0]` から推定) を `<repo>/packages/*/` で検索し、ヒットしたリポを選ぶ。複数ヒット・ノーヒットは対話で選ばせる。

hook 化候補は `audit-memory` skill 同梱のテンプレを参照できる:

- `~/.claude/skills/audit-memory/templates/lint-after-edit.json`: `PostToolUse` で format を走らせるひな形

CLAUDE.md 追加 (反映先 5) は **採用候補のうち多くて 1-2 件まで** に絞ること。1 回の triage で複数の新セクションを増やすと、次回の `audit-memory` で削除候補に逆戻りする。1 件追加したら、対になる削除候補が無いか考えて提案する。

#### 2-3: 追記文面の生成

「**禁止/推奨**」と「**理由 (Why)**」をペアで書く。理由を併記すると Claude がエッジケースを判断しやすい。

例 (sig-0002 「deprecated な機能を推奨してしまった」場合):

```markdown
- **deprecated な CLI コマンド・設定キーをユーザーに案内しない**。
  - 理由: 「`/output-style`」のように現在は廃止されている機能を推奨してしまうと、ユーザーの環境で実行できず混乱を招く。
  - 対処: 案内する前に存在確認する (slash command なら `/help` 出力、設定キーなら現行ドキュメントを確認)。
```

### Step 3: 重複チェック

追記前に既存ファイルを `rg` で検索し、同種のルールが既に書かれていないか確認する:

```bash
rg -n "deprecated|存在確認" "$TARGET_CLAUDE_MD"
```

`$TARGET_CLAUDE_MD` は Step 1 で解決した追記先パス。重複している場合は新規追加ではなく **既存セクションの拡張** として diff を作る。

### Step 4: ユーザーへの提示 (バッチ + ページング)

採用候補をまとめて提示する。`--limit N` (デフォルト 10) を超える場合は最初の N 件のみ表示し、末尾に「残り K 件: more で表示」と添える。**反映先 (5 階層のどこか) と "より下層への移行不可の理由" を明示**。

```text
📋 triage-improvements: 採用候補 N 件 (表示: 1-10 / 全 N 件)

入力: .triage/signals-<date>-<hhmm>.json (M 件中 N 件を採用候補に選定)
ヘッドルーム: ~/.claude/CLAUDE.md = 62 行 / 16 ルール (上限 21%/8%)

────────────────────────────────────────────────────
[sig-0001] user_correction → 反映先 5: CLAUDE.md (新規セクション)
sig 内容: 「apm.yml の package が悪さしている?」
採用理由: 設定起因と決めつけて実装を見ない癖を抑止
下層検討:
  - 反映先 1 (見送り): NG。3 セッション以上で類似のミスが観測されている
  - 反映先 2 (既存統合): NG。"## 推論スタイル" の既存ルールとは別観点
  - 反映先 3 (hook 化): NG。「設定 vs 実装」の判断は動的で機械化不可
  - 反映先 4 (skill 化): NG。特定タスクではなく全般指針
  → 反映先 5 (CLAUDE.md) で確定
追記先: <解決済み CLAUDE.md パス>
追記内容:
  - **設定ファイルだけで原因を断定しない**。設定が無関係な可能性も考慮し、まず実装(コードや hook 出力)を確認する。
    - 理由: ユーザーが既に設定を点検済みのケースが多く、設定起因と推測すると時間の無駄になる。
    - 対処: 設定を一周見て手がかりが無ければ、実装側 (コード/hook 出力) を読みに行く。

────────────────────────────────────────────────────
[sig-0004] tool_loop → 反映先 3: PostToolUse hook
sig 内容: extract_signals.py を 7 回連続失敗 (lint エラーループ)
採用理由: edit 後に lint を機械強制すれば未然に防げる
下層検討:
  - 反映先 1 (見送り): NG。同種の失敗が複数セッションに観測
  - 反映先 2 (既存統合): NG。既存ルールに lint 関連なし
  → 反映先 3 (hook) で確定。CLAUDE.md / SKILL.md には書かない
変更先: ~/.claude/settings.json の hooks.PostToolUse
適用テンプレ: ~/.claude/skills/audit-memory/templates/lint-after-edit.json

────────────────────────────────────────────────────
[sig-0007] tool_loop → 反映先 4: SKILL.md
sig 内容: review-pr skill 起動時に GitHub URL を取り違えた
採用理由: skill 固有の使い方の問題
下層検討:
  - 反映先 3 (hook): NG。skill 起動の引数解釈は動的
  → 反映先 4 (skill SKILL.md) で確定
追記先候補: <skill-repo>/packages/review-pr/.apm/skills/review-pr/SKILL.md
            (--skill-repo 未指定のため pending として保存)
追記内容: ...

採否を選んでください:
- 全採用: all
- 個別採用: 1,2,5  (採用するシグナル番号)
- 文面修正: edit 1   (1 番の文面を編集モードへ)
- 続きを表示: more
- 全見送り: skip
```

### Step 5: 採用分のファイル編集 / hook 追加

ユーザー承認に基づき、反映先ごとに以下を実行する:

- **反映先 1 (見送り)**: 何もしない
- **反映先 2 (既存統合)**: 既存ルールを `Edit` ツールで拡張
- **反映先 3 (hook 化)**: `~/.claude/settings.json` の `hooks` キーに JSON fragment を追記。テンプレが `audit-memory/templates/` にあれば参照、無ければ採用文面に基づき新規作成
- **反映先 4 (skill SKILL.md)**: `<skill-repo>/packages/<name>/.apm/skills/<name>/SKILL.md` を `Edit`
- **反映先 5 (CLAUDE.md)**: `$TARGET_CLAUDE_MD` を `Edit`

注意:

- 同一ファイルに複数の追記がある場合は **1 回の Edit にまとめる** (新規セクションを作るか、既存セクションを拡張するかは Step 3 の重複チェック結果で決める)
- 異なるリポの SKILL.md は別ファイルとして扱う
- `~/.claude/settings.json` の編集は **JSON 構文を壊さない** よう、編集後に `python3 -c "import json; json.load(open('...'))"` で必ず validate する

### Step 6: `git add`

編集したファイルが git 管理下なら `git add` する。**commit はしない**。

CLAUDE.md は git 管理下にないこともあるので注意:

```bash
# CLAUDE.md 側 (git 管理下のときのみ)
target_dir=$(dirname "$TARGET_CLAUDE_MD")
if git -C "$target_dir" rev-parse --git-dir > /dev/null 2>&1; then
  git -C "$target_dir" add "$TARGET_CLAUDE_MD"
fi

# skill リポ側 (--skill-repo が指定された場合のみ)
git -C "$SKILL_REPO" add "packages/<name>/.apm/skills/<name>/SKILL.md"
```

`--skill-repo` が指定されておらず SKILL.md 系の採用候補があった場合は、**対象ファイルのフルパスと提案文面を `.triage/pending-skill-md-<date>-<hhmm>.md` に書き出す** だけにとどめる。ユーザーが後でクローン取得後に手動で適用できるようにする。

### Step 7: 報告

実行内容を会話で報告する。中間ファイル (`.triage/triage-<date>.md` 等) は作らない — staged diff と `.triage/pending-skill-md-*.md` (必要時) が事実の唯一のソース。**反映先別の内訳と、見送り理由の集計** も含める (見送り理由は次回 `discover-signals` の検出器改善のフィードバック)。

```text
📋 triage-improvements 完了

入力: .triage/signals-<date>-<hhmm>.json (M 件)
採用 N 件の内訳:
  - 反映先 2 (既存統合): 1 件
  - 反映先 3 (hook 化): 1 件
  - 反映先 4 (skill SKILL.md): 1 件 (うち未適用 1 件)
  - 反映先 5 (CLAUDE.md 新規): 1 件
見送り K 件の理由:
  - 1 回限りの取り違え: 3
  - 既反映済み (重複): 2
  - 検出器の偽陽性: 1

ファイル変更 (staged):
  <解決済み CLAUDE.md パス>  (+5 行)

ファイル変更 (git 管理外):
  ~/.claude/settings.json  (+1 hook: PostToolUse → mise run format)

未適用 (--skill-repo 未指定):
  packages/review-pr/.apm/skills/review-pr/SKILL.md
    → .triage/pending-skill-md-<date>-<hhmm>.md に保存

次のステップ:
- 差分確認: git -C <repo> diff --cached
- コミット: /commit  (commit-commands plugin) または手動で `git commit`
- push と PR は別途実行

CLAUDE.md ヘッドルーム: 62 → 67 行 (上限の 22% — まだ余裕)
次回 audit-memory での整理候補が 3 件未満を維持できているか確認推奨
```

## 重要な注意事項

### 1. 勝手にコミット・push しない

- ファイル編集と `git add` で必ず停止する
- ユーザーが staged 状態の diff を確認できるようにする
- commit/push/PR はユーザーが別途実行する責務

### 2. シグナルの取り扱い

- `.triage/signals-*.json` には会話の生データが含まれる。**コミット対象に含めない** (`.gitignore` で `.triage/` 除外済みの想定)
- 提案文面に生のユーザー発話を貼らない。要約のみを書く

### 3. 重複回避と "削除と対" の意識

`Step 3` の重複チェックで既存ルールがある場合、必ず**統合する**こと。同じ趣旨のルールを複数箇所に並べると CLAUDE.md が肥大化し、優先順位もブレる。

**追加 1 件につき削除候補を 1 件考える** (公式ベストプラクティスの "Treat CLAUDE.md as code")。新規 CLAUDE.md 追加を提案する時、`audit-memory` が出した整理候補がもしあれば、同じセッション内で **削除と追加を同時に staged する**。「足すだけ」の運用は半年で必ず破綻する。

### 4. 文面のスタイル

追記先 (CLAUDE.md / SKILL.md) の既存文体に合わせる。多くの利用環境では以下の Markdown スタイルが採用されているので、特別な指示がなければ準拠する:

- 段落内で改行しない (1 段落 = 1 行)
- 強調記号 `**...**` を改行で分断しない、内側に空白を入れない
- 箇条書きは `-` を使う

追記先ファイル冒頭または同じリポ内に独自の Markdown スタイル指示があればそちらを優先する。

## 既存資産との連携

- `discover-signals`: この skill の入力 (`.triage/signals-*.json`) を生成する前段
- `audit-memory`: 対 (双方向) になる削除/移行担当 skill。本 skill が "何を足すか" を担当、`audit-memory` が "何を捨てるか・どこへ逃すか" を担当。**Step 1.5 でヘッドルームをチェックし、肥大化していたら audit-memory を先に呼ぶ案内を出す**。両者を交互に回すと CLAUDE.md は健康な状態を保つ
- `commit-message.md`: コミットメッセージのスタイル(コミット作成時にユーザーが従う)
- `commit-commands` plugin の `/commit`: 編集後のコミット作成
- `worktree` skill: 別リポ作業を隔離環境で行いたい場合

## このフローを動かさない時

- 採用候補が 0 件 = `discover-signals` の段階で何も拾えなかった = OK、何もしない
- 候補があってもユーザー承認が `skip` = 何もしない
- ファイル編集失敗(Edit が old_string にマッチしない等) = 該当シグナルだけ未適用扱いにし、報告に含める
- Step 1.5 でユーザーが `audit` を選んだ場合 = `audit-memory` を案内して本 skill は一時停止。整理後に再起動する
