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
import tempfile
import os
import json
from delta_coverage import DiffParser, CoverageMapper, ReportRenderer

class TestDeltaCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_temp_file(self, filename, content):
        path = os.path.join(self.temp_dir.name, filename)
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_deleted_file_dev_null_handling(self):
        # A commit modifies file1.cpp but completely deletes file2.cpp
        diff_content = """--- a/file1.cpp
+++ b/file1.cpp
@@ -10,3 +10,3 @@
- old_code
+ new_code
--- a/file2.cpp
+++ /dev/null
@@ -1,5 +0,0 @@
- this_file_was_deleted
"""
        diff_path = self.write_temp_file("test.diff", diff_content)
        files = DiffParser.parse(diff_path)
        
        # Only file1.cpp should be parsed
        self.assertIn("file1.cpp", files)
        self.assertNotIn("file2.cpp", files)
        self.assertNotIn("/dev/null", files)
        
        # Ensure file1.cpp has exactly one hunk with one added line
        self.assertEqual(len(files["file1.cpp"]), 1)
        self.assertEqual(len(files["file1.cpp"][0].lines), 1)
        self.assertEqual(files["file1.cpp"][0].lines[0][1], " new_code")

    def test_new_file_creation(self):
        # A commit creates a brand new file
        diff_content = """--- /dev/null
+++ b/new_file.cpp
@@ -0,0 +1,2 @@
+ new_line_1
+ new_line_2
"""
        diff_path = self.write_temp_file("test.diff", diff_content)
        files = DiffParser.parse(diff_path)
        
        self.assertIn("new_file.cpp", files)
        self.assertEqual(len(files["new_file.cpp"][0].lines), 2)

    def test_coverage_mapping_100_percent(self):
        diff_content = """--- a/test.cpp
+++ b/test.cpp
@@ -1,3 +1,3 @@
+ line1
+ line2
"""
        # Mock llvm-cov export JSON
        json_content = json.dumps({
            "data": [{
                "files": [{
                    "filename": "test.cpp",
                    "segments": [
                        [1, 0, 10, True, True, False], # Line 1, Col 0, Count 10
                        [3, 0, 0, False, False, False] # End of coverage
                    ]
                }]
            }]
        })
        
        diff_path = self.write_temp_file("test.diff", diff_content)
        json_path = self.write_temp_file("test.json", json_content)
        
        files = DiffParser.parse(diff_path)
        matrix = CoverageMapper.parse(json_path, files)
        
        self.assertIn("test.cpp", matrix)
        self.assertIn(1, matrix["test.cpp"]["covered"])
        self.assertIn(2, matrix["test.cpp"]["covered"])

    def test_uncovered_file_graceful_ignore(self):
        diff_content = """--- a/missing.cpp
+++ b/missing.cpp
@@ -1,2 +1,2 @@
+ unexecuted_code
"""
        json_content = json.dumps({
            "data": [{"files": []}] # No files in coverage data
        })
        
        diff_path = self.write_temp_file("test.diff", diff_content)
        json_path = self.write_temp_file("test.json", json_content)
        
        files = DiffParser.parse(diff_path)
        matrix = CoverageMapper.parse(json_path, files)
        
        # If the file is not in the JSON AST (not compiled/executed), 
        # it should safely map to empty sets without throwing a KeyError.
        self.assertIn("missing.cpp", matrix)
        self.assertEqual(len(matrix["missing.cpp"]["covered"]), 0)
        self.assertEqual(len(matrix["missing.cpp"]["missed"]), 0)

    def test_report_renderer_is_executable(self):
        # Lines that should NOT be counted as executable coverage targets
        self.assertFalse(ReportRenderer._is_executable("    "))
        self.assertFalse(ReportRenderer._is_executable("}"))
        self.assertFalse(ReportRenderer._is_executable("{"))
        self.assertFalse(ReportRenderer._is_executable("};"))
        self.assertFalse(ReportRenderer._is_executable("// This is a comment"))
        self.assertFalse(ReportRenderer._is_executable("/* Start of comment"))
        self.assertFalse(ReportRenderer._is_executable("* middle of block comment"))
        self.assertFalse(ReportRenderer._is_executable("*/ end of block comment"))
        
        # Lines that SHOULD be counted
        self.assertTrue(ReportRenderer._is_executable("int x = 5;"))
        self.assertTrue(ReportRenderer._is_executable("if (x == 5) {"))
        self.assertTrue(ReportRenderer._is_executable("return 0;"))
        self.assertTrue(ReportRenderer._is_executable("} else {"))

    def test_report_renderer_math(self):
        # A file has lines 1-10 added.
        # Lines 1-5 are covered.
        # Lines 6-8 are missed.
        # Lines 9-10 are brackets/comments (not executable).
        
        # Mock Diff Files
        from delta_coverage import DiffHunk
        hunk = DiffHunk("@@ -0,0 +1,10 @@")
        for i in range(1, 6):
            hunk.lines.append(('+', f'code_line_{i};', i))
        for i in range(6, 9):
            hunk.lines.append(('+', f'missed_line_{i};', i))
        hunk.lines.append(('+', '}', 9))
        hunk.lines.append(('+', '// comment', 10))
        
        diff_files = {"test.cpp": [hunk]}
        
        # Mock Coverage Matrix
        coverage_matrix = {
            "test.cpp": {
                "covered": set([1, 2, 3, 4, 5]),
                "missed": set([6, 7, 8])
            }
        }
        
        # Test ReportRenderer (we capture output or just test the math logic)
        # We can't directly intercept stdout easily without contextlib, but we can test the internal logic.
        # Actually, let's just make sure it doesn't crash when rendering.
        try:
            import io, sys
            captured_output = io.StringIO()
            sys.stdout = captured_output
            
            ReportRenderer.render(diff_files, coverage_matrix, "base", "head", "main", "feature")
            
            sys.stdout = sys.__stdout__
            output = captured_output.getvalue()
            
            # 5 covered, 3 missed, 2 non-executable. Total executable = 8.
            # Coverage = 5 / 8 = 62.50%
            self.assertIn("The code coverage on the recent commit `head` is 62.50%. The total number of lines is 8, with 3 unexecuted lines.", output)
            self.assertIn("- **Base Branch:** `main` (base)", output)
            self.assertIn("- **Head Commit:** `feature` (head)", output)
            self.assertIn("test.cpp", output)
        finally:
            sys.stdout = sys.__stdout__

if __name__ == '__main__':
    unittest.main()
