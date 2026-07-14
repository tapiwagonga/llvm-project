#!/usr/bin/env bash
#===-- coverage_post_process.sh -------------------------------------------===#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
#===----------------------------------------------------------------------===#

set -euo pipefail

# Find profile data tools
BUILD_DIR="${BUILD_DIR:-build}"
PROFDATA=$(command -v ./${BUILD_DIR}/bin/llvm-profdata || command -v llvm-profdata-19 || command -v llvm-profdata)
COV=$(command -v ./${BUILD_DIR}/bin/llvm-cov || command -v llvm-cov-19 || command -v llvm-cov)

COVERAGE_BINARY_PATH="${COVERAGE_BINARY_PATH:-${BUILD_DIR}/projects/libc/libllvm-libc.a}"

mkdir -p ${BUILD_DIR}/coverage-results
shopt -s globstar nullglob
profraw_files=(${BUILD_DIR}/**/*.profraw)

if [ ${#profraw_files[@]} -eq 0 ]; then
  echo "WARNING: No .profraw files generated across build subdirectories! Skipping profile merge."
  exit 0
fi

# Merge the raw profiles
$PROFDATA merge -sparse "${profraw_files[@]}" -o ${BUILD_DIR}/coverage-results/merged.profdata

# Clean up raw profiles to conserve disk space
rm -f "${profraw_files[@]}"

if [ ! -f ${BUILD_DIR}/coverage-results/merged.profdata ]; then
  exit 0
fi

test_binaries=($(find ${BUILD_DIR}/libc/test -type f -executable -name "*.__build__" 2>/dev/null || true))

if [ ${#test_binaries[@]} -eq 0 ]; then
  test_binaries=(${COVERAGE_BINARY_PATH})
fi

primary_binary=${test_binaries[0]}
object_args=""
for ((i=1; i<${#test_binaries[@]}; i++)); do
  object_args+=" -object=${test_binaries[$i]}"
done

# Write textual summary to GitHub Actions UI
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  echo "### Coverage & MC/DC Summary" >> $GITHUB_STEP_SUMMARY
  echo '```text' >> $GITHUB_STEP_SUMMARY
  $COV report ${primary_binary} ${object_args} \
    -instr-profile=${BUILD_DIR}/coverage-results/merged.profdata \
    --show-mcdc >> $GITHUB_STEP_SUMMARY
  echo '```' >> $GITHUB_STEP_SUMMARY
fi

# Export JSON for the line coverage verification script
$COV export ${primary_binary} ${object_args} \
  -instr-profile=${BUILD_DIR}/coverage-results/merged.profdata \
  > ${BUILD_DIR}/coverage-results/coverage.json
