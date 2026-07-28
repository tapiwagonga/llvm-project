#!/usr/bin/env bash
#
# ===- E2E Validation Script for Delta Coverage ----------------------------==#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# ==------------------------------------------------------------------------==#
# This script simulates the GitHub Actions pipeline locally to guarantee the 
# functionality works end-to-end before committing.
# Run from the root of the llvm-project:
# ./libc/utils/verify_coverage_pipeline.sh
# ==------------------------------------------------------------------------==#

set -eo pipefail

echo "========================================================="
echo " LLVM-libc Local E2E Coverage Pipeline Validation"
echo "========================================================="

if [ ! -d "build-cov" ]; then
    echo "[!] Error: 'build-cov' directory not found."
    echo "Please configure the build first: cmake -S llvm -B build-cov -G Ninja -DLLVM_ENABLE_PROJECTS=libc -DLLVM_LIBC_ENABLE_COVERAGE=ON -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19"
    exit 1
fi

echo "[1/6] Running Python Unit Tests..."
if python3 libc/utils/test_delta_coverage.py; then
    echo "[+] Unit Tests Passed."
else
    echo "[-] Unit Tests Failed."
    exit 1
fi

echo "[2/6] Cleaning old profraw files..."
find build-cov -name "*.profraw" -delete || true

echo "[3/6] Running LLVM-libc test suite..."
# Find all libc tests and run them. We use -k 0 to continue on failure, just like CI.
ninja -C build-cov check-libc -k 0 || echo "[!] Some tests failed, but proceeding to coverage."

echo "[4/6] Merging profile data..."
find build-cov -name "*.profraw" > profraw.list
if [ ! -s profraw.list ]; then
    echo "[-] Error: No profraw files generated!"
    echo "This means the C++ code failed to compile, or the tests crashed fatally."
    exit 1
fi

PROFRAW_COUNT=$(wc -l < profraw.list)
echo "[+] Found $PROFRAW_COUNT profile files. Merging..."
llvm-profdata-19 merge -sparse -input-files=profraw.list -o merged.profdata || {
    echo "[-] Merge failed! Data may be corrupted."
    exit 1
}

echo "[5/6] Exporting JSON Coverage AST..."
# Find all test binaries to pass to llvm-cov
TEST_BINARIES=$(find build-cov/projects/libc/test -name "*.__unit__" -type f -executable)
COV_ARGS=()
for bin in $TEST_BINARIES; do
    if [ ${#COV_ARGS[@]} -eq 0 ]; then
        COV_ARGS+=("$bin")
    else
        COV_ARGS+=("-object" "$bin")
    fi
done

if [ ${#COV_ARGS[@]} -eq 0 ]; then
    echo "[-] No test binaries found in build-cov/projects/libc/test"
    exit 1
fi

llvm-cov-19 export "${COV_ARGS[@]}" -instr-profile=merged.profdata -format=text > local_coverage.json

echo "[6/6] Executing delta_coverage.py..."
# For local testing, we diff against HEAD
git diff HEAD > local.diff
if [ ! -s local.diff ]; then
    echo "[!] Warning: Git diff is empty. The coverage script will output 0 files."
fi

python3 libc/utils/delta_coverage.py local.diff local_coverage.json local_coverage.md HEAD HEAD main test-branch

echo "========================================================="
echo " E2E Validation Complete!"
echo " Check local_coverage.md for the resulting output."
echo "========================================================="
