---
name: cleanup-worktrees
description: "git worktree / ローカルブランチ / リモート追跡参照の滞留を診断し、base ブランチにマージ済みの残骸を安全に削除する。PR マージ後のクリーンアップ、`git worktree list` が肥大したとき、`: gone]` ブランチが溜まったとき、Windows で `worktree remove` が `Filename too long` で失敗して孤児ディレクトリ (husk) が残ったときに使用する。dry-run で分類表を提示してからユーザー承認を取り、未マージ・未コミット作業は保護する。"
---

# cleanup-worktrees

`git worktree` を多用する運用 (the agent の worktree 分離機能、codex CLI の worktree、手動 `git worktree add`) では、**マージ後も worktree とブランチが残り続ける**。作成者が消す責務を持たないため放置され、`git worktree list` が数十行になり数百 MB を消費する。

本 skill は「消してよいもの」を機械的に判定し、判断が必要なものだけ人間に回す。

## 設計方針

**削除の可否は 5 つの事実だけで決まる。** 推測を混ぜない。

| 事実                      | 取得方法                                          | 意味                                     |
| ------------------------- | ------------------------------------------------- | ---------------------------------------- |
| マージ済みか              | `git merge-base --is-ancestor <head> <base>`      | 成果が base に取り込まれているか         |
| 未コミット変更の**中身**  | `git status --porcelain` + `git diff --numstat`   | 失う作業があるか                         |
| worktree に checkout 中か | `git worktree list --porcelain` の `branch`       | ブランチ削除が可能か                     |
| locked か                 | 同上の `locked` 行                                | 他セッションが使用中の宣言               |
| **登録されているか**      | 親ディレクトリの実体 − `git worktree list`        | 登録解除だけ済んだ孤児 (husk) かどうか   |

### 安全側に倒す判定

- **squash merge / rebase merge されたブランチは `--is-ancestor` が false になる**。この場合「未マージ」と判定して**残す**。誤って残すのは無害だが、誤って消すと復旧が要る。判定漏れを疑うときは `gh pr list --state merged --head <branch>` で PR 側を確認して個別に消す。
- **`base` は remote-tracking ref (`origin/main`) を使う。ローカル `main` を基準にしてはいけない。** `git symbolic-ref refs/remotes/origin/HEAD` の末尾セグメントだけを取るとローカルの `main` が解決されてしまい、primary のローカル main が pull されていないと直前にマージされたブランチが「未マージ」と誤判定される (実測: ローカル main が 1 commit 古く、該当ブランチが KEEP に回った)。スクリプトはこれを検出して `warn: ローカル main は origin/main より N commit 古い` を stderr に出す。
- **base を最新にするのは `fetch` だけでよい。`git pull` はしない。** 判定に使うのは `origin/main` なので fetch で十分であり、pull は primary の作業ツリーを勝手に書き換えることになる。
- **`base` を `origin/main` にするとローカル `main` の保護が別途必要になる。** ローカル main は origin より古い = `--is-ancestor` が真 = マージ済み判定になるため、`name == base` の単純比較だけでは**ローカル main 自体が DELETE 候補に出る**。スクリプトは `origin/` と `refs/remotes/` を剥がした名前、`origin/HEAD` が指す default branch、現在の HEAD を常に保護する (`--base develop` のように base を差し替えても main が守られる)。保護した名前は JSON の `protected_branches` で確認できる。

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
- `--base <branch>`: マージ判定の基準。省略時は `git symbolic-ref --short refs/remotes/origin/HEAD` から自動検出 (通常 `origin/main`)。ローカルブランチ名を渡しても対応する `origin/<name>` があればそちらへ読み替える
- `--allow-locked`: locked な worktree もマージ済みなら削除候補に含める (既定は保護)
- `--yes`: dry-run の承認をスキップして全採用 (定期実行用)

スクリプト `scripts/scan_worktrees.py` 自体が取るフラグは `--repo` / `--base` / `--allow-locked` / `--json-out` / `--self-check` である (`--yes` は skill 側の引数でスクリプトには無い)。`--self-check` は husk 検出ロジックの自己診断だけを実行するので、リポジトリを指定せずに動作確認できる。

## フロー

### Step 1: base を最新にする

判定精度が base の鮮度に依存するので先に更新する。**worktree 内にいる場合は base の worktree で実行する**。

```bash
git -C <repo> fetch --prune origin
```

`fetch --prune` はリモートで消えたブランチの追跡参照も落とすので、`: gone]` 判定が正確になる。

**`git pull` は不要かつ禁止。** 判定の基準は `origin/main` なので fetch で足りる。primary の作業ツリーを勝手に進めるのは本 skill の責務外であり、他セッションが primary で作業している可能性もある。

### Step 2: 診断 (削除しない)

```bash
uv run --script "<skill-dir>/scripts/scan_worktrees.py" --repo <repo> --json-out .triage/worktrees-<date>.json
```

`<skill-dir>` は本 SKILL.md のあるディレクトリ。**スクリプトのパスは SKILL.md からの相対** (`./scripts/scan_worktrees.py`) で参照する。配備先は環境ごとに異なる (例: Claude Code なら `~/.claude/skills/cleanup-worktrees/`) ため、絶対パスでハードコードせず SKILL.md の場所から解決する。

スクリプトは worktree / ブランチ / stale remote ref を `DELETE` / `PRUNE` / `KEEP` に分類し、登録が無いのに実体が残っているディレクトリを `HUSK` として別枠で報告する。**各判定の理由を必ず添えて**出力する。削除は一切行わない。

JSON は UTF-8 で書かれる。読み戻すときは `json.load(open(path, encoding="utf-8"))` のように encoding を明示する (Windows で省略すると cp932 として読まれて `UnicodeDecodeError` になる)。

### Step 3: ユーザーへ提示

分類表をそのまま見せる。件数が多い場合は `KEEP` の理由ごとに集約してよいが、**`DELETE` は全件列挙する**。

```text
📋 cleanup-worktrees 診断結果

repo: /Users/x/programs/foo   base: origin/main (36cca093)
  WARN  ローカル main は origin/main より 1 commit 古い。判定は origin/main を基準にする

削除対象 worktree (15):
  DELETE  (detached)                      .codex/worktrees/0da7/foo
          - origin/main にマージ済み
  DELETE  feature/757-clarify-hit-counts  .codex/worktrees/1d9d/foo
          - origin/main にマージ済み
          - dirty はファイルモード変更のみ (作業成果なし)
  ...

保護 (2):
  KEEP    codex/729-patent-indexing-deadlock
          - origin/main にマージされていない (ahead=1)
  KEEP    worktree-issue-888-faker-override
          - locked: claude session (pid 72427)

削除対象ブランチ (3):  ※worktree 削除後に削除可能になる
  DELETE  codex/review-pr760  - origin/main にマージ済み / 上流が削除済み

husk (2):  ※登録解除だけ済んだ実体。マージ判定不可なのでユーザー判断
  HUSK    .codex/worktrees/1816-conversation-config   13225 files / 234M
          - .git が無い: worktree として復帰不能 (マージ判定不可)
          - cache のみ (uv-cache): 削除で失う成果なし
  HUSK    .claude/worktrees/wip-refactor                 412 files / 8M
          - cache 以外のファイルを含む: 未コミット作業が失われる可能性あり

stale remote refs (2):  git remote prune origin で解消

採否: all / 番号指定 (1,3,5) / skip
※ source を含む husk は「all」に含めない。個別に明示承認を取る。
```

### Step 4: 削除 (承認された分のみ)

**順序が重要。** worktree がブランチを掴んでいる間は `git branch -d` が失敗するため、必ず worktree → prune → branch の順で行う。

```bash
# 1. worktree を削除。--force は「モード変更のみ」の dirty を通すために必要
git -C <repo> worktree remove --force <path>

# 2. 実体が残っていないか必ず確認する (Windows では半端に失敗する。後述)
[ -e "<path>" ] && echo "REMAINS: <path>"

# 3. 管理情報から消えた worktree の登録を掃除
git -C <repo> worktree prune

# 4. worktree から解放されたブランチを削除。-d (小文字) で未マージなら失敗させる
git -C <repo> branch -d <branch>

# 5. リモート追跡参照を掃除
git -C <repo> remote prune origin

# 6. 親ディレクトリの空の殻を除去 (worktree が入れ子だった場合は 2 回)
find <worktree-parent> -mindepth 1 -type d -empty -delete
find <worktree-parent> -mindepth 1 -type d -empty -delete
```

最後に **Step 2 の scan を再実行し、`HUSK` が増えていないことを確認する**。増えていれば次項の回収が必要。

#### Windows: MAX_PATH による半端な失敗と回収

pnpm / uv がインストールを済ませた worktree に `git worktree remove --force` を実行すると `error: failed to delete '...': Filename too long` で失敗する。しかし **git は登録解除とファイル削除を分離しており、登録解除だけ済んで実体が残る**。実測では 12 件中 9 件がこうなり、`.git` も消えているため worktree として復帰不可能な孤児ディレクトリ (husk) になった (約 1.4 GB、hardlink 重複排除後)。

`rm -rf` も同じ MAX_PATH で失敗する。長いパスを扱える `robocopy` に空ディレクトリをミラーさせて削除する。

**`robocopy <空> <target> /MIR` は target 配下を全削除する操作である。** この skill で唯一の破壊的コマンドなので、対象パスを手書きせず **Step 2 の scan JSON から供給する**。貼り間違えて main worktree やその親を渡すと、リポジトリ本体が復旧不能に消える。

```bash
JSON=.triage/worktrees-<date>.json
# パス形式を 1 つに寄せる。JSON の path は `C:\...` (バックスラッシュ)、
# git worktree list は `C:/...` (スラッシュ) なので、文字列比較の前に揃える
MAIN=$(cygpath -u "$(git -C <repo> worktree list --porcelain | head -1 | sed 's/^worktree //')")
EMPTY=$(mktemp -d)   # 固定パスを使い回すと前回の残骸が target にコピーされる

# cache のみ / 走査エラーなし / ファイルあり の husk だけを対象にする。
# source を含むものと中身不明なものは個別承認、files=0 は rmdir だけで済む
while IFS= read -r raw; do
  p=$(cygpath -u "$raw")
  # 事前条件 1: main worktree そのもの / その祖先を渡していないか
  case "$MAIN" in "$p"|"$p"/*) echo "ABORT: $raw は main worktree を含む"; continue;; esac
  # 事前条件 2: 区切り文字に依存しない二重防御。git が追跡していれば本体の一部
  git -C <repo> ls-files --error-unmatch -- "$p" >/dev/null 2>&1 && {
    echo "ABORT: $raw は git が追跡している (リポジトリ本体)"; continue; }
  [ -e "$p/.git" ] && { echo "SKIP: $raw は .git を持つ (husk ではない)"; continue; }

  # 何を消すのか先に確認する。/L は 1 バイトも消さずに削除対象を列挙する
  MSYS_NO_PATHCONV=1 robocopy "$(cygpath -w "$EMPTY")" "$(cygpath -w "$p")" \
    /MIR /XJ /L /NFL /NDL /NJH /NJS /NP

  before=$(find "$p" -type f | wc -l)
  MSYS_NO_PATHCONV=1 robocopy "$(cygpath -w "$EMPTY")" "$(cygpath -w "$p")" \
    /MIR /XJ /NFL /NDL /NJH /NJS /NP /R:1 /W:1
  after=$(find "$p" -type f | wc -l)
  echo "$p: files $before -> $after"

  # ファイルが 0 でも rmdir は Directory not empty で失敗する (空の入れ子が残る)
  find "$p" -depth -type d -exec rmdir {} +
  [ -e "$p" ] && echo "殻が残存 (files=$after): $p"
# `jq | while` はパイプでサブシェルになりループ内の集計がループ後に消える。
# プロセス置換で流し込めば件数を Step 5 の報告に使える
done < <(jq -r '.husks[] | select(.has_source == false and .walk_errors == 0 and .files > 0) | .path' "$JSON")
```

**ガードを信じる前に陰性対照を取る。** `case` の比較はパス形式が違うだけで黙って素通りする。実測でこの罠を踏んだ (JSON 側が `C:\Users\...`、`git worktree list` 側が `C:/Users/...` で、main worktree のパスを渡しても ABORT しなかった)。一度だけ次を実行し、**ABORT が実際に出ること**を確かめてから本実行に進む。

```bash
p=$(cygpath -u "$(python -c "from pathlib import Path; print(Path(r'<main-worktree-path>'))")")
case "$MAIN" in "$p"|"$p"/*) echo "ABORT fired (ガードは機能している)";; *) echo "ガードが機能していない";; esac
```

この手順には Windows 固有の罠が 6 つある。**どれも実測で踏んだもので、迂回すると静かに失敗するか、想定外の場所を消す**。

- **空ディレクトリは Bash の `mkdir -p` / `mktemp -d` で作る。** `cmd //c "mkdir ..."` を Bash から呼ぶと cmd の banner を出すだけで実際には作られず、robocopy が `rc=16` で即死する。
- **パスは `cygpath -w` で Windows 形式に変換して渡す。** `MSYS_NO_PATHCONV=1` は**その呼び出しの全引数**の変換を止めるため、`mktemp -d` が返す `/tmp/...` をそのまま渡すと robocopy が先頭の `/` をスイッチと解釈して `ERROR : Invalid Parameter` になる。`cygpath -w` ならバックスラッシュ化も同時に済み、`\` が落ちる問題も起きない。
- **robocopy は Bash から実行する。** PowerShell ツール経由だと `/MIR` を削除対象パスと誤認してコマンドごと拒否される。`MSYS_NO_PATHCONV=1` は MSYS が `/MIR` を `C:/MIR` に変換するのを止めるため。
- **`/XJ` を必ず付ける。** junction (`mklink /J`) は `/XJ` なしだとたどられ、**husk の外にある実体が消える**。Windows の junction は Python の `is_symlink()` でも検出できないため、scan 側も reparse point 属性で判定している。
- **成否は rc ではなく実行前後のファイル数で判定する。** `rc=0` は「対象なし」、`rc=2` は「EXTRA を検出した」であって「削除した」ではない (**1 バイトも消さない `/L` でも rc=2 が返る**)。rc だけ見ると成功と失敗を取り違える。`find` の stderr を `2>/dev/null` で捨てないこと。捨てると MAX_PATH で find 自体が失敗した場合に `0 -> 0` と表示され、「消えた」と「数えられなかった」を区別できなくなる。
- **`Device or resource busy` で残る殻は深追いしない。** 別プロセスが掴んでいるだけで `files=0` なので容量影響はない。

#### `git branch -d` が拒否されたとき

**`git branch -D` (大文字) は使わない。** `-d` はマージ済みでなければ拒否するので、スクリプトの判定が間違っていた場合の最後の防波堤になる。

ただし **`-d` の判定基準は `origin/main` ではなくローカル HEAD / upstream** である。primary のローカル main が古いと、マージ済みブランチが `error: the branch '<branch>' is not fully merged` で拒否される (実測で 1 件発生)。拒否されたら次の順で扱う。

```bash
# 1. origin/main を基準に再確認する
git -C <repo> merge-base --is-ancestor <branch> origin/main && echo MERGED
git -C <repo> rev-list origin/main..<branch>   # 空ならマージ済み
```

`MERGED` かつ `rev-list` が空なら、`-D` に切り替えるのではなく**次のコマンドをユーザーに提示して判断を委ねる**。primary の作業ツリーを勝手に触らないこと。**primary が別のブランチを checkout している場合に `git switch main` を案内してはいけない** — 他セッションが作業中の作業ツリーを奪うことになる。`git -C <repo> rev-parse --abbrev-ref HEAD` で場合分けする。

primary が `main` 以外を checkout しているとき (`fetch` は ref だけを更新し、**どの作業ツリーも触らない**):

````markdown
ローカル main が古いため `git branch -d <branch>` が拒否されました。origin/main を基準にするとマージ済みです。以下は作業ツリーを一切触らずローカル main の ref だけを fast-forward します。

```bash
git -C <repo> fetch . origin/main:main && git -C <repo> branch -d <branch>
```
````

primary が `main` を checkout しているとき (上の `fetch` は `refusing to fetch into branch 'refs/heads/main' checked out at ...` で拒否されるため、作業ツリーごと進める):

````markdown
ローカル main が古いため `git branch -d <branch>` が拒否されました。origin/main を基準にするとマージ済みです。primary で以下を実行すると `-d` のまま削除できます。

```bash
git -C <repo> merge --ff-only origin/main && git -C <repo> branch -d <branch>
```
````

いずれも `--ff-only` / `fetch` の refspec 形式なので、fast-forward できない場合は失敗して止まる。`fetch . <src>:<dst>` が checkout 中のブランチを拒否することは実測で確認済み (rc=128、ref は変化しない)。

`MERGED` にならなければスクリプトの判定が誤っていたということなので、削除せずユーザーに報告する。

`--allow-locked` で locked な worktree を消す場合は先に `git worktree unlock <path>` が必要。

### Step 5: 報告

削除件数、保護した対象とその理由、解放された容量を報告する。**保護した対象は必ず列挙する** — ユーザーがそれらを個別に処理したいことが多い。

```text
📋 cleanup-worktrees 完了

削除: worktree 15 / branch 3 / stale remote ref 2 / husk 9 (1.4G)
容量: 555M → 42M
robocopy で回収: 9 件 (MAX_PATH で登録解除だけ済んでいた分)
殻のみ残存: 2 件 (files=0, 別プロセスが使用中。容量影響なし)

保護:
  codex/729-patent-indexing-deadlock  (未マージ, ahead=1)
  worktree-issue-888-faker-override   (locked: claude session pid 72427)
  .claude/worktrees/wip-refactor      (husk, source を含む → ユーザー判断待ち)
```

## 重要な注意事項

### 1. 自分がいる worktree は消せない

`git worktree remove` は現在の作業ディレクトリを削除できない。専用の worktree 離脱ツール (例: the agent の `ExitWorktree` 相当機能) が使えるランタイムではそれで抜けてから実行し、無ければ base ブランチの worktree (通常はリポジトリの main 作業ディレクトリ) に `cd` してから実行する。本 skill は必ず base の worktree から実行する。

**scan は cwd を考慮しないので、自分がいる worktree も DELETE に出る。** 実測で、worktree 内から実行したセッション自身の worktree が DELETE 候補として並んだ。Step 3 で提示する前に自分の cwd に対応する行を除外し、必要なら「このセッションを終えてから消す」と明記する。

### 2. `git worktree prune` だけでは足りない

`prune` は**ディレクトリが既に消えている**登録だけを掃除する。実体が残っている worktree には効かないので、個別に `git worktree remove` が必要。「prune したのに減らない」はこれが原因。

### 3. 他プロセスが使用中の worktree

codex CLI や別のエージェントセッションが動作中の worktree を消すと、そのセッションが壊れる。`locked` はその宣言なので既定で尊重する。lock 理由に pid が入っていれば `ps -p <pid>` で生存確認できる。

### 4. detached HEAD の worktree

ブランチを持たない worktree は、HEAD が base の祖先なら安全に消せる (成果は base にある)。ただし**祖先でない detached HEAD は参照する名前がないため、消すと事実上復旧不能**になる (reflog 頼み)。この場合は必ず保護する。

### 5. 孤児 (husk) はマージ判定ができない

`git worktree list` は登録分しか列挙しないため、**登録解除だけ済んだ実体は scan からも見えなくなる**。実測では scan が「全件分類済み」と報告した状態で `.codex/worktrees/1816-conversation-config` に 234M / 13225 files の husk が残っていた。スクリプトは worktree の親ディレクトリを走査して登録パスとの差分を取り、これを `HUSK` として報告する。

husk は `.git` を失っているので `merge-base` が使えない。**マージ済みかどうかは原理的に判定できないので `DELETE` に混ぜてはいけない。** 中身の内訳を添えて扱いを分ける。

- **cache のみ** (`uv-cache` / `node_modules` / `.venv` などの下にしかファイルが無い): 失う成果がないので削除してよい
- **source を含む**: 未コミット変更があっても復元できず、削除で永久に失われる。**必ずユーザー判断に回す**
- **走査エラーあり** (MAX_PATH 等で中身を数え切れなかった): 中身不明として source 扱いで保護する
- **ファイル 0 件**: 空ディレクトリの殻だけが残った状態。容量影響はないので `find <path> -depth -type d -exec rmdir {} +` で片付ける (それでも `Device or resource busy` で残るものは深追いしない)

**`source を含む` の大半は 0 バイトのマーカーファイルである。** 実測では 10 件のうち大半が `files: 1, total_bytes: 0, top_entries: [".codex-worktree-name"]` のような worktree 名マーカーのみだった。安全側に倒す設計として正しいが、ユーザーに全件判断させると負荷が高い。Step 3 の提示では `files` と `total_bytes` を必ず添えて、「マーカーのみ」と「実際の作業成果」を見分けられるようにする。

走査候補は**名前が `worktrees` で終わる祖先ディレクトリだけ**に限る (`.claude/worktrees` / `.codex/worktrees` / `<repo>-worktrees`)。「登録 worktree の親なら候補」にすると走査範囲がリポジトリ本体まで広がる: worktree が `<main>/sandbox/wt-1` のようにリポ内の任意のディレクトリ直下にあると `<main>/sandbox` が候補になり、その兄弟である**リポジトリ本体の追跡ディレクトリが husk として列挙される**。`node_modules` だけを含む本体ディレクトリは「cache のみ = 削除可」と表示されてしまう。

**`~/.codex/worktrees` のような共有ストアには別リポジトリの生存中 worktree が混ざる。** 当リポジトリの `git worktree list` に載らないので容れ物として除外されず、husk 候補に入る。入れ子レイアウト (`<hash>/<repo>`) では `.git` が 2 階層下にあるため、深さ 1 しか見ないと「`.git` が無い = 復帰不能な残骸」という**実態と逆の理由**を付けてユーザーに削除判断を求めてしまう。スクリプトは深さ 2 まで `.git` を探し、`gitdir:` の指す先が実在するものを生存中と見なして**候補から除外する** (削除判断を求めること自体が事故の入口)。`gitdir:` の先が消えているものは孤児化した worktree なので husk として報告する。

この制限の代償として、親の名前が `worktrees` で終わらないレイアウト (`~/programs/<repo>-wt-1846`、`<main>/sandbox/wt-1` など) の husk は検出できない。**誤検出の代償が「リポジトリ本体を削除候補として提示する」なので、検出漏れ側に倒している。** 該当レイアウトを使う場合は手動で確認する。

## 関連

- `worktree`: worktree の作成・保持・削除の基本操作
- `delegate-worktrees`: 複数 worktree に並行委譲する運用。本 skill はその後片付け
- `audit-memory`: メモリファイルの削除担当。「追加だけの運用は肥大する」という同じ発想を git 資産に適用したのが本 skill
