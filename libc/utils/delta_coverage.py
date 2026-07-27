#!/usr/bin/env python3
import sys
import json
import re

def main():
    if len(sys.argv) != 3:
        print("Usage: delta_coverage.py <git_diff_file> <llvm_cov_json_file>")
        sys.exit(1)

    diff_file = sys.argv[1]
    json_file = sys.argv[2]

    # 1. Parse unified diff to extract modified lines
    changed = {}
    current_file = None
    with open(diff_file, 'r') as f:
        for line in f:
            if line.startswith('+++ b/'):
                current_file = line[6:].strip()
                changed[current_file] = set()
            elif current_file and line.startswith('@@ '):
                match = re.search(r'\+([0-9]+)(?:,([0-9]+))?', line)
                if match:
                    length_str = match.group(2)
                    length = int(length_str) if length_str is not None else 1
                    start = int(match.group(1))
                    for i in range(length):
                        changed[current_file].add(start + i)

    # 2. Parse llvm-cov JSON export
    with open(json_file, 'r') as f:
        cov_data = json.load(f)

    if not cov_data.get('data') or not cov_data['data'][0].get('files'):
        print("No C/C++ lines were modified or coverage data is missing.")
        sys.exit(0)

    covered_lines = 0
    missed_lines = 0
    mcdc_covered_count = 0
    mcdc_missed_count = 0

    missed_line_details = []
    mcdc_missed_details = []

    for file_obj in cov_data['data'][0]['files']:
        filename = file_obj.get('filename', '')
        
        # Match absolute JSON path against relative Git path
        rel_path = next((k for k in changed if filename.endswith(k)), None)
        if not rel_path:
            continue

        modified_lines = changed[rel_path]
        if not modified_lines:
            continue

        # Extract Line Coverage from Segments
        # Segment schema: [Line, Column, ExecutionCount, HasCount, IsRegionEntry, IsGapRegion]
        segments = file_obj.get('segments', [])
        line_counts = {}
        
        for i in range(len(segments)):
            seg = segments[i]
            line = seg[0]
            count = seg[2]
            has_count = seg[3]
            is_region_entry = seg[4]

            if not has_count:
                continue

            # Initialize line if not present
            if line not in line_counts:
                line_counts[line] = 0

            # The execution count of a line is the max of any region starting on it
            if is_region_entry:
                line_counts[line] = max(line_counts[line], count)
            elif count > 0:
                line_counts[line] = max(line_counts[line], count)

            # Propagate the execution state to intermediate lines AND the next line (since it partially covers it)
            if i + 1 < len(segments):
                next_line = segments[i + 1][0]
                for l in range(line + 1, next_line + 1):
                    if l not in line_counts:
                        line_counts[l] = count
                    else:
                        line_counts[l] = max(line_counts[l], count)

        # Evaluate Delta Line Coverage
        for l in modified_lines:
            # If the line exists in the coverage matrix and has a count > 0
            if l in line_counts:
                if line_counts[l] > 0:
                    covered_lines += 1
                else:
                    missed_lines += 1
                    missed_line_details.append(f"- `{rel_path}` (Line {l})")
            else:
                # Line was not executable (e.g., blank line, comment)
                pass

        # Extract MC/DC logic
        # mcdc_records schema: [LineStart, ColStart, LineEnd, ColEnd, ..., Conditions, TestVectors]
        for record in file_obj.get('mcdc_records', []):
            line_start = record[0]
            line_end = record[2]
            
            # Check if this MC/DC region overlaps with the git diff
            overlap = False
            for l in range(line_start, line_end + 1):
                if l in modified_lines:
                    overlap = True
                    break

            if overlap:
                # Find the boolean Conditions array dynamically (it's the only nested list in the record)
                conditions = next((item for item in record if isinstance(item, list)), None)
                if conditions:
                    for idx, is_covered in enumerate(conditions):
                        if is_covered:
                            mcdc_covered_count += 1
                        else:
                            mcdc_missed_count += 1
                            mcdc_missed_details.append(f"- `{rel_path}` (Line {line_start}): Condition {idx+1} Pair Missed")

    # 3. Output Markdown Report
    total_lines = covered_lines + missed_lines
    total_mcdc = mcdc_covered_count + mcdc_missed_count

    print("### LLVM-libc Delta Coverage Report")
    
    if total_lines == 0:
        print("No executable C/C++ lines were modified in this PR.")
        sys.exit(0)

    line_pct = (covered_lines / total_lines) * 100 if total_lines > 0 else 100.0
    print(f"**Line Coverage:** {line_pct:.2f}% ({covered_lines}/{total_lines})")
    
    if total_mcdc > 0:
        mcdc_pct = (mcdc_covered_count / total_mcdc) * 100
        print(f"**MC/DC Coverage:** {mcdc_pct:.2f}% ({mcdc_covered_count}/{total_mcdc})")

    if missed_lines > 0 or mcdc_missed_count > 0:
        print("\n#### Uncovered Lines (Delta Only)")
        for ml in missed_line_details:
            print(ml)
        for ml in mcdc_missed_details:
            print(ml)
        sys.exit(1)

if __name__ == '__main__':
    main()
