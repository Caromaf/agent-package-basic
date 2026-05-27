# agent-package-basic

汎用の AI agent パッケージ集 (公開可)。Claude Code / Codex CLI / Gemini で共通利用するスラッシュコマンドや skill を、[APM (Agent Package Manager)](https://microsoft.github.io/apm/) で配布する。

## レイアウト

```text
packages/
├── review-pr/                # PR レビュー用のスラッシュコマンド
│   ├── apm.yml
│   └── .apm/prompts/review-pr.prompt.md
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

## インストール (利用者側)

```bash
apm install -g Caromaf/agent-package-basic/packages/review-pr#v0.1.0
```

または `apm.yml` 経由で複数パッケージをまとめて install。

## 開発

パッケージ追加・修正の流れ:

1. ブランチを切って編集 (main 直 push しない)
2. PR を作って merge
3. `git tag vX.Y.Z` してタグ push
4. 利用側の `apm.yml` の `#vX.Y.Z` を上げて `apm install -g` で反映
