# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
