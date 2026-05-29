#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""CLAUDE.md / AGENTS.md / rules ファイルを機械的に診断し、客観指標を JSON で出す。

意味判断 (冗長か / Claude のデフォルトと被るか) はこのスクリプトでは行わない。
Claude が SKILL.md の手順に沿って評価する前段として、行数・セクション・重複候補だけを
構造化して出力する。

入力: --target でファイルパスを 1 つ以上指定するか、--auto で標準位置を自動探索
出力: audit-<date>-<hhmm>.json (.triage/ 配下)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# 公式ベストプラクティス由来のヘッドルーム閾値。
# https://code.claude.com/docs/ja/best-practices "効果的な CLAUDE.md を書く"
DEFAULT_MAX_LINES = 300
DEFAULT_MAX_RULES = 200
# 重複と判定する最小出現回数 (1 ファイル内 / 複数ファイル間 共通)。
DUPLICATE_THRESHOLD = 2

# 標準的なメモリファイルの探索位置 (--auto 時)。
AUTO_TARGETS = (
    Path.home() / ".claude" / "CLAUDE.md",
    Path.cwd() / "CLAUDE.md",
    Path.cwd() / "CLAUDE.local.md",
    Path.cwd() / "AGENTS.md",
)
AUTO_TARGET_DIRS = (
    Path.home() / ".claude" / "rules",
    Path.cwd() / ".claude" / "rules",
    Path.cwd() / ".cursor" / "rules",
)

# section の見出しレベル (## 〜 ####)。# は title なので含めない。
SECTION_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$", re.MULTILINE)
# トップレベル bullet (インデント無し)。サブ bullet (`  -`) は理由・補足扱いで除外。
TOP_BULLET_RE = re.compile(r"^[-*]\s+(.+?)\s*$", re.MULTILINE)
# 太字 bullet の中身を抜く (重複検出用の正規キー)。例: "- **deprecated な〜**" → "deprecated な〜"
BOLD_BULLET_HEAD_RE = re.compile(r"^[-*]\s+\*\*([^*]+)\*\*")
# YAML frontmatter (--- ... ---) を検出。
FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


def resolve_targets(args: argparse.Namespace) -> list[Path]:
    """--target / --auto を解決し、実在するファイルだけ返す。

    --auto 時は標準位置のファイル + AUTO_TARGET_DIRS 内の *.md を全部拾う。
    """
    targets: list[Path] = []
    if args.target:
        targets.extend(Path(p).expanduser().resolve() for p in args.target)
    if args.auto or not args.target:
        targets.extend(p for p in AUTO_TARGETS if p.exists())
        for d in AUTO_TARGET_DIRS:
            if d.is_dir():
                targets.extend(sorted(d.glob("*.md")))
    # ~/.claude/CLAUDE.md は dotfiles への symlink で同実体を二重に拾うことがあるので
    # resolve() で実体パスにしてから dedup する。
    seen: set[Path] = set()
    deduped: list[Path] = []
    for t in targets:
        real = t.resolve()
        if real in seen or not real.exists() or not real.is_file():
            continue
        seen.add(real)
        deduped.append(t)
    return deduped


def parse_frontmatter(text: str) -> tuple[str | None, str]:
    """Frontmatter を分離。ない場合は (None, text)。"""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    return m.group(1).rstrip(), text[m.end() :]


def extract_sections(body: str) -> list[dict]:
    """## 見出しごとに区切ってセクションのメタを返す。

    各エントリ: {level, title, start_line, end_line, line_count, body_excerpt}
    """
    matches = list(SECTION_RE.finditer(body))
    sections: list[dict] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_body = body[start:end]
        start_line = body.count("\n", 0, start) + 1
        end_line = start_line + section_body.count("\n")
        sections.append(
            {
                "level": len(m.group(1)),
                "title": m.group(2).strip(),
                "start_line": start_line,
                "end_line": end_line,
                "line_count": end_line - start_line + 1,
                "body_excerpt": section_body[:300].rstrip(),
            },
        )
    return sections


def extract_bullet_rules(body: str) -> list[dict]:
    """トップレベル bullet をすべてルール候補として抽出する。

    `- **xxx**` のように太字なら `rule_head` を太字内側で正規化、太字無しなら行頭 80
    文字を `rule_head` として使う (字面マッチによる重複検出のキーとなる)。
    サブ bullet (`  - `) は理由・補足とみなして除外する。
    """
    rules: list[dict] = []
    for m in TOP_BULLET_RE.finditer(body):
        line_no = body.count("\n", 0, m.start()) + 1
        text = m.group(1).strip()
        bold = BOLD_BULLET_HEAD_RE.match(m.group(0))
        rule_head = bold.group(1).strip() if bold else text[:80]
        rules.append(
            {
                "line": line_no,
                "rule_head": rule_head,
                "raw": text[:160],
                "is_bold": bool(bold),
            },
        )
    return rules


def find_duplicates(rules: list[dict]) -> list[dict]:
    """同一の rule_head が複数箇所に出てくるものを返す。"""
    counter = Counter(r["rule_head"] for r in rules)
    dups: list[dict] = []
    for head, cnt in counter.items():
        if cnt < DUPLICATE_THRESHOLD:
            continue
        lines = [r["line"] for r in rules if r["rule_head"] == head]
        dups.append({"rule_head": head, "count": cnt, "lines": lines})
    return dups


def find_cross_file_duplicates(file_results: list[dict]) -> list[dict]:
    """ファイルをまたいで同一 rule_head が登場するものを検出。

    rules 機能 (~/.claude/rules/*.md) と CLAUDE.md で同じルールが書かれているケースを
    炙り出す。同じルールが 2 箇所にあると優先順位がブレる。
    """
    head_to_files: dict[str, list[tuple[str, int]]] = {}
    for fr in file_results:
        for r in fr["bullet_rules"]:
            head_to_files.setdefault(r["rule_head"], []).append((fr["path"], r["line"]))
    dups: list[dict] = []
    for head, locations in head_to_files.items():
        files = {p for p, _ in locations}
        if len(files) >= DUPLICATE_THRESHOLD:
            dups.append(
                {
                    "rule_head": head,
                    "locations": [{"path": p, "line": ln} for p, ln in locations],
                },
            )
    return dups


def measure_file(path: Path, max_lines: int, max_rules: int) -> dict:
    """1 ファイルを機械的に計測する。

    意味判断 (冗長 / 常識被り) はしない。Claude が SKILL.md に従って後で判定する。
    """
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    line_count = text.count("\n") + (0 if text.endswith("\n") else 1)
    sections = extract_sections(body)
    bullet_rules = extract_bullet_rules(body)
    duplicates = find_duplicates(bullet_rules)

    return {
        "path": str(path),
        "real_path": str(path.resolve()),
        "size_bytes": len(text.encode("utf-8")),
        "line_count": line_count,
        "rule_count": len(bullet_rules),
        "headroom": {
            "max_lines": max_lines,
            "max_rules": max_rules,
            "lines_pct": round(line_count / max_lines * 100, 1),
            "rules_pct": round(len(bullet_rules) / max_rules * 100, 1) if max_rules else None,
            "over_limit": line_count > max_lines or len(bullet_rules) > max_rules,
        },
        "frontmatter": frontmatter,
        "sections": sections,
        "bullet_rules": bullet_rules,
        "duplicates_within_file": duplicates,
    }


def build_output(targets: Iterable[Path], max_lines: int, max_rules: int) -> dict:
    file_results = [measure_file(p, max_lines, max_rules) for p in targets]
    cross = find_cross_file_duplicates(file_results)
    return {
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "scope": {
            "target_count": len(file_results),
            "max_lines": max_lines,
            "max_rules": max_rules,
        },
        "files": file_results,
        "duplicates_across_files": cross,
    }


def main() -> int:
    description = (__doc__ or "").split("\n\n", maxsplit=1)[0]
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="診断対象ファイル (複数指定可)。省略時は --auto と同等",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="標準位置 (~/.claude/CLAUDE.md, ./CLAUDE.md, ~/.claude/rules/*.md など) を自動探索",
    )
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    parser.add_argument("--max-rules", type=int, default=DEFAULT_MAX_RULES)
    parser.add_argument("--out", type=Path, default=None, help="出力先 JSON")
    args = parser.parse_args()

    targets = resolve_targets(args)
    if not targets:
        print("対象ファイルが見つかりません。--target を指定するか --auto を使ってください。", file=sys.stderr)
        return 1

    if args.out is None:
        triage_dir = Path.cwd() / ".triage"
        triage_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).astimezone().strftime("%Y-%m-%d-%H%M")
        args.out = triage_dir / f"audit-{stamp}.json"
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)

    output = build_output(targets, args.max_lines, args.max_rules)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"診断完了: {len(targets)} ファイル")
    for fr in output["files"]:
        warn = "⚠️ " if fr["headroom"]["over_limit"] else ""
        print(
            f"  {warn}{fr['path']}: {fr['line_count']} 行 / {fr['rule_count']} ルール "
            f"({fr['headroom']['lines_pct']}% / {fr['headroom']['rules_pct']}%)",
        )
    if output["duplicates_across_files"]:
        print(f"  クロスファイル重複: {len(output['duplicates_across_files'])} 件")
    print(f"出力: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
