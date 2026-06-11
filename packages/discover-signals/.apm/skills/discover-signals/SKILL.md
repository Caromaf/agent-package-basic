---
name: discover-signals
description: Claude Code の会話ログ (`~/.claude/projects/**/*.jsonl`) を走査し、ユーザー訂正・繰り返し指示・ループといった「自己改善のシグナル」を抽出して JSON で書き出す必要があるときに使用する。出力は `triage-improvements` skill が読み取り、CLAUDE.md / SKILL.md への反映提案に使う。loop engineering の学習ループとして、失敗・訂正・繰り返し作業を skill / hook / memory 改善へ戻す場合にも使用する。
---

# discover-signals

Claude Code の会話ログから「次セッション以降のために CLAUDE.md や skill に取り込むべき改善ネタ」を抽出する skill。

`triage-improvements` skill の前段として、人間が選別する候補リストを生成する。

## 目的

- ユーザーが繰り返し言わなくて良いように、行動規則を CLAUDE.md / SKILL.md に育てていく
- 訂正コストの高い箇所をリスト化し、改善 PR の元ネタにする
- 完全自動化は狙わない。**人間が選別する一覧** を出すことに徹する
- loop 実行の失敗を次回の harness / skill / hook 改善へ戻す

## Loop 学習ループ

定期実行では、`discover-signals --days 7 --project <name>` で候補を抽出し、`triage-improvements` に渡す。自動で memory や skill を編集しない。

推奨 cadence:

- 週次: 直近 7 日の user correction / tool loop を抽出する
- 月次: `triage-improvements` と `audit-memory` を組み合わせ、追加と削除をセットで行う
- 大きな loop 失敗後: 該当 project に絞って即時抽出する

## 前提

- [`uv`](https://docs.astral.sh/uv/) が PATH に存在すること。本 skill 同梱のスクリプトは PEP 723 inline script で `uv run --script` を shebang に使う。`command not found: uv` が出た場合は `mise install uv` か `curl -LsSf https://astral.sh/uv/install.sh | sh` で導入してから再実行する。
- 解析対象の `.jsonl` は `~/.claude/projects/**/*.jsonl` に存在する想定 (Claude Code のセッションログ)。

## 入力

```text
discover-signals [--days N] [--project <name>] [--out <path>] [--projects-root <path>]
```

- `--days N`: 過去 N 日分の `.jsonl` を対象にする (デフォルト 7)
- `--project <name>`: 特定プロジェクトのみ対象 (例: `-home-ken-dotfiles`)。省略時は全プロジェクト
- `--out <path>`: 出力先の JSON ファイル。省略時は `<cwd>/.triage/signals-<YYYY-MM-DD>-<HHMM>.json` (同日複数回実行で上書きしない)
- `--projects-root <path>`: `.jsonl` を探すルート (デフォルト `~/.claude/projects`)。Codex CLI / Gemini など別ツールのログ位置が違うときに上書きする

## 出力

JSON ファイル 1 つを書き出す。フォーマット:

```json
{
  "generated_at": "2026-05-29T15:00:00+09:00",
  "scope": {"days": 7, "project": null, "session_count": 12},
  "signals": [
    {
      "id": "sig-0001",
      "kind": "user_correction",
      "session_id": "0c31e19e-...",
      "project": "-home-ken-dotfiles",
      "timestamp": "2026-05-29T14:20:00+09:00",
      "user_message": "違う、それじゃない",
      "preceding_assistant_excerpt": "...",
      "suggested_target": "CLAUDE.md",
      "rationale": "ユーザーが直前のアシスタント応答を否定している"
    }
  ]
}
```

`kind` の種類:

| kind | 検出条件 |
| --- | --- |
| `user_correction` | ユーザー発話に否定的キーワード (「違う」「やめて」「そうじゃない」「やり直し」「stop doing」等) が含まれ、直前 1-3 ターンにアシスタントの編集アクションがある |
| `repeated_instruction` | 同種の文言 (3 文字以上の n-gram 一致) が 3 セッション以上に登場 |
| `tool_loop` | 同一ツールが **3 回連続で is_error=True** を返している (連続失敗の塊。重複呼び出しでも全て成功なら除外) |

## 実行手順

### Step 1: スクリプトを実行

skill 同梱のスクリプトでパース・抽出する。**スクリプトのパスは SKILL.md からの相対** (`./scripts/extract_signals.py`) で参照する。配備先は環境ごとに異なる (Claude Code は `~/.claude/skills/discover-signals/`、Codex CLI 等は別パス) ため、絶対パスでハードコードしない。

`SKILL.md` のあるディレクトリを起点に呼ぶ:

```bash
# 起動例 (cwd は何でも可。スクリプトに引数を渡せば出力先は cwd 配下になる)
uv run --script "<skill-dir>/scripts/extract_signals.py" --days 7
```

`<skill-dir>` はこの SKILL.md がある場所。Claude Code 環境では `~/.claude/skills/discover-signals` に展開されているので、SKILL.md の場所を解決して呼べばよい:

```bash
# Claude Code: 標準配備
~/.claude/skills/discover-signals/scripts/extract_signals.py --days 7

# 別ツールで配備パスが違う場合
uv run --script "$(dirname "$(realpath "$0")")/scripts/extract_signals.py" --days 7
```

セッション件数の概算が必要なときだけ、追加で `find` を使って良い (常用しない。スクリプト本体が同じ走査をやるので二度手間):

```bash
find ~/.claude/projects -name "*.jsonl" -mtime -7 | wc -l
```

### Step 2: ユーザーへの提示

抽出した `signals[]` を以下の形式で要約表示する:

```text
シグナル抽出結果: <件数>件 (期間: 直近 N 日, セッション数: M)

┌────────────────────────────────────────────────
│ # | kind                | session     | 内容
├────────────────────────────────────────────────
│ 1 | user_correction     | 0c31e19e... | 「違う、それじゃない」
│   |                     |             | → 直前の Edit 操作を訂正
│ 2 | repeated_instruction| 5 sessions  | 「日本語で答えて」
│ ...
└────────────────────────────────────────────────

詳細: ./.triage/signals-YYYY-MM-DD-HHMM.json
次のステップ: triage-improvements skill でこのファイルを読み込み、PR 草案を生成できます。
```

### Step 3: triage への引き継ぎ

ユーザーが続行を望む場合、`triage-improvements` skill を起動する案内を出す:

```text
PR 草案を生成するには次を実行してください:

  /triage-improvements --signals ./.triage/signals-YYYY-MM-DD-HHMM.json
```

## 注意事項

- `.jsonl` には機密情報 (トークン、社内 URL 等) が含まれる可能性があるため、出力 JSON にもユーザー発話・アシスタント応答が転記される。生成された `.triage/` 配下は **コミット・公開しない**。`.gitignore` で除外する想定。
- 大量のセッションを処理するときはストリーミング (1 行ずつ JSON parse) で扱う。全行をメモリに載せない。
- 抽出された各シグナルは「候補」であり、確定した改善案ではない。`triage-improvements` の前段で人間レビューが入る前提で動く。
