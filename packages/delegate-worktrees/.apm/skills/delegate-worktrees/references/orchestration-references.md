# マルチエージェント委任の参照情報

この skill の設計判断の裏付け。実装方針に迷ったとき、または委任パターンを更新するときに参照する。記憶や推測で更新せず、下記の公式ドキュメントを `WebFetch` で確認してから書く。

## 公式ドキュメント (一次情報・優先)

- Create custom subagents: <https://code.claude.com/docs/en/sub-agents>
- Run parallel sessions with worktrees: <https://code.claude.com/docs/en/worktrees>
- Agent teams: <https://code.claude.com/docs/en/agent-teams>

## 公式仕様から確定している事実

- subagent frontmatter / Agent tool は `isolation: worktree` を持つ。設定すると一時 git worktree を生成し、**default branch から分岐**する (parent session の `HEAD` ではない)。subagent が変更を加えなければ worktree は自動でクリーンアップされる。
- subagent frontmatter で指定できるフィールド: `name`, `description`, `tools`, `disallowedTools`, `model`, `permissionMode`, `mcpServers`, `hooks`, `maxTurns`, `skills`, `initialPrompt`, `memory`, `effort`, `background`, `isolation`, `color`。
- fork は会話全体を継承する subagent。`isolation: "worktree"` を渡せて、prompt cache 再利用で fresh な subagent より安価。fork はさらに fork できない。
- Agent teams は実験的機能でデフォルト無効。`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` を settings.json または環境変数に追加して有効化する。`SendMessage` で worker 間通信ができ、各 worker が独立 context を持つ持続的並列に向く。ただし session resumption、task coordination、shutdown 挙動に既知の制約があるため、本番委任フローの前提にはせず、安定している subagent + `isolation: worktree` を主軸にする。Agent teams は明示的に opt-in したときだけ使う。

## コミュニティの heuristic (二次情報・補助)

- 同時 worker 数は 3〜5 が sweet spot。超えると統合オーバーヘッドが並列の利益を食う。
- 依存マッピングで phase 分割する。依存タスク (schema → routes → tests) は直列化し、独立タスクだけ並列化する。
- orchestrator が統合層。worker に自己統合させると重複と衝突が出る。merge/rebase 順序は coordinator が単独で握る。

参照元:

- Claude Code subagents and the orchestrator pattern (Chanl): <https://www.channel.tel/blog/claude-code-subagents-orchestrator-pattern>
- Subagent-Driven Development Skill Guide (Jonathan's Blog): <https://jonathansblog.co.uk/the-subagent-driven-development-claude-code-skill-orchestrate-multiple-agents-like-a-team>
- parallel-worktrees Skill (GitHub, spillwavesolutions): <https://github.com/spillwavesolutions/parallel-worktrees>
- Inside Claude Code's Shared Task List (MindStudio): <https://www.mindstudio.ai/blog/claude-code-agent-teams-shared-task-list>
- Agent teams の実験的位置づけと既知の制約 (YouTube): <https://www.youtube.com/watch?v=QJ9Qkypdbqs>

## ツール非依存に関する設計上の注意

`isolation: worktree`, fork, Agent teams はいずれも Claude Code ランタイム固有の機能。この skill は APM の primitive として Codex など他ランタイムにも展開されるため、native isolation を使えない環境では手動 `git worktree` 系統にフォールバックする。同梱の `worktree` skill が「claude では EnterWorktree/ExitWorktree、codex では `git worktree` コマンド」と 2 系統を併記しているのと同じ方針を取る。
