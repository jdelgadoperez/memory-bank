# Release Verification Agent — Design Spec
_2026-04-22_

## Objective

Autonomous end-to-end release verification for memory-bank. Detects behavioral regressions across install sources, self-heals via Claude API when found, and opens a PR with a fix + regression test. Runs nightly and on manual dispatch.

## Architecture

Standalone orchestrator script (`scripts/release_verify.py`) backed by a `scripts/release/` library. GitHub Action is a thin wrapper.

```
scripts/
  release_verify.py          # entry point
  release/
    __init__.py
    installer.py             # venv creation + install per scenario
    checker.py               # runs all checks → ScenarioResult list
    assertions.py            # loads assertions.yaml, evaluates invariants
    fix_agent.py             # Claude API fix loop (max 3 iterations)
    reporter.py              # writes _summaries/ markdown report
    pr.py                    # git branch + gh pr create / gh issue create

tests/release/
  assertions.yaml            # declarative behavioral invariants
  golden/
    hooks_after_install.json # expected settings.json hook structure
    uv_receipt_shape.json    # expected uv-receipt.toml field shape

_summaries/                  # gitignored; uploaded as CI artifact on failure
  .gitignore

.github/workflows/
  release-verify.yml
```

## Install Scenarios

| Scenario | Command |
|---|---|
| `local-editable` | `uv tool install --editable <repo-root>` |
| `git-main` | `uv tool install "memory-bank @ git+https://github.com/jdelgadoperez/memory-bank.git"` |
| `wheel` | `uv build` → `uv tool install dist/memory_bank-*.whl` |

Each runs in an isolated tmp directory with `MEMORY_BANK_DB` pointed at a tmp path.

## Checks (per scenario)

| Check | Type |
|---|---|
| `mb --version` exits 0 | assertion |
| `mb ingest claude-code` exits 0 | assertion |
| `mb hooks install --on all` exits 0 | assertion |
| All 5 hooks present in `hooks status` output | assertion |
| Stop and PreCompact markers are distinct strings | assertion |
| `mb distill --dry-run` exits 0 | assertion |
| `mb update` exits 0 | assertion |
| `uv-receipt.toml` field shape | snapshot diff |
| `settings.json` hook JSON after install | snapshot diff |

`--update-golden` flag regenerates snapshot files intentionally.

## assertions.yaml

```yaml
hooks:
  required_markers:
    Stop:
      - "memory-bank ingest claude-code"
      - "memory-bank distill"
    PreCompact:
      - "memory-bank ingest claude-code  # precompact"
    UserPromptSubmit:
      - "memory-bank hooks recall"
    SessionStart:
      - "memory-bank hooks context-summary"
  marker_uniqueness:
    - Stop and PreCompact must not share an identical substring match

uv_receipt:
  required_fields: [tool, version, install_type]
  tool_name: "memory-bank"

commands:
  exit_zero:
    - mb --version
    - mb ingest claude-code
    - mb hooks install --on all
    - mb distill --dry-run
    - mb update
```

## Autonomous Fix Loop

**Trigger:** Any `CheckResult.status == FAIL` after all scenarios complete.

**Context bundle sent to Claude:**
- All `CheckResult` objects (name, expected, actual, diff)
- Relevant source files from `src/memory_bank/` (grepped by failing marker)
- `assertions.yaml` + failing golden snapshot
- `tests/` directory for existing test patterns

Source files sent as a cached system prompt block (prompt caching via Anthropic SDK) — unchanged between iterations so only the failure delta is re-sent.

**Loop (max 3 iterations):**
1. Call `claude-sonnet-4-6` with context bundle + iteration history
2. Claude returns `{ explanation, patch (unified diff), test (pytest code) }`
3. Apply patch to branch `fix/release-verify-YYYYMMDD`
4. Write regression test to `tests/test_release_<check_name>.py`
5. Run `pytest tests/` in wheel scenario venv
6. Pass → open PR and break. Fail → append failure to context, continue.

**On exhaustion (3 failures):** Open GitHub Issue with full diff + iteration log. Summary status: `AGENT_FAILED`.

**PR:** title `fix: <check_name> regression`, body with failing check table + Claude explanation, labels `automated regression`. Not a draft (tests already pass).

## Summary Report

Written to `_summaries/YYYY-MM-DD-HH-MM-release-verify.md`:
- Result header (PASS / FAILED / AGENT_FAILED)
- Table: scenario × check × status
- Fix agent section: iterations, branch, PR/issue link, explanation

## GitHub Actions

```yaml
# .github/workflows/release-verify.yml
on:
  schedule:
    - cron: '0 2 * * *'   # nightly 2am UTC
  workflow_dispatch:        # manual trigger

jobs:
  release-verify:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      issues: write

    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: python scripts/release_verify.py
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          MEMORY_BANK_DB: /tmp/mb-verify-db
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: release-verify-summary
          path: _summaries/
```

## Data Types

```python
@dataclass
class CheckResult:
    name: str
    status: Literal["PASS", "FAIL", "SKIP"]
    expected: str
    actual: str
    diff: str

@dataclass
class ScenarioResult:
    scenario: str   # "local-editable" | "git-main" | "wheel"
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.status != "FAIL" for c in self.checks)
```

## Out of Scope

- Push trigger (add later when publicly published to PyPI)
- PyPI install scenario (activate automatically once `uv pip index versions memory-bank` returns a result)
- Multi-Python version matrix (single version for now)
