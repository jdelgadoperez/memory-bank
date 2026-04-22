from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.release.pr import commit_fix, create_branch, open_issue, open_pr


def _mock_run(stdout: str = "https://github.com/x/y/pull/1") -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    return m


def test_create_branch_runs_git_checkout() -> None:
    with patch("scripts.release.pr.subprocess.run", return_value=_mock_run()) as mock_run:
        create_branch("fix/release-verify-20260422")
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("checkout" in c for c in calls)


def test_open_pr_returns_url() -> None:
    with patch(
        "scripts.release.pr.subprocess.run",
        return_value=_mock_run("https://github.com/x/y/pull/42\n"),
    ):
        url = open_pr(
            branch="fix/release-verify-20260422",
            check_name="hook_markers",
            explanation="Stop marker collision",
            failing_checks=[],
        )
    assert url == "https://github.com/x/y/pull/42"


def test_open_issue_returns_url() -> None:
    with patch(
        "scripts.release.pr.subprocess.run",
        return_value=_mock_run("https://github.com/x/y/issues/5\n"),
    ):
        url = open_issue(
            check_name="hook_markers",
            iteration_log="iter 1: failed\niter 2: failed",
        )
    assert url == "https://github.com/x/y/issues/5"


def test_commit_fix_stages_and_commits() -> None:
    with patch("scripts.release.pr.subprocess.run", return_value=_mock_run("")) as mock_run:
        commit_fix(
            patch_files=["src/memory_bank/commands/hooks.py"],
            test_file="tests/test_release_hook_markers.py",
            check_name="hook_markers",
        )
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("add" in c for c in calls)
    assert any("commit" in c for c in calls)
