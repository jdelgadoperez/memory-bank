from __future__ import annotations

from click.testing import CliRunner

from memory_bank.cli import cli


def test_version_flag_shows_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    from memory_bank.cli import _get_version
    expected = _get_version()
    assert expected in result.output


def test_banner_shows_version():
    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    from memory_bank.cli import _get_version
    expected = _get_version()
    assert expected in result.output
