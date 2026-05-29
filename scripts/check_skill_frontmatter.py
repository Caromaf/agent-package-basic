#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""packages/*/.apm/skills/*/SKILL.md の frontmatter を検査する lint。

Codex CLI は YAML 1.1 系の厳格な parser を使うため、`description:` の値が無クォートで
YAML reserved indicator (`, !, &, *, ?, :, |, >, {, [, ,, #, @, %) で始まると skill
読み込みに失敗する。Claude Code 側は寛容で問題が顕在化しないので、CI で機械強制する。

判定:
- 値全体が `"..."` または `'...'` でクォート → OK (中身が何でも文字列扱い)
- 無クォートで先頭が reserved indicator → NG (exit 1)
- それ以外 (日本語 / ASCII 英字 / 数字 で始まる) → OK

使い方:
    uv run --script scripts/check_skill_frontmatter.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = REPO_ROOT / "packages"

DESC_RE = re.compile(r"^description:\s*(.+?)\s*$", re.MULTILINE)
RESERVED_INDICATORS = ("`", "!", "%", "&", "@", "*", "?", ":", "|", ">", "{", "[", ",", "#")


def check(skill_md: Path) -> str | None:
    """検査 NG なら理由を返す。OK なら None。"""
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return "frontmatter なし (--- で始まっていない)"
    end = text.find("\n---\n", 4)
    if end == -1:
        return "frontmatter 終端 (---) が見つからない"
    fm = text[4:end]
    m = DESC_RE.search(fm)
    if not m:
        return "description: フィールドが見つからない"
    raw = m.group(1)
    # クォート全包なら何でも OK。
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return None
    if raw and raw[0] in RESERVED_INDICATORS:
        return (
            f"description: が無クォートで YAML reserved indicator {raw[0]!r} で始まる。"
            f'値全体を "..." で囲むこと (Codex CLI の YAML parser でロード失敗する)'
        )
    return None


def main() -> int:
    skills = sorted(PACKAGES.glob("*/.apm/skills/*/SKILL.md"))
    if not skills:
        print(f"対象 SKILL.md が見つからない: {PACKAGES}", file=sys.stderr)
        return 1

    failures: list[tuple[Path, str]] = []
    for skill_md in skills:
        problem = check(skill_md)
        if problem:
            failures.append((skill_md, problem))

    if failures:
        print(f"❌ SKILL.md frontmatter lint 失敗: {len(failures)}/{len(skills)} 件", file=sys.stderr)
        for path, reason in failures:
            rel = path.relative_to(REPO_ROOT)
            print(f"  {rel}: {reason}", file=sys.stderr)
        return 1

    print(f"✅ SKILL.md frontmatter lint OK: {len(skills)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
