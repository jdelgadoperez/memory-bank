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
            {"hooks": [{"command": "memory-bank ingest claude-code  # precompact >> log &"}]},
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


def test_check_uv_receipt_pass():
    receipt = {"tool": "memory-bank", "version": "0.2.0", "install_type": "editable"}
    spec = load_assertions()
    result = check_uv_receipt(receipt, spec["uv_receipt"])
    assert result.status == "PASS"


def test_check_uv_receipt_missing_field():
    receipt = {"tool": "memory-bank", "version": "0.2.0"}
    spec = load_assertions()
    result = check_uv_receipt(receipt, spec["uv_receipt"])
    assert result.status == "FAIL"
    assert "install_type" in result.diff


def test_check_uv_receipt_wrong_name():
    receipt = {"tool": "other-tool", "version": "0.2.0", "install_type": "wheel"}
    spec = load_assertions()
    result = check_uv_receipt(receipt, spec["uv_receipt"])
    assert result.status == "FAIL"
