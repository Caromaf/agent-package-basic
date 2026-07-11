"""sync_profile_deps.py の unit test。"""

# ruff: noqa: D403, D415, S101

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import sync_profile_deps


class ReferencedPackagesTest(unittest.TestCase):
    """dependencies.apm の依存形式ごとの検出を確認する。"""

    def test_recognizes_string_and_object_dependencies(self) -> None:
        """文字列形式と object 形式の package 名を両方取得する。"""
        lines = [
            "dependencies:\n",
            "  apm:\n",
            "    - Caromaf/agent-package-basic/packages/architecture-review#main\n",
            "    # Claude Code にだけ配布する\n",
            "    - git: Caromaf/agent-package-basic\n",
            "      path: packages/agent-team\n",
            "      ref: main\n",
            "      targets: [claude]\n",
        ]

        assert sync_profile_deps.referenced_packages(lines) == {"agent-team", "architecture-review"}

    def test_recognizes_quoted_path_first_object_dependency(self) -> None:
        """path が先頭キーかつ quote 付きでも package 名を取得する。"""
        lines = [
            "dependencies:\n",
            "  apm:\n",
            '    - path: "packages/agent-team"\n',
            "      git: Caromaf/agent-package-basic\n",
            "      ref: main\n",
        ]

        assert sync_profile_deps.referenced_packages(lines) == {"agent-team"}

    def test_recognizes_path_after_nested_object_value(self) -> None:
        """nested list の後に path が置かれても同じ object として認識する。"""
        lines = [
            "dependencies:\n",
            "  apm:\n",
            "    - git: Caromaf/agent-package-basic\n",
            "      targets:\n",
            "        - claude\n",
            "      path: packages/agent-team\n",
            "      ref: main\n",
        ]

        assert sync_profile_deps.referenced_packages(lines) == {"agent-team"}

    def test_recognizes_inline_comment_and_flow_mapping(self) -> None:
        """inline comment 付き path と flow mapping object を認識する。"""
        lines = [
            "dependencies:\n",
            "  apm:\n",
            "    - git: Caromaf/agent-package-basic\n",
            "      path: packages/agent-team # Claude Code only\n",
            "      ref: main\n",
            "    - {git: Caromaf/agent-package-basic, path: packages/architecture-review, ref: main}\n",
        ]

        assert sync_profile_deps.referenced_packages(lines) == {"agent-team", "architecture-review"}

    def test_ignores_dev_dependencies_and_other_sections(self) -> None:
        """devDependencies.apm や他 section の path は参照済みとして数えない。"""
        lines = [
            "dependencies:\n",
            "  apm:\n",
            "    - Caromaf/agent-package-basic/packages/architecture-review#main\n",
            "devDependencies:\n",
            "  apm:\n",
            "    - git: Caromaf/agent-package-basic\n",
            "      path: packages/agent-team\n",
            "metadata:\n",
            "  items:\n",
            "    - path: packages/other-package\n",
        ]

        assert sync_profile_deps.referenced_packages(lines) == {"architecture-review"}

    def test_ignores_path_outside_object_item(self) -> None:
        """list item の外にある path は dependency として数えない。"""
        lines = [
            "metadata:\n",
            "  path: packages/agent-team\n",
        ]

        assert sync_profile_deps.referenced_packages(lines) == set()


class MainTest(unittest.TestCase):
    """profile 同期時の重複防止と既存の追記動作を確認する。"""

    def test_object_dependency_is_not_appended_as_duplicate(self) -> None:
        """object 形式で参照済みの package を文字列形式で重複追記しない。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            packages = root / "packages"
            profiles = root / "profiles"
            self._create_package(packages, "architecture-review")
            self._create_package(packages, "agent-team")
            profile = profiles / "test" / "apm.yml"
            profile.parent.mkdir(parents=True)
            original = self._profile_text()
            profile.write_text(original, encoding="utf-8")

            with (
                patch.object(sync_profile_deps, "PACKAGES", packages),
                patch.object(sys, "argv", ["sync_profile_deps.py", "--profiles-dir", str(profiles)]),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                exit_code = sync_profile_deps.main()

            assert exit_code == 0
            assert profile.read_text(encoding="utf-8") == original

    def test_missing_dependency_is_appended_without_moving_object_comment(self) -> None:
        """不足分は従来どおり文字列形式で追記し、object のコメントは保つ。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            packages = root / "packages"
            profiles = root / "profiles"
            for name in ("agent-team", "architecture-review", "new-package"):
                self._create_package(packages, name)
            profile = profiles / "test" / "apm.yml"
            profile.parent.mkdir(parents=True)
            profile.write_text(self._profile_text(), encoding="utf-8")

            with (
                patch.object(sync_profile_deps, "PACKAGES", packages),
                patch.object(sys, "argv", ["sync_profile_deps.py", "--profiles-dir", str(profiles)]),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                exit_code = sync_profile_deps.main()

            actual = profile.read_text(encoding="utf-8")
            assert exit_code == 0
            assert (
                "    - Caromaf/agent-package-basic/packages/new-package#main\n"
                "    # Claude Code にだけ配布する\n"
                "    - git: Caromaf/agent-package-basic\n"
            ) in actual
            assert "Other/repository/packages/new-package#develop" not in actual
            assert actual.count("packages/agent-team") == 1

    def _create_package(self, packages: Path, name: str) -> None:
        """検証用の package directory と apm.yml を作る。"""
        package = packages / name
        package.mkdir(parents=True)
        (package / "apm.yml").write_text("name: test\n", encoding="utf-8")

    def _profile_text(self) -> str:
        """文字列形式と object 形式を併用する profile を返す。"""
        return (
            "dependencies:\n"
            "  apm:\n"
            "    - Caromaf/agent-package-basic/packages/architecture-review#main\n"
            "    # Claude Code にだけ配布する\n"
            "    - git: Caromaf/agent-package-basic\n"
            "      path: packages/agent-team\n"
            "      ref: main\n"
            "      targets: [claude]\n"
            "  mcp: []\n"
            "devDependencies:\n"
            "  apm:\n"
            "    - Other/repository/packages/dev-only#develop\n"
        )


if __name__ == "__main__":
    unittest.main()
