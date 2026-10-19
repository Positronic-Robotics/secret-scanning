#!/usr/bin/env bash
# Scan the commits BASE..HEAD_SHA with the hash-checked .gitleaks.toml, using the gitleaks at GITLEAKS_BIN.
# The workflow embeds this file verbatim (scripts/sync_workflow.py); run it from the repository root.
set -euo pipefail
: "${BASE:?}" "${HEAD_SHA:?}" "${GITLEAKS_BIN:?}"
# remerge reports a conflict resolution's file as b/<path>, so each waiver is also written in that form.
ignore="$(mktemp -d)/.gitleaksignore"
touch "$ignore"
if [ -f .gitleaksignore ]; then
  { grep -v -E '^[[:space:]]*(#|$)' .gitleaksignore || true; } | while IFS= read -r entry; do
    printf '%s\n' "$entry"
    if [[ "$entry" =~ ^([0-9a-f]{40}):(.*)$ ]]; then
      printf '%s:b/%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    else
      printf 'b/%s\n' "$entry"
    fi
  done > "$ignore"
fi
# The config and ignore paths are explicit, so no environment variable can replace them.
env -u GITLEAKS_CONFIG -u GITLEAKS_CONFIG_TOML "$GITLEAKS_BIN" git \
  --config "$PWD/.gitleaks.toml" --gitleaks-ignore-path "$ignore" \
  --log-opts="--diff-merges=remerge $BASE..$HEAD_SHA" --redact --no-banner --verbose .
