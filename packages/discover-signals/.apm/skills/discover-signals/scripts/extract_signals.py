#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Claude Code の会話ログから自己改善シグナルを抽出する。

入力: ~/.claude/projects/<project>/<session>.jsonl
出力: signals-<date>-<hhmm>.json (人間レビュー用)

シグナル種別:
- user_correction: 直前のアシスタント応答に対する否定/訂正
- repeated_instruction: 複数セッションに登場する同種の指示
- tool_loop: 同じツールを連続失敗で叩いている

完全自動化は狙わない。`triage-improvements` skill の前段として人間が選別する候補を出す。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

NEGATION_PATTERNS = [
    r"違う",
    r"そうじゃない",
    r"そうじゃなくて",
    r"やめて",
    r"やり直し",
    r"間違って?る",
    r"勘違い",
    r"取り違え",
    r"無関係",
    r"齟齬",
    r"矛盾",
    r"待って",
    r"まって",
    r"\bwait\b",
    r"don'?t do that",
    r"stop doing",
    r"that'?s wrong",
    r"no(?:,|\s)+(?:not|don)",
    r"なさそう",
    r"本当に.+\?",
    r"ではなく",
    r"悪さしている",
    r"おかしい",
    r"おかしくない\?",
    r"違いますよ",
    r"\bI mean\b",
    r"actually\s",
]
NEGATION_RE = re.compile("|".join(NEGATION_PATTERNS), re.IGNORECASE)

TOOL_LOOP_THRESHOLD = 8
REPEATED_MIN_SESSIONS = 3
REPEATED_MIN_LEN = 8
USER_CORRECTION_LOOKBACK = 5
CONSECUTIVE_FAILURES_MIN = 3

# Claude Code の slash command / skill 起動時に「ユーザー発話」として注入される
# 既知のテンプレート本文の冒頭。これらは "ユーザーが繰り返し言っている指示" ではなく
# command 本文なので、メッセージ全体を検出対象から除外する。
COMMAND_INJECTION_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<system-reminder>",
    "Base directory for this skill:",
    # /security-review 系
    "You are a security expert reviewing",
    # /code-review 系
    "You are reviewing the current diff",
    # /review 系の一般形
    "You are a code reviewer",
)

# Claude Code 自身が user role で書き込むシステムメッセージ。完全一致で除外する。
# (途中キャンセル/再開時の自動挿入であり、ユーザーの自由発話ではない)
SYSTEM_GENERATED_USER_MESSAGES = frozenset(
    {
        "[Request interrupted by user]",
        "[Request interrupted by user for tool use]",
        "Continue from where you left off.",
    }
)

# 注入された template 本文は数千文字に及ぶことが多い。
# 人間の自由発話で 4000 文字を超えるものは稀なので、長文かつ複数セッションに登場するものは
# repeated_instruction の対象から外す (個別キーワードを足し続けるイタチごっこを避けるため)。
COMMAND_INJECTION_LENGTH_THRESHOLD = 4000


def is_command_injection(text: str) -> bool:
    """text が command/skill 起動時に注入された本文 or system 自動挿入なら True。

    判定基準:
    1. Claude Code が自動挿入する固定文 (interrupt 通知 / 再開指示)
    2. 既知の prefix で始まる (`<command-name>`, `You are a security expert ...` 等)
    3. 4000 文字超の長文 (人間の自由発話としては異常に長く、template 注入の可能性が高い)
    """
    stripped = text.strip()
    if stripped in SYSTEM_GENERATED_USER_MESSAGES:
        return True
    if stripped.startswith(("<", "{")) or stripped.startswith(COMMAND_INJECTION_PREFIXES):
        return True
    return len(text) > COMMAND_INJECTION_LENGTH_THRESHOLD


def iter_session_files(project_root: Path, days: int, project: str | None) -> Iterator[Path]:
    cutoff = datetime.now(UTC).astimezone().timestamp() - days * 86400
    base = project_root / project if project else project_root
    if not base.exists():
        return
    for path in base.rglob("*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            yield path


def iter_messages(jsonl_path: Path) -> Iterator[dict]:
    """Jsonl を 1 行ずつ stream で読む。壊れた行はスキップ。"""
    try:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def extract_text(content: str | list[dict] | None) -> str:
    """message.content から平文を抽出。content は str / list[dict] / None など色々ある。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content)


def is_tool_result_message(msg: dict) -> bool:
    """Message が tool_result を含むなら True。人間の発話と区別するため。"""
    content = msg.get("message", {}).get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)


def _last_assistant_text(messages: list[dict], end_idx: int, lookback: int) -> str:
    """end_idx の直前 lookback 件以内で最後のアシスタント発話の冒頭テキストを返す。"""
    for j in range(end_idx - 1, max(-1, end_idx - lookback - 1), -1):
        prev = messages[j]
        if prev.get("type") != "assistant":
            continue
        content = prev.get("message", {}).get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")[:200]
        elif isinstance(content, str):
            return content[:200]
    return ""


def detect_corrections(messages: list[dict], session_id: str, project: str) -> list[dict]:
    """ユーザー否定/反問発話を検出。

    丁寧な反論パターン (「〜なさそう」「本当に〜？」「ではなく」など) も拾う。
    直前 LOOKBACK 件以内にアシスタント発話があるものに限定する (会話の文脈なしの単発発話は除外)。
    """
    signals = []
    for i, msg in enumerate(messages):
        if msg.get("type") != "user":
            continue
        if is_tool_result_message(msg):
            continue
        text = extract_text(msg.get("message", {}).get("content"))
        if not text or not NEGATION_RE.search(text):
            continue
        if is_command_injection(text):
            continue

        prev_assistant = _last_assistant_text(messages, i, USER_CORRECTION_LOOKBACK)
        if not prev_assistant:
            continue

        signals.append(
            {
                "kind": "user_correction",
                "session_id": session_id,
                "project": project,
                "timestamp": msg.get("timestamp"),
                "user_message": text[:200],
                "preceding_assistant_excerpt": prev_assistant,
                "suggested_target": "CLAUDE.md",
                "rationale": "ユーザーが直前のアシスタント応答を否定/反問している",
            },
        )
    return signals


def _signature(tool: str, inp: dict) -> str:
    """ツール呼び出しの「重複判定キー」を作る。引数の主要フィールドだけ拾う。"""
    if not isinstance(inp, dict):
        return tool
    if tool == "Bash":
        return f"Bash:{inp.get('command', '')[:200]}"
    if tool in {"Read", "Edit", "Write", "NotebookEdit"}:
        return f"{tool}:{inp.get('file_path', '')}"
    if tool == "Grep":
        return f"Grep:{inp.get('pattern', '')}|{inp.get('path', '')}"
    if tool == "Glob":
        return f"Glob:{inp.get('pattern', '')}"
    return tool


def _next_tool_result_is_error(messages: list[dict], from_idx: int, tool_use_id: str) -> bool:
    """tool_use の直後にある対応する tool_result が is_error=True か。"""
    for j in range(from_idx + 1, min(from_idx + 4, len(messages))):
        m = messages[j]
        if m.get("type") != "user":
            continue
        content = m.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result" and block.get("tool_use_id") == tool_use_id:
                return bool(block.get("is_error", False))
    return False


def detect_tool_loops(messages: list[dict], session_id: str, project: str) -> list[dict]:
    """同一ツールが「連続失敗」している塊だけを tool_loop と判定する。

    重複呼び出しではなく **連続失敗 N 回** を条件にすることで、開発中の正常な複数編集を除外する。
    例: Edit が 7 回呼ばれていても各回 success なら正常 (検出しない)。
        Bash が 3 回連続で is_error=True なら、同じエラーを引きずったループとして検出する。
    """
    signals = []
    streak: list[tuple[str, str]] = []  # (signature, timestamp)

    def flush() -> None:
        if len(streak) < CONSECUTIVE_FAILURES_MIN:
            return
        sigs = [s[0] for s in streak]
        tool_name = sigs[0].split(":", 1)[0]
        signals.append(
            {
                "kind": "tool_loop",
                "session_id": session_id,
                "project": project,
                "timestamp": streak[0][1],
                "tool": tool_name,
                "signatures": list(dict.fromkeys(sigs))[:5],
                "consecutive_failures": len(streak),
                "suggested_target": "SKILL.md",
                "rationale": f"{tool_name} が {len(streak)} 回連続失敗",
            },
        )

    for i, msg in enumerate(messages):
        if msg.get("type") != "assistant":
            continue
        content = msg.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool = block.get("name", "")
            inp = block.get("input", {})
            sig = _signature(tool, inp)
            tool_use_id = block.get("id", "")
            ts = msg.get("timestamp", "")
            if _next_tool_result_is_error(messages, i, tool_use_id):
                # 別ツールに切り替わったら streak を一旦 flush して新規開始
                if streak and not streak[-1][0].startswith(tool + ":"):
                    flush()
                    streak.clear()
                streak.append((sig, ts))
            else:
                flush()
                streak.clear()
    flush()
    return signals


def detect_repeated_instructions(all_user_messages: list[tuple[str, str, str]]) -> list[dict]:
    """複数セッションに登場する同一文言を検出。

    all_user_messages: (session_id, project, text) のリスト
    """
    text_to_sessions: dict[str, set[str]] = defaultdict(set)
    text_meta: dict[str, dict] = {}

    for session_id, project, raw_text in all_user_messages:
        text = raw_text.strip()
        if len(text) < REPEATED_MIN_LEN:
            continue
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if len(line) < REPEATED_MIN_LEN:
                continue
            text_to_sessions[line].add(session_id)
            if line not in text_meta:
                text_meta[line] = {"project": project}

    signals = []
    for line, sessions in text_to_sessions.items():
        if len(sessions) >= REPEATED_MIN_SESSIONS:
            signals.append(
                {
                    "kind": "repeated_instruction",
                    "session_count": len(sessions),
                    "session_ids": sorted(sessions)[:5],
                    "project": text_meta[line]["project"],
                    "instruction": line[:200],
                    "suggested_target": "CLAUDE.md",
                    "rationale": f"{len(sessions)} セッションに同一文言が登場",
                },
            )
    return signals


def process_session(jsonl_path: Path) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """1 セッションから (シグナル一覧, ユーザー発話一覧) を返す。"""
    session_id = jsonl_path.stem
    project = jsonl_path.parent.name
    messages = list(iter_messages(jsonl_path))

    signals: list[dict] = []
    signals.extend(detect_corrections(messages, session_id, project))
    signals.extend(detect_tool_loops(messages, session_id, project))

    user_messages = []
    for msg in messages:
        if msg.get("type") != "user":
            continue
        if is_tool_result_message(msg):
            continue
        text = extract_text(msg.get("message", {}).get("content"))
        if text and not is_command_injection(text):
            user_messages.append((session_id, project, text))

    return signals, user_messages


def main() -> int:
    description = (__doc__ or "").split("\n\n", maxsplit=1)[0]
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--project", default=None, help="プロジェクト名 (~/.claude/projects/<name>)")
    parser.add_argument("--out", type=Path, default=None, help="出力先 JSON")
    parser.add_argument("--projects-root", type=Path, default=Path.home() / ".claude" / "projects")
    args = parser.parse_args()

    if args.out is None:
        triage_dir = Path.cwd() / ".triage"
        triage_dir.mkdir(parents=True, exist_ok=True)
        # 同日複数回実行しても上書きしないよう YYYY-MM-DD-HHMM まで含める。
        stamp = datetime.now(UTC).astimezone().strftime("%Y-%m-%d-%H%M")
        args.out = triage_dir / f"signals-{stamp}.json"
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)

    session_files = list(iter_session_files(args.projects_root, args.days, args.project))
    if not session_files:
        print(f"対象セッションなし: {args.projects_root} (days={args.days}, project={args.project})", file=sys.stderr)

    all_signals: list[dict] = []
    all_user_messages: list[tuple[str, str, str]] = []
    for path in session_files:
        signals, user_msgs = process_session(path)
        all_signals.extend(signals)
        all_user_messages.extend(user_msgs)

    all_signals.extend(detect_repeated_instructions(all_user_messages))

    for i, sig in enumerate(all_signals, start=1):
        sig["id"] = f"sig-{i:04d}"

    output = {
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "scope": {
            "days": args.days,
            "project": args.project,
            "session_count": len(session_files),
        },
        "signals": all_signals,
    }

    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    kind_counts = Counter(s["kind"] for s in all_signals)
    print(f"抽出完了: {len(all_signals)} 件 ({dict(kind_counts)})")
    print(f"出力: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
