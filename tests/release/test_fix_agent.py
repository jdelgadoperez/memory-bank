from __future__ import annotations

import json
from typing import Literal

from scripts.release.fix_agent import build_context_bundle, parse_agent_response
from scripts.release.types import CheckResult, ScenarioResult


def _make_check(
    name: str,
    status: Literal["PASS", "FAIL", "SKIP"] = "PASS",
    expected: str = "ok",
    actual: str = "ok",
    diff: str = "",
) -> CheckResult:
    return CheckResult(name=name, status=status, expected=expected, actual=actual, diff=diff)


def _make_scenario(scenario: str, checks: list[CheckResult]) -> ScenarioResult:
    return ScenarioResult(scenario=scenario, checks=checks)


class TestBuildContextBundle:
    def test_build_context_bundle_fail_checks(self) -> None:
        fail_check = _make_check(
            name="hook_markers",
            status="FAIL",
            expected="all markers present",
            actual="2 missing",
            diff="- missing: Stop: 'memory-bank ingest claude-code'\n- missing: Stop: 'memory-bank distill'",
        )
        scenario = _make_scenario("fresh_install", [fail_check])

        bundle = build_context_bundle([scenario])

        assert "hook_markers" in bundle
        assert "memory-bank ingest claude-code" in bundle

    def test_build_context_bundle_no_fails(self) -> None:
        pass_check = _make_check(name="hook_markers", status="PASS")
        skip_check = _make_check(name="uv_receipt_shape", status="SKIP")
        scenario = _make_scenario("fresh_install", [pass_check, skip_check])

        bundle = build_context_bundle([scenario])

        assert "FAIL" not in bundle


class TestParseAgentResponse:
    def test_parse_agent_response_valid_json(self) -> None:
        payload = {
            "explanation": "The hook command was missing the distill marker.",
            "patch": "--- a/src/memory_bank/commands/hooks.py\n+++ b/src/memory_bank/commands/hooks.py\n",
            "test": "def test_hook_marker(): assert True",
        }
        raw = json.dumps(payload)

        result = parse_agent_response(raw)

        assert result["explanation"] == payload["explanation"]
        assert result["patch"] == payload["patch"]
        assert result["test"] == payload["test"]

    def test_parse_agent_response_with_fences(self) -> None:
        payload = {
            "explanation": "Fixed by adding the missing marker.",
            "patch": "--- a/src/hooks.py\n+++ b/src/hooks.py\n",
            "test": "def test_fix(): pass",
        }
        raw = f"```json\n{json.dumps(payload)}\n```"

        result = parse_agent_response(raw)

        assert result["explanation"] == payload["explanation"]
        assert result["patch"] == payload["patch"]
        assert result["test"] == payload["test"]

    def test_parse_agent_response_invalid(self) -> None:
        raw = "This is not valid JSON at all { broken }"

        result = parse_agent_response(raw)

        assert result["explanation"] == raw
        assert result["patch"] == ""
        assert result["test"] == ""
