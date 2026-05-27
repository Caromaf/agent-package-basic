---
description: "最後の git タグからのコミットを分類し、CHANGELOG.md の Unreleased セクションを更新します"
argument-hint: "[sinceTag?]"
allowed-tools: >
  Bash(git describe:*), Bash(git log:*), Bash(grep:*), Bash(awk:*), Bash(sed:*), Bash(date:*), Bash(tr:*), Bash(git rev-list:*), Bash(git rev-parse:*), Bash(test -f:*), Bash(echo:*), Bash(cat:*), Bash(head:*), Bash(tail:*), Bash(cd:*), Bash(pwd:*), Bash(basename:*), Bash(dirname:*), Bash(touch:CHANGELOG.md), Read(CHANGELOG.md), Write(CHANGELOG.md)
---

# Prepare CHANGELOG.md

現在のリポジトリの状況を把握した上で、CHANGELOG.md の `## [Unreleased]` セクションを更新します。
以下の手順で実行してください。

## Ensure Git Repository and CHANGELOG.md

まず、現在のディレクトリが Git リポジトリであることを確認します。

```bash
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
  echo "Error: This command must be run inside a Git repository."
  exit 1
fi
```

次に、`CHANGELOG.md` ファイルが存在することを確認します。存在しない場合はエラーを出力して終了します。
現在のディレクトリがリポジトリのルートでない場合は、適宜 `cd` コマンドでルートに移動してください。

```bash
if [ ! -f CHANGELOG.md ]; then
  echo "Warning: CHANGELOG.md file not found."
fi
```

## Analyze Git History

最後のタグと対象となるコミット、および実際のファイルの差分を分析します：

```bash
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null)
BASE="${1:-$LATEST_TAG}"

if [ -n "$LATEST_TAG" ]; then
  echo "Latest tag: $LATEST_TAG"
else
  echo "Latest tag: (none found)"
fi

if [ -n "$BASE" ]; then
  echo "Base reference: $BASE"
  echo "--- Commits since $BASE ---"
  git --no-pager log "$BASE..HEAD" --pretty=format:'- %s'
  echo -e "\n--- File changes since $BASE ---"
  git --no-pager diff "$BASE..HEAD"
else
  echo "Base reference: (repository root)"
  echo "--- All commits (showing last 20) ---"
  git --no-pager log --pretty=format:'- %s' -n 20
  echo -e "\n--- Recent file changes ---"
  git --no-pager diff HEAD~20..HEAD
fi
```

## Create CHANGELOG.md if Missing

リポジトリルートに `CHANGELOG.md` が存在しない場合は、以下の `CHANGELOG.md` を作成します。

```markdown
# CHANGELOG

すべての注目すべき変更はこのファイルに記録されます。

フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.0.0/) に基づいており、
このプロジェクトは [Semantic Versioning](https://semver.org/lang/ja/) に準拠しています。

## Tagged Releases

## [Unreleased]
```

## Edit CHANGELOG.md

`CHANGELOG.md` の `## [Unreleased]` セクションを

- [Keep a Changelog](https://keepachangelog.com/ja/1.0.0/)
- [Semantic Versioning](https://semver.org/lang/ja/)

に基づいて更新します。

### Notes

- **ファイルの差分（git diff）を詳細に分析し**、コミットメッセージだけでは読み取れない「実際の機能的な変化」を把握してください。
- PR や Issue の番号は `[#123](github.com/your-repo/issues/123)` のようにリンク形式で記載してください。
- `CHANGELOG.md` には実装した詳細を書くのではなく、そのサービスを利用する人（ユーザー）から見たときにどのような機能追加・変更・修正があったのかを端的に記載してください。
- このコマンドは `CHANGELOG.md` のみを編集し、コミットやタグ付けは行いません。新しくバージョンや日付を追加しないでください。
- リスト項目は簡潔かつ統一的な表現で記載してください。
- なんでもかんでもリストに追加するのではなく、必要十分な内容を端的に記載してください。

## Suggested Next Version

CHANGELOG.md の内容を踏まえて、次のバージョンアップを行う際に、Semantic Versioning に基づいて、MAJOR, MINOR, PATCH のどれを更新するべきかを判断してください。
