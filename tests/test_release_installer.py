from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.release.installer import (
    SCENARIOS,
    build_wheel,
)
from scripts.release.types import InstalledScenario

REPO_ROOT = Path(__file__).parent.parent


def test_scenarios_list_has_three():
    assert len(SCENARIOS) == 3
    names = [s.name for s in SCENARIOS]
    assert "local-editable" in names
    assert "git-main" in names
    assert "wheel" in names


def test_installed_scenario_has_correct_fields():
    scenario = InstalledScenario(
        scenario="wheel",
        mb_bin=Path("/tmp/bin/memory-bank"),
        tmp_dir=Path("/tmp/abc"),
        env={"MEMORY_BANK_DB": "/tmp/db"},
    )
    assert scenario.mb_bin.name == "memory-bank"
    assert "MEMORY_BANK_DB" in scenario.env


def test_build_wheel_returns_whl_path(tmp_path):
    whl = tmp_path / "dist" / "memory_bank-0.2.0-py3-none-any.whl"
    whl.parent.mkdir(parents=True)
    whl.touch()
    with patch("scripts.release.installer.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("scripts.release.installer._find_wheel", return_value=whl):
            result = build_wheel(REPO_ROOT, tmp_path)
    assert result == whl


def test_scenario_config_fields():
    s = SCENARIOS[0]
    assert hasattr(s, "name")
    assert hasattr(s, "install_cmd_template")
