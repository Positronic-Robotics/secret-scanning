#!/usr/bin/env python3
"""Write derived values into the workflows and README, or check that they are current.

The reusable workflow runs in the caller's checkout and cannot read this repository's files, so it
carries the sha256 of gitleaks.toml and verbatim copies of scripts/list_waivers.sh and scripts/scan.sh.
Its GITLEAKS_VERSION and GITLEAKS_SHA256 are the one source for the version pin: this script copies
them into ci.yml and the README. Run it after editing any of these.

Usage: scripts/sync_workflow.py [--check]   (--check exits 1 when a file is out of date)
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / '.github/workflows/gitleaks.yml'
CI = ROOT / '.github/workflows/ci.yml'
README = ROOT / 'README.md'
EMBEDDED = ['scripts/list_waivers.sh', 'scripts/scan.sh']


def env_value(text, name):
    return re.search(rf'^\s*{name}: (\S+)$', text, re.M).group(1)


def set_env(text, name, value):
    return re.sub(rf'^(\s*{name}: )\S+$', lambda m: m.group(1) + value, text, count=1, flags=re.M)


def embed(text, rel):
    begin, end = f'# BEGIN {rel}', f'# END {rel}'
    start, stop = text.index(begin), text.index(end)
    indent = text[text.rindex('\n', 0, start) + 1:start]
    body = (ROOT / rel).read_text()
    lines = ''.join(indent + line if line.strip() else '\n' for line in body.splitlines(keepends=True))
    return text[:start] + begin + '\n' + lines + indent + text[stop:]


def render_workflow(text):
    digest = hashlib.sha256((ROOT / 'gitleaks.toml').read_bytes()).hexdigest()
    text = set_env(text, 'RULES_SHA256', digest)
    for rel in EMBEDDED:
        text = embed(text, rel)
    return text


def render_ci(text, version, sha):
    return set_env(set_env(text, 'GITLEAKS_VERSION', version), 'GITLEAKS_SHA256', sha)


def render_readme(text, version):
    text = re.sub(r'(rev: v)\d+\.\d+\.\d+', lambda m: m.group(1) + version, text)
    return re.sub(r'(gitleaks )\d+\.\d+\.\d+', lambda m: m.group(1) + version, text)


def main():
    workflow = render_workflow(WORKFLOW.read_text())
    version, sha = env_value(workflow, 'GITLEAKS_VERSION'), env_value(workflow, 'GITLEAKS_SHA256')
    wanted = {
        WORKFLOW: workflow,
        CI: render_ci(CI.read_text(), version, sha),
        README: render_readme(README.read_text(), version),
    }
    stale = [p for p, text in wanted.items() if p.read_text() != text]
    if '--check' in sys.argv[1:]:
        for p in stale:
            print(f'{p.relative_to(ROOT)} is out of date: run scripts/sync_workflow.py', file=sys.stderr)
        if not stale:
            print('workflows and README in sync')
        return 1 if stale else 0
    for p in stale:
        p.write_text(wanted[p])
    return 0


if __name__ == '__main__':
    sys.exit(main())
