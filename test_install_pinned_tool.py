#!/usr/bin/env python3
"""Test scripts/install_pinned_tool.sh: a cached tarball with the pinned sha256 is used, any other one is downloaded.

Usage: python3 -I test_install_pinned_tool.py   (standard library only; run by ci.yml)
"""
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / 'scripts' / 'install_pinned_tool.sh'
URL = 'https://example.invalid/releases/download/v1.2.3/gitleaks_1.2.3_linux_x64.tar.gz'
RELEASE_GITLEAKS = '#!/bin/sh\necho release\n'


def tarball(text):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as bundle:
        body = text.encode()
        member = tarfile.TarInfo('gitleaks')
        member.size, member.mode = len(body), 0o755
        bundle.addfile(member, io.BytesIO(body))
    return data.getvalue()


def run(d, release, sha256):
    """Run the script with a curl that writes `release` and counts its calls. Return the result and the outputs."""
    (d / 'release').write_bytes(release)
    commands = d / 'bin'
    commands.mkdir(exist_ok=True)
    curl = commands / 'curl'
    curl.write_text(
        '#!/bin/bash\n'
        'echo "$*" >> "$TEST_DIR/curl.log"\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = -o ]; then cp "$TEST_DIR/release" "$2"; fi\n'
        '  shift\n'
        'done\n'
    )
    curl.chmod(0o755)
    output = d / 'output'
    output.unlink(missing_ok=True)
    env = {
        **os.environ,
        'PATH': f'{commands}{os.pathsep}{os.environ["PATH"]}',
        'TEST_DIR': str(d),
        'TOOL': 'gitleaks',
        'TOOL_URL': URL,
        'TOOL_SHA256': sha256,
        'DOWNLOAD_DIR': str(d / 'download'),
        'GITHUB_OUTPUT': str(output),
    }
    p = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True)
    outputs = dict(line.split('=', 1) for line in output.read_text().splitlines()) if output.exists() else {}
    return p, outputs


def downloads(d):
    log = d / 'curl.log'
    return len(log.read_text().splitlines()) if log.exists() else 0


def check(condition, message):
    if not condition:
        print(f'FAIL: {message}', file=sys.stderr)
        sys.exit(1)


def main():
    release = tarball(RELEASE_GITLEAKS)
    sha256 = hashlib.sha256(release).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p, out = run(d, release, sha256)
        check(p.returncode == 0, f'a cache miss downloads the release: {p.stderr}')
        check(downloads(d) == 1, 'a cache miss downloads once')
        check(Path(out['bin']).read_text() == RELEASE_GITLEAKS, 'bin is the gitleaks of the release')

        p, out = run(d, tarball('#!/bin/sh\necho other\n'), sha256)
        check(p.returncode == 0, f'a cache hit installs: {p.stderr}')
        check(downloads(d) == 1, 'a cache hit downloads nothing')
        check(Path(out['bin']).read_text() == RELEASE_GITLEAKS, 'a cache hit installs the cached gitleaks')

        (d / 'download' / URL.rsplit('/', 1)[1]).write_bytes(tarball('#!/bin/sh\necho changed\n'))
        p, out = run(d, release, sha256)
        check(p.returncode == 0, f'a changed cached tarball is downloaded again: {p.stderr}')
        check(downloads(d) == 2, 'a changed cached tarball is not used')

        (d / 'download').rename(d / 'old')
        p, out = run(d, tarball('#!/bin/sh\necho changed\n'), sha256)
        check(p.returncode != 0 and out == {}, 'a release with another sha256 fails and gives no gitleaks')
    print('ok: install_pinned_tool.sh uses a cached tarball only with the pinned sha256')


if __name__ == '__main__':
    main()
