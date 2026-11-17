"""Unit tests for the bundled work-loop queue classifier."""

# ruff: noqa: PT027, S101 - match the repository's unittest and assertion test style.

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import Any

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "work-loop"
    / ".apm"
    / "skills"
    / "work-loop"
    / "scripts"
    / "work_queue.py"
)
SPEC = importlib.util.spec_from_file_location("work_queue", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
work_queue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(work_queue)


class ClassifyWorkTest(unittest.TestCase):
    """Check the state and replanning rules used before dispatching work."""

    def test_open_pending_decision_blocks_work(self) -> None:
        """An open pending Decision cannot be dispatched as ready work."""
        work, decision = self._issues(
            decision_state="OPEN",
            decision_body="decision-status: pending\ndecision-revision: 1",
        )

        result = work_queue.classify_work(work, [decision])

        assert result["state"] == "blocked"
        assert "unresolved" in result["reason"]

    def test_closed_decision_without_applied_record_needs_replan(self) -> None:
        """Closing a Decision alone does not record its plan in the Work issue."""
        work, decision = self._issues(
            decision_state="CLOSED",
            decision_body="decision-status: decided\ndecision-revision: 2\ndecision-outcome: Keep current API.",
            closed_at="2026-10-19T12:00:00Z",
        )

        result = work_queue.classify_work(work, [decision])

        assert result["state"] == "needs-replan"
        assert "no applied revision/closed-at record" in result["reason"]

    def test_matching_applied_revision_and_closed_at_is_ready(self) -> None:
        """A closed decision is ready only after its revision and close time are applied."""
        work, decision = self._issues(
            decision_state="CLOSED",
            decision_body="decision-status: decided\ndecision-revision: 2\ndecision-outcome: Keep current API.",
            closed_at="2026-10-19T12:00:00Z",
        )
        work["body"] = (
            "decision-applied: https://github.com/acme/project/issues/7 @ 2 ; closed-at: 2026-10-19T12:00:00Z"
        )

        result = work_queue.classify_work(work, [decision])

        assert result["state"] == "ready"

    def test_incomplete_blocked_by_connection_fails_closed(self) -> None:
        """A truncated blocker list must never make the Work issue ready."""
        work, _ = self._issues(
            decision_state="CLOSED",
            decision_body="decision-status: decided\ndecision-revision: 2\ndecision-outcome: Keep current API.",
            closed_at="2026-10-19T12:00:00Z",
        )
        work["blockedBy"] = {"nodes": [], "totalCount": 1}

        with self.assertRaises(work_queue.QueueError):
            work_queue.classify_work(work, [])

    def _issues(
        self,
        *,
        decision_state: str,
        decision_body: str,
        closed_at: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build one valid Work issue with one blocking Decision."""
        decision = {
            "number": 7,
            "title": "API choice",
            "body": decision_body,
            "state": decision_state,
            "closedAt": closed_at,
            "url": "https://github.com/acme/project/issues/7",
            "labels": [{"name": "ai-decision"}],
        }
        work = {
            "number": 8,
            "title": "Implement API",
            "body": "Plan the API implementation.",
            "state": "OPEN",
            "url": "https://github.com/acme/project/issues/8",
            "labels": [{"name": "ai-work"}],
            "blockedBy": {
                "nodes": [{"number": 7, "url": decision["url"]}],
                "totalCount": 1,
            },
        }
        return work, decision


if __name__ == "__main__":
    unittest.main()
