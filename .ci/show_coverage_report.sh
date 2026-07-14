#!/usr/bin/env bash
#===-- show_coverage_report.sh --------------------------------------------===#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
#===----------------------------------------------------------------------===#

set -euo pipefail

BUILD_DIR="${BUILD_DIR:-build-cov}"
COV=$(command -v ./${BUILD_DIR}/bin/llvm-cov || command -v llvm-cov-19 || command -v llvm-cov)

if [ ! -f "${BUILD_DIR}/coverage-results/merged.profdata" ]; then
  echo "Error: Profile data not found at ${BUILD_DIR}/coverage-results/merged.profdata"
  echo "Please run the coverage pipeline first."
  exit 1
fi

test_binaries=($(find "${BUILD_DIR}/libc/test" -type f -executable -name "*.__build__" 2>/dev/null || true))
if [ ${#test_binaries[@]} -eq 0 ]; then
  echo "Error: No test binaries found in ${BUILD_DIR}/libc/test"
  exit 1
fi

primary_binary=${test_binaries[0]}
object_args=""
for ((i=1; i<${#test_binaries[@]}; i++)); do
  object_args+=" -object=${test_binaries[$i]}"
done

# We support multiple modular view formats
FORMAT="${1:-text}"

if [ "$FORMAT" == "html" ]; then
  echo "[*] Generating HTML report across ${#test_binaries[@]} test binaries..."
  mkdir -p "${BUILD_DIR}/coverage-html"
  $COV show ${primary_binary} ${object_args} \
    -instr-profile="${BUILD_DIR}/coverage-results/merged.profdata" \
    -format=html \
    -output-dir="${BUILD_DIR}/coverage-html"
  echo "[*] HTML report generated at: ${BUILD_DIR}/coverage-html/index.html"

elif [ "$FORMAT" == "summary" ]; then
  echo "[*] Compiling Summary report..."
  # By ignoring all filenames, we force the table to only print the headers and the TOTAL row
  $COV report ${primary_binary} ${object_args} \
    -instr-profile="${BUILD_DIR}/coverage-results/merged.profdata" \
    --ignore-filename-regex=".*"

elif [ "$FORMAT" == "less" ]; then
  echo "[*] Opening full table in interactive pager. Use arrow keys to scroll, press 'q' to quit."
  $COV report ${primary_binary} ${object_args} \
    -instr-profile="${BUILD_DIR}/coverage-results/merged.profdata" | less -S

else
  # Textual Terminal Output
  echo "[*] Dumping full raw table to stdout..."
  $COV report ${primary_binary} ${object_args} \
    -instr-profile="${BUILD_DIR}/coverage-results/merged.profdata"
fi
