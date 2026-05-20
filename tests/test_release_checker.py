from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.release.checker import _read_settings_json, _run_command, run_checks
from scripts.release.types import CheckResult, InstalledScenario

MB_BIN = Path("/fake/bin/memory-bank")
TMP_DIR = Path("/tmp/fake")
SCENARIO = InstalledScenario(
    scenario="wheel",
    mb_bin=MB_BIN,
    tmp_dir=TMP_DIR,
    env={"MEMORY_BANK_DB": "/tmp/db"},
)


def _mock_run(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_run_command_pass():
    with patch("scripts.release.checker.subprocess.run", return_value=_mock_run(0, "0.2.0")):
        result = _run_command(SCENARIO, ["--version"])
    assert result.status == "PASS"
    assert result.name == "--version"


def test_run_command_fail():
    with patch("scripts.release.checker.subprocess.run", return_value=_mock_run(1, "", "error")):
        result = _run_command(SCENARIO, ["ingest", "claude-code"])
    assert result.status == "FAIL"
    assert "exit code 1" in result.diff


def test_run_checks_returns_scenario_result():
    with (
        patch("scripts.release.checker.subprocess.run", return_value=_mock_run(0, "")),
        patch("scripts.release.checker._check_hooks", return_value=[
            CheckResult("hook_markers", "PASS", "", "", ""),
            CheckResult("marker_uniqueness", "PASS", "", "", ""),
        ]),
        patch("scripts.release.checker._check_uv_receipt", return_value=
            CheckResult("uv_receipt_shape", "PASS", "", "", "")),
        patch("scripts.release.checker._check_snapshot", return_value=
            CheckResult("hooks_snapshot", "PASS", "", "", "")),
    ):
        result = run_checks(SCENARIO)
    assert result.scenario == "wheel"
    assert len(result.checks) > 0
    assert result.passed


def test_read_settings_json_missing(tmp_path):
    scenario = InstalledScenario("w", MB_BIN, tmp_path, {})
    with patch.dict("os.environ", {"HOME": str(tmp_path)}):
        result = _read_settings_json(scenario)
    assert result == {}
