"""Runs snapshot.sh with a stub gh that answers from fixture pages."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

# The stub stands in for `gh api --paginate`: it records its arguments and
# prints every fixture page through the --jq expression with the real jq, one
# page after the other, as gh does. The fixture file holds one JSON array per
# page; jq runs the expression on each array in turn.
STUB = """#!/bin/sh
printf '%s\\n' "$@" >"$STUB_ARGS"
if [ -n "${STUB_FAIL:-}" ]; then echo "stub: request failed" >&2; exit 1; fi
expr=""
while [ $# -gt 0 ]; do
  case "$1" in --jq) expr="$2"; shift ;; esac
  shift
done
jq -c "$expr" "$STUB_PAGES"
"""

DRAFT = {
    "tag_name": "v3",
    "draft": True,
    "prerelease": False,
    "published_at": None,
    "assets": [{"name": "SHA256SUMS", "download_count": 1}],
}
V2 = {
    "tag_name": "v2",
    "draft": False,
    "prerelease": True,
    "published_at": "2026-11-09T22:05:41Z",
    "assets": [
        {"name": "SHA256SUMS", "download_count": 27, "size": 1},
        {"name": "rancher-linux-amd64", "download_count": 20, "size": 2},
    ],
}
V1 = {
    "tag_name": "v1",
    "draft": False,
    "prerelease": False,
    "published_at": "2026-10-01T10:00:00Z",
    "assets": [],
}


# CI must run these tests; only a local run without jq may skip them.
@unittest.skipUnless(shutil.which("jq") or os.environ.get("CI"), "jq is not installed")
class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        bin_dir = os.path.join(self.dir, "bin")
        os.mkdir(bin_dir)
        stub = os.path.join(bin_dir, "gh")
        with open(stub, "w", encoding="utf-8") as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        self.pages = os.path.join(self.dir, "pages.json")
        self.args = os.path.join(self.dir, "args")
        self.out = os.path.join(self.dir, "data", "downloads.jsonl")
        self.env = dict(
            os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"], STUB_PAGES=self.pages, STUB_ARGS=self.args
        )
        self.env.pop("SOURCE_REPO", None)

    def run_snapshot(self, pages, **env):
        with open(self.pages, "w", encoding="utf-8") as f:
            for page in pages:
                json.dump(page, f)
                f.write("\n")
        return subprocess.run(
            [os.path.join(HERE, "snapshot.sh"), self.out],
            env=dict(self.env, **env),
            capture_output=True,
            text=True,
            check=False,
        )

    def records(self):
        with open(self.out, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_appends_one_record_of_the_published_releases_of_every_page(self):
        for _ in range(2):
            result = self.run_snapshot([[DRAFT, V2], [V1]])
            self.assertEqual(result.returncode, 0, result.stderr)
        records = self.records()
        self.assertEqual(len(records), 2)
        record = records[0]
        self.assertEqual(record["repo"], "rancher/rancher-cli")
        self.assertRegex(record["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(
            record["releases"],
            [
                {
                    "tag": "v2",
                    "prerelease": True,
                    "published": "2026-11-09T22:05:41Z",
                    "assets": {"SHA256SUMS": 27, "rancher-linux-amd64": 20},
                },
                {"tag": "v1", "prerelease": False, "published": "2026-10-01T10:00:00Z", "assets": {}},
            ],
        )

    def test_asks_for_the_releases_of_the_source_repo_by_page(self):
        result = self.run_snapshot([[V2]], SOURCE_REPO="example/project")
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(self.args, encoding="utf-8") as f:
            args = f.read().split("\n")
        self.assertEqual(args[:3], ["api", "--paginate", "repos/example/project/releases?per_page=100"])
        self.assertIn("--jq", args)
        self.assertEqual(self.records()[0]["repo"], "example/project")

    def test_writes_nothing_when_no_release_is_published(self):
        result = self.run_snapshot([[DRAFT]])
        self.assertEqual(result.returncode, 1)
        self.assertIn("no published release", result.stderr)
        self.assertFalse(os.path.exists(self.out))

    def test_writes_nothing_when_the_request_fails(self):
        result = self.run_snapshot([[V2]], STUB_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stub: request failed", result.stderr)
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
