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
  }
}

END {
  total = covered + missed
  print "### Patch Coverage Metrics (Changed Lines Only)"
  print "| Metric | Value |"
  print "|--------|-------|"
  if (total == 0) {
    print "| **Patch Coverage** | `N/A (No executable lines changed)` |"
  } else {
    printf "| **Patch Coverage** | `%.2f%%` (%d/%d lines) |\n", (covered/total)*100, covered, total
    if (missed > 0) {
      printf "| **Missed Lines** | `%d` |\n", missed
      print "\n#### Untested Lines:"
      print "The following lines were introduced in this patch but were not executed by the test suite. Please write tests to cover them:"
      print missed_details
    }
  }
}
