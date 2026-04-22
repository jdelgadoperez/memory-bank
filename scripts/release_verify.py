#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

from scripts.release.checker import run_checks
from scripts.release.fix_agent import FixLoopResult, run_fix_loop
from scripts.release.installer import REPO_ROOT, SCENARIOS, cleanup, install_scenario
from scripts.release.pr import commit_fix, create_branch, open_issue, open_pr, push_branch
from scripts.release.reporter import write_report
from scripts.release.types import CheckResult, ScenarioResult


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Release verification orchestrator for memory-bank.")
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Regenerate golden snapshot files (not yet implemented).",
    )
    parser.add_argument(
        "--scenario",
        metavar="NAME",
        help="Run only the named scenario (e.g. local-editable, git-main, wheel).",
    )
    return parser.parse_args(argv)


def _collect_failing_checks(results: list[ScenarioResult]) -> list[CheckResult]:
    return [check for scenario_result in results for check in scenario_result.checks if check.status == "FAIL"]


def _run_scenarios(scenario_name_filter: str | None) -> tuple[list[ScenarioResult], bool]:
    scenarios = SCENARIOS
    if scenario_name_filter is not None:
        scenarios = [s for s in SCENARIOS if s.name == scenario_name_filter]
        if not scenarios:
            print(f"Unknown scenario: {scenario_name_filter!r}. Valid names: {[s.name for s in SCENARIOS]}")
            sys.exit(1)

    results: list[ScenarioResult] = []
    had_install_failure = False

    for config in scenarios:
        print(f"Running scenario: {config.name}...")
        installed = None
        try:
            installed = install_scenario(config, REPO_ROOT)
            result = run_checks(installed)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"  {config.name}: {status}")
        except Exception as exc:
            print(f"  {config.name}: INSTALL ERROR — {exc}")
            had_install_failure = True
        finally:
            if installed is not None:
                cleanup(installed)

    return results, had_install_failure


def _handle_fix_loop(results: list[ScenarioResult]) -> tuple[FixLoopResult, dict[str, Any]]:
    branch = f"fix/release-verify-{datetime.now(UTC).strftime('%Y%m%d')}"
    create_branch(branch)

    agent_result_typed = run_fix_loop(results, REPO_ROOT, branch)
    agent_result: dict[str, Any] = dict(agent_result_typed)

    failing_checks = _collect_failing_checks(results)

    if agent_result_typed["status"] == "TESTS_PASS" and failing_checks:
        commit_fix(agent_result_typed["modified_files"], "", failing_checks[0].name)
        push_branch(branch)
        pr_url = open_pr(branch, failing_checks[0].name, agent_result_typed["explanation"], failing_checks)
        agent_result["pr_url"] = pr_url

    elif agent_result_typed["status"] == "AGENT_FAILED" and failing_checks:
        issue_url = open_issue(failing_checks[0].name, agent_result_typed["iteration_log"])
        agent_result["issue_url"] = issue_url

    return agent_result_typed, agent_result


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.update_golden:
        print("--update-golden is not yet implemented. Run the checker manually to regenerate golden files.")
        return 1

    results, had_install_failure = _run_scenarios(args.scenario)

    all_passed = not had_install_failure and all(r.passed for r in results)

    agent_result: dict[str, Any] | None = None
    fix_status: str | None = None

    if not all_passed and results:
        _, agent_result = _handle_fix_loop(results)
        fix_status = agent_result.get("status")

    report_path = write_report(results, agent_result=agent_result)

    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count
    total = len(SCENARIOS) if args.scenario is None else 1

    print(f"\nScenarios: {passed_count}/{total} passed, {failed_count} failed")
    if fix_status is not None:
        print(f"Fix agent: {fix_status}")
    print(f"Report: {report_path}")

    if all_passed:
        return 0
    if fix_status == "TESTS_PASS":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
