from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scripts.release.types import CheckResult

ASSERTIONS_PATH = Path(__file__).parent.parent.parent / "tests" / "release" / "assertions.yaml"


def load_assertions() -> dict[str, Any]:
    """Load assertions spec from YAML file."""
    return yaml.safe_load(ASSERTIONS_PATH.read_text())


def check_hook_markers(
    settings: dict[str, Any],
    required_markers: dict[str, list[str]],
) -> CheckResult:
    """Verify that all required marker strings exist in hook commands.

    Args:
        settings: Hook settings dict with event names as keys.
        required_markers: Dict mapping event names to required marker substrings.

    Returns:
        CheckResult with PASS if all markers found, FAIL with diff listing missing.
    """
    missing: list[str] = []
    hooks_cfg = settings.get("hooks", {})
    for event, markers in required_markers.items():
        event_commands = [
            h.get("command", "")
            for entry in hooks_cfg.get(event, [])
            for h in entry.get("hooks", [])
        ]
        for marker in markers:
            if not any(marker in cmd for cmd in event_commands):
                missing.append(f"{event}: {marker!r}")

    if missing:
        diff = "\n".join(f"- missing: {m}" for m in missing)
        return CheckResult(
            name="hook_markers",
            status="FAIL",
            expected="all markers present",
            actual=f"{len(missing)} missing",
            diff=diff,
        )
    return CheckResult(
        name="hook_markers",
        status="PASS",
        expected="all present",
        actual="all present",
        diff="",
    )


def check_marker_uniqueness(
    settings: dict[str, Any],
    uniqueness_spec: dict[str, str],
) -> CheckResult:
    """Verify that Stop and PreCompact hooks are uniquely identifiable.

    PreCompact must contain the unique substring; Stop must not.

    Args:
        settings: Hook settings dict.
        uniqueness_spec: Dict with 'stop_unique_substring' key.

    Returns:
        CheckResult with PASS if separation is correct, FAIL with violation details.
    """
    stop_unique = uniqueness_spec.get("stop_unique_substring", "# precompact")
    hooks_cfg = settings.get("hooks", {})
    stop_commands = [
        h.get("command", "")
        for entry in hooks_cfg.get("Stop", [])
        for h in entry.get("hooks", [])
    ]
    precompact_commands = [
        h.get("command", "")
        for entry in hooks_cfg.get("PreCompact", [])
        for h in entry.get("hooks", [])
    ]
    for cmd in precompact_commands:
        if stop_unique not in cmd:
            return CheckResult(
                name="marker_uniqueness",
                status="FAIL",
                expected=f"PreCompact commands contain {stop_unique!r}",
                actual=f"PreCompact command missing substring: {cmd!r}",
                diff=f"- PreCompact: {cmd!r}\n  missing: {stop_unique!r}",
            )
    for cmd in stop_commands:
        if stop_unique in cmd:
            return CheckResult(
                name="marker_uniqueness",
                status="FAIL",
                expected=f"Stop commands must not contain {stop_unique!r}",
                actual=f"Stop command contains unique substring: {cmd!r}",
                diff=f"- Stop: {cmd!r}\n  contains: {stop_unique!r}",
            )
    return CheckResult(
        name="marker_uniqueness",
        status="PASS",
        expected="distinct",
        actual="distinct",
        diff="",
    )


def check_uv_receipt(receipt: dict[str, Any], spec: dict[str, Any]) -> CheckResult:
    """Verify uv installation receipt has required fields and correct tool name.

    Args:
        receipt: Installation receipt dict.
        spec: Spec dict with 'required_fields' and 'tool_name' keys.

    Returns:
        CheckResult with PASS if valid, FAIL with missing fields or wrong tool name.
    """
    missing = [f for f in spec.get("required_fields", []) if f not in receipt]
    wrong_name = receipt.get("tool") != spec.get("tool_name")

    issues: list[str] = []
    if missing:
        issues.append(f"missing fields: {missing}")
    if wrong_name:
        issues.append(
            f"tool name: expected {spec['tool_name']!r}, got {receipt.get('tool')!r}"
        )

    if issues:
        diff = "\n".join(f"- {i}" for i in issues)
        return CheckResult(
            name="uv_receipt_shape",
            status="FAIL",
            expected=str(spec),
            actual=str(receipt),
            diff=diff,
        )
    return CheckResult(
        name="uv_receipt_shape",
        status="PASS",
        expected="valid",
        actual="valid",
        diff="",
    )
