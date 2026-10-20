#!/usr/bin/env bash
# Print, as notices, every gitleaks:allow line and .gitleaksignore entry that BASE...HEAD_SHA adds.
# File and line only: a line marked gitleaks:allow may hold a fake value, so it is never printed.
# The workflow embeds this file verbatim (scripts/sync_workflow.py); run it from the repository root.
set -euo pipefail
: "${BASE:?}" "${HEAD_SHA:?}"
git diff --no-ext-diff --no-textconv -U0 "$BASE...$HEAD_SHA" | awk '
  /^\+\+\+ / { file = ($2 ~ /^b\//) ? substr($2, 3) : ""; next }
  /^@@/ { split($3, a, ","); line = substr(a[1], 2) - 1; next }
  /^\+/ { line++; if (file != "" && $0 ~ /gitleaks:allow/) printf "::notice file=%s,line=%d::adds a gitleaks:allow waiver\n", file, line }
'
git diff --no-ext-diff --no-textconv -U0 "$BASE...$HEAD_SHA" -- .gitleaksignore | awk '
  /^@@/ { split($3, a, ","); line = substr(a[1], 2) - 1; next }
  /^\+\+\+ / { next }
  /^\+/ { line++; entry = substr($0, 2); if (entry !~ /^[[:space:]]*(#|$)/) printf "::notice file=.gitleaksignore,line=%d::adds ignore entry %s\n", line, entry }
'
