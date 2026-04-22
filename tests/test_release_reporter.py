from __future__ import annotations

from scripts.release.reporter import write_report
from scripts.release.types import CheckResult, ScenarioResult


def _scenario(name: str, statuses: list[str]) -> ScenarioResult:
    checks = [CheckResult(f"check-{i}", s, "exp", "act", "") for i, s in enumerate(statuses)]
    return ScenarioResult(scenario=name, checks=checks)


def test_write_report_creates_file(tmp_path):
    results = [_scenario("wheel", ["PASS", "PASS"])]
    path = write_report(results, summaries_dir=tmp_path, agent_result=None)
    assert path.exists()
    assert path.suffix == ".md"


def test_write_report_pass_header(tmp_path):
    results = [_scenario("wheel", ["PASS"])]
    path = write_report(results, summaries_dir=tmp_path, agent_result=None)
    content = path.read_text()
    assert "PASS" in content


def test_write_report_fail_header(tmp_path):
    results = [_scenario("wheel", ["FAIL"])]
    path = write_report(results, summaries_dir=tmp_path, agent_result=None)
    content = path.read_text()
    assert "FAILED" in content


def test_write_report_table_has_all_scenarios(tmp_path):
    results = [
        _scenario("local-editable", ["PASS"]),
        _scenario("git-main", ["FAIL"]),
        _scenario("wheel", ["PASS"]),
    ]
    path = write_report(results, summaries_dir=tmp_path, agent_result=None)
    content = path.read_text()
    assert "local-editable" in content
    assert "git-main" in content
    assert "wheel" in content


def test_write_report_with_agent_result(tmp_path):
    results = [_scenario("wheel", ["FAIL"])]
    agent = {
        "status": "PR_OPENED",
        "pr_url": "https://github.com/x/y/pull/1",
        "explanation": "fixed the marker",
        "iterations": 1,
    }
    path = write_report(results, summaries_dir=tmp_path, agent_result=agent)
    content = path.read_text()
    assert "PR_OPENED" in content
    assert "https://github.com/x/y/pull/1" in content
