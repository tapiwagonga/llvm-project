#!/usr/bin/env bash
#===-- run_coverage_pipeline.sh -------------------------------------------===#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
#===----------------------------------------------------------------------===#

set -uo pipefail

BUILD_DIR="${BUILD_DIR:-build-cov}"
echo "================================================================="
echo "Step 1: Executing Test Suite"
echo "================================================================="

# Temporarily disable 'Exit on Error' so we can capture test failures
# but still continue to run the coverage extraction.
set +e
ninja -C "${BUILD_DIR}" check-libc
TEST_EXIT_CODE=$?
set -e

echo ""
echo "================================================================="
echo "Step 2: Aggregating Profile Data"
echo "================================================================="
BUILD_DIR="${BUILD_DIR}" bash .ci/coverage_post_process.sh

echo ""
echo "================================================================="
echo "Step 3: Verifying Deterministic Line Coverage"
echo "================================================================="
GITHUB_EVENT_PATH="${GITHUB_EVENT_PATH:-push_event.json}" \
GITHUB_EVENT_NAME="${GITHUB_EVENT_NAME:-push}" \
python3 .ci/check_line_coverage.py --coverage-json "${BUILD_DIR}/coverage-results/coverage.json"
REVIEW_EXIT_CODE=$?

echo ""
echo "================================================================="
echo "Pipeline Final Status"
echo "================================================================="
if [ $TEST_EXIT_CODE -ne 0 ]; then
  echo "FATAL: Pipeline failed. C++ Unit Tests exited with code ${TEST_EXIT_CODE}."
  exit $TEST_EXIT_CODE
fi

if [ $REVIEW_EXIT_CODE -ne 0 ]; then
  echo "FATAL: Pipeline failed. Coverage regressions were detected."
  exit $REVIEW_EXIT_CODE
fi

echo "SUCCESS: All tests passed and no coverage regressions found."
exit 0
