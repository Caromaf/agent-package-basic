#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""dotfiles の各 profile apm.yml に、packages/ の APM 依存の不足分を追記する。

このリポの packages/*/ (apm.yml を持つ dir) を single source of truth とし、
`$HOME/dotfiles/agents/profiles/*/apm.yml` の dependencies.apm リストが網羅して
いるかを確認する。不足している package があれば、各 profile の既存依存行と同じ
prefix/ref/インデントで末尾に追記する。

YAML parser は使わず行ベースで処理する (check_skill_frontmatter.py と同方針)。
依存行の書式は安定しているため、正規表現で package 名を抽出し、既存行を雛形に
新規行を組み立てる。これにより PyYAML 依存を避け、コメントや並びを壊さない。

使い方:
    uv run --script scripts/sync_profile_deps.py            # 不足分を追記する
    uv run --script scripts/sync_profile_deps.py --check     # 追記せず不足を報告 (CI 用、不足あれば exit 1)
    uv run --script scripts/sync_profile_deps.py --profiles-dir <path>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = REPO_ROOT / "packages"
DEFAULT_PROFILES_DIR = Path.home() / "dotfiles" / "agents" / "profiles"

# 依存行: `    - Caromaf/agent-package-basic/packages/<name>#main`
# indent / prefix(packages/ まで) / name / ref(#... ) を捕捉する。
DEP_RE = re.compile(r"^(?P<indent>\s*)-\s*(?P<prefix>\S*/packages/)(?P<name>[a-z0-9-]+)(?P<ref>#\S+)\s*$")


def repo_packages() -> list[str]:
    """packages/ 配下で apm.yml を持つ dir 名を返す。"""
    return sorted(p.name for p in PACKAGES.iterdir() if (p / "apm.yml").is_file())


def referenced_packages(lines: list[str]) -> set[str]:
    """profile apm.yml の行から、参照済み package 名の集合を返す。"""
    found: set[str] = set()
    for line in lines:
        m = DEP_RE.match(line)
        if m:
            found.add(m.group("name"))
    return found


def append_missing(path: Path, missing: list[str]) -> bool:
    """不足 package を末尾の依存行の後に追記する。成功で True。

    既存の依存行を雛形に indent/prefix/ref を引き継ぐ。依存行が 1 つも無い profile は
    雛形を推定できないため警告して skip する。
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    last_idx = -1
    template: re.Match[str] | None = None
    for i, line in enumerate(lines):
        m = DEP_RE.match(line)
        if m:
            last_idx = i
            template = m
    if template is None or last_idx == -1:
        print(f"  ⚠️  {path}: 既存の依存行が無く雛形を推定できないため skip", file=sys.stderr)
        return False

    indent, prefix, ref = template.group("indent"), template.group("prefix"), template.group("ref")
    newline = "\n" if not lines[last_idx].endswith("\r\n") else "\r\n"
    new_lines = [f"{indent}- {prefix}{name}{ref}{newline}" for name in missing]
    lines[last_idx + 1 : last_idx + 1] = new_lines
    path.write_text("".join(lines), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        default=DEFAULT_PROFILES_DIR,
        help=f"profile ディレクトリ (default: {DEFAULT_PROFILES_DIR})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="追記せず不足を報告するだけ。不足があれば exit 1 (CI 用)",
    )
    args = parser.parse_args()

    pkgs = repo_packages()
    if not pkgs:
        print(f"packages/ に apm.yml を持つ dir が無い: {PACKAGES}", file=sys.stderr)
        return 1

    profiles = sorted(args.profiles_dir.glob("*/apm.yml"))
    if not profiles:
        print(f"profile apm.yml が見つからない: {args.profiles_dir}/*/apm.yml", file=sys.stderr)
        return 1

    total_missing = 0
    changed = 0
    for path in profiles:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        missing = sorted(set(pkgs) - referenced_packages(lines))
        if not missing:
            continue
        total_missing += len(missing)
        rel = path.relative_to(args.profiles_dir)
        if args.check:
            print(f"❌ {rel}: 不足 {len(missing)} 件: {', '.join(missing)}", file=sys.stderr)
        elif append_missing(path, missing):
            changed += 1
            print(f"✅ {rel}: {len(missing)} 件追記: {', '.join(missing)}")

    if args.check:
        if total_missing:
            print(f"❌ profile に不足あり: 合計 {total_missing} 件。追記するには --check 無しで実行", file=sys.stderr)
            return 1
        print(f"✅ 全 profile が packages/ を網羅 ({len(profiles)} profile / {len(pkgs)} package)")
        return 0

    if total_missing == 0:
        print(f"✅ 追記不要。全 profile が packages/ を網羅 ({len(profiles)} profile / {len(pkgs)} package)")
    else:
        print(f"✅ {changed} profile に合計 {total_missing} 件を追記した")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
