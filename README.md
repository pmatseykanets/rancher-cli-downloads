# rancher-cli-downloads

Daily download counts of the [rancher-cli](https://github.com/rancher/rancher-cli)
release assets.

GitHub keeps one running download count per release asset and no history.
Once a day, the `snapshot` workflow reads the counts of every published
release from the public GitHub API and adds one line to
[`data/downloads.jsonl`](data/downloads.jsonl). A line looks like this
(wrapped, and with most assets left out):

```json
{"at":"2026-11-18T05:41:12Z","repo":"rancher/rancher-cli","releases":[
  {"assets":{"SHA256SUMS":27,"rancher-credential-vault-linux-amd64":20,"rancher-linux-amd64":20},
   "prerelease":true,"published":"2026-11-09T22:05:41Z","tag":"v0.1.0-beta.1"}]}
```

## Report

    ./report.py                       # downloads per week
    ./report.py --by day              # or --by month
    ./report.py --exclude my-runs.txt # subtract downloads listed in a file

What an asset gained between two snapshots is counted in the period of the
later one. The counts held by the first snapshot are listed as
`before <date>`.

| Column | Meaning |
|---|---|
| `INSTALLER` | downloads of `SHA256SUMS`: a run of `install.sh` or `install.ps1` downloads it about once (a retry downloads it again), and so does a manual download that checks the sums |
| `MANUAL` | downloads of a `rancher` binary beyond those of the credential helper for the same platform: the installers download both, a manual download usually takes only the CLI |
| `PLATFORMS` | downloads of each `rancher` binary, by platform |

An installer run that a snapshot splits (the CLI downloaded before it, the
helper after it) counts as manual in one period and is taken back in a later
one, so `MANUAL` summed over all periods is the CLI downloads minus the
helper downloads.

The `install.sh` and `install.ps1` release assets have counts of their own,
which the report leaves out; the install command in the rancher-cli README
fetches the script from `raw.githubusercontent.com` instead, which has no
count.

An exclusion file lists downloads to leave out, such as test runs, one per
line: `TIME TAG ASSET COUNT`, with `#` for comments. `TIME` is in UTC, either
`YYYY-MM-DDTHH:MM:SSZ` or `YYYY-MM-DD` (the end of that day). A line is
subtracted from the first snapshot taken after `TIME`. The report warns about
a line whose release asset no snapshot has, a line with no snapshot after it
yet, and a count that goes negative.

## Limits

- A download is not an install: an update reruns the installer and downloads
  again, and so does a retry.
- The counts carry no user or machine, so they cannot tell how many people
  downloaded.
- Requests from crawlers and automation are counted too.
- GitHub may run a scheduled workflow late or skip a run; each line carries
  its own time, so a missed day only makes the next difference cover two
  days.

## Development

Needs make, Python 3.11 or later, [uv](https://docs.astral.sh/uv/), Go and
jq.

| Command | Does |
|---|---|
| `make validate` | lint and test, reporting both; the pre-commit hook and CI run this |
| `make lint` | ruff (check and format), shellcheck and shfmt on the shell files, actionlint and zizmor on the workflows |
| `make test` | the unit tests of `report.py` and of `snapshot.sh` (with a stub `gh`; skipped without jq, except in CI) |
| `make fmt` | rewrite Python and shell files to their formatted form |
| `make hooks` | make git run the hooks in `.githooks`, by setting this repo's `core.hooksPath` |
| `make help` | list the targets |

The linters run at the versions pinned in the `Makefile`, through `uvx` or
`go run`, so local runs and CI lint with the same versions. The `ci` workflow
runs `make validate` on every push to `main` and every pull request that
changes code, tooling or workflows. The pre-commit hook runs it only for a
commit that changes such a file, and checks the files as they are on disk,
staged or not. A `core.hooksPath` set in this repo hides one set in the
global git config, so `.githooks/commit-msg` runs the global `commit-msg`
hook, when there is one.
