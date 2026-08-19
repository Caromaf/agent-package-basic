---
name: npm-supply-chain-triage
description: npm / pnpm / yarn のサプライチェーン侵害（Shai-Hulud 系ワーム、IoC 付き侵害パッケージの公開、悪性版の混入等）に関するニュース記事を受け取り、このリポジトリに対応が必要かを調査する必要があるときに使用する。
---

# npm サプライチェーン侵害トリアージ

npm サプライチェーン侵害のニュース記事を読んで、このリポジトリに実害があるか、緊急対応（クレデンシャルローテーション等）が必要かを再現可能な手順で判定する。

## 判定の 3 層構造

「対応が必要か」は次の 3 層すべてで判定する。依存グラフ照合だけで答えを返してはいけない。

1. 依存グラフ照合（lockfile の解決版 vs 公式 IoC リスト）
2. 取得痕跡の実測（パッケージマネージャのキャッシュ / store / 実展開物）
3. 端末側 IoC スキャン（dropper 痕跡・IDE 永続化・C2 文字列・exfil repo）

3 層すべてを終えたら、結論として「緊急対応（クレデンシャルローテーション）の要否」を明示する。

## Step 1: IoC リストの取得

記事本文に列挙されたパッケージ一覧は抜粋であることが多い。実例として Wiz blog は 43 件掲載だったが、ベンダの IoC repo の実体は 443 件だった。記事の一覧だけで判定を確定させず、必ずベンダの IoC repo から全リストを取得する。

- `https://api.github.com/repos/wiz-sec-public/wiz-research-iocs/git/trees/HEAD?recursive=1` で `reports/*.csv` を探し、`raw.githubusercontent.com` から取得する
- CSV 形式は `Package,Malicious Versions` で、versions は `"1.1.7, 1.1.8"` のようにカンマ区切り引用符付き

記事が複数ある場合は日本語記事（Flatt Security 等）とベンダ記事（Wiz 等）の両方を読む。日本語記事は対応指針が充実している傾向があり、ベンダ記事は IoC と全リストが正確な傾向がある。侵害の発生日を必ず確定すること。同じパッケージ名（例: keyv）の侵害は複数回起きうるので、年月日を取り違えると照合すべきバージョンが変わる。

## Step 2: lockfile 照合スクリプト（pnpm）

pnpm lockfile の `packages:` セクションが全解決版の正本であり、2 スペースインデントの `name@version:` キーを拾う。以下の正規表現は実際に動作確認済みなのでそのまま使う。

```python
key_re = re.compile(r"^  '?((?:@[^/']+/)?[^@'/][^@']*)@([^':()]+)'?(?:\([^)]*\))*:\s*$")
```

- scoped 名（`@cacheable/utils`）とクォート付きキーの両方に対応する必要がある
- `snapshots:` セクションは peer 修飾子付きキーがあり一部一致しないが、`packages:` を全件取れていれば判定には十分
- パースの網羅率を数えて `packages:` セクション行数に対する一致件数が 100% であることを確認する。ここが 100% でないと「該当なし」が静かな取りこぼしに化ける。網羅率を出力するコードを含めること
- monorepo で lockfile が複数ある場合は全部を個別に照合する。ワークスペースごとに独立した lockfile がありうる

## Step 3: 変異テスト（必須）

「一致 0 件」は検知が動いていない場合と区別できないので、既知の悪性版を lockfile のコピーに注入して検知されることを確認する。

- lockfile を `/tmp` にコピーし、既存エントリを悪性版に書き換える（例: `keyv@4.5.4:` を `keyv@6.0.0:` に変更）
- scoped パッケージと、元々存在しないパッケージの両方を注入する（`@cacheable/utils@2.5.1`, `cache-manager@7.2.10`）。scoped 名は正規表現から漏れやすいため両方試す
- 注入した全件が検出されることを assert する。検出漏れがあれば正規表現を直す

## Step 4: 取得痕跡の実測（pnpm）

lockfile に無くても侵害期間中に install していれば取得の可能性がある。次を確認する。

- `~/.cache/pnpm/v11/metadata/registry.npmjs.org/<pkg>.jsonl` と `metadata-full/` の同名ファイル。JSONL の各行の `versions` キーに悪性版が記録されているか（悪性版が takedown 済みなら記録されない。これは取得していない証拠になる）
- `~/.local/share/pnpm/store/v*/index/**/<pkg>@<ver>.json` の存在（store path は `pnpm store path` で取得）
- `node_modules/.pnpm/` の実際の展開版を `ls | rg '^<pkg>@'` で確認する。lockfile と乖離しうる
- `node_modules` と `.modules.yaml` の mtime を侵害開始時刻と比較し、そもそも侵害後に install したのかを判断する。侵害前の install なら 2 層目以降は不要になる
- 侵害開始後の lockfile 変更 commit を `git log --since=<侵害日>` で洗い、実際に何が bump されたか差分を見る
- CI でも install が走るので `gh run list` で侵害期間中の実行を確認する

npm / yarn の場合も同様の考え方で `package-lock.json` の `packages` / `dependencies` や yarn.lock を辿る（この skill で実測したのは pnpm のみで、npm / yarn は未検証）。

## Step 5: 端末側 IoC スキャンと false positive の罠

この節は特に丁寧に扱う。今回の調査で一番危なかった箇所である。

- ファイル名一致だけで感染判定してはいけない。Mini Shai-Hulud 系のペイロードは実在パッケージのファイル名を借用する。`Math_Symbol.js` は `regenerate-unicode-properties/General_Category/` に正規ファイルとして存在する（1038 バイト, SHA1 `a275055aabffc662bf000137164f8ff11446ed8c`）。悪性版は 728KB（SHA1 `35a672cf34b996b91f3e1c28cbf3a05a37e036e4`）。判定はパス（侵害パッケージ直下の `node_modules/<pkg>/` か）とサイズ・ハッシュで行う
- IoC 文字列を grep する前に canary ファイルで自分のパターンが実際にマッチすることを確認する。`rg` が除外設定や timeout で空振りしても検出ゼロと区別できない。`printf 'x npm-cache.com y\n' > /tmp/canary.txt` して引っかかることを確認してから本番の検索に進む
- 自分が保存した記事テキスト自身が IoC 文字列でヒットする。調査中に記事を `/tmp` や tool-results に保存すると C2 ドメインを含むため、ヒットしたファイルのパスを必ず確認する
- 広範囲の `rg` / `fd` は timeout しやすい。`node_modules` を除外して設定ファイル・hook 系に絞る、対象ディレクトリを列挙する等で完走させる。timeout（exit 124）を「検出ゼロ」と読み違えないこと
- 確認する痕跡: `bun` バイナリ（`which bun`, `~/.bun`, `/tmp/bun-dl-*`）、ペイロードのロックファイル、`node_modules/<pkg>/Math_Symbol.js`、`math_init.js`
- IDE 永続化: 最近の worm は `~/.claude/settings.json` の hooks と `.vscode/tasks.json` に永続化する。窃取対象に Claude Code / Codex / Cursor の認証情報が含まれる。hooks は正規のものと区別が必要なので中身を目視で確認する
- exfil 先: 侵害アカウント配下に public repo を作って送出する。`gh repo list --json name,createdAt,description` で侵害日以降の新規 repo と、特徴的な description（例: `Shai-Hulud: Here We Go Again`）を確認する

## Step 6: provenance を判定に使わない

侵害版が正規の CI/CD（GitHub Actions）経由で publish されると有効な npm OIDC provenance が付く。「provenance があるから安全」は今回のような CI 侵害では成立しない。効くのは検疫期間と lifecycle script の無効化である。

## Step 7: 防御の評価と推奨

調査の締めとして、そのリポジトリの既存防御を評価する。

- Dependabot `cooldown: default-days` / Renovate `minimumReleaseAge` はいずれも bot 経由の更新にしか効かない
- pnpm 11 の `minimumReleaseAge` は `minimumReleaseAgeStrict: true` がないと検疫にならない。新しすぎる版を拒否せず `minimumReleaseAgeExclude` を自動追記して通してしまう。この対照実験を今回行い確認した事実を根拠として示す。
  - 未設定側の出力: `Added 1 entry to minimumReleaseAgeExclude in pnpm-workspace.yaml (set minimumReleaseAgeStrict to true to gate these updates with a prompt)`
  - strict 側の出力: `[ERR_PNPM_NO_MATURE_MATCHING_VERSION] 1 version does not meet the minimumReleaseAge constraint`
  - 検証方法: `/tmp` に空プロジェクトを 2 つ作り、片方だけ `minimumReleaseAgeStrict: true` にして、publish 直後の版（age < 24h）を `pnpm add -D --lockfile-only` する。成熟版（age 279h）は strict でも exclude 追記なしで通るので誤検知はしない
- lifecycle script の制御: pnpm の `allowBuilds`（旧 `onlyBuiltDependencies`）、`--ignore-scripts`、npm v12 は既定で lifecycle script を無視する
- `--frozen-lockfile` による integrity 固定
- 副作用的な防御にも言及する。major 更新を Dependabot で ignore していると、悪性版が新しい major 系にしかない場合に結果的に守られることがある

## Step 8: 報告テンプレート

「調べて」の答えは「該当なし」ではなく「緊急対応が不要である根拠」であるべきである。結論を先頭に置き、以下の型で報告する。

```markdown
## 結論

- 影響の有無: なし / あり（詳細）
- 緊急対応（クレデンシャルローテーション）の要否: 不要 / 必要（理由）

## 照合結果

| レイヤー | 対象 | 結果 | 備考 |
| --- | --- | --- | --- |
| 依存グラフ照合 | lockfile 全ファイル | 一致 0 件（網羅率 100%） | |
| 取得痕跡 | cache / store / node_modules | 痕跡なし | |
| 端末 IoC スキャン | dropper / hooks / exfil repo | 痕跡なし | |

## 陰性だった IoC 項目

- ...

## なぜ防げたか

- ...

## 任意の強化余地

- [ ] ...
```
