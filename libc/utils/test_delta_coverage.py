#!/usr/bin/env python3
#
# ===- Test suite for delta_coverage.py --------------------*- python -*--==#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# ==------------------------------------------------------------------------==#

import unittest
import json
import sys
import io
from unittest.mock import patch
from urllib.error import HTTPError

from delta_coverage import (
    CoverageHistoryEntry,
    CoverageHistoryModel,
    CommentRenderer,
    CoverageMapper,
    DiffParser,
    ReportRenderer,
    GitHubPRClient,
)


class TestDiffParserInMemory(unittest.TestCase):
    def test_parse_generic_git_diff(self):
        diff_text = """diff --git a/source_file b/source_file
index 1111111..2222222 100644
--- a/source_file
+++ b/source_file
@@ -10,3 +10,5 @@
 void example_func() {
+  int x = 1;
+  return x;
 }
"""
        files = DiffParser.parse_str(diff_text)

        self.assertIn("source_file", files)
        hunks = files["source_file"]
        self.assertEqual(len(hunks), 1)

        added_lines = [
            (l_num, text) for l_type, text, l_num in hunks[0].lines if l_type == "+"
        ]
        self.assertEqual(len(added_lines), 2)
        self.assertEqual(added_lines[0], (11, "  int x = 1;"))
        self.assertEqual(added_lines[1], (12, "  return x;"))

    def test_parse_deleted_and_new_files(self):
        diff_text = """--- /dev/null
+++ b/new_module
@@ -0,0 +1,2 @@
+  int x = 1;
+  return x;
--- a/old_module
+++ /dev/null
@@ -1,5 +0,0 @@
-  old_code;
"""
        files = DiffParser.parse_str(diff_text)

        self.assertIn("new_module", files)
        self.assertNotIn("old_module", files)
        self.assertNotIn("/dev/null", files)

    def test_parse_multi_hunk_file(self):
        diff_text = """--- a/multi_hunk_source
+++ b/multi_hunk_source
@@ -10,2 +10,4 @@
+  first_addition_line_10;
+  first_addition_line_11;
@@ -50,1 +52,3 @@
+  second_addition_line_52;
+  second_addition_line_53;
"""
        files = DiffParser.parse_str(diff_text)

        self.assertIn("multi_hunk_source", files)
        hunks = files["multi_hunk_source"]
        self.assertEqual(len(hunks), 2)
        self.assertEqual(hunks[0].lines[0][2], 10)
        self.assertEqual(hunks[0].lines[1][2], 11)
        self.assertEqual(hunks[1].lines[0][2], 52)
        self.assertEqual(hunks[1].lines[1][2], 53)


class TestCoverageMapperInMemory(unittest.TestCase):
    def test_map_coverage_segments(self):
        diff_text = """--- a/target_source
+++ b/target_source
@@ -15,0 +16,4 @@
+  if (ptr == nullptr)
+    return 0;
+  const char *p = ptr;
+  return 1;
"""
        cov_dict = {
            "data": [
                {
                    "files": [
                        {
                            "filename": "target_source",
                            "segments": [
                                [16, 3, 10, True, True, False],
                                [17, 5, 0, True, True, False],
                                [18, 3, 10, True, True, False],
                                [19, 3, 10, True, True, False],
                                [20, 0, 0, False, False, False],
                            ],
                        }
                    ]
                }
            ]
        }

        files = DiffParser.parse_str(diff_text)
        matrix = CoverageMapper.parse_dict(cov_dict, files)

        self.assertIn("target_source", matrix)
        cov_data = matrix["target_source"]

        self.assertIn(16, cov_data["covered"])
        self.assertIn(18, cov_data["covered"])
        self.assertIn(19, cov_data["covered"])
        self.assertIn(17, cov_data["missed"])

    def test_uncompiled_file_fallback(self):
        diff_text = """--- a/uncompiled_source
+++ b/uncompiled_source
@@ -1,0 +2,2 @@
+  uncompiled_line_1;
+  uncompiled_line_2;
"""
        cov_dict = {"data": [{"files": []}]}

        files = DiffParser.parse_str(diff_text)
        matrix = CoverageMapper.parse_dict(cov_dict, files)

        self.assertIn("uncompiled_source", matrix)
        self.assertEqual(len(matrix["uncompiled_source"]["covered"]), 0)
        self.assertEqual(len(matrix["uncompiled_source"]["missed"]), 0)


class TestReportRendererInMemory(unittest.TestCase):
    def test_render_end_to_end_report(self):
        diff_text = """--- a/module_a
+++ b/module_a
@@ -20,0 +21,2 @@
+  if (x == 0)
+    return;
--- a/module_b
+++ b/module_b
@@ -18,0 +19,2 @@
+  if (y == 0)
+    return;
"""
        cov_dict = {
            "data": [
                {
                    "files": [
                        {
                            "filename": "module_a",
                            "segments": [
                                [21, 3, 0, True, True, False],
                                [22, 5, 0, True, True, False],
                            ],
                        },
                        {
                            "filename": "module_b",
                            "segments": [
                                [19, 3, 15, True, True, False],
                                [20, 5, 15, True, True, False],
                            ],
                        },
                    ]
                }
            ]
        }

        files = DiffParser.parse_str(diff_text)
        matrix = CoverageMapper.parse_dict(cov_dict, files)

        captured_out = io.StringIO()
        captured_err = io.StringIO()
        sys.stdout = captured_out
        sys.stderr = captured_err
        try:
            ReportRenderer.render(
                files,
                matrix,
                "1111111111111111111111111111111111111111",
                "2222222222222222222222222222222222222222",
                "main",
                "feature-branch",
            )
            output = captured_out.getvalue()
            err_output = captured_err.getvalue()
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

        self.assertIn(
            "is 50.00%. The total number of lines is 4, with 2 unexecuted lines.",
            output,
        )
        self.assertIn("| `module_a` | 0.00% | 2 |", output)
        self.assertIn("| `module_b` | 100.00% | 0 |", output)

        self.assertIn(
            "::warning file=module_a,line=21::Coverage Missed: This delta line was not executed.",
            err_output,
        )
        self.assertIn(
            "::warning file=module_a,line=22::Coverage Missed: This delta line was not executed.",
            err_output,
        )

        self.assertIn(
            "https://github.com/llvm/llvm-project/commit/1111111111111111111111111111111111111111",
            output,
        )
        self.assertIn("main` (1111111)", output)
        self.assertIn("feature-branch` (2222222)", output)

    def test_zero_executable_lines_validation(self):
        diff_text = """--- a/comment_source
+++ b/comment_source
@@ -10,0 +11,2 @@
+  // Pure comment line
+  /* Block comment */
"""
        files = DiffParser.parse_str(diff_text)
        matrix = CoverageMapper.parse_dict({"data": []}, files)

        captured = io.StringIO()
        sys.stdout = captured
        try:
            with self.assertRaises(SystemExit) as cm:
                ReportRenderer.render(files, matrix, "base", "head", "main", "feature")
            self.assertEqual(cm.exception.code, 0)
            output = captured.getvalue()
            self.assertIn("**Coverage Validated**", output)
            self.assertIn("No executable C/C++ lines were added or modified.", output)
        finally:
            sys.stdout = sys.__stdout__


class TestCommentManagerAndHistoryInMemory(unittest.TestCase):
    def test_history_model_idempotency_and_truncation(self):
        body = 'Report\n<!-- cov_history: [{"sha":"1111111","line_pct":"80.00%","mcdc_pct":"75.00%","timestamp":"2026-07-28"}] -->'
        history = CoverageHistoryModel.extract(body)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].sha, "1111111")

        updated = CoverageHistoryEntry("1111111", "100.00%", "95.00%", "2026-07-30")
        history = CoverageHistoryModel.upsert_entry(history, updated)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].line_pct, "100.00%")

        for i in range(15):
            entry = CoverageHistoryEntry(f"sha_{i}", f"{80 + i}%", "80%", "2026-07-30")
            history = CoverageHistoryModel.upsert_entry(history, entry)
        self.assertEqual(len(history), 10)
        self.assertEqual(history[-1].sha, "sha_14")

    @patch("urllib.request.urlopen")
    def test_rest_api_client_error_handling(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            url="https://api.github.com",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=io.BytesIO(b"{}"),
        )
        client = GitHubPRClient("llvm/llvm-project", 123, "test_token")
        comment = client.find_bot_comment("### LLVM-libc Patch Coverage Report")
        self.assertIsNone(comment)


if __name__ == "__main__":
    unittest.main()
