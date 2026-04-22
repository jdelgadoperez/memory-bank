from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.release.types import ScenarioResult

SUMMARIES_DIR = Path(__file__).parent.parent.parent / "_summaries"

_STATUS_ICON = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}


def _overall_status(results: list[ScenarioResult], agent_result: dict[str, Any] | None) -> str:
    if all(r.passed for r in results):
        return "PASS"
    if agent_result is None:
        return "FAILED"
    return agent_result.get("status", "FAILED")


def write_report(
    results: list[ScenarioResult],
    summaries_dir: Path | None = None,
    agent_result: dict[str, Any] | None = None,
) -> Path:
    out_dir = summaries_dir or SUMMARIES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    filename = now.strftime("%Y-%m-%d-%H-%M-release-verify.md")
    out_path = out_dir / filename

    status = _overall_status(results, agent_result)
    total_fail = sum(1 for r in results for c in r.checks if c.status == "FAIL")

    lines = [
        f"# Release Verification — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"## Result: {status}" + (f" ({total_fail} failed checks)" if total_fail else ""),
        "",
        "| Scenario | Check | Status |",
        "|---|---|---|",
    ]

    for scenario_result in results:
        for check in scenario_result.checks:
            icon = _STATUS_ICON.get(check.status, check.status)
            lines.append(f"| {scenario_result.scenario} | {check.name} | {icon} {check.status} |")

    if total_fail:
        lines += ["", "## Failures", ""]
        for scenario_result in results:
            for check in scenario_result.checks:
                if check.status == "FAIL":
                    lines += [
                        f"### {scenario_result.scenario} / {check.name}",
                        f"**Expected:** {check.expected}",
                        f"**Actual:** {check.actual}",
                        "```diff",
                        check.diff,
                        "```",
                        "",
                    ]

    if agent_result:
        lines += [
            "## Fix Agent",
            "",
            f"- **Status:** {agent_result.get('status')}",
            f"- **Iterations:** {agent_result.get('iterations', 0)}",
        ]
        if pr_url := agent_result.get("pr_url"):
            lines.append(f"- **PR:** {pr_url}")
        if issue_url := agent_result.get("issue_url"):
            lines.append(f"- **Issue:** {issue_url}")
        if explanation := agent_result.get("explanation"):
            lines += ["", "### Explanation", "", explanation]

    out_path.write_text("\n".join(lines) + "\n")
    return out_path
