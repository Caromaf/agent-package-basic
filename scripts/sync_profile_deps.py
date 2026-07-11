#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["PyYAML>=6.0.2,<7"]
# ///
"""dotfiles の各 profile apm.yml に、packages/ の APM 依存の不足分を追記する。

このリポの packages/*/ (apm.yml を持つ dir) を single source of truth とし、
`$HOME/dotfiles/agents/profiles/*/apm.yml` の dependencies.apm リストが網羅して
いるかを確認する。不足している package があれば、各 profile の既存依存行と同じ
prefix/ref/インデントで末尾に追記する。

dependencies.apm の参照判定は PyYAML の node tree で意味解析する。追記時は
対象 sequence の行範囲だけを調べ、既存の文字列依存行を雛形に新規行を組み立てる。
YAML 自体は書き戻さないため、コメントや並びは保持される。

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

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = REPO_ROOT / "packages"
DEFAULT_PROFILES_DIR = Path.home() / "dotfiles" / "agents" / "profiles"

# 文字列形式の依存行: `    - Caromaf/agent-package-basic/packages/<name>#main`
# indent / prefix(packages/ まで) / name / ref(#... ) を捕捉する。
DEP_RE = re.compile(r"^(?P<indent>\s*)-\s*(?P<prefix>\S*/packages/)(?P<name>[a-z0-9-]+)(?P<ref>#\S+)\s*$")
DEP_VALUE_RE = re.compile(r"^(?P<prefix>\S*/packages/)(?P<name>[a-z0-9-]+)(?P<ref>#\S+)$")
PACKAGE_PATH_RE = re.compile(r"^(?:\S*/)?packages/(?P<name>[a-z0-9-]+)/?$", re.ASCII)


def repo_packages() -> list[str]:
    """packages/ 配下で apm.yml を持つ dir 名を返す。"""
    return sorted(p.name for p in PACKAGES.iterdir() if (p / "apm.yml").is_file())


def referenced_packages(lines: list[str]) -> set[str]:
    """profile apm.yml の行から、参照済み package 名の集合を返す。

    トップレベルの `dependencies.apm` sequence だけを YAML として読み、
    文字列形式と object 形式の `path` から package 名を取得する。
    """
    found: set[str] = set()
    apm = _dependencies_apm_node("".join(lines))
    if not isinstance(apm, SequenceNode):
        return found

    for dependency in apm.value:
        if isinstance(dependency, ScalarNode):
            match = DEP_VALUE_RE.fullmatch(dependency.value)
            if match:
                found.add(match.group("name"))
        elif isinstance(dependency, MappingNode):
            path = _mapping_value(dependency, "path")
            if isinstance(path, ScalarNode):
                _add_package_path(found, path.value)

    return found


def _dependencies_apm_node(text: str) -> Node | None:
    """YAML document のトップレベル dependencies.apm node を返す。"""
    document = yaml.compose(text, Loader=yaml.SafeLoader)
    dependencies = _mapping_value(document, "dependencies")
    return _mapping_value(dependencies, "apm")


def _mapping_value(mapping: Node | None, key: str) -> Node | None:
    """mapping node から scalar key に対応する value node を返す。"""
    if not isinstance(mapping, MappingNode):
        return None
    for key_node, value_node in mapping.value:
        if isinstance(key_node, ScalarNode) and key_node.value == key:
            return value_node
    return None


def _add_package_path(found: set[str], value: str) -> None:
    """object dependency の path 値が package を指す場合に found へ追加する。"""
    path = value.strip()
    quote = path[:1]
    if quote == path[-1:] and quote in {'"', "'"}:
        path = path[1:-1]
    match = PACKAGE_PATH_RE.fullmatch(path)
    if match:
        found.add(match.group("name"))


def append_missing(path: Path, missing: list[str]) -> bool:
    """不足 package を末尾の依存行の後に追記する。成功で True。

    既存の依存行を雛形に indent/prefix/ref を引き継ぐ。依存行が 1 つも無い profile は
    雛形を推定できないため警告して skip する。
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    apm = _dependencies_apm_node(text)
    if not isinstance(apm, SequenceNode) or apm.start_mark is None or apm.end_mark is None:
        print(f"  ⚠️  {path}: dependencies.apm が list でないため skip", file=sys.stderr)
        return False

    last_idx = -1
    template: re.Match[str] | None = None
    for i in range(apm.start_mark.line, apm.end_mark.line):
        line = lines[i]
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
