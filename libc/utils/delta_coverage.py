#!/usr/bin/env python3
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

class ReportRenderer:
    @staticmethod
    def _is_executable(text):
        s = text.strip()
        if not s:
            return False
        if s.startswith('//') or s.startswith('/*') or s.startswith('*') or s.startswith('*/'):
            return False
        if s in ('{', '}', '};'):
            return False
        return True

    @staticmethod
    def render(diff_files, coverage_matrix, base_sha, head_sha, base_branch, head_branch):
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
            print("\n> [!NOTE]")
            print("> **Coverage Validated:** No executable C/C++ lines were modified.")
            sys.exit(0)

        line_pct = (total_covered / total_lines) * 100
        if total_missed == 0:
            print("\n> [!NOTE]")
            print(f"> **Coverage Validated:** Patch coverage is 100.00%.")
        else:
            print("\n> [!CAUTION]")
            print(f"> **Coverage Degradation:** Patch coverage is {line_pct:.2f}% ({total_missed} unexecuted lines).")
        
        print("")
        if base_sha and head_sha and base_branch and head_branch:
            print(f"**Context:** Comparing `{base_branch}` (`{base_sha}`) to `{head_branch}` (`{head_sha}`).")
        elif base_sha and head_sha:
            print(f"**Context:** Comparing base (`{base_sha}`) to head (`{head_sha}`).")

        print("\n### Modified Files Summary")
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

        if total_missed > 0:
            print("\n### Missing Coverage Details")
            print("> **Legend:** Red (`-`) indicates unexecuted lines. Green (`+`) indicates executed lines.")
            
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
                elif len(f_missed) == 0:
                    continue
                
                print(f"\n**`{fpath}`**")
                print("```diff")
                
                for hunk in hunks:
                    hunk_has_miss = any((l_num in f_missed and l_type == '+') for l_type, text, l_num in hunk.lines)
                    if not hunk_has_miss:
                        continue
                        
                    print(hunk.header)
                    for l_type, text, l_num in hunk.lines:
                        if l_type == '+':
                            if l_num in f_missed:
                                print(f"- {text}")
                                sys.stderr.write(f"::error file={fpath},line={l_num}::Coverage Missed: This delta line was not executed.\n")
                            elif l_num in f_covered:
                                print(f"+ {text}")
                            else:
                                print(f"  {text}")
                        elif l_type == ' ':
                            print(f"  {text}")
                print("```")

            sys.exit(1)

def main():
    if len(sys.argv) not in [3, 5, 7]:
        print("Usage: delta_coverage.py <git_diff_file> <llvm_cov_json_file> [base_sha] [head_sha] [base_branch] [head_branch]")
        sys.exit(1)

    diff_file = sys.argv[1]
    json_file = sys.argv[2]
    base_sha = sys.argv[3] if len(sys.argv) >= 5 else None
    head_sha = sys.argv[4] if len(sys.argv) >= 5 else None
    base_branch = sys.argv[5] if len(sys.argv) == 7 else None
    head_branch = sys.argv[6] if len(sys.argv) == 7 else None

    diff_files = DiffParser.parse(diff_file)
    coverage_matrix = CoverageMapper.parse(json_file, diff_files)
    ReportRenderer.render(diff_files, coverage_matrix, base_sha, head_sha, base_branch, head_branch)

if __name__ == '__main__':
    main()
