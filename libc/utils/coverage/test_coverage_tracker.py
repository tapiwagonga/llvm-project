#!/usr/bin/env python3
#
# ====- Unit tests for continuous coverage tracker -------------*- python -*--==#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# ==-------------------------------------------------------------------------==#

import json
import os
import shutil
import tempfile
import unittest

from coverage_tracker import (
    MAX_HISTORY_DAYS,
    add_daily_run,
    extract_coverage_metrics,
    format_delta,
    generate_dashboard_html,
    generate_issue_markdown,
    get_change,
    get_directory_changes,
    read_history,
    write_history,
)


class TestCoverageTracker(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.history_file = os.path.join(self.test_dir, "history.json")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_read_and_write_history(self):
        self.assertEqual(read_history(self.history_file), [])

        sample = [{"date": "2026-08-24", "commit": "abc12345", "global": {"line_pct": 95.0}}]
        write_history(self.history_file, sample)
        loaded = read_history(self.history_file)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["commit"], "abc12345")

    def test_history_cap_at_365_days(self):
        large_history = [
            {"date": f"2025-01-{i:02d}", "commit": f"commit_{i}", "global": {"line_pct": 90.0}}
            for i in range(1, 401)
        ]
        write_history(self.history_file, large_history, max_days=365)
        loaded = read_history(self.history_file)
        self.assertEqual(len(loaded), 365)
        self.assertEqual(loaded[-1]["commit"], "commit_400")

    def test_add_daily_run_same_day_deduplication(self):
        history = []
        metrics_1 = {
            "global": {"line_pct": 95.0, "lines_cov": 950, "lines_tot": 1000},
            "directories": {"string": {"line_pct": 98.0}},
        }
        history = add_daily_run(history, metrics_1, "commit_first")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["commit"], "commit_f")

        metrics_2 = {
            "global": {"line_pct": 96.5, "lines_cov": 965, "lines_tot": 1000},
            "directories": {"string": {"line_pct": 99.0}},
        }
        history = add_daily_run(history, metrics_2, "commit_second")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["commit"], "commit_s")
        self.assertEqual(history[0]["global"]["line_pct"], 96.5)

    def test_daily_and_weekly_deltas(self):
        history = [
            {"date": f"2026-08-{i:02d}", "global": {"line_pct": 90.0 + i, "mcdc_pct": 80.0 + i}}
            for i in range(1, 10)
        ]
        daily = get_change(history, days_ago=1)
        self.assertEqual(daily["line_change"], 1.0)
        self.assertEqual(daily["mcdc_change"], 1.0)

        weekly = get_change(history, days_ago=7)
        self.assertEqual(weekly["line_change"], 7.0)
        self.assertEqual(weekly["mcdc_change"], 7.0)

    def test_delta_formatting(self):
        self.assertEqual(format_delta(0.25), "+0.25%")
        self.assertEqual(format_delta(-0.15), "-0.15%")
        self.assertEqual(format_delta(0.0), "+0.00%")

    def test_extract_coverage_metrics(self):
        mock_export = {
            "data": [
                {
                    "files": [
                        {
                            "filename": "/workspace/libc/src/string/strlen.cpp",
                            "summary": {
                                "lines": {"count": 20, "covered": 19},
                                "functions": {"count": 1, "covered": 1},
                                "mcdc": {"count": 4, "covered": 4},
                            },
                            "mcdc_records": [[1, 2, 3, 4, 5, 6, 7, 8, 9, [True, True]]],
                        },
                        {
                            "filename": "/workspace/libc/src/math/sin.cpp",
                            "summary": {
                                "lines": {"count": 100, "covered": 90},
                                "functions": {"count": 2, "covered": 2},
                                "mcdc": {"count": 10, "covered": 8},
                            },
                            "mcdc_records": [],
                        },
                    ]
                }
            ]
        }
        metrics = extract_coverage_metrics(mock_export)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["global"]["lines_tot"], 120)
        self.assertEqual(metrics["global"]["lines_cov"], 109)
        self.assertEqual(metrics["global"]["line_pct"], 90.83)
        self.assertIn("string", metrics["directories"])
        self.assertIn("math", metrics["directories"])

    def test_generate_issue_markdown(self):
        history = [
            {
                "date": "2026-08-25",
                "commit": "5eadf025",
                "timestamp": "2026-08-25 02:00:00 UTC",
                "global": {
                    "lines_cov": 45000,
                    "lines_tot": 46000,
                    "line_pct": 97.83,
                    "func_cov": 1200,
                    "func_tot": 1220,
                    "func_pct": 98.36,
                    "mcdc_cov": 3000,
                    "mcdc_tot": 3200,
                    "mcdc_pct": 93.75,
                    "decisions_tot": 1400,
                    "decisions_full": 1300,
                    "decisions_pct": 92.86,
                },
                "directories": {
                    "string": {
                        "lines_cov": 2000,
                        "lines_tot": 2040,
                        "line_pct": 98.04,
                        "mcdc_cov": 100,
                        "mcdc_tot": 100,
                        "mcdc_pct": 100.0,
                    }
                },
            }
        ]
        md = generate_issue_markdown(history, "5eadf0251a4c")
        self.assertIn("LLVM-libc Continuous Code Coverage", md)
        self.assertIn("97.83%", md)
        self.assertIn("`string/`", md)

    def test_generate_dashboard_html(self):
        history = [
            {
                "date": "2026-08-25",
                "commit": "5eadf025",
                "timestamp": "2026-08-25 02:00:00 UTC",
                "global": {"line_pct": 97.83, "lines_cov": 45000, "lines_tot": 46000},
                "directories": {"string": {"line_pct": 98.04, "lines_cov": 2000, "lines_tot": 2040}},
            }
        ]
        html = generate_dashboard_html(history)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("LLVM-libc Code Coverage Dashboard", html)
        self.assertIn("97.83%", html)
        self.assertIn("<code>string/</code>", html)


if __name__ == "__main__":
    unittest.main()
