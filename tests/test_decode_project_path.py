"""Tests for _decode_project_path — the filesystem-based project name decoder."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from memory_bank.ingestors.claude_code import _decode_project_path


class TestDecodeProjectPath:
    def test_simple_project(self, tmp_path):
        """A plain project name with no dashes decodes correctly."""
        project = tmp_path / "myproject"
        project.mkdir()
        # Encode: replace each / with -, prepend leading -
        encoded = str(project).replace("/", "-")
        assert _decode_project_path(encoded) == "myproject"

    def test_hyphenated_project_name(self, tmp_path):
        """The core bug: 'memory-bank' must not be split into 'bank'."""
        project = tmp_path / "memory-bank"
        project.mkdir()
        encoded = str(project).replace("/", "-")
        assert _decode_project_path(encoded) == "memory-bank"

    def test_multi_hyphen_project_name(self, tmp_path):
        """Projects with multiple dashes in their name are handled correctly."""
        project = tmp_path / "my-cool-project"
        project.mkdir()
        encoded = str(project).replace("/", "-")
        assert _decode_project_path(encoded) == "my-cool-project"

    def test_nested_path_with_hyphenated_name(self, tmp_path):
        """Nested path where the final segment contains dashes."""
        nested = tmp_path / "work" / "my-app"
        nested.mkdir(parents=True)
        encoded = str(nested).replace("/", "-")
        assert _decode_project_path(encoded) == "my-app"

    def test_nonexistent_path_falls_back_gracefully(self):
        """When the path doesn't exist on the filesystem, return the last segment."""
        # This path definitely won't exist
        result = _decode_project_path("-nonexistent-path-that-does-not-exist-anywhere")
        # Should not raise, and should return something reasonable
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_encoded_string(self):
        """Empty or root-only encoded string does not crash."""
        result = _decode_project_path("-")
        assert isinstance(result, str)
