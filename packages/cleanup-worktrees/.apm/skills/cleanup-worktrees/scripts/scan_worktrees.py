#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""git worktree / ブランチ / リモート追跡参照の滞留を分類する診断スクリプト。

削除は一切行わない。分類結果を JSON で出力するだけ。
判定に必要な事実だけを集め、削除の可否判断は呼び出し側 (Claude + ユーザー) に委ねる。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# git diff --numstat の 1 行は "追加\t削除\tパス" の 3 列。パス欠落行は 2 列未満で捨てる。
NUMSTAT_MIN_FIELDS = 2
# for-each-ref のフォーマットは name/head/upstream/track の 4 列固定。
BRANCH_REF_FIELDS = 4
# 未コミット内容変更ファイルのプレビュー表示件数。
DIRTY_PREVIEW_LIMIT = 3


def git(*args: str, cwd: str | Path | None = None, strip: bool = True) -> str:
    """git を実行して stdout を返す。失敗時は空文字列。

    `strip=False` は `status --porcelain` のようなカラム位置に意味がある出力用。
    porcelain は `XY <path>` 形式で先頭がスペースになりうるため、strip すると
    パス抽出が 1 文字ずれる。
    """
    result = subprocess.run(  # noqa: S603 — 固定コマンド "git" + 呼び出し元が組み立てる固定引数列のみ
        ["git", *args],  # noqa: S607 — PATH 上の git を使う想定 (フルパス固定は環境依存になるため避ける)
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip() if strip else result.stdout.rstrip("\n")


def git_ok(*args: str, cwd: str | Path | None = None) -> bool:
    """git の終了コードが 0 かどうかだけを見る。"""
    result = subprocess.run(  # noqa: S603 — 固定コマンド "git" + 呼び出し元が組み立てる固定引数列のみ
        ["git", *args],  # noqa: S607 — PATH 上の git を使う想定 (フルパス固定は環境依存になるため避ける)
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


@dataclass
class Worktree:
    """1 つの `git worktree` エントリの状態と削除可否判定の結果。"""

    path: str
    head: str
    branch: str | None
    detached: bool
    is_main: bool
    locked: bool
    lock_reason: str
    exists: bool
    merged: bool
    ahead: int
    dirty_files: list[str] = field(default_factory=list)
    dirty_kind: str = "clean"  # clean | mode-only | content
    verdict: str = ""
    reasons: list[str] = field(default_factory=list)


def parse_worktrees(repo: Path) -> list[Worktree]:
    """`git worktree list --porcelain` を構造化する。"""
    out = git("worktree", "list", "--porcelain", cwd=repo)
    blocks = [b for b in out.split("\n\n") if b.strip()]
    worktrees: list[Worktree] = []
    for i, block in enumerate(blocks):
        path = ""
        head = ""
        branch = None
        detached = False
        locked = False
        lock_reason = ""
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree ") :]
            elif line.startswith("HEAD "):
                head = line[len("HEAD ") :]
            elif line.startswith("branch "):
                branch = line[len("branch ") :].removeprefix("refs/heads/")
            elif line == "detached":
                detached = True
            elif line.startswith("locked"):
                locked = True
                lock_reason = line[len("locked") :].strip()
        if not path:
            continue
        worktrees.append(
            Worktree(
                path=path,
                head=head,
                branch=branch,
                detached=detached,
                is_main=(i == 0),
                locked=locked,
                lock_reason=lock_reason,
                exists=Path(path).is_dir(),
                merged=False,
                ahead=0,
            )
        )
    return worktrees


def inspect_dirty(repo_path: str) -> tuple[list[str], str]:
    """worktree の未コミット変更を調べ、(変更ファイル一覧, 種類) を返す。

    種類は clean / mode-only / content の 3 値。

    ファイルモード変更のみ (100644 -> 100755) は `mise run` などが実行権限を
    付けた副作用で頻出し、失う作業成果はない。しかし `git status --porcelain`
    では内容変更と同じ ` M` として出るため区別できない。そこで `--numstat` の
    追加/削除行数がすべて 0 かどうかで判定する。

    パス指定 (`-- <file>`) は使わない。porcelain のカラム解析ミスで壊れやすく、
    リポジトリ全体の diff を見れば同じ判定ができるため。
    """
    status = git("status", "--porcelain", cwd=repo_path, strip=False)
    files = [line[3:] for line in status.splitlines() if line.strip()]
    if not files:
        return [], "clean"

    # untracked ファイル (`??`) は内容そのものが成果なので即 content。
    if any(line.startswith("??") for line in status.splitlines()):
        return files, "content"

    numstat = git("diff", "--numstat", cwd=repo_path)
    staged = git("diff", "--cached", "--numstat", cwd=repo_path)
    for line in (numstat + "\n" + staged).splitlines():
        parts = line.split("\t")
        if len(parts) < NUMSTAT_MIN_FIELDS:
            continue
        added, deleted = parts[0], parts[1]
        # "-" はバイナリファイル。行数不明なので content 扱いで保護する。
        if added != "0" or deleted != "0":
            return files, "content"

    # numstat が出ているのに全部 0 行 = モード変更のみ。
    if numstat or staged:
        return files, "mode-only"
    # status には出たが diff に出ない (submodule の HEAD 差異など) は保護側へ。
    return files, "content"


def scan_worktrees(repo: Path, base: str, *, allow_locked: bool) -> list[Worktree]:
    """worktree ごとに削除可否を判定する。`allow_locked` はキーワード専用引数として渡す。"""
    worktrees = parse_worktrees(repo)
    for wt in worktrees:
        if wt.is_main:
            wt.verdict = "keep"
            wt.reasons.append("メインの作業ディレクトリ")
            continue

        if not wt.exists:
            wt.verdict = "prune"
            wt.reasons.append("ディレクトリが存在しない (git worktree prune で解消)")
            continue

        wt.merged = git_ok("merge-base", "--is-ancestor", wt.head, base, cwd=repo)
        count = git("rev-list", "--count", f"{base}..{wt.head}", cwd=repo)
        wt.ahead = int(count) if count.isdigit() else 0

        wt.dirty_files, wt.dirty_kind = inspect_dirty(wt.path)

        if not wt.merged:
            wt.verdict = "keep"
            wt.reasons.append(f"{base} にマージされていない (ahead={wt.ahead})")
            if wt.detached:
                wt.reasons.append("detached HEAD かつ未マージ: 消すと参照名がなく復旧困難")
        elif wt.dirty_kind == "content":
            wt.verdict = "keep"
            preview = ", ".join(wt.dirty_files[:DIRTY_PREVIEW_LIMIT])
            more_count = len(wt.dirty_files) - DIRTY_PREVIEW_LIMIT
            more = f" ほか {more_count} 件" if more_count > 0 else ""
            wt.reasons.append(f"未コミットの内容変更あり: {preview}{more}")
        elif wt.locked and not allow_locked:
            wt.verdict = "keep"
            wt.reasons.append(f"locked: {wt.lock_reason}")
        else:
            wt.verdict = "remove"
            wt.reasons.append(f"{base} にマージ済み")
            if wt.dirty_kind == "mode-only":
                wt.reasons.append("dirty はファイルモード変更のみ (作業成果なし)")
            if wt.locked:
                wt.reasons.append(f"locked だが --allow-locked 指定: {wt.lock_reason}")
    return worktrees


@dataclass
class Branch:
    """1 つのローカルブランチの状態と削除可否判定の結果。"""

    name: str
    head: str
    upstream: str | None
    upstream_gone: bool
    checked_out_at: str | None
    merged: bool
    verdict: str
    reasons: list[str] = field(default_factory=list)


def scan_branches(repo: Path, base: str, worktrees: list[Worktree]) -> list[Branch]:
    """ローカルブランチを分類する。worktree にチェックアウト中のものは削除不可。"""
    checked_out = {wt.branch: wt.path for wt in worktrees if wt.branch and wt.exists}
    fmt = "%(refname:short)%09%(objectname)%09%(upstream:short)%09%(upstream:track)"
    out = git("for-each-ref", "--format", fmt, "refs/heads/", cwd=repo)
    branches: list[Branch] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < BRANCH_REF_FIELDS:
            continue
        name, head, upstream, track = parts[0], parts[1], parts[2] or None, parts[3]
        gone = "gone" in track
        at = checked_out.get(name)
        merged = git_ok("merge-base", "--is-ancestor", head, base, cwd=repo)

        if name == base:
            verdict, reasons = "keep", ["base ブランチ"]
        elif at:
            verdict, reasons = "keep", [f"worktree にチェックアウト中: {at}"]
        elif not merged:
            verdict, reasons = "keep", [f"{base} にマージされていない"]
        else:
            verdict, reasons = "remove", [f"{base} にマージ済み"]
            if gone:
                reasons.append("上流が削除済み (: gone)")
            elif upstream is None:
                reasons.append("上流なし (ローカル専用)")

        branches.append(Branch(name, head, upstream, gone, at, merged, verdict, reasons))
    return branches


def scan_stale_remotes(repo: Path) -> list[str]:
    """prune 対象のリモート追跡参照を列挙する (削除はしない)。"""
    out = git("remote", "prune", "origin", "--dry-run", cwd=repo)
    return [line.split()[-1] for line in out.splitlines() if "would prune" in line or "pruned" in line]


def resolve_base(repo: Path, requested_base: str) -> str | None:
    """base ブランチ名を解決する。指定がなければ `origin/HEAD` から自動検出する。

    解決できない/存在しない場合は None を返す。
    """
    base = requested_base
    if not base:
        head_ref = git("symbolic-ref", "refs/remotes/origin/HEAD", cwd=repo)
        base = head_ref.split("/")[-1] if head_ref else "main"
    if not git_ok("rev-parse", "--verify", base, cwd=repo):
        return None
    return base


@dataclass
class ScanResult:
    """worktree / branch / stale remote ref の分類結果をまとめたもの。"""

    worktrees: list[Worktree]
    branches: list[Branch]
    stale_remotes: list[str]


def build_report(repo: Path, base: str, result: ScanResult, *, allow_locked: bool) -> dict:
    """診断結果を JSON 出力用の dict にまとめる。"""
    worktrees, branches, stale_remotes = result.worktrees, result.branches, result.stale_remotes
    return {
        "repo": str(repo),
        "base": base,
        "base_head": git("rev-parse", "--short", base, cwd=repo),
        "allow_locked": allow_locked,
        "worktrees": [asdict(w) for w in worktrees],
        "branches": [asdict(b) for b in branches],
        "stale_remote_refs": stale_remotes,
        "summary": {
            "worktrees_remove": sum(1 for w in worktrees if w.verdict == "remove"),
            "worktrees_prune": sum(1 for w in worktrees if w.verdict == "prune"),
            "worktrees_keep": sum(1 for w in worktrees if w.verdict == "keep"),
            "branches_remove": sum(1 for b in branches if b.verdict == "remove"),
            "branches_keep": sum(1 for b in branches if b.verdict == "keep"),
            "stale_remote_refs": len(stale_remotes),
        },
    }


def print_report(report: dict, result: ScanResult) -> None:
    """診断結果を人間向けのテキストとして標準出力に書き出す。"""
    base = report["base"]
    print(f"repo={report['repo']}  base={base} ({report['base_head']})")
    print()
    print("== worktrees ==")
    for w in result.worktrees:
        if w.is_main:
            continue
        mark = {"remove": "DELETE", "prune": "PRUNE ", "keep": "KEEP  "}[w.verdict]
        label = w.branch or "(detached)"
        print(f"  {mark} {label:<45} {w.path}")
        for r in w.reasons:
            print(f"         - {r}")
    print()
    print("== branches ==")
    for b in result.branches:
        if b.verdict == "keep" and b.name == base:
            continue
        mark = "DELETE" if b.verdict == "remove" else "KEEP  "
        print(f"  {mark} {b.name}")
        for r in b.reasons:
            print(f"         - {r}")
    if result.stale_remotes:
        print()
        print("== stale remote refs (prune 対象) ==")
        for r in result.stale_remotes:
            print(f"  PRUNE  {r}")
    print()
    print("== summary ==")
    for k, v in report["summary"].items():
        print(f"  {k}: {v}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="対象リポジトリ (default: cwd)")
    parser.add_argument("--base", default="", help="マージ判定の基準ブランチ (default: 自動検出)")
    parser.add_argument(
        "--allow-locked",
        action="store_true",
        help="locked な worktree もマージ済みなら削除候補に含める",
    )
    parser.add_argument("--json-out", default="", help="診断 JSON の出力先")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not git_ok("rev-parse", "--git-dir", cwd=repo):
        print(f"error: {repo} は git リポジトリではない", file=sys.stderr)
        return 1

    base = resolve_base(repo, args.base)
    if base is None:
        print(f"error: base ブランチ '{args.base}' が存在しない", file=sys.stderr)
        return 1

    worktrees = scan_worktrees(repo, base, allow_locked=args.allow_locked)
    branches = scan_branches(repo, base, worktrees)
    stale_remotes = scan_stale_remotes(repo)
    result = ScanResult(worktrees=worktrees, branches=branches, stale_remotes=stale_remotes)
    report = build_report(repo, base, result, allow_locked=args.allow_locked)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print_report(report, result)
    if args.json_out:
        print(f"\n診断 JSON: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
