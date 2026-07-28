#!/usr/bin/env python3
#
# ===- Parse llvm-cov output to GitHub Delta Coverage Markdown -*- python -*--==#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# ==------------------------------------------------------------------------==#
import sys
import json
import re

class DiffHunk:
    def __init__(self, header):
        self.header = header
        self.lines = [] # Tuples of (prefix_type, text, absolute_line_number)

class DiffParser:
    @staticmethod
    def parse(diff_path):
        files = {}
        current_file = None
        current_hunk = None
        current_line_num = 0

        with open(diff_path, 'r') as f:
            for line in f:
                line = line.rstrip('\n')
                
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
                    match = re.search(r'\+([0-9]+)', line)
                    if match:
                        current_line_num = int(match.group(1))
                        current_hunk = DiffHunk(line)
                        files[current_file].append(current_hunk)
                    continue

                if current_hunk is None:
                    continue

                if line.startswith('-'):
                    # Aggressively drop removed lines to prevent execution confusion
                    continue
                elif line.startswith('+'):
                    current_hunk.lines.append(('+', line[1:], current_line_num))
                    current_line_num += 1
                elif line.startswith(' '):
                    current_hunk.lines.append((' ', line[1:], current_line_num))
                    current_line_num += 1
                else:
                    pass

        return files

class CoverageMapper:
    @staticmethod
    def parse(json_path, diff_files):
        try:
            with open(json_path, 'r') as f:
                cov_data = json.load(f)
        except Exception as e:
            sys.stderr.write(f"::error::Failed to parse coverage JSON: {e}\n")
            sys.exit(1)

        coverage_matrix = {}
        for fpath in diff_files.keys():
            coverage_matrix[fpath] = {'covered': set(), 'missed': set()}

        if 'data' not in cov_data or not cov_data['data']:
            return coverage_matrix

        for item in cov_data['data'][0].get('files', []):
            fpath = item['filename']
            rel_path = next((rp for rp in diff_files.keys() if fpath.endswith(rp)), None)
            if not rel_path:
                continue
                
            segments = item.get('segments', [])
            for i in range(len(segments) - 1):
                current = segments[i]
                nxt = segments[i+1]
                
                line_start = current[0]
                line_end = nxt[0]
                count = current[2]
                has_count = current[3]
                
                if has_count:
                    for line_num in range(line_start, line_end + 1):
                        if count > 0:
                            coverage_matrix[rel_path]['covered'].add(line_num)
                        else:
                            coverage_matrix[rel_path]['missed'].add(line_num)
                            
        return coverage_matrix

import argparse
from typing import Dict, List, Set, Optional, Tuple

class ReportRenderer:
    @staticmethod
    def _is_executable(text: str) -> bool:
        s = text.strip()
        if not s:
            return False
        if s.startswith('//') or s.startswith('/*') or s.startswith('*') or s.startswith('*/'):
            return False
        if s in ('{', '}', '};'):
            return False
        return True

    @staticmethod
    def render(diff_files: Dict[str, List[DiffHunk]], coverage_matrix: Dict[str, Dict[str, Set[int]]], 
               base_sha: Optional[str], head_sha: Optional[str], 
               base_branch: Optional[str], head_branch: Optional[str]) -> None:
        total_covered = 0
        total_missed = 0
        
        for fpath, data in coverage_matrix.items():
            added_lines = set()
            for hunk in diff_files.get(fpath, []):
                for l_type, text, l_num in hunk.lines:
                    if l_type == '+':
                        if not ReportRenderer._is_executable(text):
                            continue
                        added_lines.add(l_num)
                        
            f_covered = added_lines.intersection(data['covered'])
            f_missed = added_lines.intersection(data['missed'])
            
            total_covered += len(f_covered)
            total_missed += len(f_missed)

        total_lines = total_covered + total_missed

        print("## LLVM-libc Delta Coverage Report")
        
        if total_lines == 0:
            print("\n**Coverage Validated**")
            print("No executable C/C++ lines were added or modified.")
            sys.exit(0)
            
        coverage_percent = (total_covered / total_lines) * 100
        
        if total_missed == 0:
            print("\n**Coverage Perfect**")
        else:
            print("\n**Coverage Degradation**")
            
        commit_str = f"`{head_sha}` " if head_sha else ""
        print(f"The code coverage on the recent commit {commit_str}is {coverage_percent:.2f}%. The total number of lines is {total_lines}, with {total_missed} unexecuted lines.")
            
        print("\n<details>")
        print("<summary><b>View Full Diff</b></summary>\n")
        print("<br>\n")
        
        if base_sha and head_sha and base_branch and head_branch:
            print(f"- **Base Branch:** `{base_branch}` ({base_sha})")
            print(f"- **Head Commit:** `{head_branch}` ({head_sha})\n")
            print("---\n<br>\n")
            
        print("### Modified Files Summary")
        print("| File Path | Patch Coverage | Missing Lines |")
        print("| :--- | :---: | :---: |")
        for fpath, hunks in diff_files.items():
            data = coverage_matrix[fpath]
            
            added_lines = set()
            for hunk in hunks:
                for l_type, text, l_num in hunk.lines:
                    if l_type == '+':
                        if not ReportRenderer._is_executable(text):
                            continue
                        added_lines.add(l_num)
            
            f_covered = added_lines.intersection(data['covered'])
            f_missed = added_lines.intersection(data['missed'])
            f_total = len(f_covered) + len(f_missed)
            
            if f_total == 0:
                if len(added_lines) > 0:
                    f_missed = added_lines
                    f_total = len(added_lines)
                else:
                    continue
                
            f_pct = (len(f_covered) / f_total) * 100
            print(f"| `{fpath}` | {f_pct:.2f}% | {len(f_missed)} |")

        print("\n### Delta Coverage (Source Map)")
        
        for fpath, hunks in diff_files.items():
            data = coverage_matrix[fpath]
            
            added_lines = set()
            for hunk in hunks:
                for l_type, text, l_num in hunk.lines:
                    if l_type == '+':
                        if not ReportRenderer._is_executable(text):
                            continue
                        added_lines.add(l_num)
            
            f_missed = added_lines.intersection(data['missed'])
            f_covered = added_lines.intersection(data['covered'])
            
            if len(f_missed) == 0 and len(f_covered) == 0:
                if len(added_lines) > 0:
                    f_missed = added_lines
                else:
                    continue
            
            print(f"\n**`{fpath}`**")
            print("```diff")
            
            for hunk in hunks:
                print(hunk.header)
                for l_type, text, l_num in hunk.lines:
                    if l_type == '+':
                        if l_num in f_missed:
                            print(f"- {text}")
                            sys.stderr.write(f"::warning file={fpath},line={l_num}::Coverage Missed: This delta line was not executed.\n")
                        elif l_num in f_covered:
                            print(f"+ {text}")
                        else:
                            print(f"  {text}")
                    elif l_type == ' ':
                        print(f"  {text}")
            print("```")

def main() -> None:
    parser = argparse.ArgumentParser(description="LLVM-libc Delta Coverage Analyzer")
    parser.add_argument("diff_file")
    parser.add_argument("json_file")
    parser.add_argument("base_sha", nargs='?')
    parser.add_argument("head_sha", nargs='?')
    parser.add_argument("base_branch", nargs='?')
    parser.add_argument("head_branch", nargs='?')
    
    args = parser.parse_args()

    diff_files = DiffParser.parse(args.diff_file)
    coverage_matrix = CoverageMapper.parse(args.json_file, diff_files)
    ReportRenderer.render(diff_files, coverage_matrix, args.base_sha, args.head_sha, args.base_branch, args.head_branch)

if __name__ == '__main__':
    main()
