from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scripts.release.types import InstalledScenario

REPO_ROOT = Path(__file__).parent.parent.parent


@dataclass
class ScenarioConfig:
    name: str
    install_cmd_template: list[str]


SCENARIOS: list[ScenarioConfig] = [
    ScenarioConfig(
        name="local-editable",
        install_cmd_template=["uv", "tool", "install", "--editable", "{repo_root}"],
    ),
    ScenarioConfig(
        name="git-main",
        install_cmd_template=[
            "uv",
            "tool",
            "install",
            "memory-bank @ git+https://github.com/jdelgadoperez/memory-bank.git",
        ],
    ),
    ScenarioConfig(
        name="wheel",
        install_cmd_template=["uv", "tool", "install", "{wheel_path}"],
    ),
]


def _find_wheel(dist_dir: Path) -> Path:
    wheels = list(dist_dir.glob("memory_bank-*.whl"))
    if not wheels:
        raise FileNotFoundError(f"No wheel found in {dist_dir}")
    return sorted(wheels)[-1]


def build_wheel(repo_root: Path, build_dir: Path) -> Path:
    dist_dir = build_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "build", "--out-dir", str(dist_dir)],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return _find_wheel(dist_dir)


def install_scenario(config: ScenarioConfig, repo_root: Path) -> InstalledScenario:
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"mb-verify-{config.name}-"))
    tool_dir = tmp_dir / "tools"
    db_dir = tmp_dir / "db"
    tool_dir.mkdir()
    db_dir.mkdir()

    env_override = {
        "UV_TOOL_DIR": str(tool_dir),
        "MEMORY_BANK_DB": str(db_dir),
    }

    wheel_path: Path | None = None
    if config.name == "wheel":
        wheel_path = build_wheel(repo_root, tmp_dir)

    cmd = [
        part.format(repo_root=str(repo_root), wheel_path=str(wheel_path or ""))
        for part in config.install_cmd_template
    ]

    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        env={**_base_env(), **env_override},
    )

    mb_bin = tool_dir / "memory-bank" / "bin" / "memory-bank"
    return InstalledScenario(
        scenario=config.name,
        mb_bin=mb_bin,
        tmp_dir=tmp_dir,
        env=env_override,
    )


def cleanup(installed: InstalledScenario) -> None:
    shutil.rmtree(installed.tmp_dir, ignore_errors=True)


def _base_env() -> dict[str, str]:
    return dict(os.environ)
