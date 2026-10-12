#!/usr/bin/env bash
# Apply the main-branch ruleset and merge settings to this repository.
# Run once, from your own machine, as the repository owner:
#   gh auth login            # needs a token with admin rights on the repo
#   ./scripts/apply_branch_rules.sh
set -euo pipefail

REPO="${REPO:-madhurmishra9/ecoops-navigator}"
RULESET_FILE="$(dirname "$0")/../.github/rulesets/protect-main.json"

echo "Configuring merge settings on ${REPO}..."
gh repo edit "${REPO}" \
  --enable-squash-merge \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge

existing_id="$(gh api "repos/${REPO}/rulesets" --jq '.[] | select(.name=="protect-main") | .id' || true)"
if [[ -n "${existing_id}" ]]; then
  echo "Updating existing ruleset ${existing_id}..."
  gh api -X PUT "repos/${REPO}/rulesets/${existing_id}" --input "${RULESET_FILE}" >/dev/null
else
  echo "Creating ruleset protect-main..."
  gh api -X POST "repos/${REPO}/rulesets" --input "${RULESET_FILE}" >/dev/null
fi

echo "Done. Active rulesets:"
gh api "repos/${REPO}/rulesets" --jq '.[] | "\(.id)  \(.name)  \(.enforcement)"'
