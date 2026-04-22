from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class CheckResult:
    name: str
    status: Literal["PASS", "FAIL", "SKIP"]
    expected: str
    actual: str
    diff: str


@dataclass
class ScenarioResult:
    scenario: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.status != "FAIL" for c in self.checks)


@dataclass
class InstalledScenario:
    scenario: str
    mb_bin: Path
    tmp_dir: Path
    env: dict[str, str]
