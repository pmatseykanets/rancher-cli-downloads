import os
import tempfile
import unittest

import report


def snapshot(at, releases):
    return (report.parse_time(at), list(releases.items()))


def assets(sums, cli, helper):
    return {
        "SHA256SUMS": sums,
        "rancher-linux-amd64": cli,
        "rancher-credential-vault-linux-amd64": helper,
        "rancher-schema.json": 5,
        "install.sh": 1,
    }


def exclusion(time, tag, asset, count):
    return (report.parse_time(time), tag, asset, count)


class ReportTest(unittest.TestCase):
    def table(self, snapshots, by="week", exclusions=()):
        totals, periods, warnings = report.gains(snapshots, by)
        known = {(tag, a) for _, releases in snapshots for tag, assets in releases for a in assets}
        warnings += report.subtract(totals, list(exclusions), periods, known)
        table, more = report.rows(totals, snapshots[0][0])
        return table, warnings + more

    def test_first_snapshot_is_listed_as_before_its_date(self):
        rows, _ = self.table([snapshot("2026-11-18T05:41:00Z", {"v1": assets(10, 8, 6)})])
        self.assertEqual(rows, [("before 2026-11-18", "v1", 10, 2, "linux-amd64 8")])

    def test_gains_between_snapshots_go_to_the_period_of_the_later_one(self):
        rows, _ = self.table(
            [
                snapshot("2026-11-18T05:41:00Z", {"v1": assets(10, 8, 6)}),
                snapshot("2026-11-19T05:41:00Z", {"v1": assets(13, 11, 9)}),
                snapshot("2026-11-25T05:41:00Z", {"v1": assets(14, 14, 10)}),
            ]
        )
        self.assertEqual(
            rows,
            [
                ("before 2026-11-18", "v1", 10, 2, "linux-amd64 8"),
                ("2026-11-16", "v1", 3, 0, "linux-amd64 3"),
                ("2026-11-23", "v1", 1, 2, "linux-amd64 3"),
            ],
        )

    def test_by_day_and_by_month(self):
        snapshots = [
            snapshot("2026-11-18T05:41:00Z", {"v1": assets(1, 1, 1)}),
            snapshot("2026-11-19T05:41:00Z", {"v1": assets(2, 2, 2)}),
            snapshot("2026-12-01T05:41:00Z", {"v1": assets(4, 4, 4)}),
        ]
        days, _ = self.table(snapshots, by="day")
        self.assertEqual([r[0] for r in days], ["before 2026-11-18", "2026-11-19", "2026-12-01"])
        months, _ = self.table(snapshots, by="month")
        self.assertEqual([r[0] for r in months], ["before 2026-11-18", "2026-11", "2026-12"])

    def test_a_new_release_counts_from_zero(self):
        rows, _ = self.table(
            [
                snapshot("2026-11-18T05:41:00Z", {"v1": assets(10, 8, 8)}),
                snapshot("2026-11-19T05:41:00Z", {"v1": assets(10, 8, 8), "v2": assets(3, 3, 3)}),
            ]
        )
        self.assertEqual(rows[-1], ("2026-11-16", "v2", 3, 0, "linux-amd64 3"))

    def test_a_release_missing_from_a_snapshot_keeps_its_last_count(self):
        rows, _ = self.table(
            [
                snapshot("2026-11-18T05:41:00Z", {"v1": assets(10, 8, 8)}),
                snapshot("2026-11-19T05:41:00Z", {}),
                snapshot("2026-11-20T05:41:00Z", {"v1": assets(12, 10, 10)}),
            ]
        )
        self.assertEqual(rows[-1], ("2026-11-16", "v1", 2, 0, "linux-amd64 2"))

    def test_a_count_that_falls_is_counted_as_new_and_warned(self):
        rows, warnings = self.table(
            [
                snapshot("2026-11-18T05:41:00Z", {"v1": assets(10, 8, 8)}),
                snapshot("2026-11-19T05:41:00Z", {"v1": assets(2, 8, 8)}),
            ]
        )
        self.assertEqual(rows[-1], ("2026-11-16", "v1", 2, 0, ""))
        self.assertEqual(len(warnings), 1)
        self.assertIn("SHA256SUMS fell from 10 to 2", warnings[0])

    def test_an_exclusion_goes_to_the_first_snapshot_after_its_time(self):
        snapshots = [
            snapshot("2026-11-18T05:41:00Z", {"v1": assets(10, 8, 8)}),
            snapshot("2026-11-19T05:41:00Z", {"v1": assets(13, 11, 11)}),
            snapshot("2026-11-20T05:41:00Z", {"v1": assets(15, 13, 13)}),
        ]
        rows, warnings = self.table(
            snapshots,
            by="day",
            exclusions=[
                exclusion("2026-11-18T05:00:00Z", "v1", "SHA256SUMS", 4),
                exclusion("2026-11-18T14:00:00Z", "v1", "SHA256SUMS", 1),
                exclusion("2026-11-18", "v1", "SHA256SUMS", 1),
                exclusion("2026-11-19T06:00:00Z", "v1", "SHA256SUMS", 2),
            ],
        )
        self.assertEqual(warnings, [])
        self.assertEqual(
            [r[:3] for r in rows],
            [
                ("before 2026-11-18", "v1", 6),
                ("2026-11-19", "v1", 1),
                ("2026-11-20", "v1", 0),
            ],
        )

    def test_an_exclusion_with_no_later_snapshot_or_unknown_asset_is_warned(self):
        rows, warnings = self.table(
            [snapshot("2026-11-18T05:41:00Z", {"v1": assets(10, 8, 8)})],
            exclusions=[
                exclusion("2026-11-19", "v1", "SHA256SUMS", 1),
                exclusion("2026-11-17", "v9", "SHA256SUMS", 1),
                exclusion("2026-11-17", "v1", "rancher-linux-amd65", 1),
            ],
        )
        self.assertEqual(rows[0][2], 10)
        self.assertEqual(len(warnings), 3)
        self.assertIn("no snapshot taken after it", warnings[0])
        self.assertIn("no snapshot has this release asset", warnings[1])
        self.assertIn("no snapshot has this release asset", warnings[2])

    def test_an_exclusion_larger_than_the_downloads_is_warned(self):
        _, warnings = self.table(
            [snapshot("2026-11-18T05:41:00Z", {"v1": assets(1, 1, 1)})],
            exclusions=[exclusion("2026-11-17", "v1", "SHA256SUMS", 3)],
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("negative count", warnings[0])

    def test_a_split_installer_run_is_taken_back_in_a_later_period(self):
        rows, _ = self.table(
            [
                snapshot("2026-11-18T05:41:00Z", {"v1": assets(10, 9, 8)}),
                snapshot("2026-11-19T05:41:00Z", {"v1": assets(11, 9, 9)}),
                snapshot("2026-11-20T05:41:00Z", {"v1": assets(11, 10, 9)}),
                snapshot("2026-11-21T05:41:00Z", {"v1": assets(11, 11, 9)}),
            ],
            by="day",
        )
        self.assertEqual(
            [(r[0], r[3]) for r in rows],
            [
                ("before 2026-11-18", 1),
                ("2026-11-19", 0),
                ("2026-11-20", 0),
                ("2026-11-21", 1),
            ],
        )

    def test_only_platform_binaries_count(self):
        installer, cli, helper = report.split(
            {
                "rancher-windows-amd64.exe": 5,
                "rancher-credential-vault-windows-amd64.exe": 3,
                "rancher-schema.json": 7,
                "rancher-linux-amd64.sbom.json": 7,
                "install.ps1": 7,
            }
        )
        self.assertEqual((installer, dict(cli), dict(helper)), (0, {"windows-amd64": 5}, {"windows-amd64": 3}))

    def test_load_exclusions_reads_comments_and_refuses_bad_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "exclude")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# test runs\n2026-11-19T10:00:00Z v1 SHA256SUMS 2  # test run\n2026-11-20 v1 SHA256SUMS 1\n\n")
            self.assertEqual(len(report.load_exclusions(path)), 2)
            for bad in ("2026-11-19 v1 SHA256SUMS\n", "2026-11-19T10:00:00 v1 SHA256SUMS 2\n"):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(bad)
                with self.assertRaises(SystemExit):
                    report.load_exclusions(path)

    def test_load_snapshots_refuses_a_record_without_its_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "downloads.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"at":"2026-11-18T05:41:00Z"}\n')
            with self.assertRaises(SystemExit):
                report.load_snapshots(path)

    def test_an_empty_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "downloads.jsonl")
            open(path, "w").close()
            with self.assertRaises(SystemExit):
                report.main([path])


if __name__ == "__main__":
    unittest.main()
