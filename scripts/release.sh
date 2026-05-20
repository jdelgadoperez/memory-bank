#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# memory-bank release script
# Usage: ./scripts/release.sh patch | minor | major | <explicit-version>
# ---------------------------------------------------------------------------

PYPROJECT="pyproject.toml"
CHANGELOG="CHANGELOG.md"

# ── 1. Validate clean working tree ──────────────────────────────────────────
if [[ -n "$(git status --porcelain)" ]]; then
  echo "❌ Working tree is not clean. Commit or stash changes before releasing."
  exit 1
fi

# ── 2. Run test suite ────────────────────────────────────────────────────────
echo "→ Running tests..."
if ! uv run pytest -q; then
  echo "❌ Tests failed. Fix them before releasing."
  exit 1
fi
echo "✓ All tests passed."

# ── 3. Resolve new version ───────────────────────────────────────────────────
BUMP="${1:-}"
if [[ -z "$BUMP" ]]; then
  echo "❌ Usage: $0 patch | minor | major | <version>"
  exit 1
fi

CURRENT=$(python3 -c "
import re
content = open('$PYPROJECT').read()
m = re.search(r'version = \"([^\"]+)\"', content)
print(m.group(1))
")

if [[ "$BUMP" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  NEW_VERSION="$BUMP"
else
  NEW_VERSION=$(python3 -c "
parts = '$CURRENT'.split('.')
major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
bump = '$BUMP'
if bump == 'major':
    print(f'{major + 1}.0.0')
elif bump == 'minor':
    print(f'{major}.{minor + 1}.0')
elif bump == 'patch':
    print(f'{major}.{minor}.{patch + 1}')
else:
    raise ValueError(f'Unknown bump type: {bump}')
")
fi

echo "→ Bumping $CURRENT → $NEW_VERSION"

# ── 4. Bump version in pyproject.toml ────────────────────────────────────────
python3 -c "
import re
content = open('$PYPROJECT').read()
updated = re.sub(r'version = \"[^\"]+\"', 'version = \"$NEW_VERSION\"', content, count=1)
open('$PYPROJECT', 'w').write(updated)
"
echo "✓ Updated $PYPROJECT"

# ── 5. Update CHANGELOG.md ───────────────────────────────────────────────────
TODAY=$(date +%Y-%m-%d)
python3 -c "
content = open('$CHANGELOG').read()
new_header = '## [Unreleased]\n\n## [$NEW_VERSION] — $TODAY'
if '## [Unreleased]' not in content:
    print('❌ No [Unreleased] section found in \$CHANGELOG')
    exit(1)
updated = content.replace('## [Unreleased]', new_header, 1)
open('$CHANGELOG', 'w').write(updated)
"
echo "✓ Updated $CHANGELOG"

# ── 6. Commit ────────────────────────────────────────────────────────────────
git add "$PYPROJECT" "$CHANGELOG"
git commit -m "chore(release): v$NEW_VERSION"
echo "✓ Committed v$NEW_VERSION"

# ── 7. Tag ───────────────────────────────────────────────────────────────────
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"
echo "✓ Tagged v$NEW_VERSION"

# ── 8. Confirm before push ───────────────────────────────────────────────────
echo ""
echo "Ready to push:"
echo "  Commit: $(git log -1 --oneline)"
echo "  Tag:    v$NEW_VERSION → $(git rev-parse HEAD)"
echo ""
read -rp "Push commit and tag to origin? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
  echo "Aborted. Commit and tag created locally — push manually when ready:"
  echo "  git push && git push origin v$NEW_VERSION"
  exit 0
fi

# ── 9. Push ──────────────────────────────────────────────────────────────────
git push
git push origin "v$NEW_VERSION"
echo "✓ Released v$NEW_VERSION"
