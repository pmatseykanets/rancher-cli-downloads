#!/usr/bin/env bash
# Appends one snapshot of the download counts of every published release
# asset of SOURCE_REPO (default rancher/rancher-cli) to the JSONL file named
# by the first argument (default data/downloads.jsonl). Needs gh and jq; gh
# reads its token from GH_TOKEN.
set -euo pipefail

source_repo="${SOURCE_REPO:-rancher/rancher-cli}"
out="${1:-data/downloads.jsonl}"
at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

releases="$(gh api --paginate "repos/$source_repo/releases?per_page=100" \
  --jq '.[] | select(.draft | not) | {
    tag: .tag_name,
    prerelease,
    published: .published_at,
    assets: (.assets | map({key: .name, value: .download_count}) | from_entries)
  }')"

record="$(printf '%s\n' "$releases" |
  jq -s -c --arg at "$at" --arg repo "$source_repo" '{at: $at, repo: $repo, releases: .}')"

count="$(printf '%s' "$record" | jq '.releases | length')"
if [ "$count" -eq 0 ]; then
  echo "snapshot: no published release found in $source_repo; nothing written" >&2
  exit 1
fi

mkdir -p "$(dirname "$out")"
printf '%s\n' "$record" >>"$out"
echo "snapshot: $count releases of $source_repo at $at"
