#!/usr/bin/env python3
"""Prints release downloads per period from the snapshots in a JSONL file.

Each snapshot holds the running download count of every release asset. The
report subtracts consecutive snapshots: what an asset gained between two
snapshots is counted in the period of the later one. The first snapshot has
no earlier one, so its counts are listed as "before <date>".

Columns:
  installer  downloads of SHA256SUMS; a run of install.sh or install.ps1
             downloads it about once (a retry downloads it again, and a
             manual download that checks the sums downloads it too)
  manual     downloads of a rancher binary beyond those of the credential
             helper for the same platform; the installers download both, a
             manual download usually takes only the CLI. A period with more
             helper than CLI downloads carries the difference to the next
             period of that tag and platform, so the sum over all periods is
             the CLI downloads minus the helper downloads; an installer run
             that a snapshot splits counts as manual in one period and is
             taken back in a later one.
  platforms  downloads of each rancher binary, by platform

An exclusion file lists downloads to subtract, such as test runs, one per
line: "TIME TAG ASSET COUNT"; "#" starts a comment. TIME is in UTC, either
YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DD (the end of that day). A line is
subtracted from the first snapshot taken after TIME; a TIME before the first
snapshot is subtracted from the "before" row.

Usage: report.py [--by day|week|month] [--exclude FILE] [FILE]
"""

import argparse
import bisect
import datetime
import json
import re
import sys
from collections import defaultdict

SUMS = "SHA256SUMS"
CLI_ASSET = re.compile(r"^rancher-((?:linux|darwin|windows)-[a-z0-9]+)(?:\.exe)?$")
HELPER_ASSET = re.compile(r"^rancher-credential-vault-((?:linux|darwin|windows)-[a-z0-9]+)(?:\.exe)?$")


def parse_time(text):
    """Parses YYYY-MM-DDTHH:MM:SSZ, or YYYY-MM-DD as the last second of that day."""
    if len(text) == 10:
        day = datetime.date.fromisoformat(text)
        return datetime.datetime.combine(day, datetime.time(23, 59, 59), datetime.UTC)
    if not text.endswith("Z"):
        raise ValueError(f"time {text!r} is not in UTC (no trailing Z)")
    return datetime.datetime.fromisoformat(text[:-1]).replace(tzinfo=datetime.UTC)


def load_snapshots(path):
    snapshots = []
    with open(path, encoding="utf-8") as f:
        for number, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                at = parse_time(record["at"])
                releases = [(r["tag"], dict(r["assets"])) for r in record["releases"]]
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                raise SystemExit(f"{path}:{number}: not a snapshot record: {e!r}") from None
            snapshots.append((at, releases))
    snapshots.sort(key=lambda s: s[0])
    return snapshots


def load_exclusions(path):
    exclusions = []
    with open(path, encoding="utf-8") as f:
        for number, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) != 4:
                raise SystemExit(f"{path}:{number}: want 'TIME TAG ASSET COUNT', got {line!r}")
            time, tag, asset, count = fields
            try:
                exclusions.append((parse_time(time), tag, asset, int(count)))
            except ValueError as e:
                raise SystemExit(f"{path}:{number}: {e}") from None
    return exclusions


def period_of(day, by):
    if by == "day":
        return day.isoformat()
    if by == "week":
        return (day - datetime.timedelta(days=day.weekday())).isoformat()
    return day.strftime("%Y-%m")


def gains(snapshots, by):
    """Returns ({(period, tag): {asset: gain}}, [(snapshot time, period)], warnings)."""
    totals = defaultdict(lambda: defaultdict(int))
    periods = []
    last = {}
    warnings = []
    for index, (at, releases) in enumerate(snapshots):
        period = "before" if index == 0 else period_of(at.date(), by)
        periods.append((at, period))
        for tag, assets in releases:
            for asset, count in assets.items():
                previous = last.get((tag, asset), 0)
                gain = count - previous
                if gain < 0:
                    # The asset was replaced and its count started again.
                    warnings.append(
                        f"{at:%Y-%m-%dT%H:%M:%SZ}: {tag} {asset} fell from {previous} to {count}; counted {count}"
                    )
                    gain = count
                last[(tag, asset)] = count
                if gain:
                    totals[(period, tag)][asset] += gain
    return totals, periods, warnings


def subtract(totals, exclusions, periods, known):
    """Subtracts each exclusion from the first snapshot taken after its time."""
    warnings = []
    times = [at for at, _ in periods]
    for time, tag, asset, count in exclusions:
        where = f"exclusion {time:%Y-%m-%dT%H:%M:%SZ} {tag} {asset}"
        if (tag, asset) not in known:
            warnings.append(f"{where}: no snapshot has this release asset; not subtracted")
            continue
        index = bisect.bisect_right(times, time)
        if index == len(times):
            warnings.append(f"{where}: no snapshot taken after it yet; not subtracted")
            continue
        totals[(periods[index][1], tag)][asset] -= count
    return warnings


def split(assets):
    """Returns (SHA256SUMS gain, {platform: CLI gain}, {platform: helper gain})."""
    cli = defaultdict(int)
    helper = defaultdict(int)
    for asset, gain in assets.items():
        if m := HELPER_ASSET.match(asset):
            helper[m.group(1)] += gain
        elif m := CLI_ASSET.match(asset):
            cli[m.group(1)] += gain
    return assets.get(SUMS, 0), cli, helper


def rows(totals, first):
    """Yields (period label, tag, installer, manual, platforms) and collects warnings."""

    def order(key):
        period, tag = key
        return ("" if period == "before" else period, tag)

    carry = defaultdict(int)
    table = []
    warnings = []
    for period, tag in sorted(totals, key=order):
        installer, cli, helper = split(totals[(period, tag)])
        manual = 0
        for p in sorted(set(cli) | set(helper)):
            difference = cli.get(p, 0) - helper.get(p, 0) + carry[(tag, p)]
            manual += max(0, difference)
            carry[(tag, p)] = min(0, difference)
        label = f"before {first:%Y-%m-%d}" if period == "before" else period
        if installer < 0 or any(n < 0 for n in cli.values()):
            warnings.append(f"{label} {tag}: negative count; an exclusion subtracts more than was downloaded")
        if not installer and not manual and not any(cli.values()):
            continue
        platforms = ", ".join(f"{p} {n}" for p, n in sorted(cli.items()) if n)
        table.append((label, tag, installer, manual, platforms))
    return table, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Release downloads per period.")
    parser.add_argument("file", nargs="?", default="data/downloads.jsonl")
    parser.add_argument(
        "--by",
        choices=("day", "week", "month"),
        default="week",
        help="length of a period; a week starts on Monday (default week)",
    )
    parser.add_argument("--exclude", metavar="FILE", help="downloads to subtract")
    args = parser.parse_args(argv)

    snapshots = load_snapshots(args.file)
    if not snapshots:
        raise SystemExit(f"{args.file}: no snapshot")
    totals, periods, warnings = gains(snapshots, args.by)
    if args.exclude:
        known = {(tag, asset) for _, releases in snapshots for tag, assets in releases for asset in assets}
        warnings += subtract(totals, load_exclusions(args.exclude), periods, known)

    table, more = rows(totals, snapshots[0][0])
    warnings += more
    header = ("PERIOD", "TAG", "INSTALLER", "MANUAL", "PLATFORMS")
    widths = [max(len(str(r[i])) for r in [header, *table]) for i in range(4)]
    for r in [header, *table]:
        print(f"{r[0]:<{widths[0]}}  {r[1]:<{widths[1]}}  {r[2]:>{widths[2]}}  {r[3]:>{widths[3]}}  {r[4]}")
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
