from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.release.types import CheckResult, ScenarioResult
from scripts.release_verify import main


def _make_passing_result(scenario_name: str) -> ScenarioResult:
    return ScenarioResult(
        scenario=scenario_name,
        checks=[CheckResult(name="--version", status="PASS", expected="exit 0", actual="exit 0", diff="")],
    )


def _make_failing_result(scenario_name: str) -> ScenarioResult:
    return ScenarioResult(
        scenario=scenario_name,
        checks=[CheckResult(name="--version", status="FAIL", expected="exit 0", actual="exit 1", diff="exit code 1")],
    )


def test_main_all_pass_exits_0() -> None:
    passing_results = [_make_passing_result(name) for name in ("local-editable", "git-main", "wheel")]
    mock_installed = MagicMock()

    with (
        patch("scripts.release_verify.install_scenario", return_value=mock_installed),
        patch("scripts.release_verify.run_checks", side_effect=passing_results),
        patch("scripts.release_verify.cleanup"),
        patch("scripts.release_verify.create_branch") as mock_create_branch,
        patch("scripts.release_verify.write_report", return_value=Path("/tmp/report.md")) as mock_write_report,
    ):
        result = main([])

    assert result == 0
    mock_write_report.assert_called_once()
    mock_create_branch.assert_not_called()


def test_main_install_failure_exits_1() -> None:
    mock_installed = MagicMock()
    fix_loop_result = {
        "status": "SKIP",
        "iterations": 0,
        "explanation": "ANTHROPIC_API_KEY not set",
        "modified_files": [],
        "iteration_log": "",
    }

    with (
        patch(
            "scripts.release_verify.install_scenario",
            side_effect=[RuntimeError("install failed"), mock_installed, mock_installed],
        ),
        patch(
            "scripts.release_verify.run_checks",
            side_effect=[_make_passing_result("git-main"), _make_passing_result("wheel")],
        ),
        patch("scripts.release_verify.cleanup"),
        patch("scripts.release_verify.create_branch"),
        patch("scripts.release_verify.run_fix_loop", return_value=fix_loop_result),
        patch("scripts.release_verify.write_report", return_value=Path("/tmp/report.md")) as mock_write_report,
    ):
        result = main([])

    assert result == 1
    mock_write_report.assert_called_once()


def test_main_scenario_fail_triggers_fix_loop() -> None:
    failing_results = [_make_failing_result(name) for name in ("local-editable", "git-main", "wheel")]
    mock_installed = MagicMock()
    fix_loop_result = {
        "status": "SKIP",
        "iterations": 0,
        "explanation": "ANTHROPIC_API_KEY not set",
        "modified_files": [],
        "iteration_log": "",
    }

    with (
        patch("scripts.release_verify.install_scenario", return_value=mock_installed),
        patch("scripts.release_verify.run_checks", side_effect=failing_results),
        patch("scripts.release_verify.cleanup"),
        patch("scripts.release_verify.create_branch"),
        patch("scripts.release_verify.run_fix_loop", return_value=fix_loop_result) as mock_run_fix_loop,
        patch("scripts.release_verify.open_pr") as mock_open_pr,
        patch("scripts.release_verify.open_issue") as mock_open_issue,
        patch("scripts.release_verify.write_report", return_value=Path("/tmp/report.md")),
    ):
        result = main([])

    assert result == 1
    mock_run_fix_loop.assert_called_once()
    mock_open_pr.assert_not_called()
    mock_open_issue.assert_not_called()


def test_main_tests_pass_exits_0() -> None:
    failing_results = [_make_failing_result(name) for name in ("local-editable", "git-main", "wheel")]
    mock_installed = MagicMock()
    fix_loop_result = {
        "status": "TESTS_PASS",
        "iterations": 1,
        "explanation": "fixed",
        "modified_files": ["tests/test_release_foo.py", "src/foo.py"],
        "iteration_log": "",
    }

    with (
        patch("scripts.release_verify.install_scenario", return_value=mock_installed),
        patch("scripts.release_verify.run_checks", side_effect=failing_results),
        patch("scripts.release_verify.cleanup"),
        patch("scripts.release_verify.create_branch"),
        patch("scripts.release_verify.run_fix_loop", return_value=fix_loop_result),
        patch("scripts.release_verify.commit_fix") as mock_commit_fix,
        patch("scripts.release_verify.push_branch"),
        patch("scripts.release_verify.open_pr", return_value="http://pr-url") as mock_open_pr,
        patch("scripts.release_verify.write_report", return_value=Path("/tmp/report.md")) as mock_write_report,
    ):
        result = main([])

    assert result == 0
    mock_commit_fix.assert_called_once()
    mock_open_pr.assert_called_once()
    mock_write_report.assert_called_once()


def test_main_agent_failed_opens_issue() -> None:
    failing_results = [_make_failing_result(name) for name in ("local-editable", "git-main", "wheel")]
    mock_installed = MagicMock()
    fix_loop_result = {
        "status": "AGENT_FAILED",
        "iterations": 3,
        "explanation": "Agent could not determine a fix",
        "modified_files": [],
        "iteration_log": "attempt 1 failed\nattempt 2 failed\nattempt 3 failed",
    }

    with (
        patch("scripts.release_verify.install_scenario", return_value=mock_installed),
        patch("scripts.release_verify.run_checks", side_effect=failing_results),
        patch("scripts.release_verify.cleanup"),
        patch("scripts.release_verify.create_branch"),
        patch("scripts.release_verify.run_fix_loop", return_value=fix_loop_result),
        patch("scripts.release_verify.open_issue", return_value="http://issue-url") as mock_open_issue,
        patch("scripts.release_verify.write_report", return_value=Path("/tmp/report.md")),
    ):
        result = main([])

    assert result == 1
    mock_open_issue.assert_called_once()
