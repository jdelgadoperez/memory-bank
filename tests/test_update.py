from __future__ import annotations

import os
import subprocess as subprocess_module
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestDetectInstallDir:
    def test_returns_none_for_non_venv_path(self):
        from memory_bank.commands.update import _detect_install_dir
        result = _detect_install_dir("/usr/bin/python3")
        assert result is None

    def test_detects_repo_root_from_venv_python(self):
        from memory_bank.commands.update import _detect_install_dir
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_bin = Path(tmpdir) / ".venv" / "bin"
            venv_bin.mkdir(parents=True)
            (Path(tmpdir) / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
            fake_python = venv_bin / "python"
            fake_python.touch()
            result = _detect_install_dir(str(fake_python))
            assert result == Path(tmpdir)


class TestUpdateCommand:
    def test_fails_when_install_dir_not_found(self):
        from click.testing import CliRunner

        from memory_bank.cli import cli
        with patch("memory_bank.commands.update._detect_install_dir", return_value=None):
            result = CliRunner().invoke(cli, ["update"])
        assert result.exit_code != 0

    def test_fails_when_not_git_repo(self):
        from click.testing import CliRunner

        from memory_bank.cli import cli
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "memory_bank.commands.update._detect_install_dir", return_value=Path(tmpdir)
        ):
            result = CliRunner().invoke(cli, ["update"])
        assert result.exit_code != 0
        output = result.output.lower()
        assert "git repository" in output or "not a git" in output or "error" in output

    def _no_conflict_mock(self) -> MagicMock:
        def side_effect(cmd, **kwargs):
            stdout = "Already up to date.\n" if "pull" in cmd else ""
            return MagicMock(returncode=0, stdout=stdout, stderr="")
        return MagicMock(side_effect=side_effect)

    def test_runs_git_pull_and_uv_sync(self):
        from click.testing import CliRunner

        from memory_bank.cli import cli
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
                   "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"}
            subprocess_module.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess_module.run(["git", "commit", "--allow-empty", "-m", "init"],
                                   cwd=str(repo), check=True, capture_output=True, env=env)
            mock_run = self._no_conflict_mock()
            with patch("memory_bank.commands.update._detect_install_dir", return_value=repo), \
                    patch("memory_bank.commands.update.subprocess.run", mock_run), \
                    patch("memory_bank.commands.update._available_skills", return_value=[]):
                result = CliRunner().invoke(cli, ["update"])
            assert result.exit_code == 0
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("pull" in c for c in calls)
            assert any("uv" in c and "sync" in c for c in calls)
            assert not any("reinstall" in c for c in calls)

    def test_fails_when_autostash_leaves_conflicts(self):
        from click.testing import CliRunner

        from memory_bank.cli import cli
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
                   "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"}
            subprocess_module.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess_module.run(["git", "commit", "--allow-empty", "-m", "init"],
                                   cwd=str(repo), check=True, capture_output=True, env=env)

            def mock_run_with_conflicts(cmd, **kwargs):
                result = MagicMock(returncode=0, stdout="", stderr="")
                if "diff" in cmd and "--diff-filter=U" in cmd:
                    result.stdout = "uv.lock\n"
                elif "pull" in cmd:
                    result.stdout = "Already up to date.\n"
                return result

            with patch("memory_bank.commands.update._detect_install_dir", return_value=repo), \
                    patch("memory_bank.commands.update.subprocess.run", mock_run_with_conflicts):
                result = CliRunner().invoke(cli, ["update"])
            assert result.exit_code != 0
            assert "uv.lock" in result.output
            assert "checkout" in result.output

    def test_force_flag_passes_reinstall_to_uv_sync(self):
        from click.testing import CliRunner

        from memory_bank.cli import cli
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
                   "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"}
            subprocess_module.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess_module.run(["git", "commit", "--allow-empty", "-m", "init"],
                                   cwd=str(repo), check=True, capture_output=True, env=env)
            mock_run = self._no_conflict_mock()
            with patch("memory_bank.commands.update._detect_install_dir", return_value=repo), \
                    patch("memory_bank.commands.update.subprocess.run", mock_run), \
                    patch("memory_bank.commands.update._available_skills", return_value=[]):
                result = CliRunner().invoke(cli, ["update", "--force"])
            assert result.exit_code == 0
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("uv" in c and "sync" in c and "reinstall" in c for c in calls)

    def test_force_flag_uses_reinstall_for_uv_tool(self):
        from click.testing import CliRunner

        from memory_bank.cli import cli
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        with patch("memory_bank.commands.update._detect_uv_tool_install", return_value=True), \
                patch("memory_bank.commands.update._uv_tool_local_path", return_value=None), \
                patch("memory_bank.commands.update.subprocess.run", mock_run):
            result = CliRunner().invoke(cli, ["update", "--force"])
        assert result.exit_code == 0
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("install" in c and "reinstall" in c for c in calls)
        assert not any("upgrade" in c for c in calls)
