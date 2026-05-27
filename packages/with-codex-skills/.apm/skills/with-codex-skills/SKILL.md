---
name: with-codex-skills
description: the agent (Claude Code) を OpenAI Codex CLI と tmux で協調動作させる必要があるときに使用する。second opinion を取る、Claude と Codex のアプローチを比較する、両 AI を活用した collaborative problem-solving を行うときに適用。non-interactive モード (自動応答取得) と interactive モード (tmux 分割表示) の両方に対応。
---

# With Codex - the agent and Codex Collaboration

This skill enables collaboration between the agent (Claude Code) and OpenAI Codex CLI for second opinions, validation, and collaborative problem-solving.

## CRITICAL REQUIREMENT

**The agent MUST be running inside a tmux session for this skill to work.**

If not in tmux, inform the user:
"このスキルを使用するには、tmuxセッション内で the agent を起動する必要があります。以下のコマンドを実行してください:

```bash
tmux new-session -s claude
claude
```

"

## Environment Requirements

- WSL (Ubuntu) with tmux installed
- OpenAI Codex CLI installed and authenticated in WSL
- The agent running inside a tmux session
- Skill scripts at: `~/.claude/skills/with-codex-skills/scripts/`

## Standard Workflow (MUST FOLLOW)

When this skill is triggered, ALWAYS execute these steps in order:

### Step 1: Setup - Split pane and start Codex

```bash
~/.claude/skills/with-codex-skills/scripts/codex-manager.sh setup
```

This splits the current tmux pane:

- Left pane: the agent (current)
- Right pane: Codex CLI (newly created, with dark background)

### Step 2: The agent performs its own analysis first

Analyze the user's request independently before querying Codex.

### Step 3: Send the same prompt to Codex

```bash
~/.claude/skills/with-codex-skills/scripts/codex-manager.sh send "YOUR_PROMPT_HERE"
```

Replace `YOUR_PROMPT_HERE` with the actual question/task from the user.

### Step 4: Wait for Codex response

```bash
~/.claude/skills/with-codex-skills/scripts/codex-manager.sh wait 60
```

Wait up to 60 seconds for Codex to complete its response.

### Step 5: Capture Codex output

```bash
~/.claude/skills/with-codex-skills/scripts/codex-manager.sh capture 200
```

Capture the last 200 lines of Codex's output.

### Step 6: Present combined results

Present results in this format:

```markdown
## The agent's Analysis

[Your independent analysis]

## Codex's Analysis

[Captured response from Codex]

## Synthesis

- **Agreement**: [Points where both AIs agree]
- **Differences**: [Alternative perspectives from Codex]
- **Recommendation**: [Best combined approach]
```

### Step 7: Cleanup (when conversation ends or user requests)

```bash
~/.claude/skills/with-codex-skills/scripts/codex-manager.sh cleanup
```

## Available Commands

| Command | Description |
| ------- | ----------- |
| `setup` | Split pane and start Codex on the right |
| `send "prompt"` | Send prompt to Codex pane |
| `capture [lines]` | Capture Codex output (default: 100 lines) |
| `wait [timeout]` | Wait for response to stabilize (default: 60s) |
| `cleanup` | Close the Codex pane |
| `status` | Check pane status |
| `focus` | Switch focus to Codex pane |

## Error Handling

If setup fails with "Not running inside tmux":

- Inform user they need to start the agent inside tmux
- Provide the commands: `tmux new-session -s claude` then `claude`

## Alternative: Non-Interactive Mode

Only use when tmux is unavailable or user explicitly requests:

```bash
codex exec "your prompt" 2>/dev/null
```

## Best Practices

1. ALWAYS use tmux interactive mode by default
2. Let user see both AIs working side-by-side
3. Wait adequate time (30-60s) for complex Codex queries
4. Present both perspectives without bias
5. Acknowledge both AIs can be wrong - user makes final decision
