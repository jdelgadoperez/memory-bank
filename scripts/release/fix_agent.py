from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Literal, TypedDict

import anthropic

from scripts.release.types import CheckResult, ScenarioResult


class ParsedAgentResponse(TypedDict):
    explanation: str
    patch: str
    test: str


class FixLoopResult(TypedDict):
    status: Literal["TESTS_PASS", "AGENT_FAILED", "SKIP"]
    iterations: int
    explanation: str
    modified_files: list[str]
    iteration_log: str


def build_context_bundle(results: list[ScenarioResult]) -> str:
    """Summarize all FAIL CheckResults across all scenarios as a human-readable string.

    Args:
        results: List of ScenarioResult objects from the release verification run.

    Returns:
        A string with one block per failing check showing scenario, check name,
        expected, actual, and diff. Returns an empty string if there are no failures.
    """
    blocks: list[str] = []
    for scenario_result in results:
        for check in scenario_result.checks:
            if check.status == "FAIL":
                blocks.append(
                    f"Scenario: {scenario_result.scenario}\n"
                    f"Check: {check.name}\n"
                    f"Expected: {check.expected}\n"
                    f"Actual: {check.actual}\n"
                    f"Diff:\n{check.diff}"
                )
    return "\n\n---\n\n".join(blocks)


def _failing_checks(results: list[ScenarioResult]) -> list[CheckResult]:
    return [check for sr in results for check in sr.checks if check.status == "FAIL"]


def _find_relevant_source_files(check_names: list[str], repo_root: Path) -> list[Path]:
    """Grep src/memory_bank/ for files containing any of the check name tokens."""
    src_dir = repo_root / "src" / "memory_bank"
    if not src_dir.exists():
        return []

    matched: set[Path] = set()
    for name in check_names:
        tokens = [t for t in name.replace("_", " ").split() if len(t) > 3]
        for token in tokens:
            result = subprocess.run(
                ["grep", "-rIl", token, str(src_dir)],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                matched.add(Path(line))

    return sorted(matched)


def _build_system_prompt(results: list[ScenarioResult], repo_root: Path) -> str:
    """Build the Claude system prompt with assertions YAML and relevant source files.

    Args:
        results: Scenario results containing FAIL checks.
        repo_root: Root of the repository.

    Returns:
        A system prompt string for the Claude API call.
    """
    assertions_path = repo_root / "tests" / "release" / "assertions.yaml"
    assertions_content = assertions_path.read_text() if assertions_path.exists() else ""

    failing = _failing_checks(results)
    check_names = [c.name for c in failing]
    relevant_files = _find_relevant_source_files(check_names, repo_root)

    source_sections: list[str] = []
    for file_path in relevant_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            relative = file_path.relative_to(repo_root)
            source_sections.append(f"### {relative}\n```python\n{content}\n```")
        except (OSError, UnicodeDecodeError):
            continue

    source_block = "\n\n".join(source_sections)

    context_bundle = build_context_bundle(results)

    return (
        "You are an autonomous release-verification fix agent for the memory-bank project.\n\n"
        "Your job is to analyze failing release verification checks and produce a minimal fix.\n\n"
        "## Behavioral Invariants (assertions.yaml)\n\n"
        f"```yaml\n{assertions_content}\n```\n\n"
        "## Failing Checks\n\n"
        f"{context_bundle}\n\n"
        "## Relevant Source Files\n\n"
        f"{source_block}\n\n"
        "## Instructions\n\n"
        "Respond with a single JSON object (no markdown prose before or after) containing:\n"
        "- `explanation` (str): What is wrong and why your fix addresses it.\n"
        "- `patch` (str): A unified diff (`diff -u` format, `-p1` applicable) that fixes the issue. "
        "Empty string if no source change is needed.\n"
        "- `test` (str): A self-contained pytest test function that verifies the fix.\n\n"
        "Only output valid JSON. Do not include commentary outside the JSON object."
    )


def _call_claude(
    client: anthropic.Anthropic,
    system: str,
    messages: list[dict[str, str]],
) -> str:
    """Call the Claude API with ephemeral cache control on the system prompt.

    Args:
        client: An initialized Anthropic client.
        system: The system prompt text.
        messages: Accumulated message history for multi-turn context.

    Returns:
        The text content of the first content block in the response.
    """
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )
    return response.content[0].text


def parse_agent_response(raw: str) -> ParsedAgentResponse:
    """Parse a Claude response into a structured dict.

    Strips markdown code fences (```json ... ```) before parsing.

    Args:
        raw: Raw string response from Claude.

    Returns:
        Dict with keys 'explanation', 'patch', and 'test'. On parse failure,
        returns explanation=raw with empty patch and test.
    """
    text = raw.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        inner_lines = lines[1:]
        if inner_lines and inner_lines[-1].strip() == "```":
            inner_lines = inner_lines[:-1]
        text = "\n".join(inner_lines).strip()

    try:
        parsed = json.loads(text)
        return ParsedAgentResponse(
            explanation=parsed.get("explanation", ""),
            patch=parsed.get("patch", ""),
            test=parsed.get("test", ""),
        )
    except (json.JSONDecodeError, ValueError):
        return ParsedAgentResponse(explanation=raw, patch="", test="")


def apply_patch(
    patch_str: str,
    test_code: str,
    check_name: str,
    repo_root: Path,
) -> list[str]:
    """Apply a unified diff patch and write the generated test file.

    Args:
        patch_str: Unified diff string. Skipped if empty.
        test_code: Pytest source code to write as a test file.
        check_name: Used to derive the test filename.
        repo_root: Root of the repository.

    Returns:
        List of file paths that were written or modified.
    """
    safe_name = check_name.replace(" ", "_")
    test_file = repo_root / "tests" / f"test_release_{safe_name}.py"
    test_file.write_text(test_code)
    modified: list[str] = [str(test_file)]

    if not patch_str.strip():
        return modified

    result = subprocess.run(
        ["patch", "-p1"],
        input=patch_str,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )

    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.startswith("patching file "):
                patched = line.removeprefix("patching file ").strip()
                full_path = str(repo_root / patched)
                if full_path not in modified:
                    modified.append(full_path)

    return modified


def _run_tests(repo_root: Path) -> tuple[bool, str]:
    """Run the full pytest suite.

    Args:
        repo_root: Root of the repository.

    Returns:
        A tuple of (passed, output) where passed is True if all tests pass
        (exit code 0) and output is the combined stdout/stderr.
    """
    result = subprocess.run(
        ["uv", "run", "python", "-m", "pytest", "tests/", "-q"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def run_fix_loop(
    results: list[ScenarioResult],
    repo_root: Path,
    branch: str,
) -> FixLoopResult:
    """Run the autonomous Claude fix loop up to 3 iterations.

    Builds the system prompt once (cached across iterations via ephemeral cache_control),
    then iterates: call Claude → parse response → apply patch → run tests.
    Stops early on first passing test run.

    Args:
        results: Scenario results with at least one FAIL check.
        repo_root: Root of the repository.
        branch: Git branch name (passed through to the result dict for callers).

    Returns:
        FixLoopResult with keys: status, iterations, explanation, modified_files, iteration_log.
        status is one of: "TESTS_PASS", "AGENT_FAILED", "SKIP".
    """
    if "ANTHROPIC_API_KEY" not in os.environ:
        return FixLoopResult(
            status="SKIP",
            iterations=0,
            explanation="ANTHROPIC_API_KEY not set",
            modified_files=[],
            iteration_log="",
        )

    client = anthropic.Anthropic()
    system = _build_system_prompt(results, repo_root)
    messages: list[dict[str, str]] = [
        {"role": "user", "content": "Analyze the failing checks and produce a fix."}
    ]

    log_lines: list[str] = []
    max_iterations = 3

    for iteration in range(max_iterations):
        log_lines.append(f"=== Iteration {iteration + 1} ===")

        raw_response = _call_claude(client, system, messages)
        messages.append({"role": "assistant", "content": raw_response})

        parsed = parse_agent_response(raw_response)
        log_lines.append(f"Explanation: {parsed['explanation'][:200]}")

        failing = _failing_checks(results)
        check_name = failing[0].name if failing else "unknown"
        modified_files = apply_patch(parsed["patch"], parsed["test"], check_name, repo_root)

        log_lines.append(f"Modified files: {modified_files}")

        passed, test_output = _run_tests(repo_root)
        if passed:
            return FixLoopResult(
                status="TESTS_PASS",
                iterations=iteration + 1,
                explanation=parsed["explanation"],
                modified_files=modified_files,
                iteration_log="\n".join(log_lines),
            )

        log_lines.append(f"Test output:\n{test_output[-500:]}")
        failure_message = (
            f"Tests still failing after iteration {iteration + 1}. "
            "Please revise the patch or test to address the remaining failures."
        )
        messages.append({"role": "user", "content": failure_message})
        log_lines.append("Tests failed — continuing to next iteration.")

    return FixLoopResult(
        status="AGENT_FAILED",
        iterations=max_iterations,
        explanation="",
        modified_files=[],
        iteration_log="\n".join(log_lines),
    )
