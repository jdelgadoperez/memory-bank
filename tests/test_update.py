from __future__ import annotations

import importlib.metadata

from click.testing import CliRunner

from memory_bank.cli import cli


def test_version_flag_shows_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    expected = importlib.metadata.version("memory-bank")
    assert expected in result.output


def test_banner_shows_version():
    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    expected = importlib.metadata.version("memory-bank")
    assert expected in result.output
