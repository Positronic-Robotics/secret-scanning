#!/usr/bin/env python3
"""Write the rules hash and the embedded canary into the reusable workflow, or check them.

The reusable workflow runs in the caller's checkout and cannot read this repository's files, so it
carries the sha256 of gitleaks.toml and a copy of canary_test.py. Run this after editing either.

Usage: scripts/sync_workflow.py [--check]   (--check exits 1 when the workflow is out of date)
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / '.github/workflows/gitleaks.yml'
BEGIN, END = '# BEGIN CANARY', '# END CANARY'


def render(text):
    digest = hashlib.sha256((ROOT / 'gitleaks.toml').read_bytes()).hexdigest()
    text = re.sub(r'(RULES_SHA256: )\S+', lambda m: m.group(1) + digest, text, count=1)
    start, end = text.index(BEGIN), text.index(END)
    indent = text[text.rindex('\n', 0, start) + 1:start]
    body = (ROOT / 'canary_test.py').read_text()
    embedded = ''.join(indent + line if line.strip() else '\n' for line in body.splitlines(keepends=True))
    return text[:start] + BEGIN + '\n' + embedded + indent + text[end:]


def main():
    current = WORKFLOW.read_text()
    wanted = render(current)
    if '--check' in sys.argv[1:]:
        if wanted != current:
            print(f'{WORKFLOW.relative_to(ROOT)} is out of date: run scripts/sync_workflow.py', file=sys.stderr)
            return 1
        print('workflow in sync with gitleaks.toml and canary_test.py')
        return 0
    WORKFLOW.write_text(wanted)
    return 0


if __name__ == '__main__':
    sys.exit(main())
