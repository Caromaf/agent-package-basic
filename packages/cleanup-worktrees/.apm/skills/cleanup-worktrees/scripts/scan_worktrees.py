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
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

# git diff --numstat の 1 行は "追加\t削除\tパス" の 3 列。パス欠落行は 2 列未満で捨てる。
NUMSTAT_MIN_FIELDS = 2
# for-each-ref のフォーマットは name/head/upstream/track の 4 列。ただし upstream と
# 同期済みのブランチは track が空で末尾タブになり、出力全体を strip すると最終行だけ
# 3 列になる。4 列を必須にすると「辞書順で最後かつ同期済み」のブランチが丸ごと分類から
# 落ちる (実測: ローカル main が origin/main と同一のとき main が branches に出なかった)。
# 必須は name と objectname の 2 列だけにして、足りない列は空文字で埋める。
BRANCH_REF_FIELDS = 4
BRANCH_REF_MIN_FIELDS = 2
# 未コミット内容変更ファイルのプレビュー表示件数。
DIRTY_PREVIEW_LIMIT = 3
# husk の top-level エントリ表示件数。
HUSK_ENTRY_LIMIT = 6
# husk 内で「作業成果ではない」と見なすディレクトリ名。これらの下のファイルしか
# 無ければ cache のみの残骸なので削除しても失うものがない。
NON_SOURCE_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".pnpm-store",
        ".venv",
        "venv",
        "uv-cache",
        ".uv-cache",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".turbo",
        ".next",
        "target",
        "dist",
        "build",
        ".gradle",
    }
)
# husk 走査 root として認める祖先ディレクトリ名の末尾。main worktree の親
# (例 ~/programs) を候補にすると兄弟リポジトリを全部 husk と誤報するため名前で絞る。
# 部分一致 ("worktree" を含む) にすると `claude-worktrees-<session>` のような
# 無関係な中間ディレクトリまで root になるので、末尾一致に限定する。
WORKTREE_DIR_SUFFIX = "worktrees"


def git(*args: str, cwd: str | Path | None = None, strip: bool = True) -> str:
    """git を実行して stdout を返す。失敗時は空文字列。

    `strip=False` は `status --porcelain` のようなカラム位置に意味がある出力用。
    porcelain は `XY <path>` 形式で先頭がスペースになりうるため、strip すると
    パス抽出が 1 文字ずれる。

    `encoding="utf-8"` は必須。`text=True` 単独だと locale encoding (Windows
    では cp932) でデコードされ、git が UTF-8 で吐くパスやブランチ名が化ける。
    化けた文字列はそのまま JSON へ流れるので、出力側だけ直しても直らない。
    """
    result = subprocess.run(  # noqa: S603 — 固定コマンド "git" + 呼び出し元が組み立てる固定引数列のみ
        ["git", *args],  # noqa: S607 — PATH 上の git を使う想定 (フルパス固定は環境依存になるため避ける)
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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
        encoding="utf-8",
        errors="replace",
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
    protected = protected_branches(repo, base)
    fmt = "%(refname:short)%09%(objectname)%09%(upstream:short)%09%(upstream:track)"
    out = git("for-each-ref", "--format", fmt, "refs/heads/", cwd=repo, strip=False)
    branches: list[Branch] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < BRANCH_REF_MIN_FIELDS:
            continue
        parts += [""] * (BRANCH_REF_FIELDS - len(parts))
        name, head, upstream, track = parts[0], parts[1], parts[2] or None, parts[3]
        gone = "gone" in track
        at = checked_out.get(name)
        merged = git_ok("merge-base", "--is-ancestor", head, base, cwd=repo)

        if name in protected:
            verdict, reasons = "keep", [protected[name]]
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


@dataclass
class Husk:
    """`git worktree list` に登録が無いのに実体が残っているディレクトリ。

    Windows で pnpm 済み worktree に `git worktree remove` を実行すると
    `Filename too long` (MAX_PATH) で失敗するが、git は**登録解除とファイル削除
    を分離している**ため登録解除だけ済んで実体が残る。`.git` も失われているので
    worktree として復帰できず、マージ判定もできない。
    """

    path: str
    files: int
    total_bytes: int
    top_entries: list[str]
    has_source: bool
    has_git: bool
    walk_errors: int
    verdict: str = "husk"
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 走査エラーがあるなら必ず保護側に倒す。reasons が「中身不明として保護」と
        # 書きながら judge が「削除可」になる矛盾を、生成時点で不可能にする。
        # 呼び出し側の計算順序に依存させると、このバグクラスが再発する。
        self.has_source = self.has_source or bool(self.walk_errors)


def norm_path(path: str | Path) -> str:
    """パス比較用に正規化する。Windows の大小文字差と区切り文字差を吸収する。

    `git worktree list --porcelain` は Windows でも `C:/Users/...` と forward
    slash で出すため、`Path` 同士の比較では実体と一致しないことがある。
    """
    return os.path.normcase(str(Path(path).resolve()))


def husk_roots(worktrees: list[Worktree]) -> list[Path]:
    """husk を探す親ディレクトリの候補を返す。

    **候補は「名前が `worktrees` で終わる祖先」だけに限る。** 「登録 worktree の親
    なら候補」にすると、main の親 (`~/programs`) を走査して兄弟リポジトリを全部
    husk と誤報したり、repo 内の任意のディレクトリ (`<main>/sandbox`) を走査して
    リポジトリ本体を削除候補として提示してしまう。

    入れ子レイアウト (`.codex/worktrees/<hash>/<repo>`) では `.codex/worktrees` が
    末尾一致で候補になり、容れ物の `<hash>` は登録パスの祖先として除外される。
    登録済み worktree が全滅して候補が空になる場合に備え、main 配下の既知レイアウト
    (`.claude/worktrees` / `.codex/worktrees`) も足す。
    """
    main = next((Path(w.path) for w in worktrees if w.is_main), None)
    # キーは比較用の正規化パス、値は表示用の元の表記 (normcase は Windows で
    # 小文字化するため、そのまま表示すると登録パスと表記が食い違う)。
    roots: dict[str, Path] = {}

    def add(cand: Path) -> None:
        roots.setdefault(norm_path(cand), cand)

    for wt in worktrees:
        if wt.is_main:
            continue
        # **root は名前が worktrees で終わる祖先だけに限る。** 「登録 worktree の
        # 親なら root」にすると、worktree が `<main>/sandbox/wt-1` のようにリポ内の
        # 任意のディレクトリ直下にある場合に `<main>/sandbox` が root になり、その
        # 兄弟であるリポジトリ本体の追跡ディレクトリが husk として列挙される。
        # node_modules だけを含む本体ディレクトリは「cache のみ = 削除可」と表示され、
        # robocopy /MIR の対象になりうる。入れ子レイアウト
        # (`.codex/worktrees/<hash>/<repo>`) は `.codex/worktrees` が末尾一致で root に
        # なり `<hash>` は containers 側で除外されるため、この制限で失うものはない。
        for anc in Path(wt.path).parents:
            if anc.name.lower().endswith(WORKTREE_DIR_SUFFIX):
                add(anc)
    if main:
        for known in (".claude/worktrees", ".codex/worktrees"):
            add(main / known)
    # ponytail: 親ディレクトリ名が worktrees で終わらないレイアウト (main の兄弟に
    # 直置きされた ~/programs/repo-wt-1846、repo 内の <main>/sandbox/wt-1 など) の
    # husk は検出できない。兄弟リポジトリやリポジトリ本体と区別できず、誤検出の代償が
    # 「本体を削除候補として提示する」なので検出漏れ側に倒している。必要になったら
    # 「親に .git を持つ兄弟がいるか」「git が追跡しているか」で判定する方向に拡張する。
    return sorted((p for p in roots.values() if p.is_dir()), key=str)


def is_reparse_point(path: Path, errors: list[OSError] | None = None) -> bool:
    """symlink / junction / mount point のいずれかを判定する。

    **判定できなかった場合の「安全側」は呼び出し側によって逆になる。** 候補を除外
    する用途では `True` (触らない) が安全だが、`os.walk` の枝刈りに使うと `True` は
    「そこへ降りない = `onerror` も呼ばれない」になり、中身不明なのに `walk_errors`
    が 0 のまま「cache のみ = 削除可」と結論してしまう。枝刈りで使う側は `errors` を
    渡し、数え落とした分を必ず保護側の材料として積むこと。

    **Windows の junction (`mklink /J`) は `Path.is_symlink()` が False を返す。**
    symlink ガードだけでは素通りするため、junction が husk 候補に入り `robocopy /MIR`
    がリンク先の実体まで消す経路ができる。`os.walk` も `islink` が False だと
    `followlinks=False` が効かずリンク先へ降りて中身を数えてしまい、リンク先が cache
    構成なら「cache のみ = 削除可」と表示される。reparse point は一律で除外する。
    """
    try:
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as exc:
        if errors is not None:
            errors.append(exc)
        return True  # 判定できないものは触らない
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attrs & reparse) or path.is_symlink()


def worktree_git_state(path: Path) -> tuple[bool, bool]:
    """(`.git` が見つかったか, 生存中の worktree か) を返す。

    **`.codex/worktrees` は全リポジトリ共有のストア**なので、別リポジトリの生存中の
    worktree が混ざる。当リポジトリの `git worktree list` には載らないため容れ物として
    除外されず、husk 候補に入ってしまう。さらに入れ子レイアウト (`<hash>/<repo>`) では
    `.git` が 2 階層下にあり、深さ 1 だけ見ると「`.git` が無い = 復帰不能な残骸」という
    **実態と逆の理由**を付けてユーザーに削除判断を求めることになる。

    深さ 2 まで探し、`gitdir:` の指す先が実在するなら生存中と見なす。判定できない場合は
    生存側 (触らない) に倒す。
    """
    try:
        children = [c for c in path.iterdir() if c.is_dir() and not is_reparse_point(c)]
    except OSError:
        children = []
    for marker in (path / ".git", *(c / ".git" for c in children)):
        if not marker.exists():
            continue
        if marker.is_dir():
            return True, True  # 通常の clone の .git ディレクトリ
        try:
            head = marker.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return True, True  # 読めない = 判定不能なので触らない側へ
        gitdir = head.removeprefix("gitdir:").strip()
        # gitdir が消えていれば孤児化した worktree (= husk)、実在すれば生存中。
        return True, bool(gitdir) and Path(gitdir).exists()
    return False, False


def measure_husk(path: Path, *, has_git: bool) -> Husk:
    """husk の中身を数えて「作業成果を含むか」を判定する。

    `os.walk` は既定でエラーを黙って捨てるため `onerror` を必ず渡す。MAX_PATH で
    途中から辿れなかった場合に「cache のみ」と誤分類すると、復元不能な作業成果を
    削除する判断に直結する。エラーが 1 件でもあれば安全側 (has_source) に倒す。
    """
    errors: list[OSError] = []
    files = 0
    total = 0
    has_source = False
    # hardlink (pnpm store / uv cache が多用する) の二重計上を防ぐ。同じ実体を
    # 複数回足すと削減見込み容量を過大申告する。
    seen_inodes: set[tuple[int, int]] = set()
    for dirpath, dirnames, filenames in os.walk(path, onerror=errors.append):
        dirnames[:] = [d for d in dirnames if not is_reparse_point(Path(dirpath) / d, errors)]
        if not filenames:
            continue
        parts = Path(dirpath).relative_to(path).parts
        if not any(part in NON_SOURCE_DIRS for part in parts):
            has_source = True
        files += len(filenames)
        for name in filenames:
            try:
                st = (Path(dirpath) / name).stat()
            except OSError as exc:
                # 1 ファイル分の失敗で walk 全体を捨てず、安全側判定の材料として積む。
                errors.append(exc)
                continue
            key = (st.st_dev, st.st_ino)
            if st.st_ino and key in seen_inodes:
                continue
            if st.st_ino:
                seen_inodes.add(key)
            total += st.st_size

    try:
        entries = sorted(p.name for p in path.iterdir())
    except OSError as exc:
        entries = []
        errors.append(exc)
    # 走査エラーによる安全側への倒しは Husk.__post_init__ が強制するので、ここで
    # has_source を補正する必要はない (補正の順序に依存させないための設計)。
    husk = Husk(
        path=str(path),
        files=files,
        total_bytes=total,
        top_entries=entries[:HUSK_ENTRY_LIMIT],
        has_source=has_source,
        has_git=has_git,
        walk_errors=len(errors),
    )
    husk.reasons = husk_reasons(husk)
    return husk


def husk_reasons(husk: Husk) -> list[str]:
    """husk の扱いをユーザーが判断できる理由文を組み立てる。"""
    reasons = ["git worktree list に登録が無いが実体が残っている"]
    if husk.has_git:
        reasons.append(".git が残っている: 未登録の worktree / clone の可能性")
    else:
        reasons.append(".git が無い: worktree として復帰不能 (マージ判定不可)")
    if husk.walk_errors:
        reasons.append(f"走査エラー {husk.walk_errors} 件 (MAX_PATH 等): 中身不明として保護")
    elif husk.files == 0:
        reasons.append("ファイルは 0 件で空ディレクトリの殻のみ: rmdir で解消 (容量影響なし)")
    elif husk.has_source:
        reasons.append("cache 以外のファイルを含む: 未コミット作業が失われる可能性あり")
    else:
        reasons.append(f"cache のみ ({', '.join(husk.top_entries)}): 削除で失う成果なし")
    return reasons


def scan_husks(worktrees: list[Worktree]) -> list[Husk]:
    """worktree の親ディレクトリを走査し、登録パスとの差分を husk として返す。

    `git worktree list` は登録分しか列挙しないので、登録解除だけ済んだ残骸は
    scan からも消えてしまう。実測では「全件分類済み」と報告した状態で 234M /
    13225 files の husk が残っていた。**判定は DELETE ではなく HUSK** とし、
    マージ判定ができないことを明示してユーザーへ回す。
    """
    registered = {norm_path(w.path) for w in worktrees}
    # 登録パスの祖先は「入れ子 worktree の容れ物」なので husk ではない。
    containers = {norm_path(anc) for w in worktrees for anc in Path(w.path).parents}
    husks: list[Husk] = []
    seen: set[str] = set()
    for root in husk_roots(worktrees):
        try:
            children = sorted(root.iterdir(), key=str)
        except OSError:
            continue
        for child in children:
            key = norm_path(child)
            if key in registered or key in containers or key in seen:
                continue
            if is_reparse_point(child) or not child.is_dir():
                continue
            seen.add(key)
            has_git, live = worktree_git_state(child)
            if live:
                # 別リポジトリの生存中 worktree。当リポジトリの片付け対象ではないので
                # 候補から外す (削除判断をユーザーに求めること自体が事故の入口)。
                continue
            husks.append(measure_husk(child, has_git=has_git))
    return husks


def resolve_base(repo: Path, requested_base: str) -> tuple[str | None, list[str]]:
    """base を解決する。ローカルブランチではなく remote-tracking ref を優先する。

    `git symbolic-ref refs/remotes/origin/HEAD` の**末尾セグメントだけ**を取ると
    `origin/main` ではなく**ローカルの `main`** を解決してしまう。primary の
    ローカル main が pull されていないと、直前にマージされたブランチが「未マージ」
    と誤判定されて削除対象から漏れる (実測: local main が 1 commit 古く、該当
    ブランチが KEEP に回った)。判定は常に fetch 済みの remote-tracking ref で行う。

    戻り値は (base ref, 警告メッセージ). 解決できない場合は (None, 警告).
    """
    warnings: list[str] = []
    base = requested_base
    if not base:
        base = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=repo) or "origin/main"

    if not base.startswith("origin/"):
        remote = f"origin/{base}"
        if git_ok("rev-parse", "--verify", remote, cwd=repo):
            base = remote

    if not git_ok("rev-parse", "--verify", base, cwd=repo):
        return None, warnings

    # base が remote-tracking ref なら、同名ローカルブランチとの乖離を必ず確認する。
    # 自動検出で最初から `origin/main` になる経路でも警告が要る: 判定自体は正しく
    # なるが、後続の `git branch -d` はローカル基準で判定するため拒否されるため。
    local = base.removeprefix("origin/")
    if local != base and git_ok("rev-parse", "--verify", f"refs/heads/{local}", cwd=repo):
        behind = git("rev-list", "--count", f"refs/heads/{local}..{base}", cwd=repo)
        if behind.isdigit() and int(behind) > 0:
            warnings.append(
                f"ローカル {local} は {base} より {behind} commit 古い。判定は {base} を基準にする。"
                f"`git branch -d` はローカル基準なので拒否されることがある (SKILL.md Step 4 参照)"
            )
    return base, warnings


def base_name_aliases(base: str) -> set[str]:
    """base 文字列から導ける保護すべきブランチ名 (リポジトリ非依存)。

    base が `origin/main` になると `name == base` がローカル `main` に一致しなく
    なる。ローカル main は origin より古い = マージ済み判定になるため、保護を
    外すと**ローカル main 自体が DELETE 候補に出る**。`refs/remotes/origin/main`
    のようなフルレフで渡された場合も同じ穴が開くので、接頭辞を剥がしてから集める。
    """
    short = base.removeprefix("refs/remotes/").removeprefix("refs/heads/")
    return {n for n in (base, short, short.removeprefix("origin/")) if n}


def protected_branches(repo: Path, base: str) -> dict[str, str]:
    """削除してはいけないローカルブランチ名 → 保護理由。base 以外の default branch も守る。

    `--base develop` のように base を差し替えると、default branch (`main`) が
    develop の祖先ならマージ済み判定で DELETE 候補に出る。`git branch -d` も
    「マージ済み」として受理するので防波堤にならない。default branch と現在の
    HEAD は base が何であっても常に保護する。

    理由を名前ごとに持つのは「各判定の理由を必ず添える」という skill の原則のため。
    1 つの集合に潰すと、base ではない default branch が守られたときも理由が
    「base ブランチ」になり、ユーザーへの提示材料として誤りになる。
    """
    protected = dict.fromkeys(base_name_aliases(base), "base ブランチ")
    head_ref = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=repo)
    if head_ref:
        for name in base_name_aliases(head_ref):
            protected.setdefault(name, "default branch (base ではないが常に保護)")
    current = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    if current and current != "HEAD":
        protected.setdefault(current, "リポジトリの現在の HEAD")
    return protected


@dataclass
class ScanResult:
    """worktree / branch / stale remote ref の分類結果をまとめたもの。"""

    worktrees: list[Worktree]
    branches: list[Branch]
    stale_remotes: list[str]
    husks: list[Husk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_report(repo: Path, base: str, result: ScanResult, *, allow_locked: bool) -> dict:
    """診断結果を JSON 出力用の dict にまとめる。"""
    worktrees, branches, stale_remotes = result.worktrees, result.branches, result.stale_remotes
    husks = result.husks
    return {
        "repo": str(repo),
        "base": base,
        "base_head": git("rev-parse", "--short", base, cwd=repo),
        "allow_locked": allow_locked,
        "warnings": result.warnings,
        "protected_branches": protected_branches(repo, base),
        "worktrees": [asdict(w) for w in worktrees],
        "branches": [asdict(b) for b in branches],
        "husks": [asdict(h) for h in husks],
        "stale_remote_refs": stale_remotes,
        "summary": {
            "worktrees_remove": sum(1 for w in worktrees if w.verdict == "remove"),
            "worktrees_prune": sum(1 for w in worktrees if w.verdict == "prune"),
            "worktrees_keep": sum(1 for w in worktrees if w.verdict == "keep"),
            "branches_remove": sum(1 for b in branches if b.verdict == "remove"),
            "branches_keep": sum(1 for b in branches if b.verdict == "keep"),
            "husks": len(husks),
            "husks_cache_only": sum(1 for h in husks if not h.has_source),
            "husks_with_source": sum(1 for h in husks if h.has_source),
            "husk_bytes": sum(h.total_bytes for h in husks),
            "stale_remote_refs": len(stale_remotes),
        },
    }


def print_branches(branches: list[Branch], protected: set[str]) -> None:
    """branches セクションを出力する。base 相当の保護は列挙から省く。"""
    print()
    print("== branches ==")
    for b in branches:
        if b.verdict == "keep" and b.name in protected:
            continue
        mark = "DELETE" if b.verdict == "remove" else "KEEP  "
        print(f"  {mark} {b.name}")
        for r in b.reasons:
            print(f"         - {r}")


def print_husks(husks: list[Husk]) -> None:
    """husk セクションを出力する。source を含むものは DELETE に混ぜられないので目立たせる。"""
    if not husks:
        return
    print()
    print("== husks (登録解除だけ済んだ実体) ==")
    for h in husks:
        size_mb = h.total_bytes / 1024 / 1024
        judge = "要ユーザー判断" if h.has_source else "削除可"
        print(f"  HUSK   {h.path}  [{judge}]")
        print(f"         {h.files} files / {size_mb:.0f}M")
        for r in h.reasons:
            print(f"         - {r}")


def print_report(report: dict, result: ScanResult) -> None:
    """診断結果を人間向けのテキストとして標準出力に書き出す。"""
    base = report["base"]
    print(f"repo={report['repo']}  base={base} ({report['base_head']})")
    for w in report["warnings"]:
        print(f"  WARN  {w}")
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
    print_branches(result.branches, set(report["protected_branches"]))
    print_husks(result.husks)
    if result.stale_remotes:
        print()
        print("== stale remote refs (prune 対象) ==")
        for r in result.stale_remotes:
            print(f"  PRUNE  {r}")
    print()
    print("== summary ==")
    for k, v in report["summary"].items():
        print(f"  {k}: {v}")


def make_junction_fixtures(root: Path, container: Path, cache_husk: Path) -> None:
    """self-check 用に junction を 2 本張る (Windows 以外と作成失敗時は何もしない)。

    既存の assert がそのまま回帰ガードになるように配置する。`is_symlink()` 判定に
    戻すと `junction-husk` が husk 集合に混入して集合比較が落ち、`os.walk` の枝刈りを
    戻すと `cache-only` が junction 先の source を数えて has_source が True になり
    「node_modules だけを source 扱いにしている」の assert が落ちる。
    """
    if sys.platform != "win32":
        print("self-check: junction フィクスチャは win32 以外では作らない (重大 3 の回帰ガード無効)")
        return
    target = root / "junction-target"
    (target / "src").mkdir(parents=True)
    (target / "src" / "c.py").write_text("j", encoding="utf-8")
    for link in (container / "junction-husk", cache_husk / "link"):
        result = subprocess.run(  # noqa: S603 — 固定コマンド + 一時ディレクトリ内の自前パスのみ
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],  # noqa: S607
            capture_output=True,
            check=False,
        )
        # 作成に失敗すると junction 用の assert が「何も検査せずに通る」状態になる。
        if result.returncode != 0:
            print(f"self-check: junction 作成失敗 ({link.name}): 重大 3 の回帰ガードが無効")


def build_self_check_tree(root: Path) -> tuple[Path, list[Worktree]]:
    """self-check 用のディレクトリ構成を作り、(container, 登録済み worktree) を返す。

    各フィクスチャは「これを消すと既存の assert が落ちる」形で配置してある。退行を
    入れたときに落ちる assert を `make_junction_fixtures` の docstring と併せて読む。
    """
    main_wt = root / "repo"
    container = main_wt / ".claude" / "worktrees"
    live = container / "live"
    (live / "src").mkdir(parents=True)
    (live / "src" / "a.py").write_text("x", encoding="utf-8")
    cache_husk = container / "cache-only"
    (cache_husk / "node_modules" / "pkg").mkdir(parents=True)
    (cache_husk / "node_modules" / "pkg" / "index.js").write_text("x", encoding="utf-8")
    # pnpm store / uv cache と同じ hardlink 構成。実体 1 つを 2 回数えないこと。
    big = cache_husk / "node_modules" / "pkg" / "big.bin"
    big.write_bytes(b"0" * 4096)
    os.link(big, big.with_name("big-link.bin"))
    # 表示用パスの大小文字が保たれるか見るため、意図的に大文字を混ぜる。
    source_husk = container / "With-Source"
    (source_husk / "src").mkdir(parents=True)
    (source_husk / "src" / "b.py").write_text("y", encoding="utf-8")
    (container / "empty-shell" / "nested").mkdir(parents=True)  # files=0 の殻
    (main_wt / "apps").mkdir()  # main 配下の普通のディレクトリ: husk ではない
    (root / "other-repo").mkdir()  # main の兄弟: 走査してはいけない
    # 名前に worktree を含むが worktrees で終わらない容れ物。ここを root にすると
    # リポジトリ本体の兄弟ディレクトリが husk として列挙される。
    loose = main_wt / "My-Worktree-Stuff"
    (loose / "wt-x").mkdir(parents=True)
    (loose / "sibling-dir").mkdir()
    (loose / "sibling-dir" / "f.txt").write_text("z", encoding="utf-8")
    # 別リポジトリの生存中 worktree (共有ストアに混ざる)。`.git` は 2 階層下の
    # ファイルで、gitdir が実在するので husk にしてはいけない。
    other_admin = root / "other-repo-git" / "worktrees" / "wt"
    other_admin.mkdir(parents=True)
    (container / "other-repo-live" / "repo").mkdir(parents=True)
    (container / "other-repo-live" / "repo" / ".git").write_text(f"gitdir: {other_admin}", encoding="utf-8")
    # gitdir が消えた孤児 worktree は husk 側 (has_git=True で理由を書き分ける)。
    (container / "other-repo-dead" / "repo").mkdir(parents=True)
    (container / "other-repo-dead" / "repo" / ".git").write_text(
        f"gitdir: {root / 'gone' / 'worktrees' / 'wt'}", encoding="utf-8"
    )
    make_junction_fixtures(root, container, cache_husk)

    def fixture(path: Path, *, is_main: bool) -> Worktree:
        return Worktree(
            path=str(path),
            head="0" * 40,
            branch=path.name,
            detached=False,
            is_main=is_main,
            locked=False,
            lock_reason="",
            exists=True,
            merged=not is_main,
            ahead=0,
        )

    return container, [
        fixture(main_wt, is_main=True),
        fixture(live, is_main=False),
        fixture(loose / "wt-x", is_main=False),
    ]


def self_check() -> int:
    """husk 検出のロジックだけを一時ディレクトリで検証する (依存なしの自己診断)。

    ponytail: base 解決とマージ判定は実 git リポジトリが必要なのでここでは見ない。
    それらは SKILL.md の Step 2 の実行そのものが検証になる。
    """
    with tempfile.TemporaryDirectory() as tmp:
        container, worktrees = build_self_check_tree(Path(tmp))
        husks = {Path(h.path).name: h for h in scan_husks(worktrees)}

        expected = {"cache-only", "With-Source", "empty-shell", "other-repo-dead"}
        assert set(husks) == expected, f"想定外の husk 集合: {set(husks)}"
        assert husks["other-repo-dead"].has_git, "2 階層下の .git を見落としている"
        assert not husks["cache-only"].has_source, "node_modules だけを source 扱いにしている"
        assert husks["With-Source"].has_source, "src/*.py を cache 扱いにしている"
        assert husks["cache-only"].files == 3, f"files={husks['cache-only'].files}"
        # index.js(1) + big.bin(4096)。big-link.bin は同一実体なので加算しない。
        assert husks["cache-only"].total_bytes == 4097, (
            f"hardlink を二重計上している: {husks['cache-only'].total_bytes}"
        )
        assert husks["empty-shell"].files == 0, "空ディレクトリの殻でファイルを数えている"
        assert "殻" in " ".join(husks["empty-shell"].reasons), "files=0 を cache のみと説明している"
        assert all(h.verdict == "husk" for h in husks.values()), "husk が DELETE 判定になっている"
        # 表示パスは root 部分まで元の表記を保つこと (normcase は root 側を小文字化する)。
        shown_parent = str(Path(husks["With-Source"].path).parent)
        assert shown_parent == str(container), f"表示パスが正規化されている: {shown_parent}"
        # 走査エラーがあれば生成時点で保護側に倒る不変条件 (iterdir だけが失敗する
        # 状態は移植性のあるフィクスチャで作れないため、型の側で直接確かめる)。
        errored = Husk(path="x", files=1, total_bytes=0, top_entries=[], has_source=False, has_git=False, walk_errors=1)
        assert errored.has_source, "走査エラーがあるのに has_source が False のままになる"

        for name, want in (
            ("origin/main", {"origin/main", "main"}),
            ("refs/remotes/origin/main", {"refs/remotes/origin/main", "origin/main", "main"}),
        ):
            assert base_name_aliases(name) == want, f"{name} の保護名が不足: {base_name_aliases(name)}"
    print("self-check: ok")
    return 0


def main() -> int:
    # Windows の locale encoding (cp932) では日本語の理由文が化けるので UTF-8 に固定する。
    # 出力が差し替えられている実行環境 (StringIO など) には reconfigure が無い。
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="対象リポジトリ (default: cwd)")
    parser.add_argument("--base", default="", help="マージ判定の基準ブランチ (default: 自動検出)")
    parser.add_argument(
        "--allow-locked",
        action="store_true",
        help="locked な worktree もマージ済みなら削除候補に含める",
    )
    parser.add_argument("--json-out", default="", help="診断 JSON の出力先")
    parser.add_argument("--self-check", action="store_true", help="husk 検出ロジックの自己診断のみ実行")
    args = parser.parse_args()

    if args.self_check:
        return self_check()

    repo = Path(args.repo).resolve()
    if not git_ok("rev-parse", "--git-dir", cwd=repo):
        print(f"error: {repo} は git リポジトリではない", file=sys.stderr)
        return 1

    base, warnings = resolve_base(repo, args.base)
    if base is None:
        print(f"error: base ブランチ '{args.base}' が存在しない", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"warn: {w}", file=sys.stderr)

    worktrees = scan_worktrees(repo, base, allow_locked=args.allow_locked)
    branches = scan_branches(repo, base, worktrees)
    stale_remotes = scan_stale_remotes(repo)
    result = ScanResult(
        worktrees=worktrees,
        branches=branches,
        stale_remotes=stale_remotes,
        husks=scan_husks(worktrees),
        warnings=warnings,
    )
    report = build_report(repo, base, result, allow_locked=args.allow_locked)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # JSON は仕様上 UTF-8。encoding 省略だと Windows で cp932 になり
        # json.load(open(path, encoding="utf-8")) が UnicodeDecodeError で落ちる。
        # newline="" は Path.write_text が LF を CRLF に変換するのを防ぐため。
        with open(out_path, "w", encoding="utf-8", newline="") as fp:  # noqa: PTH123
            json.dump(report, fp, ensure_ascii=False, indent=2)
            fp.write("\n")

    print_report(report, result)
    if args.json_out:
        print(f"\n診断 JSON: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
