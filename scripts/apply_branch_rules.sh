#!/usr/bin/env bash
# Apply the "rule-for_main" ruleset (same pattern as madhurmishra9/soinsight, plus a
# pull-request + code-owner review requirement). Run once as the repository owner:
#   gh auth login            # token needs admin rights on the repo
#   ./scripts/apply_branch_rules.sh
set -euo pipefail

REPO="${REPO:-madhurmishra9/ecoops-navigator}"
NAME="rule-for_main"
RULESET_FILE="$(dirname "$0")/../.github/rulesets/${NAME}.json"

existing_id="$(gh api "repos/${REPO}/rulesets" --jq ".[] | select(.name==\"${NAME}\") | .id" || true)"
if [[ -n "${existing_id}" ]]; then
  echo "Updating ruleset ${NAME} (${existing_id}) on ${REPO}..."
  gh api -X PUT "repos/${REPO}/rulesets/${existing_id}" --input "${RULESET_FILE}" >/dev/null
else
  echo "Creating ruleset ${NAME} on ${REPO}..."
  gh api -X POST "repos/${REPO}/rulesets" --input "${RULESET_FILE}" >/dev/null
fi

echo "Effective rules on main:"
gh api "repos/${REPO}/rules/branches/main" --jq '.[].type'
