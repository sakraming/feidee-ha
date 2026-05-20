#!/usr/bin/env bash
# Publish feidee-ha to GitHub (run after: gh auth login)
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="${1:-zhangqiming/feidee-ha}"
VERSION="v0.4.2"

if ! command -v gh >/dev/null 2>&1; then
  echo "Install GitHub CLI: brew install gh"
  exit 1
fi

gh auth status

if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo create "${REPO#*/}" --public --source=. --remote=origin \
    --description "Home Assistant HACS integration for Feidee (飞蛋记账)"
else
  git push -u origin main
fi

git push origin "${VERSION}" 2>/dev/null || true

gh release create "${VERSION}" \
  --title "Feidee HA ${VERSION}" \
  --notes "$(cat <<EOF
## Feidee Home Assistant Integration ${VERSION}

- HACS custom integration for Feidee (飞蛋记账)
- Multi-book + user-selected metrics at setup
- Default refresh: 15 min (configurable 5–60 min)
- Local API demo script included (no credentials)

### HACS install
Add custom repository: \`https://github.com/${REPO}\` (category: Integration)
EOF
)"

echo "Done: https://github.com/${REPO}"
