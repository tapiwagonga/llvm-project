#===-- patch_coverage.awk ----------------------------------------------------===#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
#===------------------------------------------------------------------------===#
# Parses git diff headers and llvm-cov text output to calculate strict patch coverage
NR==FNR {
  # First file: git diff --unified=0
  if (match($0, /^\+\+\+ b\/(.*)/, arr)) {
    current_file = arr[1]
  } else if (current_file != "" && match($0, /^@@ -[0-9]+(,[0-9]+)? \+([0-9]+)(,([0-9]+))? @@/, arr)) {
    start = arr[2]
    len = (arr[4] == "" ? 1 : arr[4])
    for (i = 0; i < len; i++) {
      changed[current_file, start+i] = 1
    }
  }
  next
}

{
  # Second file: llvm-cov show text output
  if (match($0, /^([^ ]+):$/, arr)) {
    path = arr[1]
    current_file = ""
    # Match the absolute path to our relative git paths
    for (key in changed) {
      split(key, parts, SUBSEP)
      rel_path = parts[1]
      if (substr(path, length(path) - length(rel_path) + 1) == rel_path) {
        current_file = rel_path
        break
      }
    }
  } else if (current_file != "" && match($0, /^ *([0-9]+)\| *([^\| ]*)? *\|/, arr)) {
    line = arr[1]
    count = arr[2]
    # Check if this exact line was added/modified
    if (changed[current_file, line] == 1) {
      if (count == "0") {
        missed++
        missed_details = missed_details sprintf("- `%s` (Line %d)\n", current_file, line)
      } else if (count != "") {
        covered++
      }
    }
  } else if (current_file != "" && match($0, /Branch \(([0-9]+):[0-9]+\): \[True: ([^, ]+), False: ([^\] ]+)\]/, arr)) {
    branch_line = arr[1]
    true_count = arr[2]
    false_count = arr[3]
    if (changed[current_file, branch_line] == 1) {
      mcdc_total++
      if (true_count == "0" || false_count == "0") {
        mcdc_missed++
        mcdc_missed_details = mcdc_missed_details sprintf("- `%s` (Line %d): Incomplete Branch Logic\n", current_file, branch_line)
      } else {
        mcdc_covered++
      }
    }
  }
}

END {
  total = covered + missed
  print "### Patch Coverage Metrics (Changed Lines Only)"
  print "| Metric | Value |"
  print "|--------|-------|"
  if (total == 0) {
    print "| **Line Coverage** | `N/A (No executable lines changed)` |"
  } else {
    printf "| **Line Coverage** | `%.2f%%` (%d/%d lines) |\n", (covered/total)*100, covered, total
    
    if (mcdc_total > 0) {
      printf "| **MC/DC Logic** | `%.2f%%` (%d/%d conditions) |\n", (mcdc_covered/mcdc_total)*100, mcdc_covered, mcdc_total
    }
    
    if (missed > 0 || mcdc_missed > 0) {
      print "\n#### Untested Code:"
      print "The following lines or branches were introduced in this patch but were not fully executed by the test suite. Please write tests to cover them:"
      if (missed > 0) print missed_details
      if (mcdc_missed > 0) print mcdc_missed_details
    }
  }
}
