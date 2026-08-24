#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["pyyaml"]
# ///
"""packages/*/.apm/skills/*/SKILL.md の frontmatter を検査する lint。

Codex CLI は YAML 1.1 系の厳格な parser を使うため、frontmatter が壊れていると skill
読み込みに失敗する。Claude Code 側は寛容で問題が顕在化しないので、CI で機械強制する。

検査内容:
1. frontmatter 全体が `yaml.safe_load` で parse できること。
2. `name` / `description` / `argument-hint` / `allowed-tools` は、存在する場合
   値が文字列型であること (YAML 1.1 が `on` / `no` / `017` 等を bool/int に
   解釈してしまうケースを弾く)。
3. 無クォートの単一行の値に、`#` によるサイレント切り詰め (`foo # bar` のように
   YAML コメントとして扱われ、値が黙って途中で切れる) が起きていないこと。
4. トップレベルキーの重複がないこと (`yaml.safe_load` は後勝ちで黙って上書きするため)。
5. 無クォートで値の先頭が YAML reserved indicator (`, !, &, *, ?, :, |, >, {, [, ,, #, @, %)
   で始まっていないこと (yaml.safe_load が通っても、Codex 側の YAML 1.1 parser が
   別の理由で落ちるケースを防ぐ保険)。

使い方:
    uv run --script scripts/check_skill_frontmatter.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = REPO_ROOT / "packages"

CHECKED_KEYS = ("name", "description", "argument-hint", "allowed-tools")
RESERVED_INDICATORS = ("`", "!", "%", "&", "@", "*", "?", ":", "|", ">", "{", "[", ",", "#")
MIN_QUOTED_LEN = 2  # 先頭・終端のクォート文字それぞれ 1 文字分。
DUPLICATE_KEY_COUNT = 2  # 2 回目の出現で「重複」と判定する。

# トップレベルキー: 行頭 (インデント無し) から始まる `key:` のみを対象にする。
# ネストした値やブロックスカラーの続き行はインデントされているため対象外になる。
TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_-]+):")

# 各キーの単一行の値を取り出す (ブロックスカラー導入行 `key: >` / `key: |` も含む)。
KEY_VALUE_RE_TEMPLATE = r"^{key}:[ \t]*(.*?)[ \t]*$"

# YAML の未クォート値内で `#` がコメント開始として解釈される条件: 行頭、または
# 直前が空白文字であること。
COMMENT_START_RE = re.compile(r"(?:^|\s)#")


def _is_fully_quoted(raw: str) -> bool:
    if len(raw) < MIN_QUOTED_LEN:
        return False
    return (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'"))


def _is_block_scalar_intro(raw: str) -> bool:
    """`key: >` / `key: |` のようなブロックスカラー導入かどうか。

    先頭が `>` / `|` で、その後にチョンピング/インデント指示子 (`-`, `+`, 数字) しか
    続かない場合はブロックスカラーの開始であり、reserved indicator 違反ではない。
    """
    return bool(re.fullmatch(r"[>|][+\-0-9]*", raw))


def find_duplicate_keys(fm_text: str) -> list[str]:
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    for line in fm_text.splitlines():
        m = TOP_LEVEL_KEY_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == DUPLICATE_KEY_COUNT:
            duplicates.append(key)
    return duplicates


def find_key_raw_value(fm_text: str, key: str) -> str | None:
    """フロントマターのテキストからキーの単一行の生の値を取り出す。

    キーが見つからない場合は None を返す。値がブロックスカラー等で次行以降に
    続く場合は、この行に書かれている範囲 (空文字列や `>` 等) のみを返す。
    """
    pattern = re.compile(KEY_VALUE_RE_TEMPLATE.format(key=re.escape(key)), re.MULTILINE)
    m = pattern.search(fm_text)
    if not m:
        return None
    return m.group(1)


def check_key(fm: str, key: str, value: object) -> list[str]:
    """`name` / `description` 等の 1 キーについて検査 NG の理由リストを返す。"""
    problems: list[str] = []

    if not isinstance(value, str):
        problems.append(f"`{key}:` の値が文字列型ではない (型: {type(value).__name__}, 値: {value!r})")
        # 型が違う場合、以降の生テキスト比較は意味を持たないためスキップする。
        return problems

    raw = find_key_raw_value(fm, key)
    if raw is None:
        return problems

    if _is_fully_quoted(raw) or _is_block_scalar_intro(raw):
        return problems

    # 3. `#` によるサイレント切り詰め検出。
    m = COMMENT_START_RE.search(raw)
    if m and raw[: m.start()].rstrip() != raw.rstrip():
        quote_hint = '"..."'
        problems.append(
            f"`{key}:` の値が無クォートで `#` を含み、YAML コメントとして黙って切り詰められている "
            f"(生テキスト: {raw!r} → parse 後: {value!r})。値全体を {quote_hint} で囲むこと"
        )

    # 5. 無クォートで先頭が reserved indicator。
    if raw and raw[0] in RESERVED_INDICATORS:
        quote_hint = '"..."'
        problems.append(
            f"`{key}:` が無クォートで YAML reserved indicator {raw[0]!r} で始まる。"
            f"値全体を {quote_hint} で囲むこと (Codex CLI の YAML parser でロード失敗する)"
        )

    return problems


def check(skill_md: Path) -> list[str]:
    """検査 NG の理由リストを返す。OK なら空リスト。"""
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return ["frontmatter なし (--- で始まっていない)"]
    end = text.find("\n---\n", 4)
    if end == -1:
        return ["frontmatter 終端 (---) が見つからない"]
    fm = text[4:end]

    # 1. 重複キー検出 (yaml.safe_load 前に生テキストで確認する)。
    problems = [
        f"トップレベルキー `{key}:` が重複している (yaml.safe_load は後勝ちで黙って上書きする)"
        for key in find_duplicate_keys(fm)
    ]

    # 2. yaml.safe_load で parse できること。
    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError as e:
        problems.append(f"yaml.safe_load に失敗: {e}")
        return problems

    if not isinstance(data, dict):
        problems.append(f"frontmatter のトップレベルが mapping ではない (型: {type(data).__name__})")
        return problems

    for key in CHECKED_KEYS:
        if key in data:
            problems.extend(check_key(fm, key, data[key]))

    return problems


def main() -> int:
    skills = sorted(PACKAGES.glob("*/.apm/skills/*/SKILL.md"))
    if not skills:
        print(f"対象 SKILL.md が見つからない: {PACKAGES}", file=sys.stderr)
        return 1

    failures: list[tuple[Path, list[str]]] = []
    for skill_md in skills:
        problems = check(skill_md)
        if problems:
            failures.append((skill_md, problems))

    if failures:
        print(f"❌ SKILL.md frontmatter lint 失敗: {len(failures)}/{len(skills)} 件", file=sys.stderr)
        for path, problems in failures:
            rel = path.relative_to(REPO_ROOT)
            for reason in problems:
                print(f"  {rel}: {reason}", file=sys.stderr)
        return 1

    print(f"✅ SKILL.md frontmatter lint OK: {len(skills)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
