from __future__ import annotations

from pathlib import Path

from scripts.release.types import CheckResult, InstalledScenario, ScenarioResult


def test_check_result_defaults():
    r = CheckResult(name="mb --version", status="PASS", expected="0", actual="0", diff="")
    assert r.name == "mb --version"
    assert r.status == "PASS"

def test_scenario_result_passed_all_pass():
    r = ScenarioResult(scenario="wheel", checks=[
        CheckResult("a", "PASS", "", "", ""),
        CheckResult("b", "PASS", "", "", ""),
    ])
    assert r.passed is True

def test_scenario_result_passed_one_fail():
    r = ScenarioResult(scenario="wheel", checks=[
        CheckResult("a", "PASS", "", "", ""),
        CheckResult("b", "FAIL", "0", "1", "- 0\n+ 1"),
    ])
    assert r.passed is False

def test_scenario_result_skip_does_not_fail():
    r = ScenarioResult(scenario="wheel", checks=[
        CheckResult("a", "SKIP", "", "", ""),
    ])
    assert r.passed is True

def test_installed_scenario_fields():
    s = InstalledScenario(
        scenario="local-editable",
        mb_bin=Path("/tmp/venv/bin/memory-bank"),
        tmp_dir=Path("/tmp/mb-verify-abc"),
        env={"MEMORY_BANK_DB": "/tmp/db"},
    )
    assert s.scenario == "local-editable"
    assert s.mb_bin.name == "memory-bank"
