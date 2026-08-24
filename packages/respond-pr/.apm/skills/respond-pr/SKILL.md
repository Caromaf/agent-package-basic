---
name: respond-pr
description: "GitHub PR のレビュースレッドを状態分類し、各スレッドへ返信する skill。コード修正後は再確認待ちとして unresolved のまま残し、自動 resolve された場合も `unresolveReviewThread` で open に戻す。修正不要・質問回答のみの場合だけ `resolveReviewThread` を実行する。`gh` CLI に相当コマンドがない GraphQL 操作と、actionable のみを再処理するループを扱う。SKIP: 自分が PR を review する側（「この PR を review してほしい」「コードの気になる点を指摘して」）は review-pr / codex-review 側。PR 作成・マージ・レビュアー指名も別スキル。"
argument-hint: "[<PR Number or URL>] — 省略時はカレントブランチの PR"
allowed-tools: Bash(gh pr view:*), Bash(gh pr checks:*), Bash(gh pr diff:*), Bash(gh api:*), Bash(git status:*), Bash(git log:*), Bash(git diff:*), Bash(git fetch:*), Bash(git pull:*), Bash(git push:*), Bash(git switch:*), Bash(git checkout:*), Bash(git add:*), Bash(git commit:*), Bash(git rev-parse:*), Bash(git merge-base:*), Bash(make:*), Bash(mise:*), Bash(date:*), Bash(cat:*), Bash(ls:*), Bash(cd:*), Bash(bash ~/.claude/skills/respond-pr/scripts/*.sh), Bash(~/.claude/skills/respond-pr/scripts/*.sh), Bash(bash ~/.agents/skills/respond-pr/scripts/*.sh), Bash(~/.agents/skills/respond-pr/scripts/*.sh), Bash(~/.claude/skills/respond-pr/scripts/unresolve_thread.sh:*), Bash(~/.agents/skills/respond-pr/scripts/unresolve_thread.sh:*)
---

# PR レビュー対応スキル

Pull Request に付いたレビューコメントをスレッド単位の work unit として扱い、**妥当性判断 → 必要な対応 → 返信 → 条件付き resolve** のサイクルを行うスキル。コードを修正したスレッドは、レビュワーが再確認できるよう unresolved のまま残す。

## なぜこのスキルがあるのか

普通にコードを直して push するだけだと、以下のような見落としが起きる：

- **コード修正はしたが、スレッドに返信を残さない** → レビュアーは「見てくれた？」となる
- **コード修正はしたが、スレッドが未解決のまま放置される** → 返信に commit と検証結果を含め、レビュワーが再確認できる状態にする
- **対応不要と判断したがコメントしない** → レビュアーに理由が伝わらない
- **修正後に新しいレビューが付いたのに気づかない** → CI が追加レビューをトリガーする環境で発生

このスキルは上記を「各スレッドに必ず返信する」「修正したスレッドは resolve せず再確認を待つ」という workflow で防ぐ。修正不要または質問への回答だけで会話が完了した場合に限り、返信後の resolve を行う。

## 前提条件

- `gh` CLI が認証済み
- 対象リポジトリへの write 権限
- カレントブランチに対応する PR が存在する（または PR 番号が明示されている）

## Loop 実行ガード

自動実行から呼ばれた場合は、bot / 自分のレビューコメントだけを自律処理してよい。人間レビュアーの Major / Critical、仕様判断、スコープ拡大、破壊的変更は必ず停止して人間に渡す。

- 最大 2 周まで実行する。push 後に同じ指摘が再発したら停止する。
- 1 周で処理する未解決スレッドは最大 20 件までにする。超える場合は優先度付きで報告する。
- PR の目的と無関係な問題を見つけても直さない。後続 Issue 候補として報告する。
- 最後に未 resolve 件数、CI 状態、停止理由を必ず報告する。
- 可能なら Issue に PR 番号、処理スレッド数、commit、残件を追記する。
- run 開始時に `REVIEWED_THREAD_IDS=()` を初期化し、コード修正・部分対応・判断保留を行った thread ID をこの配列へ追加する。再列挙結果に依存せず、CI 待機後と完了報告直前に配列の全 ID を個別再照会する。

## ワークフロー概要

```text
┌───────────────────────────────────────────┐
│ 1. 対象 PR を特定                          │
│ 2. 未 resolve のレビュースレッドを列挙     │
│ 3. 各スレッドに対して:                     │
│    a. 妥当性判断                           │
│    b-1. 妥当 → 1 thread 単位で修正 → commit │
│    b-2. 不要/質問回答 → 理由を明確化       │
│    c. commit/push 後にスレッドへ返信        │
│    d. 修正なしの場合だけ resolve            │
│ 4. 再度スレッド一覧を取得                  │
│    新規レビューがあれば 2. に戻る          │
│    無ければ完了（再確認待ち open は報告）   │
└───────────────────────────────────────────┘
```

## ステップ詳細

### 1. 対象 PR を特定

ユーザーが PR 番号を指定していればそれを使う。指定がなければカレントブランチから特定する。

```bash
# 引数で指定された場合
PR_NUMBER=13

# カレントブランチから特定（このコマンドは現ブランチの PR を返す）
PR_NUMBER=$(gh pr view --json number --jq '.number')
```

特定できなかったら skill を終了し、ユーザーに「対象 PR を教えてください」と聞く。

### 2. 未 resolve スレッドを列挙

**重要**: `gh pr view --comments` は body しか返さず `isResolved` を含まない。必ず GraphQL の `reviewThreads` を使う。

```bash
gh api graphql -f query='
{
  repository(owner: "OWNER", name: "REPO") {
    pullRequest(number: PR_NUMBER) {
      reviewThreads(first: 100) {
        pageInfo { hasNextPage }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 100) {
            pageInfo { hasNextPage }
            nodes {
              author { login }
              body
              createdAt
              url
            }
          }
        }
      }
    }
  }
}' | jq '
  if (.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage or
      ([.data.repository.pullRequest.reviewThreads.nodes[].comments.pageInfo.hasNextPage] | any))
  then error("reviewThreads or comments exceeded 100 items; stop and rerun with pagination or handle manually")
  else .
  end'

# reviewThreads または各スレッドの comments が 100 件を超える場合は、
# 見落としを避けるため処理を停止し、ページング対応後に再実行する。
```

そして `isResolved == false` のスレッドだけを候補にする。`isOutdated` は無視する（コードが変わっていても会話は未解決というケースが多い）。各候補は `actionable`、`awaiting-re-review`、`no-change-resolvable`、`blocked` のいずれかに分類し、`actionable` だけをこの周回の処理対象にする。`list_unresolved_threads.sh` を使う場合は、各スレッドの全コメントまたは `lastCommentAuthor`、`lastCommentBody`、`lastCommentCreatedAt` を使って分類する。

| 状態                   | 判定                                                                                 | ループでの扱い                                |
| ---------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------- |
| `actionable`           | レビュワーの最新コメントが未対応の指摘・質問で、修正または明確な返信が必要           | Step 3 で処理する                             |
| `awaiting-re-review`   | こちらがコード修正・部分対応・判断保留を返信して push 済みで、レビュワーの再確認待ち | 再処理しない。open のまま報告する             |
| `no-change-resolvable` | 修正不要または質問回答のみで会話が完了し、返信後に resolve できる                    | 初回分類で返信して resolve する。再周回しない |
| `blocked`              | 人間の仕様判断、Major / Critical、権限、または追加情報が必要                         | 処理を止め、ユーザーへ報告する                |

自分のログイン名は `gh api user --jq .login` で取得し、最新コメントの author と返信履歴を照合する。自分の修正返信が最新なら `awaiting-re-review` として扱う。状態を判定できない場合は安全側に `blocked` とし、同じ open スレッドを次の周回で重複処理しない。

初回分類では `actionable` と `no-change-resolvable` をそれぞれ処理してよい。ただし push や返信後に再取得するループでは、新たに現れた `actionable` だけを対象にし、`awaiting-re-review` と既処理の `no-change-resolvable` は再処理しない。

### 3. 各スレッドを処理

#### 3a. 妥当性判断

コメント本文を読み、以下のどれに該当するかを判断する：

| 判定                 | 基準                                                                   | アクション                           |
| -------------------- | ---------------------------------------------------------------------- | ------------------------------------ |
| **Major / Critical** | アーキテクチャ変更、API 破壊、依存追加、ユーザー体験に影響する挙動変更 | **必ずユーザーに確認**してから進める |
| **Minor / Nit**      | typo、ドキュメント微修正、コメント、軽い refactor、ログ改善            | 自律的に判断して OK                  |
| **不要**             | 既に別の方法で解決済み、既存の設計意図と合わない、誤読による指摘       | 理由を明文化してユーザーに確認       |

bot レビューでは本文先頭に priority / severity (🔴 Major, 🟡 Minor など) が書かれていることが多いので、判断の**参考**にする。

自動実行では、bot の不要指摘は独立検証の証拠を返信して resolve してよい。人間レビュアーの不要指摘は返信案だけ作り、resolve せず停止する。人間レビュワーへの resolve は既存方針どおり、ユーザー確認または相手の判断に委ねる。

##### **必ず独立検証してから判断する**

bot の主張は **古い情報に基づくことが多い**。手を動かす前に、指摘内容を独立して再現・検証する：

- **依存バージョンの指摘** (`package.json` / `pyproject.toml` など): 変更前に必ず現行版の実態を確認する。
  - 例: `npm view @typescript-eslint/parser@<current> peerDependencies`
  - 例: `pip show <pkg>` / `cargo search <crate>`
  - 特に「peer range 外」「deprecated」系は、bot が古いメタデータを見ている可能性が高い。
- **レビュー本文にシェルスクリプトが含まれる場合** (CodeRabbit や codex-connector): **そのスクリプトをそのまま実行** して出力を確かめる。bot が結論を見落としているケースもある。
- **「本当にこのリポジトリで壊れているか」** を確かめる。論理上の整合性ではなく、**実際のビルド・テストが red になるか** を基準にする。

検証結果が bot の主張と食い違った場合、**修正せずに「確認した結果、問題ありません」** と返信し、bot の指摘で会話が完了した場合だけ resolve する。PR に不要な差分を足さない方が価値が高い。

#### 3b-1. 妥当 → 修正 → commit → push

各未解決スレッドを独立した work unit として処理する。原則として 1 thread → 1 commit → 1 reply とし、次のスレッドの修正を同じ commit に混ぜない。

1. 指摘箇所を `Read` で確認
2. `Edit` で修正
3. テスト・lint を実行（プロジェクトの方法を自動検出。例: `mise run test`、`uv run pytest`、`npm test`、`cargo test` など）
   - 失敗したら修正を続ける。ユーザー判断が必要なら一度止める
4. このスレッドの修正だけを 1 コミットにまとめる
5. commit メッセージは日本語で簡潔に書く。**「〜のレビュー対応」だけではなく、何を直したかを書く**
   - 悪い例: `"PR レビュー対応"`
   - 良い例: `"hook のタイムアウトと OSError ハンドリングを追加"`
6. `git push` で同一ブランチに push
7. commit SHA、変更概要、検証結果を含む返信を投稿する。コード修正、部分対応、判断保留のスレッドは、push 後も **resolve しない**。
8. `REVIEWED_THREAD_IDS+=("$THREAD_ID")` として run 内の再確認対象へ追加する。再列挙でスレッドが resolved 扱いになり一覧から消えても、この配列から除外しない。

複数スレッドが同一の不可分な修正を要求している場合に限り、同じ commit を共有してよい。その場合も各スレッドへ個別に返信し、同じ commit を共有する理由を明記する。

#### 3b-2. 修正不要 → 理由を明確化

以下のどれかに当てはまることを確認：

- 既存の設計意図と矛盾する（「この実装は意図的」）
- 別の場所で既に解決済み（「〜の箇所で対応済み」）
- コストに見合わない（「影響範囲が小さく、修正コストと釣り合わない」）
- 誤読による指摘（「このコードは実際には〜なので問題ない」）

必ず具体的な理由を用意する。定型文「問題ありません」では伝わらない。修正不要または質問への回答のみで会話が完了した場合は返信後に resolve してよい。部分対応や判断保留は返信後も unresolved のまま残す。

#### 3c. スレッドに返信コメント

**これが一番抜けやすいステップ**。修正した場合でも、不要と判断した場合でも、必ず返信を残す。

返信は `gh api` でスレッドに対して post する：

```bash
# review comment に reply するには、元コメントの id が必要
gh api --method POST \
  "repos/OWNER/REPO/pulls/PR_NUMBER/comments/COMMENT_ID/replies" \
  -f body="..."
```

返信の書き方：

| 状況     | 返信例                                                                  |
| -------- | ----------------------------------------------------------------------- |
| 修正した | `ご指摘ありがとうございます。〜の commit (SHA) で対応しました。` + 補足 |
| 修正不要 | `ご指摘ありがとうございます。〜の理由でこの実装を維持します。`          |
| 部分対応 | `〜の部分は反映しました。〜は別 PR で扱います（理由: XXX）。`           |

#### 3d. 修正なしの場合だけ resolveReviewThread で resolve

コード修正、部分対応、判断保留のスレッドにはこの操作を行わない。修正不要または質問への回答のみで会話が完了し、resolve が適切なスレッドに限って実行する。
**`gh` CLI には resolve コマンドが無い**ので、GraphQL で叩く。`scripts/resolve_thread.sh` を使うか、以下を直接実行：

```bash
gh api graphql -f query='
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { isResolved }
  }
}' -f threadId="$THREAD_ID"
```

返り値が `isResolved: true` になっていることを確認する。人間レビュワーのスレッドは、既存方針どおりユーザー確認または相手に委ねる。

コード修正・部分対応・判断保留のスレッドについて、返信または push 後に対象 thread の `isResolved` を再取得する。bot の自動処理などで `isResolved: true` になっていた場合は、直ちに `unresolve_thread.sh "$THREAD_ID"`（または `unresolveReviewThread` mutation）を実行し、返り値が `isResolved: false` であることを確認する。修正済みスレッドを自動 resolve された状態のまま完了にしてはならない。

```bash
gh api graphql -f threadId="$THREAD_ID" -f query='
query($threadId: ID!) {
  node(id: $threadId) {
    ... on PullRequestReviewThread { isResolved }
  }
}' --jq '.data.node.isResolved'

bash ~/.agents/skills/respond-pr/scripts/unresolve_thread.sh "$THREAD_ID"
```

CI 待機後（通常は push から 1〜2 分後）に `REVIEWED_THREAD_IDS` の全 ID を個別に再照会する。再照会は再列挙 query とは独立して行い、`isResolved: true` なら `unresolve_thread.sh` を実行して `false` を確認する。thread が未解決一覧から消えていても、ID が取得できる限りこの確認を省略しない。

### 4. 新規レビューの検知 → actionable だけをループ

push すると CI 経由で新しい bot レビューが付くことがある（CodeRabbit は push 毎に再レビューする）。処理したスレッドの状態と新しい未解決スレッドを確認するため、もう一度 Step 2 のクエリを叩く。

- 新しい `actionable` があれば → Step 3 に戻る
- `awaiting-re-review`、`no-change-resolvable`、`blocked` だけが残っている場合は Step 3 を繰り返さない
- 増えていなかったら → 完了報告（resolve した件数と、修正後の再確認待ちで open の件数を分けて報告）

無限ループ防止のため、**同じ内容のレビューが繰り返し付く場合は 2 周目で止めてユーザーに相談する**。

新しい actionable の処理が終わったら、完了報告を作る直前に `REVIEWED_THREAD_IDS` の全 ID をもう一度個別再照会する。コード修正・部分対応・判断保留の ID は `isResolved: false` を確認できるまで完了扱いにせず、true の場合は unresolve してから報告する。各 ID の最終状態（false の再確認済み、または照会不能で blocked）を完了報告に記載する。

## 重要な注意点

### GraphQL 必須の操作

以下は `gh` CLI のサブコマンドが無いため、GraphQL 経由で叩く必要がある：

- `reviewThreads` の取得（`isResolved` を含む）
- `resolveReviewThread` mutation
- `unresolveReviewThread` mutation

`scripts/resolve_thread.sh`、`scripts/unresolve_thread.sh`、`scripts/list_unresolved_threads.sh` に便利スクリプトを用意してある。

### bot の違い

| bot                | 修正後の自動 resolve                           | 備考                                                    |
| ------------------ | ---------------------------------------------- | ------------------------------------------------------- |
| CodeRabbit         | ✅ 自動で resolve してくれる                   | `fix committed` のような返信にすると resolve する       |
| Gemini Code Assist | ❌ 自動 resolve しない                         | 修正なしで会話が完了した場合だけ明示的に resolve する   |
| CodeX              | 状況による                                     | 修正したスレッドは unresolved のまま再確認を待つ        |
| 人間レビュアー     | ❌ レビュアー自身が resolve するのが本来の流儀 | 返信だけして resolve は相手に任せるのが無難な場合もある |

**人間レビュアーのコメントに対しては、返信を残した後 resolve するかはユーザーに確認する**。コード修正・部分対応・判断保留の場合は確認を待たず unresolved のまま残し、修正不要または質問回答のみの場合も自分から resolve せず、相手に委ねることができる。

### push 後の CI レース

push 直後に CI が走り始め、新しい bot レビューが数分後に付くことがある。Step 4 のループでスレッドを再取得するタイミングは、push から少なくとも 1〜2 分は待つのが良い。待たない場合は「CI 完走後に再チェック」とユーザーに伝えて一旦止める。

### 既に別の the agent が対応している場合

たまに「別のセッションが同じ PR を触っている」ことがある。最初に `git log origin/<branch> -5` でリモートの最新コミットを確認し、**自分のローカル作業より先に進んでいたら一度 pull してから判断する**。diverged なら skill を止めてユーザーに報告。

### Scope 判断 — レビューに無い別の問題を見つけたら

レビュー対応中に、**コメントに含まれない別の問題**（CI が既に red、別の deprecation warning、他ファイルの lint 違反など）を発見することがある。判断基準：

- **PR のスコープに直接関係する**（例: PR で入った変更が原因で CI が red になっている）→ 同じ commit にバンドルして修正して OK。commit メッセージで「＋ついでに〜も修正」と明示する。
- **完全に別件**（無関係な依存更新、別ファイルの refactor、TODO 消化）→ **絶対に触らない**。ユーザーに「この問題を見つけたが別 PR にしますか？」と報告して判断を仰ぐ。
- **グレー（直接関係と断言できないが近い領域）**→ 1 コミットに押し込むのではなく、**同じ PR に別 commit** として分ける。レビュアーが diff を追えるようにする。

原則：**PR の本来の目的を膨らませない**。skill の価値は「レビューを完走する」ことで、「ついでにリファクタする」ことではない。

## 完了報告の形式

skill 完走時は以下を報告する：

```text
## PR #N レビュー対応完了

- 処理したスレッド数: X
  - 修正対応: Y スレッド (commit SHA の一覧)
  - 修正不要: Z スレッド (判断理由付き)
- 追加 push: N commits
- resolve 済み: R スレッド (修正不要または質問回答のみ)
- 再確認待ち open: O スレッド (コード修正・部分対応・判断保留。レビュワーの再確認が必要)
- 人間レビュアー: H スレッド (返信済み、resolve はユーザー確認または相手に委ねる)
- CI 状況: ALL GREEN / 〜 待ち
```

## 参考スクリプト

配備先は Claude Code なら `~/.claude/skills/respond-pr/scripts/...`、Codex CLI / Gemini CLI なら `~/.agents/skills/respond-pr/scripts/...` を使う。

- `list_unresolved_threads.sh <pr-number> [owner/repo]` — 未 resolve スレッドを JSON で出力
- `reply_to_thread.sh <pr-number> <first-comment-database-id> <body> [owner/repo]` — スレッドに返信
- `resolve_thread.sh <thread-node-id>` — スレッドを resolve
- `unresolve_thread.sh <thread-node-id>` — 自動 resolve されたスレッドを unresolved に戻す

これらは GraphQL / gh api のラッパー。直接呼んでも良い。
