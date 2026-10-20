# secret-scanning

Shared gitleaks rules and a reusable CI workflow for Positronic-Robotics repositories. Every repository runs the same check on each pull request and each push to its default branch, with the same rules.

## What the check does

The reusable workflow `.github/workflows/gitleaks.yml` has one job, `gitleaks`. In a calling repository its check is expected to be named `gitleaks / gitleaks`. On every run it:

1. Installs gitleaks 8.30.1 from the release tarball into a fresh temporary directory and verifies its sha256.
2. Fails if the repository's `.gitleaks.toml` is not a byte copy of `gitleaks.toml` here, at the commit the caller pins.
3. Prints, as notices, every `gitleaks:allow` marker and `.gitleaksignore` entry the change adds (`scripts/list_waivers.sh`). It prints file and line only.
4. Scans only the commits the pull request or push adds (`scripts/scan.sh`), with `--diff-merges=remerge` so that conflict resolutions in merge commits are scanned too. The rules file and the ignore list are passed explicitly, so no environment variable can replace them.

A finding fails the check and prints file, line, commit and rule id. It never prints the value. A push whose base commit cannot be resolved (the first push of a branch, or a force push) fails rather than scanning less.

The job runs on a GitHub-hosted runner with `contents: read` and no secrets, so it is safe on pull requests from forks. No step executes a file from the checkout, which holds the pull request's code: the two scripts are copied into the workflow (`scripts/sync_workflow.py`).

The canary runs in this repository's CI on every change and weekly, not in callers: generated fakes of every guarded shape must be caught, placeholders must stay quiet, a fake added while resolving a merge conflict must be caught, and `scripts/scan.sh` must honour a `.gitleaksignore` waiver for one.

## Rules

`gitleaks.toml` extends the gitleaks default rules with four of ours:

| Rule | Catches |
|---|---|
| `nebius-iam-token` | Nebius IAM access tokens (`ne1` prefix) |
| `anthropic-oauth-token` | Anthropic OAuth access and refresh tokens (`sk-ant-oat01-`, `sk-ant-ort01-`) |
| `tailscale-key` | Tailscale auth, API, OAuth client and webhook keys (`tskey-`) |
| `cli-flag-secret` | A literal credential passed as a flag, such as `--token`, `--api-key`, `--password`, `--client-secret` or `--hf-token`, in any case |

`cli-flag-secret` ignores variables, placeholders and paths (`$TOKEN`, `<token>`, `/run/secrets/x`), flags that only name a file or field (`--token-file`, `--password-stdin`), `lpass show --password <item>`, and values that say where a secret lives (`file:<path>`, docker `id=<name>,src=<path>`, `NAME=<secret-name>`).

## Adopting it in a repository

1. Copy `examples/caller.yml` to `.github/workflows/gitleaks.yml`. Replace `<PIN>` with the full sha of the commit of this repository you are adopting. Keep the job id `gitleaks` and the `owner-free: allow` comments on the `branches:` and `uses:` lines.
2. Copy `gitleaks.toml` from that same commit to `.gitleaks.toml` at the repository root. Both CI and the pre-commit hook read it from there with no arguments.
3. Run a full-tree scan from inside an export of the default branch, so gitignored files are not read:

   ```sh
   tmp=$(mktemp -d) && git archive HEAD | tar -x -C "$tmp" && cp .gitleaks.toml "$tmp"/ && (cd "$tmp" && gitleaks dir --redact .)
   ```

   Review every finding. Revoke anything real (see below). Put each false positive in `.gitleaksignore` as `file:rule:line`, then rerun until it exits 0.
4. Optionally add the pre-commit hook:

   ```yaml
   - repo: https://github.com/gitleaks/gitleaks
     rev: v8.30.1
     hooks:
       - id: gitleaks
         # gitleaks 8.30.1 reads no changes from git output it colors (color.ui or color.diff set to
         # always), and then passes. Turn git color off for its run.
         entry: env GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=color.ui GIT_CONFIG_VALUE_0=never GIT_CONFIG_KEY_1=color.diff GIT_CONFIG_VALUE_1=never gitleaks git --pre-commit --redact --staged --verbose
   ```

   It scans staged changes. Keep the `entry:` line until a gitleaks release includes gitleaks/gitleaks#2284; without it, a contributor whose git config forces color gets no scan. Its first run on a machine builds gitleaks, which takes about a minute. If CI runs `pre-commit run --all-files`, set `SKIP=gitleaks` there: nothing is staged in CI, so the hook would only spend time.

## Waiving a finding

- A deliberate fake value in a test: add `gitleaks:allow` in a comment on that line.
- A file that cannot take comments: add `file:rule:line` to `.gitleaksignore`. Do not use the commit-qualified fingerprint the scan prints, because a squash merge changes the commit and the entry would stop matching. The same entry also covers the line when it shows up in a merge commit's conflict resolution, where gitleaks reports the path as `b/<path>`.

An entry in `.gitleaksignore` also suppresses any later finding of the same rule on the same line of that file. Keep the list short and review additions; the check lists them on every pull request.

## When a real secret is caught

1. Revoke or rotate the credential first. Once pushed, the value is on GitHub, and a pull request ref stays readable after the branch is deleted.
2. Remove the value from the branch.
3. Tell the repository owner. For a public repository, ask GitHub support to purge the pull request ref.

## Upgrading the rules or gitleaks

1. Edit `gitleaks.toml`, the scripts, or the version pin (`GITLEAKS_VERSION` and `GITLEAKS_SHA256` in `.github/workflows/gitleaks.yml`, the one source for it). Run `python3 scripts/sync_workflow.py`, which writes the rules hash and the two scripts into the reusable workflow and copies the version pin into `ci.yml` and this README. CI fails while any of them is out of date.
2. After the change merges, open one PR per repository. Each PR bumps the pinned sha in `.github/workflows/gitleaks.yml` and copies the new `gitleaks.toml` to `.gitleaks.toml`. A pin bump without the copy fails the check.
3. Rerun the full-tree scan from step 3 of the adoption steps in each repository, and refresh stale `.gitleaksignore` entries.

## Making the check required, and rolling it back

A failing check blocks a merge only once a repository admin adds it, under its exact name, as a required status check in the branch ruleset. Until then it reports.

To roll back, remove the required check from the ruleset first, then delete the workflow. A required check that never reports blocks every pull request.

## Local test

```sh
python3 -I canary_test.py gitleaks.toml
python3 -I canary_test.py gitleaks.toml --tree NAME=DIR[:IGNOREFILE]   # also scan a checkout's tree
python3 -I test_list_waivers.py
python3 -I scripts/sync_workflow.py --check
```

The canary generates every value at run time and prints rule ids and file names only.
