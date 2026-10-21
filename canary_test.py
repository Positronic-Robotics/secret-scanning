#!/usr/bin/env python3
"""Canary test for the shared gitleaks rules.

Generated fakes of every guarded shape must be caught by the expected rule, placeholders must stay
quiet, a fake added while resolving a merge conflict must be caught, and scripts/scan.sh must honour a
.gitleaksignore waiver for such a fake. Values are generated at run time and never printed; output
names rule ids and file names only.

Usage: canary_test.py CONFIG [--tree NAME=DIR[:IGNOREFILE] ...]
Run by ci.yml in this repository only; callers never run it. Standard library only.
"""
import argparse
import json
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
from pathlib import Path

R = random.SystemRandom()
AN = string.ascii_letters + string.digits
HEX = '0123456789abcdef'


def rs(n, alpha=AN):
    return ''.join(R.choice(alpha) for _ in range(n))


def nebius():
    return 'ne1' + rs(1) + rs(298, AN + '-.')


def tailscale(kind='auth'):
    return f'tskey-{kind}-' + rs(12) + '-' + rs(33)


FLAG_NAMES = [
    'token', 'TOKEN', 'api-key', 'api_key', 'apikey', 'password', 'passwd', 'secret', 'secret-key',
    'access-key', 'auth-key', 'authkey', 'access-token', 'api-token', 'client-secret', 'hf-token', 'HF-TOKEN',
]

# Fakes the rules must catch. Each value is random and generated fresh on every run, so this file holds no
# real secret, only the shapes.
POSITIVE = {
    'nebius.txt': ('nebius-iam-token', lambda: 'NEBIUS_TOKEN=' + nebius()),
    'nebius_header.txt': ('nebius-iam-token', lambda: 'curl -H "Authorization: Bearer ' + nebius() + '"'),
    'anthropic_oat.json': ('anthropic-oauth-token', lambda: '{"accessToken": "sk-ant-oat01-' + rs(95, AN + '-_') + '"}'),
    'anthropic_ort.txt': ('anthropic-oauth-token', lambda: 'refresh = sk-ant-ort01-' + rs(95, AN + '-_')),
    'tailscale_auth.sh': ('tailscale-key', lambda: 'tailscale up --login-server=x --hostname=y ' + tailscale('auth')),
    'tailscale_client.txt': ('tailscale-key', lambda: tailscale('client')),
    'cli_punctuation.sh': ('cli-flag-secret', lambda: 'mysql --password=' + rs(10) + '!@#%' + rs(8)),
    'cli_hex.sh': ('cli-flag-secret', lambda: 'tool --api-key ' + rs(32, HEX)),
    # Quoted values may hold shell punctuation; single quotes keep $ literal.
    'cli_quoted_single.sh': ('cli-flag-secret', lambda: "mysql --password='" + rs(3) + '$?()' + rs(16) + "'"),
    'cli_quoted_double.sh': ('cli-flag-secret', lambda: 'tool --api-key "' + rs(3) + '?()!' + rs(16) + '"'),
    'default_github_pat.txt': ('github-pat', lambda: 'ghp_' + rs(36)),
    'curl_literal.sh': ('curl-auth-user', lambda: 'curl -u admin:' + rs(20) + ' https://api.example.com/v2/devices'),
    'curl_var_user.sh': ('curl-auth-user', lambda: 'curl -u "$API_USER:' + rs(20) + '" https://api.example.com/v2/devices'),
    # A literal flag on the same line as an lpass command is still caught, before or after it.
    'cli_before_lpass.sh': ('cli-flag-secret', lambda: 'tool --api-key=' + rs(25) + '  # or: lpass show --password Infra/x'),
    'cli_after_lpass.sh': ('cli-flag-secret', lambda: 'lpass show --password "Infra/' + rs(30) + '" && tool --token ' + rs(25)),
}
for _i, _flag in enumerate(FLAG_NAMES):
    _sep = '=' if _i % 2 else ' '
    POSITIVE[f'flag_{_i:02d}.sh'] = ('cli-flag-secret', lambda f=_flag, s=_sep: f'run --{f}{s}{rs(25)}')

# Placeholders and references the rules must ignore. The random parts are generated fresh on every run too.
NEGATIVE = {
    'neg_env.sh': lambda: 'run --token "$TOKEN" --api-key ${API_KEY} --password "$(cat pw)"',
    'neg_placeholder.md': lambda: 'run --token <token> --secret {{ secret }} --password changeme',
    'neg_suffix.sh': lambda: 'run --token-file /etc/token --password-stdin --api-key-id 12345 --secret-name db-password',
    'neg_path.sh': lambda: 'run --token /run/secrets/' + rs(20) + ' --password ~/.config/' + rs(20),
    'neg_count.sh': lambda: 'serve --max-tokens 4096 --num-tokens 128',
    'neg_quoted_expand.sh': lambda: 'run --api-key "sk-$OPENAI_API_KEY_' + rs(8).upper() + '" --secret "name of the secret to read"',
    'neg_lpass.sh': lambda: 'lpass show --password "Infra/' + rs(30) + '"',
    'neg_lpass_subst.sh': lambda: "export PW=\"$(lpass show --sync=now --password 'Infra/" + rs(30) + "')\"",
    'neg_secret_refs.sh': lambda: ('tailscale up --auth-key=file:/run/' + rs(8).lower() + '/tskey && '
                                   'docker buildx build --secret id=hf_token,src=/root/.hf_token . && '
                                   'nebius ai job create --env-secret HF_TOKEN=' + rs(6).lower() + '-team-hf-token'),
    'neg_curl_var.sh': lambda: 'R=$(curl -s -u "$TS_API_KEY:" "https://api.example.com/v2/devices")',
    'neg_curl_vars.sh': lambda: 'curl -u "${API_USER}:$API_PASS" https://api.example.com/v2/devices',
    'neg_prose.md': lambda: 'tskey-auth keys are minted in the admin console; ne1 tokens expire in 12 hours',
}


def git(d, *args):
    return subprocess.run(['git', *args], cwd=d, check=True, capture_output=True, text=True).stdout.strip()


def scan(cmd, cwd):
    with tempfile.NamedTemporaryFile(suffix='.json') as rep:
        p = subprocess.run(cmd + ['--redact', '--no-banner', '--log-level', 'error', '-f', 'json', '-r', rep.name],
                           cwd=cwd, capture_output=True, text=True)
        try:
            found = json.load(open(rep.name))
        except ValueError:
            found = []
        return p.returncode, found


def new_repo(d, config):
    git(d, 'init', '-q', '-b', 'main', '.')
    for k, v in (('user.email', 'canary@example.invalid'), ('user.name', 'canary'), ('commit.gpgsign', 'false')):
        git(d, 'config', k, v)
    shutil.copy(config, Path(d) / '.gitleaks.toml')
    git(d, 'add', '.')
    git(d, 'commit', '-qm', 'config')


def report(ok, what, name, detail):
    print(f"{'PASS' if ok else 'FAIL'} {what:7s} {name:24s} {detail}")
    return not ok


def shapes(config):
    fails = 0
    with tempfile.TemporaryDirectory() as d:
        new_repo(d, config)
        for name, (_, gen) in POSITIVE.items():
            (Path(d) / name).write_text(gen() + '\n')
        for name, gen in NEGATIVE.items():
            (Path(d) / name).write_text(gen() + '\n')
        git(d, 'add', '.')
        git(d, 'commit', '-qm', 'canaries')
        code, found = scan(['gitleaks', 'git', '--log-opts=HEAD~1..HEAD', '.'], d)
        by_file = {}
        for f in found:
            by_file.setdefault(f['File'], set()).add(f['RuleID'])
        for name, (rule, _) in POSITIVE.items():
            fails += report(rule in by_file.get(name, set()), 'caught', name, f'expect {rule}, got {sorted(by_file.get(name, []))}')
        for name in NEGATIVE:
            fails += report(name not in by_file, 'quiet', name, f'got {sorted(by_file.get(name, []))}')
        fails += report(code == 1, 'exit', 'shape scan', f'exit={code}, 1 expected')
    return fails


def merge_repo(d, config, ignore=''):
    """A repository whose last commit resolves a conflict by adding a fake on line 2 of settings.txt."""
    new_repo(d, config)
    conf = Path(d) / 'settings.txt'
    conf.write_text('mode = base\n')
    (Path(d) / '.gitleaksignore').write_text(ignore)
    git(d, 'add', '.')
    git(d, 'commit', '-qm', 'base')
    base = git(d, 'rev-parse', 'HEAD')
    git(d, 'checkout', '-qb', 'side')
    conf.write_text('mode = side\n')
    git(d, 'commit', '-qam', 'side')
    git(d, 'checkout', '-q', 'main')
    conf.write_text('mode = main\n')
    git(d, 'commit', '-qam', 'main')
    subprocess.run(['git', 'merge', '-q', 'side'], cwd=d, capture_output=True)
    fake = tailscale('auth')
    conf.write_text('mode = merged\nkey = ' + fake + '\n')
    git(d, 'add', '.')
    git(d, 'commit', '-qm', 'merge')
    return base, fake


def merge_resolution(config):
    """A fake that exists only in a conflict resolution is visible only with --diff-merges=remerge."""
    with tempfile.TemporaryDirectory() as d:
        base, _ = merge_repo(d, config)
        code, found = scan(['gitleaks', 'git', f'--log-opts=--diff-merges=remerge {base}..HEAD', '.'], d)
        # gitleaks names a file from a remerge diff `b/<path>`, so match the suffix.
        caught = any(f['File'].endswith('settings.txt') and f['RuleID'] == 'tailscale-key' for f in found)
        return report(caught and code == 1, 'caught', 'merge resolution', f'exit={code}, found={sorted({(f["File"], f["RuleID"]) for f in found})}')


def scan_script(config):
    """scripts/scan.sh, as the workflow runs it: a waived resolution passes, an unwaived one fails."""
    script = Path(__file__).resolve().parent / 'scripts' / 'scan.sh'
    fails = 0
    for name, ignore, want in (('waived resolution', 'settings.txt:tailscale-key:2\n', 0), ('unwaived resolution', '', 1)):
        with tempfile.TemporaryDirectory() as d:
            base, fake = merge_repo(d, config, ignore)
            env = {**os.environ, 'BASE': base, 'HEAD_SHA': git(d, 'rev-parse', 'HEAD'), 'GITLEAKS_BIN': shutil.which('gitleaks'),
                   'GITLEAKS_CONFIG': '/nonexistent/config.toml'}
            p = subprocess.run(['bash', str(script)], cwd=d, env=env, capture_output=True, text=True)
            leaked = fake in p.stdout + p.stderr
            fails += report(p.returncode == want and not leaked, 'script', name, f'exit={p.returncode}, {want} expected, value printed={leaked}')
    # An ignore file with no entries (empty, or comments only) must not fail a clean range.
    for name, ignore in (('empty ignore file', ''), ('comment-only ignore file', '# waivers go here\n')):
        with tempfile.TemporaryDirectory() as d:
            new_repo(d, config)
            (Path(d) / '.gitleaksignore').write_text(ignore)
            (Path(d) / 'notes.txt').write_text('first\n')
            git(d, 'add', '.')
            git(d, 'commit', '-qm', 'base')
            base = git(d, 'rev-parse', 'HEAD')
            (Path(d) / 'notes.txt').write_text('first\nsecond\n')
            git(d, 'commit', '-qam', 'clean change')
            env = {**os.environ, 'BASE': base, 'HEAD_SHA': git(d, 'rev-parse', 'HEAD'), 'GITLEAKS_BIN': shutil.which('gitleaks')}
            p = subprocess.run(['bash', str(script)], cwd=d, env=env, capture_output=True, text=True)
            fails += report(p.returncode == 0, 'script', name, f'exit={p.returncode}, 0 expected')
    return fails


def tree(name, spec, config):
    src, _, ignore = spec.partition(':')
    with tempfile.TemporaryDirectory() as d:
        shutil.copytree(src, d, dirs_exist_ok=True, symlinks=True)
        shutil.copy(config, Path(d) / '.gitleaks.toml')
        if ignore:
            shutil.copy(ignore, Path(d) / '.gitleaksignore')
        code, found = scan(['gitleaks', 'dir', '.'], d)
    return report(code == 0, 'tree', name, f'exit={code}, findings={[(f["File"], f["RuleID"], f["StartLine"]) for f in found]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('config')
    ap.add_argument('--tree', action='append', default=[], help='NAME=DIR[:IGNOREFILE], scanned from inside DIR')
    a = ap.parse_args()
    config = str(Path(a.config).resolve())
    fails = shapes(config) + merge_resolution(config) + scan_script(config)
    for t in a.tree:
        n, _, spec = t.partition('=')
        fails += tree(n, spec, config)
    print('FAILURES', fails)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
