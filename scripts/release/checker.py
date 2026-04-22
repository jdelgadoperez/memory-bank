from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

from scripts.release.assertions import (
    check_hook_markers,
    check_marker_uniqueness,
    check_uv_receipt,
    load_assertions,
)
from scripts.release.types import CheckResult, InstalledScenario, ScenarioResult

GOLDEN_DIR = Path(__file__).parent.parent.parent / "tests" / "release" / "golden"

COMMAND_CHECKS = [
    ["--version"],
    ["ingest", "claude-code"],
    ["hooks", "install", "--on", "all"],
    ["distill", "--dry-run"],
    ["update"],
]


def _base_env() -> dict[str, str]:
    return dict(os.environ)


def _run_command(installed: InstalledScenario, args: list[str]) -> CheckResult:
    name = " ".join(args)
    result = subprocess.run(
        [str(installed.mb_bin), *args],
        capture_output=True,
        text=True,
        env={**_base_env(), **installed.env},
        cwd=str(installed.tmp_dir),
    )
    if result.returncode != 0:
        diff = f"exit code {result.returncode}\nstderr: {result.stderr[:500]}"
        return CheckResult(
            name=name,
            status="FAIL",
            expected="exit 0",
            actual=f"exit {result.returncode}",
            diff=diff,
        )
    return CheckResult(name=name, status="PASS", expected="exit 0", actual="exit 0", diff="")


def _read_settings_json(installed: InstalledScenario) -> dict:
    settings_path = installed.tmp_dir / "tools" / "memory-bank" / "settings.json"
    if not settings_path.exists():
        merged_env = {**os.environ, **installed.env}
        home_dir = merged_env.get("HOME", "~")
        home_settings = Path(home_dir).expanduser() / ".claude" / "settings.json"
        if "HOME" in installed.env and home_settings.exists():
            return json.loads(home_settings.read_text())
        return {}
    return json.loads(settings_path.read_text())


def _read_uv_receipt(installed: InstalledScenario) -> dict:
    receipt_path = installed.tmp_dir / "tools" / "memory-bank" / "uv-receipt.toml"
    if not receipt_path.exists():
        return {}
    with open(receipt_path, "rb") as f:
        return tomllib.load(f)


def _check_hooks(installed: InstalledScenario, spec: dict) -> list[CheckResult]:
    settings = _read_settings_json(installed)
    markers_result = check_hook_markers(settings, spec["hooks"]["required_markers"])
    uniqueness_result = check_marker_uniqueness(settings, spec["hooks"]["marker_uniqueness"])
    return [markers_result, uniqueness_result]


def _check_uv_receipt(installed: InstalledScenario, spec: dict) -> CheckResult:
    receipt = _read_uv_receipt(installed)
    return check_uv_receipt(receipt, spec["uv_receipt"])


def _check_snapshot(installed: InstalledScenario) -> CheckResult:
    golden_path = GOLDEN_DIR / "hooks_after_install.json"
    golden = json.loads(golden_path.read_text())
    settings = _read_settings_json(installed)
    hooks = settings.get("hooks", {})

    failures: list[str] = []
    for event in golden.get("required_events", []):
        entries = hooks.get(event, [])
        all_commands = [h.get("command", "") for e in entries for h in e.get("hooks", [])]
        event_spec = golden.get(event, {})
        for marker in event_spec.get("must_contain", []):
            if not any(marker in cmd for cmd in all_commands):
                failures.append(f"{event} missing: {marker!r}")

    if failures:
        diff = "\n".join(f"- {f}" for f in failures)
        return CheckResult("hooks_snapshot", "FAIL", "golden matches", f"{len(failures)} mismatches", diff)
    return CheckResult("hooks_snapshot", "PASS", "golden matches", "golden matches", "")


def run_checks(installed: InstalledScenario) -> ScenarioResult:
    spec = load_assertions()
    checks: list[CheckResult] = []

    for args in COMMAND_CHECKS:
        checks.append(_run_command(installed, args))

    checks.extend(_check_hooks(installed, spec))
    checks.append(_check_uv_receipt(installed, spec))
    checks.append(_check_snapshot(installed))

    return ScenarioResult(scenario=installed.scenario, checks=checks)
