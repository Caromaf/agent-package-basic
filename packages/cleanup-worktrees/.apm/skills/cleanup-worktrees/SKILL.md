---
name: cleanup-worktrees
description: git worktree / ローカルブランチ / リモート追跡参照の滞留を診断し、base ブランチにマージ済みの残骸を安全に削除する。PR マージ後のクリーンアップ、`git worktree list` が肥大したとき、`: gone]` ブランチが溜まったときに使用する。dry-run で分類表を提示してからユーザー承認を取り、未マージ・未コミット作業は保護する。
---

# cleanup-worktrees

`git worktree` を多用する運用 (the agent の worktree 分離機能、codex CLI の worktree、手動 `git worktree add`) では、**マージ後も worktree とブランチが残り続ける**。作成者が消す責務を持たないため放置され、`git worktree list` が数十行になり数百 MB を消費する。

本 skill は「消してよいもの」を機械的に判定し、判断が必要なものだけ人間に回す。

## 設計方針

**削除の可否は 4 つの事実だけで決まる。** 推測を混ぜない。

| 事実                      | 取得方法                                        | 意味                             |
| ------------------------- | ----------------------------------------------- | -------------------------------- |
| マージ済みか              | `git merge-base --is-ancestor <head> <base>`    | 成果が base に取り込まれているか |
| 未コミット変更の**中身**  | `git status --porcelain` + `git diff --numstat` | 失う作業があるか                 |
| worktree に checkout 中か | `git worktree list --porcelain` の `branch`     | ブランチ削除が可能か             |
| locked か                 | 同上の `locked` 行                              | 他セッションが使用中の宣言       |

### 安全側に倒す判定

- **squash merge / rebase merge されたブランチは `--is-ancestor` が false になる**。この場合「未マージ」と判定して**残す**。誤って残すのは無害だが、誤って消すと復旧が要る。判定漏れを疑うときは `gh pr list --state merged --head <branch>` で PR 側を確認して個別に消す。
- **`base` はデフォルトで `origin/HEAD` から自動検出する**。判定前に `git pull` して base を最新にしておくこと。古い base だとマージ済みが未マージに見える。

### dirty の中身を必ず見る

`git status --porcelain` の行数だけで「未コミット作業あり」と判断してはいけない。**ファイルモード変更のみ (`100644` → `100755`) が頻出する**。各 worktree で `mise run` / `npm run` が実行権限を付けた副作用で、内容差分はゼロ行であり失う成果はない。

スクリプトはこれを `dirty_kind` として区別する。判定は `git diff --numstat` の追加/削除行数が全て 0 かで行う。

- `clean`: 変更なし → 削除可
- `mode-only`: モード変更のみ、内容差分 0 行 → **削除可**
- `content`: 内容差分あり / untracked あり / バイナリ (`-`) / status に出て diff に出ない → **保護**

**`git status --porcelain` の出力を `strip()` してはいけない。** porcelain は `XY <path>` 形式でカラム位置に意味があり、内容変更は先頭がスペースの `" M path"` になる。strip するとパス抽出が 1 文字ずれて実在しないパスになり、後続の diff が空になって**内容変更ありの worktree を clean と誤判定する** (本 skill の初版で実際に発生し、内容変更ありの worktree が DELETE 候補に出た)。判定ロジックはパス指定を使わずリポジトリ全体の diff で行うのが安全。

## 引数

```text
cleanup-worktrees [--repo <path>] [--base <branch>] [--allow-locked] [--yes]
```

- `--repo <path>`: 対象リポジトリ。省略時は cwd
- `--base <branch>`: マージ判定の基準。省略時は `origin/HEAD` から自動検出 (通常 `main`)
- `--allow-locked`: locked な worktree もマージ済みなら削除候補に含める (既定は保護)
- `--yes`: dry-run の承認をスキップして全採用 (定期実行用)

## フロー

### Step 1: base を最新にする

判定精度が base の鮮度に依存するので先に更新する。**worktree 内にいる場合は base の worktree で実行する**。

```bash
git -C <repo> fetch --prune origin
```

`fetch --prune` はリモートで消えたブランチの追跡参照も落とすので、`: gone]` 判定が正確になる。

### Step 2: 診断 (削除しない)

```bash
uv run --script "<skill-dir>/scripts/scan_worktrees.py" --repo <repo> --json-out .triage/worktrees-<date>.json
```

`<skill-dir>` は本 SKILL.md のあるディレクトリ。**スクリプトのパスは SKILL.md からの相対** (`./scripts/scan_worktrees.py`) で参照する。配備先は環境ごとに異なる (例: Claude Code なら `~/.claude/skills/cleanup-worktrees/`) ため、絶対パスでハードコードせず SKILL.md の場所から解決する。

スクリプトは worktree / ブランチ / stale remote ref を `DELETE` / `PRUNE` / `KEEP` に分類し、**各判定の理由を必ず添えて**出力する。削除は一切行わない。

### Step 3: ユーザーへ提示

分類表をそのまま見せる。件数が多い場合は `KEEP` の理由ごとに集約してよいが、**`DELETE` は全件列挙する**。

```text
📋 cleanup-worktrees 診断結果

repo: /Users/x/programs/foo   base: main (36cca093)

削除対象 worktree (15):
  DELETE  (detached)                      .codex/worktrees/0da7/foo
          - main にマージ済み
  DELETE  feature/757-clarify-hit-counts  .codex/worktrees/1d9d/foo
          - main にマージ済み
          - dirty はファイルモード変更のみ (作業成果なし)
  ...

保護 (2):
  KEEP    codex/729-patent-indexing-deadlock
          - main にマージされていない (ahead=1)
  KEEP    worktree-issue-888-faker-override
          - locked: claude session (pid 72427)

削除対象ブランチ (3):  ※worktree 削除後に削除可能になる
  DELETE  codex/review-pr760  - main にマージ済み / 上流が削除済み

stale remote refs (2):  git remote prune origin で解消

採否: all / 番号指定 (1,3,5) / skip
```

### Step 4: 削除 (承認された分のみ)

**順序が重要。** worktree がブランチを掴んでいる間は `git branch -d` が失敗するため、必ず worktree → prune → branch の順で行う。

```bash
# 1. worktree を削除。--force は「モード変更のみ」の dirty を通すために必要
git -C <repo> worktree remove --force <path>

# 2. 管理情報から消えた worktree の登録を掃除
git -C <repo> worktree prune

# 3. worktree から解放されたブランチを削除。-d (小文字) で未マージなら失敗させる
git -C <repo> branch -d <branch>

# 4. リモート追跡参照を掃除
git -C <repo> remote prune origin

# 5. 親ディレクトリの空の殻を除去 (worktree が入れ子だった場合は 2 回)
find <worktree-parent> -mindepth 1 -type d -empty -delete
find <worktree-parent> -mindepth 1 -type d -empty -delete
```

**`git branch -D` (大文字) は使わない。** `-d` はマージ済みでなければ拒否するので、スクリプトの判定が間違っていた場合の最後の防波堤になる。`-d` が失敗したら削除せずユーザーに報告する。

`--allow-locked` で locked な worktree を消す場合は先に `git worktree unlock <path>` が必要。

### Step 5: 報告

削除件数、保護した対象とその理由、解放された容量を報告する。**保護した対象は必ず列挙する** — ユーザーがそれらを個別に処理したいことが多い。

```text
📋 cleanup-worktrees 完了

削除: worktree 15 / branch 3 / stale remote ref 2
容量: 555M → 42M

保護:
  codex/729-patent-indexing-deadlock  (未マージ, ahead=1)
  worktree-issue-888-faker-override   (locked: claude session pid 72427)
```

## 重要な注意事項

### 1. 自分がいる worktree は消せない

`git worktree remove` は現在の作業ディレクトリを削除できない。専用の worktree 離脱ツール (例: the agent の `ExitWorktree` 相当機能) が使えるランタイムではそれで抜けてから実行し、無ければ base ブランチの worktree (通常はリポジトリの main 作業ディレクトリ) に `cd` してから実行する。本 skill は必ず base の worktree から実行する。

### 2. `git worktree prune` だけでは足りない

`prune` は**ディレクトリが既に消えている**登録だけを掃除する。実体が残っている worktree には効かないので、個別に `git worktree remove` が必要。「prune したのに減らない」はこれが原因。

### 3. 他プロセスが使用中の worktree

codex CLI や別のエージェントセッションが動作中の worktree を消すと、そのセッションが壊れる。`locked` はその宣言なので既定で尊重する。lock 理由に pid が入っていれば `ps -p <pid>` で生存確認できる。

### 4. detached HEAD の worktree

ブランチを持たない worktree は、HEAD が base の祖先なら安全に消せる (成果は base にある)。ただし**祖先でない detached HEAD は参照する名前がないため、消すと事実上復旧不能**になる (reflog 頼み)。この場合は必ず保護する。

## 関連

- `worktree`: worktree の作成・保持・削除の基本操作
- `delegate-worktrees`: 複数 worktree に並行委譲する運用。本 skill はその後片付け
- `audit-memory`: メモリファイルの削除担当。「追加だけの運用は肥大する」という同じ発想を git 資産に適用したのが本 skill
