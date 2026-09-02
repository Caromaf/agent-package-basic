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
