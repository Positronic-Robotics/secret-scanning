#!/usr/bin/env python3
"""Test scripts/list_waivers.sh: it names each added waiver by file and line, and never prints a value.

Usage: python3 -I test_list_waivers.py   (standard library only; run by ci.yml)
"""
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / 'scripts' / 'list_waivers.sh'


def git(d, *args):
    return subprocess.run(['git', *args], cwd=d, check=True, capture_output=True, text=True).stdout.strip()


def main():
    value = secrets.token_hex(20)
    with tempfile.TemporaryDirectory() as d:
        git(d, 'init', '-q', '-b', 'main', '.')
        for k, v in (('user.email', 'test@example.invalid'), ('user.name', 'test'), ('commit.gpgsign', 'false')):
            git(d, 'config', k, v)
        Path(d, 'app.py').write_text('a = 1\nb = 2\n')
        Path(d, 'old.txt').write_text('marker gitleaks:allow\n')
        Path(d, '.gitleaksignore').write_text('# reviewed\nold.txt:generic-api-key:1\n')
        git(d, 'add', '.')
        git(d, 'commit', '-qm', 'base')
        base = git(d, 'rev-parse', 'HEAD')
        Path(d, 'app.py').write_text(f'a = 1\nb = 2\nc = "{value}"  # gitleaks:allow\n')
        Path(d, 'sub').mkdir()
        Path(d, 'sub', 'notes.md').write_text(f'x\n\ny\n<!-- {value} gitleaks:allow -->\n')
        os.remove(Path(d, 'old.txt'))
        Path(d, '.gitleaksignore').write_text('# reviewed\nold.txt:generic-api-key:1\n# new\napp.py:generic-api-key:3\n\n')
        git(d, 'add', '-A')
        git(d, 'commit', '-qm', 'change')
        env = {**os.environ, 'BASE': base, 'HEAD_SHA': git(d, 'rev-parse', 'HEAD')}
        p = subprocess.run(['bash', str(SCRIPT)], cwd=d, env=env, capture_output=True, text=True)
    want = [
        '::notice file=app.py,line=3::adds a gitleaks:allow waiver',
        '::notice file=sub/notes.md,line=4::adds a gitleaks:allow waiver',
        '::notice file=.gitleaksignore,line=4::adds ignore entry app.py:generic-api-key:3',
    ]
    got = sorted(p.stdout.splitlines())
    ok = p.returncode == 0 and got == sorted(want) and value not in p.stdout + p.stderr
    print('PASS' if ok else 'FAIL', 'list_waivers.sh', f'exit={p.returncode}', 'value printed' if value in p.stdout + p.stderr else 'no value printed')
    if got != sorted(want):
        print('  want', sorted(want), '\n  got ', got)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
