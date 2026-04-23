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
    """Verify the uv installation receipt has the expected shape.

    The actual layout uv writes to ``uv-receipt.toml`` is::

        [tool]
        requirements = [{name = "memory-bank", ...}]
        entrypoints  = [{name = "memory-bank", install-path = "...", from = "..."}]

    So this check validates that the receipt has a ``tool`` table with both a
    ``requirements`` list containing the expected tool name and an
    ``entrypoints`` list containing the expected entrypoint name with a
    populated ``install-path``.

    Args:
        receipt: Parsed ``uv-receipt.toml`` dict.
        spec: Spec dict with ``tool_name`` (and optionally ``entrypoint_name``,
            defaulting to ``tool_name``).

    Returns:
        CheckResult with PASS if shape matches, FAIL otherwise.
    """
    tool_name = spec.get("tool_name", "")
    entrypoint_name = spec.get("entrypoint_name", tool_name)

    tool_section = receipt.get("tool")
    if not isinstance(tool_section, dict):
        return CheckResult(
            name="uv_receipt_shape",
            status="FAIL",
            expected=str(spec),
            actual=str(receipt),
            diff=f"- expected a [tool] table, got {type(tool_section).__name__}",
        )

    requirements = tool_section.get("requirements") or []
    entrypoints = tool_section.get("entrypoints") or []

    issues: list[str] = []

    if not isinstance(requirements, list) or not any(
        isinstance(r, dict) and r.get("name") == tool_name for r in requirements
    ):
        issues.append(f"tool.requirements missing entry with name={tool_name!r}")

    matching_entrypoints = [
        e for e in entrypoints
        if isinstance(e, dict) and e.get("name") == entrypoint_name
    ]
    if not matching_entrypoints:
        issues.append(f"tool.entrypoints missing entry with name={entrypoint_name!r}")
    elif not any(e.get("install-path") for e in matching_entrypoints):
        issues.append(f"tool.entrypoints[name={entrypoint_name!r}] missing 'install-path'")

    if issues:
        return CheckResult(
            name="uv_receipt_shape",
            status="FAIL",
            expected=str(spec),
            actual=str(receipt),
            diff="\n".join(f"- {i}" for i in issues),
        )
    return CheckResult(
        name="uv_receipt_shape",
        status="PASS",
        expected="valid",
        actual="valid",
        diff="",
    )
