# agent-package-basic

汎用の AI agent パッケージ集 (公開可)。Claude Code / Codex CLI / Gemini で
共通利用する skill を、[APM (Agent Package Manager)](https://microsoft.github.io/apm/)
で配布する。各 skill は `/` メニューからスラッシュコマンドとして明示起動することもできる。

## レイアウト

```text
packages/
├── review-pr/                # PR レビュー用の skill
│   ├── apm.yml
│   └── .apm/skills/review-pr/SKILL.md
├── work-loop/                # ai-work / ai-decision の依存・再計画 gate
│   ├── apm.yml
│   └── .apm/skills/work-loop/{SKILL.md,references/,scripts/}
└── <name>/                   # 他のパッケージも同じ形
```

各パッケージは独立した `apm.yml` を持ち、依存側は次のように参照する:

```yaml
# 利用側 (例: ~/dotfiles/agents/profiles/<machine>/apm.yml)
dependencies:
  apm:
    - Caromaf/agent-package-basic/packages/review-pr#v0.1.0
```

`#v0.1.0` の部分は repo の git tag。タグを切ることでマシン横断で
バージョン pin できる。

repo の全 package を一括で取り込む場合 (root `apm.yml` の `dependencies:` ブロック (curated aggregator) 経由):

```yaml
dependencies:
  apm:
    - Caromaf/agent-package-basic#main
```

## インストール (利用者側)

```bash
apm install -g Caromaf/agent-package-basic/packages/review-pr#v0.1.0
```

または `apm.yml` 経由で複数パッケージをまとめて install。

## Work-loop の利用

`work-loop` package は `ai-work` / `ai-decision` Issue の依存と Decision 再計画ゲートを確認する skill と、依存なしの PEP 723 Python CLI を配布する。CLI は読み取り専用で、GitHub CLI (`gh`) と Python 3.12 以上を使う。

```bash
uv run --script "<installed work-loop skill directory>/scripts/work_queue.py" status --repo OWNER/REPO --json
uv run --script "<installed work-loop skill directory>/scripts/work_queue.py" explain 123 --repo OWNER/REPO --json
```

`status` は open な `ai-work` queue と各 gate の `state` / `reason` を表示する。`explain` は正の Issue 番号またはcanonical HTTPS Issue URLだけを受け付け、Issueごとの gateを判定して `ready` / `blocked` / `needs-replan` を返す。repo URLのhost / owner / repoは `gh repo view` のcanonical URLと照合する。未知の形式や GitHub の `blockedBy.nodes` と `totalCount` の不一致は `unknown` として fail-closed に扱う。Skill と CLI の同梱先を基準に script を探し、リポジトリの相対パスは使わない。

Decision Issue は `decision-status` と `decision-revision` を本文に記録し、決定後は `decision-outcome` も記録する。Work Issue には各 Decision の URL・適用済み revision・GitHub `closedAt` を記録する。Decision を close しただけでは Work は再開せず、close 後の再計画記録と `needs-replan` の解除後に依存・再計画 gate が ready になる。`ready` は既存の `ai-auto` / `loop-approved` / Project `Ready` などの Worker 条件を置き換えない。詳細は [Work-loop Issue contract](packages/work-loop/.apm/skills/work-loop/references/issue-contract.md) を参照。

## 開発

このリポジトリは **public** だが、特定マシンからしか push しない運用。
パッケージ追加・修正の流れ:

1. ブランチを切って編集 (main 直 push しない)
   - 新しい package を追加したら、`packages/` に追加するだけでなく、root `apm.yml` の `dependencies.apm` ブロックにも追記すること。追加を忘れると一括取り込みに反映されない。
2. PR を作って merge
3. `git tag vX.Y.Z` してタグ push
4. 利用側の `apm.yml` の `#vX.Y.Z` を上げて `apm install -g` で反映

## ライセンス

MIT
