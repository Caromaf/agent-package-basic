# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# ruff: noqa: EM101, EM102, TRY003
# Context-rich fail-closed messages are part of this read-only CLI's output contract.
"""Read-only dependency and replanning gate for ai-work GitHub issues."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Sequence

LABEL_WORK = "ai-work"
LABEL_DECISION = "ai-decision"
LABEL_NEEDS_REPLAN = "needs-replan"
ISSUE_FIELDS = "number,title,body,state,url,labels,blockedBy"
DECISION_FIELDS = "number,title,body,state,closedAt,url,labels"
MAX_WORK_ISSUES = 1000
REPO_NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
HOST_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"
DECISION_STATUS_PATTERN = re.compile(r"^\s*decision-status:\s*(.*?)\s*$", re.IGNORECASE)
DECISION_REVISION_PATTERN = re.compile(r"^\s*decision-revision:\s*(.*?)\s*$", re.IGNORECASE)
DECISION_OUTCOME_PATTERN = re.compile(r"^\s*decision-outcome:\s*(.*?)\s*$", re.IGNORECASE)
APPLIED_PATTERN = re.compile(
    r"^\s*decision-applied:\s*(https?://\S+)\s*@\s*(\d+)\s*;\s*closed-at:\s*(\S+)\s*$",
    re.IGNORECASE,
)


class QueueError(Exception):
    """An input, GitHub CLI, or completeness failure that prevents a safe decision."""

    @classmethod
    def create(cls, message: str) -> QueueError:
        """Build an exception with a contextual message at a call site."""
        return cls(message)


def validate_repo(repo: str) -> str:
    """Validate the CLI's owner/repo argument."""
    if not re.fullmatch(rf"{REPO_NAME_PATTERN}/{REPO_NAME_PATTERN}", repo):
        raise argparse.ArgumentTypeError(f"Invalid repository {repo!r}; expected owner/repo.")
    return repo


def issue_repo_from_url(issue_url: str) -> str:
    """Return owner/repo from a canonical GitHub issue URL."""
    _, owner, repo, _ = issue_url_identity(issue_url)
    return f"{owner}/{repo}"


def issue_url_identity(issue_url: str) -> tuple[str, str, str, int]:
    """Parse a canonical HTTPS issue URL into host, owner, repo, and positive number."""
    try:
        parts = urlsplit(issue_url)
    except ValueError as exc:
        raise QueueError(f"Unrecognized issue URL: {issue_url!r}.") from exc
    path_parts = [part for part in parts.path.split("/") if part]
    try:
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise QueueError(f"Unrecognized issue URL: {issue_url!r}.") from exc
    if (
        parts.scheme != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or len(path_parts) != 4
        or path_parts[2] != "issues"
        or not re.fullmatch(REPO_NAME_PATTERN, path_parts[0])
        or not re.fullmatch(REPO_NAME_PATTERN, path_parts[1])
        or not re.fullmatch(r"[1-9][0-9]*", path_parts[3])
        or not re.fullmatch(HOST_PATTERN, host)
        or issue_url != issue_url.strip()
        or "?" in issue_url
        or "#" in issue_url
    ):
        raise QueueError(f"Unrecognized issue URL: {issue_url!r}.")
    canonical_host = host.lower()
    if port is not None:
        canonical_host = f"{canonical_host}:{port}"
    if parts.path != f"/{path_parts[0]}/{path_parts[1]}/issues/{path_parts[3]}":
        raise QueueError(f"Issue URL is not canonical: {issue_url!r}.")
    try:
        issue_number = int(path_parts[3])
    except ValueError as exc:
        raise QueueError(f"Issue URL has an invalid issue number: {issue_url!r}.") from exc
    return canonical_host, path_parts[0].lower(), path_parts[1].lower(), issue_number


def repository_url_identity(repository_url: str) -> tuple[str, str, str]:
    """Parse the canonical HTTPS URL returned by `gh repo view`."""
    try:
        parts = urlsplit(repository_url)
    except ValueError as exc:
        raise QueueError("GitHub CLI returned an invalid repository URL.") from exc
    path_parts = [part for part in parts.path.split("/") if part]
    try:
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise QueueError("GitHub CLI returned an invalid repository URL.") from exc
    if (
        parts.scheme != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or len(path_parts) != 2
        or not re.fullmatch(REPO_NAME_PATTERN, path_parts[0])
        or not re.fullmatch(REPO_NAME_PATTERN, path_parts[1])
        or not re.fullmatch(HOST_PATTERN, host)
        or "?" in repository_url
        or "#" in repository_url
    ):
        raise QueueError("GitHub CLI returned a repository URL with an unknown format.")
    canonical_host = host.lower()
    if port is not None:
        canonical_host = f"{canonical_host}:{port}"
    if parts.path != f"/{path_parts[0]}/{path_parts[1]}":
        raise QueueError("GitHub CLI returned a non-canonical repository URL.")
    return canonical_host, path_parts[0].lower(), path_parts[1].lower()


def canonical_repository(repo_argument: str) -> tuple[tuple[str, str, str], str]:
    """Resolve and validate a repository through the native GitHub CLI."""
    response = run_gh(["repo", "view", repo_argument, "--json", "url"])
    if not isinstance(response, dict) or not isinstance(response.get("url"), str):
        raise QueueError("GitHub CLI returned no canonical repository URL.")
    identity = repository_url_identity(response["url"])
    requested_parts = repo_argument.split("/")
    if len(requested_parts) == 2:
        requested_identity = (identity[0], requested_parts[0].lower(), requested_parts[1].lower())
    elif len(requested_parts) == 3:
        requested_identity = (requested_parts[0].lower(), requested_parts[1].lower(), requested_parts[2].lower())
    else:
        raise QueueError("Repository identifier has an unknown format.")
    if identity != requested_identity:
        raise QueueError("Canonical repository URL does not match the requested repository identity.")
    return identity, repo_argument


def parse_issue_argument(value: str) -> tuple[int, tuple[str, str, str] | None]:
    """Accept only a positive issue number or a canonical HTTPS issue URL."""
    if re.fullmatch(r"[1-9][0-9]*", value):
        try:
            return int(value), None
        except ValueError as exc:
            raise QueueError("Issue number is too large or invalid.") from exc
    host, owner, repo, number = issue_url_identity(value)
    return number, (host, owner.lower(), repo.lower())


def parse_timestamp(value: object) -> datetime | None:
    """Parse a timezone-aware GitHub timestamp into UTC."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def labels_of(issue: dict[str, Any]) -> set[str]:
    """Parse GitHub CLI labels while rejecting unknown representations."""
    labels = issue.get("labels")
    if not isinstance(labels, list):
        raise QueueError("Issue labels are missing or have an unknown format.")
    names: set[str] = set()
    for label in labels:
        if isinstance(label, str):
            names.add(label)
        elif isinstance(label, dict) and isinstance(label.get("name"), str):
            names.add(label["name"])
        else:
            raise QueueError("An Issue label has an unknown format.")
    return names


def validate_issue(issue: object, *, require_body: bool = True) -> dict[str, Any]:
    """Validate the common issue fields returned by gh."""
    if not isinstance(issue, dict):
        raise QueueError("GitHub returned an Issue with an unknown format.")
    if not isinstance(issue.get("number"), int) or isinstance(issue.get("number"), bool):
        raise QueueError("GitHub returned an Issue without a valid number.")
    if not isinstance(issue.get("title"), str) or not isinstance(issue.get("url"), str):
        raise QueueError("GitHub returned an Issue without a valid title or URL.")
    issue_repo_from_url(issue["url"])
    if issue.get("state") not in {"OPEN", "CLOSED"}:
        raise QueueError(f"Issue #{issue['number']} has an unknown state.")
    if require_body and issue.get("body") is not None and not isinstance(issue.get("body"), str):
        raise QueueError(f"Issue #{issue['number']} body is missing or has an unknown format.")
    labels_of(issue)
    validated = dict(issue)
    if require_body and validated.get("body") is None:
        validated["body"] = ""
    return validated


def complete_blocked_by(issue: dict[str, Any]) -> list[dict[str, Any]]:
    """Require an intact GraphQL connection rather than a possibly truncated list."""
    connection = issue.get("blockedBy")
    if not isinstance(connection, dict):
        raise QueueError(f"Issue #{issue['number']} blockedBy is not a connection object.")
    nodes = connection.get("nodes")
    total_count = connection.get("totalCount")
    if (
        not isinstance(nodes, list)
        or not isinstance(total_count, int)
        or isinstance(total_count, bool)
        or total_count < 0
        or len(nodes) != total_count
    ):
        raise QueueError(f"Issue #{issue['number']} blockedBy nodes/totalCount are incomplete.")
    parsed: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("url"), str):
            raise QueueError(f"Issue #{issue['number']} has a malformed blockedBy node.")
        issue_repo_from_url(node["url"])
        if node["url"] in seen_urls:
            raise QueueError(f"Issue #{issue['number']} has a duplicate blockedBy URL.")
        seen_urls.add(node["url"])
        parsed.append(node)
    return parsed


def decision_record(decision: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    """Parse decision status, revision, and outcome from the documented body contract."""
    body = decision.get("body")
    if not isinstance(body, str):
        return None, None, "Decision body is missing."
    statuses: list[str] = []
    revisions: list[str] = []
    outcomes: list[str] = []
    for line in body.splitlines():
        if match := DECISION_STATUS_PATTERN.fullmatch(line):
            statuses.append(match.group(1).lower())
        if match := DECISION_REVISION_PATTERN.fullmatch(line):
            revisions.append(match.group(1))
        if match := DECISION_OUTCOME_PATTERN.fullmatch(line):
            outcomes.append(match.group(1))
    if len(statuses) != 1 or statuses[0] not in {"pending", "decided"}:
        return None, None, "Decision status is missing, duplicated, or invalid."
    if len(revisions) != 1 or not revisions[0].isdigit() or int(revisions[0]) < 1:
        return statuses[0], None, "Decision revision is missing, duplicated, or invalid."
    if statuses[0] == "decided" and (len(outcomes) != 1 or not outcomes[0].strip()):
        return statuses[0], int(revisions[0]), "A decided Decision needs one non-empty decision-outcome."
    if statuses[0] == "pending" and len(outcomes) > 1:
        return statuses[0], int(revisions[0]), "Decision has duplicated decision-outcome fields."
    return statuses[0], int(revisions[0]), None


def applied_revisions(work: dict[str, Any]) -> tuple[dict[str, tuple[int, datetime]], str | None]:
    """Read explicit decision-applied URL/revision entries from a Work body."""
    body = work.get("body")
    if not isinstance(body, str):
        return {}, "Work body is missing."
    applied: dict[str, tuple[int, datetime]] = {}
    for line in body.splitlines():
        if not re.match(r"^\s*decision-applied\b", line, re.IGNORECASE):
            continue
        match = APPLIED_PATTERN.fullmatch(line)
        if match is None:
            return applied, "A decision-applied record has an invalid format."
        decision_url = match.group(1)
        try:
            issue_repo_from_url(decision_url)
        except QueueError:
            return applied, f"A decision-applied record has an invalid URL: {decision_url}."
        if decision_url in applied:
            return applied, f"Decision {decision_url} has duplicate decision-applied records."
        closed_at = parse_timestamp(match.group(3))
        if closed_at is None:
            return applied, f"Decision {decision_url} has an invalid closed-at timestamp."
        applied[decision_url] = (int(match.group(2)), closed_at)
    return applied, None


def validate_work_issue(work: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Validate Work identity and its labels."""
    issue = validate_issue(work)
    labels = labels_of(issue)
    if LABEL_WORK not in labels:
        raise QueueError(f"Issue #{issue['number']} is not labeled {LABEL_WORK}.")
    if LABEL_DECISION in labels:
        raise QueueError(
            f"Issue #{issue['number']} has both {LABEL_WORK} and {LABEL_DECISION}; refusing to classify it."
        )
    return issue, labels


def validate_blocking_decisions(
    issue: dict[str, Any], blockers: list[dict[str, Any]], decisions: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Ensure fetched blocker details match every canonical blockedBy node."""
    if len(blockers) != len(decisions):
        raise QueueError(f"Issue #{issue['number']} blocker details are incomplete.")
    validated_decisions: list[dict[str, Any]] = []
    for blocker, decision in zip(blockers, decisions, strict=True):
        parsed = validate_issue(decision)
        if blocker["url"] != parsed["url"] or blocker.get("number") != parsed["number"]:
            raise QueueError(f"Issue #{issue['number']} blocker details do not match {blocker['url']}.")
        decision_labels = labels_of(parsed)
        if LABEL_WORK in decision_labels and LABEL_DECISION in decision_labels:
            raise QueueError(f"Blocking issue {parsed['url']} has both {LABEL_WORK} and {LABEL_DECISION}.")
        if LABEL_DECISION not in decision_labels:
            raise QueueError(f"Blocking issue {parsed['url']} is not labeled {LABEL_DECISION}.")
        validated_decisions.append(parsed)
    return validated_decisions


def inspect_decisions(
    decisions: Sequence[dict[str, Any]],
) -> tuple[list[str], list[tuple[dict[str, Any], int, datetime]]]:
    """Separate unresolved Decisions from closed, recorded decisions."""
    pending_reasons: list[str] = []
    finalized: list[tuple[dict[str, Any], int, datetime]] = []
    for decision in decisions:
        status, revision, invalid_reason = decision_record(decision)
        if invalid_reason:
            pending_reasons.append(f"Decision #{decision['number']}: {invalid_reason}")
            continue
        if decision["state"] == "OPEN" or status == "pending":
            pending_reasons.append(
                f"Decision #{decision['number']} is unresolved (state={decision['state']}, status={status})."
            )
            continue
        if status != "decided" or revision is None:
            pending_reasons.append(f"Decision #{decision['number']} has no final decision record.")
            continue
        closed_at = parse_timestamp(decision.get("closedAt"))
        if closed_at is None:
            pending_reasons.append(f"Decision #{decision['number']} has no valid GitHub closedAt timestamp.")
            continue
        finalized.append((decision, revision, closed_at))
    return pending_reasons, finalized


def replan_reasons(
    issue: dict[str, Any], labels: set[str], finalized: Sequence[tuple[dict[str, Any], int, datetime]]
) -> list[str]:
    """Find closed Decision revisions not recorded as applied by the Work issue."""
    applied, applied_error = applied_revisions(issue)
    stale_reasons = [applied_error] if applied_error else []
    for decision, revision, closed_at in finalized:
        recorded = applied.get(decision["url"])
        if recorded == (revision, closed_at):
            continue
        recorded_text = (
            "no applied revision/closed-at record"
            if recorded is None
            else f"revision {recorded[0]} with closed-at {recorded[1].isoformat()}"
        )
        stale_reasons.append(
            f"Decision #{decision['number']} is revision {revision}, closed at {closed_at.isoformat()}, "
            f"but Work records {recorded_text}."
        )
    if LABEL_NEEDS_REPLAN in labels:
        stale_reasons.append("Work still has the needs-replan label.")
    return stale_reasons


def classify_work(work: dict[str, Any], decisions: Sequence[dict[str, Any]]) -> dict[str, str]:
    """Purely classify an already retrieved Work issue and its blocking issues."""
    issue, labels = validate_work_issue(work)
    if issue["state"] != "OPEN":
        return {"state": "blocked", "reason": "Work Issue is closed and cannot be dispatched."}
    blockers = complete_blocked_by(issue)
    validated_decisions = validate_blocking_decisions(issue, blockers, decisions)
    pending_reasons, finalized = inspect_decisions(validated_decisions)
    if pending_reasons:
        return {"state": "blocked", "reason": " ".join(pending_reasons)}

    stale_reasons = replan_reasons(issue, labels, finalized)
    if stale_reasons:
        return {"state": "needs-replan", "reason": " ".join(stale_reasons)}
    return {"state": "ready", "reason": "All blocking Decisions are closed and applied at their current revisions."}


def run_gh(args: Sequence[str]) -> object:
    """Run gh and decode its JSON output."""
    gh_executable = shutil.which("gh")
    if gh_executable is None:
        raise QueueError("GitHub CLI (gh) is not installed or is not on PATH.")
    try:
        result = subprocess.run(  # noqa: S603 - argv is fixed or validated and shell execution is disabled.
            [gh_executable, *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise QueueError("GitHub CLI (gh) disappeared from PATH during execution.") from exc
    if result.returncode != 0:
        message = result.stderr.strip() or f"gh exited with status {result.returncode}."
        raise QueueError(f"GitHub CLI failed: {message}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise QueueError("GitHub CLI returned invalid JSON.") from exc


def view_issue(issue_number: int, repo_argument: str, expected_identity: tuple[str, str, str]) -> dict[str, Any]:
    """Retrieve an issue by validated number and verify its canonical repository URL."""
    issue = run_gh(["issue", "view", str(issue_number), "--repo", repo_argument, "--json", ISSUE_FIELDS])
    validated = validate_issue(issue)
    identity = issue_url_identity(validated["url"])
    if identity[:3] != expected_identity or identity[3] != issue_number:
        raise QueueError(f"Issue #{issue_number} URL does not match its canonical repository identity.")
    return validated


def retrieve_decisions(work: dict[str, Any]) -> list[dict[str, Any]]:
    """Retrieve complete details for every blocker listed on a Work issue."""
    blockers = complete_blocked_by(work)
    decisions = []
    for blocker in blockers:
        if (
            not isinstance(blocker.get("number"), int)
            or isinstance(blocker.get("number"), bool)
            or blocker["number"] < 1
        ):
            raise QueueError(f"Issue #{work['number']} has a blockedBy node without a valid number.")
        blocker_identity = issue_url_identity(blocker["url"])
        blocker_repo_argument = "/".join(blocker_identity[:3])
        resolved_identity, resolved_repo_argument = canonical_repository(blocker_repo_argument)
        if resolved_identity != (blocker_identity[0], blocker_identity[1].lower(), blocker_identity[2].lower()):
            raise QueueError(f"Blocking issue URL does not match its canonical repository: {blocker['url']}.")
        decision = run_gh(
            [
                "issue",
                "view",
                str(blocker["number"]),
                "--repo",
                resolved_repo_argument,
                "--json",
                DECISION_FIELDS,
            ],
        )
        validated = validate_issue(decision)
        actual_identity = issue_url_identity(validated["url"])
        if actual_identity[:3] != resolved_identity or actual_identity[3] != blocker["number"]:
            raise QueueError(f"Blocking issue details do not match canonical URL {blocker['url']}.")
        decisions.append(validated)
    return decisions


def evaluate(work: dict[str, Any]) -> dict[str, str]:
    """Retrieve blocker details, then invoke the pure classifier."""
    return classify_work(work, retrieve_decisions(work))


def list_work(repo: str, expected_identity: tuple[str, str, str]) -> list[dict[str, Any]]:
    """List open Work issues and refuse a potentially truncated result."""
    issues = run_gh(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            LABEL_WORK,
            "--limit",
            str(MAX_WORK_ISSUES),
            "--json",
            ISSUE_FIELDS,
        ],
    )
    if not isinstance(issues, list):
        raise QueueError("GitHub CLI returned a work queue with an unknown format.")
    if len(issues) >= MAX_WORK_ISSUES:
        raise QueueError(f"Work queue reached the {MAX_WORK_ISSUES}-issue limit; completeness is unknown.")
    work_issues = [validate_issue(issue) for issue in issues]
    if any(issue_url_identity(issue["url"])[:3] != expected_identity for issue in work_issues):
        raise QueueError("GitHub returned an ai-work issue outside the requested repository.")
    return work_issues


def aggregate_state(results: Sequence[dict[str, str]]) -> tuple[str, str]:
    """Summarize a completely evaluated queue for status output."""
    counts = {
        state: sum(result["state"] == state for result in results) for state in ("blocked", "needs-replan", "ready")
    }
    if counts["blocked"]:
        state = "blocked"
    elif counts["needs-replan"]:
        state = "needs-replan"
    else:
        state = "ready"
    reason = (
        f"Inspected {len(results)} open ai-work issue(s): {counts['ready']} ready, "
        f"{counts['blocked']} blocked, {counts['needs-replan']} needs-replan."
    )
    return state, reason


def output(value: dict[str, Any], *, as_json: bool) -> None:
    """Write structured JSON or a concise human-readable representation."""
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    print(f"{value['state']}: {value['reason']}")
    for issue in value.get("issues", []):
        print(f"#{issue['number']} [{issue['state']}] {issue['title']} — {issue['reason']}")


def parser() -> argparse.ArgumentParser:
    """Build the deliberately small read-only CLI interface."""
    root = argparse.ArgumentParser(description="Inspect ai-work dependency and replanning gates (read-only).")
    commands = root.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="inspect the open ai-work queue")
    status.add_argument("--repo", required=True, type=validate_repo, help="repository in owner/repo form")
    status.add_argument("--json", action="store_true", help="print JSON including state and reason")
    explain = commands.add_parser("explain", help="explain the gate for one Work issue")
    explain.add_argument("issue", help="issue number or URL")
    explain.add_argument("--repo", required=True, type=validate_repo, help="repository in owner/repo form")
    explain.add_argument("--json", action="store_true", help="print JSON including state and reason")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and fail closed when retrieval or classification is uncertain."""
    args = parser().parse_args(argv)
    try:
        issue_number = None
        reference_identity = None
        if args.command == "explain":
            issue_number, reference_identity = parse_issue_argument(args.issue)
        expected_identity, _ = canonical_repository(args.repo)
        if args.command == "status":
            work_issues = list_work(args.repo, expected_identity)
            output_issues = []
            for work in work_issues:
                gate = evaluate(work)
                output_issues.append(
                    {
                        "number": work["number"],
                        "title": work["title"],
                        "url": work["url"],
                        **gate,
                    },
                )
            state, reason = aggregate_state(output_issues)
            output({"repo": args.repo, "state": state, "reason": reason, "issues": output_issues}, as_json=args.json)
            return 0

        if reference_identity is not None and reference_identity != expected_identity:
            raise QueueError.create(f"Issue URL does not belong to requested repository {args.repo}.")
        if issue_number is None:
            raise QueueError.create("Issue reference could not be resolved.")
        work = view_issue(issue_number, args.repo, expected_identity)
        gate = evaluate(work)
        result = {
            "repo": args.repo,
            "number": work["number"],
            "title": work["title"],
            "url": work["url"],
            **gate,
        }
        output(result, as_json=args.json)
        return 0 if gate["state"] == "ready" else 1
    except (QueueError, OSError, subprocess.SubprocessError) as exc:
        error = {"state": "unknown", "reason": str(exc)}
        if getattr(args, "json", False):
            print(json.dumps(error, ensure_ascii=False))
        else:
            print(f"unknown: {error['reason']}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
