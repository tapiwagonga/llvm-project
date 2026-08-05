#!/usr/bin/env python3
#
# ====- Parsing utilities for diffs and coverage JSON ----------*- python -*--==#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# ==-------------------------------------------------------------------------==#

import json
import re
import sys
from typing import Dict, List, Optional, Set, Tuple


class DiffHunk:
    def __init__(self, header: str):
        self.header: str = header
        self.lines: List[Tuple[str, str, int]] = []  # (prefix, text, line_number)


class DiffParser:
    @staticmethod
    def parse(diff_path: str) -> Dict[str, List[DiffHunk]]:
        files: Dict[str, List[DiffHunk]] = {}
        current_file: Optional[str] = None
        current_hunk: Optional[DiffHunk] = None
        current_line_num: int = 0

        with open(diff_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")

                if line.startswith("+++ b/"):
                    current_file = line[6:]
                    files[current_file] = []
                    current_hunk = None
                    continue

                if line.startswith("+++ /dev/null"):
                    current_file = None
                    current_hunk = None
                    continue

                if current_file is None:
                    continue

                if line.startswith("@@"):
                    match = re.search(r"\+([0-9]+)", line)
                    if match:
                        current_line_num = int(match.group(1))
                        current_hunk = DiffHunk(line)
                        files[current_file].append(current_hunk)
                    continue

                if current_hunk is None:
                    continue

                if line.startswith("-"):
                    continue
                elif line.startswith("+"):
                    current_hunk.lines.append(("+", line[1:], current_line_num))
                    current_line_num += 1
                elif line.startswith(" "):
                    current_hunk.lines.append((" ", line[1:], current_line_num))
                    current_line_num += 1

        return files


class CoverageJSONParser:
    @staticmethod
    def load(json_path: str) -> dict:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            sys.stderr.write(f"Error: Failed to parse coverage JSON: {e}\n")
            sys.exit(1)

    @staticmethod
    def extract_patch_matrix(
        cov_data: dict, diff_files: Dict[str, List[DiffHunk]]
    ) -> Dict[str, Dict[str, Set[int]]]:
        coverage_matrix: Dict[str, Dict[str, Set[int]]] = {
            fpath: {"covered": set(), "missed": set()} for fpath in diff_files.keys()
        }

        if "data" not in cov_data or not cov_data["data"]:
            return coverage_matrix

        for item in cov_data["data"][0].get("files", []):
            fpath = item["filename"]
            rel_path = next(
                (rp for rp in diff_files.keys() if fpath.endswith(rp)), None
            )
            if not rel_path:
                continue

            segments = item.get("segments", [])
            for i in range(len(segments) - 1):
                current = segments[i]
                nxt = segments[i + 1]

                line_start = current[0]
                line_end = nxt[0]
                count = current[2]
                has_count = current[3]

                if has_count:
                    for line_num in range(line_start, line_end + 1):
                        if count > 0:
                            coverage_matrix[rel_path]["covered"].add(line_num)
                        else:
                            coverage_matrix[rel_path]["missed"].add(line_num)

        return coverage_matrix
