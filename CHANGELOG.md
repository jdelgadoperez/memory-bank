# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- The auto-started Qdrant container now uses a pinned image (`qdrant/qdrant:v1.20.2`) instead of the untagged `qdrant/qdrant`, and `qdrant-client` is constrained to `>=1.19,<1.21` to match. Previously the container stayed on whatever version Docker pulled first, while `uv tool install` (which ignores `uv.lock`) installed the newest client, which caused the "client version … is incompatible with server version …" warning. Existing containers keep their image; the README's new "Upgrading the Qdrant server" section walks through upgrading one.

### Documentation
- README: new **Storage modes** section explaining embedded vs. server Qdrant, how the mode is chosen, how to switch in each direction, where `QDRANT_URL` must be set, and a script for copying data between modes. Corrects the earlier claim that switching needs no migration: the two modes use different on-disk formats.

## [0.5.4] — 2026-05-26

### Fixed
- `install.sh` and manual install docs now use the GitHub URL (`git+https://github.com/jdelgadoperez/memory-bank.git`) instead of the bare PyPI name, which resolves to an unrelated third-party `memory-bank` package.
- `memory-bank update` now correctly upgrades git-URL installs by re-running `uv tool install git+<url> --reinstall` instead of `uv tool upgrade memory-bank` (which would pick up the wrong PyPI package).

## [0.5.3] — 2026-05-26

### Fixed
- `memory-bank update` now automatically resets modified tracked files (e.g. `uv.lock` left dirty by a prior failed `uv sync`) before running `git pull`, preventing autostash conflicts that would block future updates.

## [0.5.2] — 2026-05-26

### Fixed
- `memory-bank update` now detects when `git pull --ff-only` with autostash leaves merge conflict markers (e.g. in `uv.lock`) and aborts with a clear error message and recovery instructions, instead of passing a corrupt lock file to `uv sync`.

## [0.5.1] — 2026-05-26

### Added
- `memory-bank update --force`: reinstalls all packages from scratch (`uv sync --reinstall` for git installs, `uv tool install --reinstall` for uv tool installs). Useful for recovering from a broken venv after a Python version change.

### Fixed
- `memory-bank update` no longer crashes with `ModuleNotFoundError: No module named 'rich._unicode_data.unicode17-0-0'` when `uv sync` rebuilds the venv under a different Python version during the same run.

## [0.5.0] — 2026-05-20

## [0.4.0] — 2026-05-20

## [0.3.0] — 2026-05-20

## [0.2.0] — 2026-05-20

### Added
- Soft deletes: `memory-bank delete` now soft-deletes by default (recoverable, purged after 90 days). Use `--hard` for immediate permanent removal.
- Auto-purge: soft-deleted records older than 90 days are hard-deleted automatically at the start of each ingest run.
- Release script: `scripts/release.sh` validates, bumps version, updates changelog, commits, tags, and prompts before pushing.

### Changed
- Ingest output: duplicate count now labeled "duplicates skipped" instead of "already existed".
