from __future__ import annotations

from scripts.release.assertions import (
    check_hook_markers,
    check_marker_uniqueness,
    check_uv_receipt,
    load_assertions,
)

SAMPLE_SETTINGS = {
    "hooks": {
        "Stop": [
            {"hooks": [{"command": "memory-bank ingest claude-code >> log &"}]},
            {"hooks": [{"command": "memory-bank distill --since 3h >> log &"}]},
        ],
        "PreCompact": [
            {"hooks": [{"command": "( memory-bank ingest claude-code ) >> log &  # precompact"}]},
        ],
        "UserPromptSubmit": [
            {"hooks": [{"command": "memory-bank hooks recall 2>> log"}]},
        ],
        "SessionStart": [
            {"hooks": [{"command": "memory-bank hooks context-summary >> log &"}]},
        ],
    }
}


def test_load_assertions_returns_dict():
    data = load_assertions()
    assert "hooks" in data
    assert "uv_receipt" in data
    assert "commands" in data


def test_check_hook_markers_all_present():
    spec = load_assertions()
    result = check_hook_markers(SAMPLE_SETTINGS, spec["hooks"]["required_markers"])
    assert result.status == "PASS"


def test_check_hook_markers_missing():
    settings = {"hooks": {"Stop": []}}
    spec = load_assertions()
    result = check_hook_markers(settings, spec["hooks"]["required_markers"])
    assert result.status == "FAIL"
    assert "memory-bank ingest claude-code" in result.diff


def test_check_marker_uniqueness_pass():
    spec = load_assertions()
    result = check_marker_uniqueness(SAMPLE_SETTINGS, spec["hooks"]["marker_uniqueness"])
    assert result.status == "PASS"


def _valid_receipt() -> dict:
    return {
        "tool": {
            "requirements": [{"name": "memory-bank", "editable": "/some/path"}],
            "entrypoints": [
                {
                    "name": "memory-bank",
                    "install-path": "/home/runner/.local/bin/memory-bank",
                    "from": "memory-bank",
                }
            ],
        }
    }


def test_check_uv_receipt_pass():
    spec = load_assertions()
    result = check_uv_receipt(_valid_receipt(), spec["uv_receipt"])
    assert result.status == "PASS"


def test_check_uv_receipt_missing_tool_table():
    spec = load_assertions()
    result = check_uv_receipt({}, spec["uv_receipt"])
    assert result.status == "FAIL"
    assert "[tool] table" in result.diff


def test_check_uv_receipt_wrong_requirement_name():
    receipt = _valid_receipt()
    receipt["tool"]["requirements"] = [{"name": "other-tool"}]
    spec = load_assertions()
    result = check_uv_receipt(receipt, spec["uv_receipt"])
    assert result.status == "FAIL"
    assert "tool.requirements" in result.diff


def test_check_uv_receipt_missing_entrypoint_install_path():
    receipt = _valid_receipt()
    receipt["tool"]["entrypoints"] = [{"name": "memory-bank", "from": "memory-bank"}]
    spec = load_assertions()
    result = check_uv_receipt(receipt, spec["uv_receipt"])
    assert result.status == "FAIL"
    assert "install-path" in result.diff
