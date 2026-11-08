#!/usr/bin/env bash
# Extract the binary TOOL from the release tarball at TOOL_URL into a new directory, and write its path as bin to GITHUB_OUTPUT.
# The tarball comes from DOWNLOAD_DIR when the Actions cache put it there with the sha256 TOOL_SHA256, else from TOOL_URL.
# The workflows embed this file verbatim (scripts/sync_workflow.py).
set -euo pipefail
: "${TOOL:?}" "${TOOL_URL:?}" "${TOOL_SHA256:?}" "${DOWNLOAD_DIR:?}" "${GITHUB_OUTPUT:?}"
tarball="$DOWNLOAD_DIR/${TOOL_URL##*/}"
if [ -f "$tarball" ] && echo "$TOOL_SHA256  $tarball" | sha256sum --check --status --strict; then
  echo "$TOOL: the Actions cache holds ${tarball##*/}, so nothing is downloaded."
else
  echo "$TOOL: the Actions cache does not hold ${tarball##*/}. Download $TOOL_URL."
  rm -rf "$DOWNLOAD_DIR"
  mkdir -p "$DOWNLOAD_DIR"
  # The retries span 3 minutes: an outage of the download server can last minutes.
  curl -sSfL --retry 12 --retry-delay 15 --retry-max-time 180 --retry-all-errors -o "$tarball" "$TOOL_URL"
  echo "$TOOL_SHA256  $tarball" | sha256sum --check --strict
fi
dir="$(mktemp -d)"
tar -xzf "$tarball" -C "$dir" "$TOOL"
echo "bin=$dir/$TOOL" >> "$GITHUB_OUTPUT"
