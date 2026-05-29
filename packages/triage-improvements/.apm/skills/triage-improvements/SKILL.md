---
name: triage-improvements
description: `discover-signals` が抽出した自己改善シグナル (`.triage/signals-*.json`) を読み込み、CLAUDE.md / SKILL.md への追記提案を生成、ユーザー承認を経て対象ファイルを編集し `git add` まで行うときに使用する。完全自動化はせず、各シグナルごとに採否と文面をユーザーが確認する対話型のフロー。コミット・push・PR 作成は本 skill の責務外 (別途実行する)。
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

### Step 2: シグナルの評価と提案文面の生成

各シグナルを以下の観点で評価する。

#### 2-1: 採否の方針

| シグナル種別 | 採用基準 |
| --- | --- |
| `user_correction` | アシスタントの応答に**繰り返されそうな性質の誤り**があれば採用。1 回限りの取り違えは見送り |
| `repeated_instruction` | 3 セッション以上に登場 = 確実に CLAUDE.md 化候補 |
| `tool_loop` | 失敗を伴う反復 = SKILL.md(該当 skill のドキュメント)に注意書き追加候補 |

#### 2-2: 反映先の判定

| 内容 | 反映先 |
| --- | --- |
| 全般的な振る舞い・文体・確認スタイル | `--target-claude-md` で解決した CLAUDE.md (デフォルト `~/.claude/CLAUDE.md`) |
| 特定 skill の使い方の問題 | `<skill-repo>/packages/<name>/.apm/skills/<name>/SKILL.md` (`--skill-repo` のいずれか配下を `find` で検索) |
| 判定不能 | ユーザーに選んでもらう |

判定に迷ったら **CLAUDE.md (全般行動規則) を優先** する。SKILL.md は skill の使い方が明確に問題のあるときだけ。

`--skill-repo` が複数指定されている場合、対象 skill 名 (`tool_loop` シグナルの `tool` または `signatures[0]` から推定) を `<repo>/packages/*/` で検索し、ヒットしたリポを選ぶ。複数ヒット・ノーヒットは対話で選ばせる。

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

採用候補をまとめて提示する。`--limit N` (デフォルト 10) を超える場合は最初の N 件のみ表示し、末尾に「残り K 件: more で表示」と添える。

```text
📋 triage-improvements: 採用候補 N 件 (表示: 1-10 / 全 N 件)

入力: .triage/signals-<date>-<hhmm>.json (M 件中 N 件を採用候補に選定)

────────────────────────────────────────────────────
[sig-0001] user_correction → CLAUDE.md
sig 内容: 「apm.yml の package が悪さしている?」
採用理由: 設定起因と決めつけて実装を見ない癖を抑止
追記先: <解決済み CLAUDE.md パス>
追記内容:
  - **設定ファイルだけで原因を断定しない**。設定が無関係な可能性も考慮し、まず実装(コードや hook 出力)を確認する。
  - 理由: ユーザーが既に設定を点検済みのケースが多く、設定起因と推測すると時間の無駄になる。

(既存セクションへの統合: なし / 新規 "## 観察と推論" セクションへ追加)
────────────────────────────────────────────────────
[sig-0004] tool_loop → SKILL.md
sig 内容: extract_signals.py を 7 回連続失敗
追記先候補: <skill-repo>/packages/discover-signals/.apm/skills/discover-signals/SKILL.md
            (--skill-repo 未指定のため pending として保存)
追記内容: ...

採否を選んでください:
- 全採用: all
- 個別採用: 1,2,5  (採用するシグナル番号)
- 文面修正: edit 1   (1 番の文面を編集モードへ)
- 続きを表示: more
- 全見送り: skip
```

### Step 5: 採用分のファイル編集

ユーザー承認に基づき、対象ファイルを `Edit` ツールで編集する。

- 同一ファイルに複数の追記がある場合は **1 回の Edit にまとめる** (新規セクションを作るか、既存セクションを拡張するかは Step 3 の重複チェック結果で決める)
- 異なるリポの SKILL.md は別ファイルとして扱う

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

実行内容を会話で報告する。中間ファイル (`.triage/triage-<date>.md` 等) は作らない — staged diff と `.triage/pending-skill-md-*.md` (必要時) が事実の唯一のソース。

```text
📋 triage-improvements 完了

入力: .triage/signals-<date>-<hhmm>.json (M 件)
採用: N 件 / 見送り: K 件

ファイル変更 (staged):
  <解決済み CLAUDE.md パス>  (+12 行)

未適用 (--skill-repo 未指定):
  packages/discover-signals/.apm/skills/discover-signals/SKILL.md
    → .triage/pending-skill-md-<date>-<hhmm>.md に保存

次のステップ:
- 差分確認: git -C <repo> diff --cached
- コミット: /commit  (commit-commands plugin) または手動で `git commit`
- push と PR は別途実行
```

## 重要な注意事項

### 1. 勝手にコミット・push しない

- ファイル編集と `git add` で必ず停止する
- ユーザーが staged 状態の diff を確認できるようにする
- commit/push/PR はユーザーが別途実行する責務

### 2. シグナルの取り扱い

- `.triage/signals-*.json` には会話の生データが含まれる。**コミット対象に含めない** (`.gitignore` で `.triage/` 除外済みの想定)
- 提案文面に生のユーザー発話を貼らない。要約のみを書く

### 3. 重複回避

`Step 3` の重複チェックで既存ルールがある場合、必ず**統合する**こと。同じ趣旨のルールを複数箇所に並べると CLAUDE.md が肥大化し、優先順位もブレる。

### 4. 文面のスタイル

追記先 (CLAUDE.md / SKILL.md) の既存文体に合わせる。多くの利用環境では以下の Markdown スタイルが採用されているので、特別な指示がなければ準拠する:

- 段落内で改行しない (1 段落 = 1 行)
- 強調記号 `**...**` を改行で分断しない、内側に空白を入れない
- 箇条書きは `-` を使う

追記先ファイル冒頭または同じリポ内に独自の Markdown スタイル指示があればそちらを優先する。

## 既存資産との連携

- `commit-message.md`: コミットメッセージのスタイル(コミット作成時にユーザーが従う)
- `commit-commands` plugin の `/commit`: 編集後のコミット作成
- `worktree` skill: 別リポ作業を隔離環境で行いたい場合
- `discover-signals`: この skill の入力を生成する前段

## このフローを動かさない時

- 採用候補が 0 件 = `discover-signals` の段階で何も拾えなかった = OK、何もしない
- 候補があってもユーザー承認が `skip` = 何もしない
- ファイル編集失敗(Edit が old_string にマッチしない等) = 該当シグナルだけ未適用扱いにし、報告に含める
