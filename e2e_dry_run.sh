#!/bin/bash
set -euo pipefail

echo "=== E2E DRY RUN: TARGET ISOLATION ==="
# Simulate git diff for unstaged changes + last commit
git diff HEAD~4 > dry_run.patch
CHANGED_FILES=$(git diff HEAD~4 --name-only)

echo "Changed Files Detected:"
echo "$CHANGED_FILES"

PROJECT="libc"
SRCDIR="libc/src"
FALLBACK="check-libc"
BUILD_DIR="build"

CORE_CHANGE=0
if echo "$CHANGED_FILES" | grep -qE "^(${PROJECT}/test/UnitTest/|${SRCDIR}/__support/|${PROJECT}/CMakeLists.txt)|\.h$"; then
  CORE_CHANGE=1
fi

NINJA_TARGETS=()
if [ $CORE_CHANGE -eq 1 ] || [ -z "$CHANGED_FILES" ]; then
  echo "Core framework or header modified. Executing fallback full suite."
  NINJA_TARGETS=("$FALLBACK")
else
  for file in $CHANGED_FILES; do
    if [[ "$file" =~ ^${SRCDIR}/([^/]+)/(.*/)?([^/]+)\.cpp$ ]]; then
      dir="${BASH_REMATCH[1]}"
      func="${BASH_REMATCH[3]}"
      
      ALL_MATCHES=$(ninja -C $BUILD_DIR -t targets | grep -oE "^${PROJECT}\.test\.src\.${dir}\.([a-zA-Z0-9_]+\.)?${func}_test\.__unit__" || true)
      FOUND_TARGET=$(echo "$ALL_MATCHES" | grep "\.smoke\." | head -n 1 | tr -d '\r\n ' || true)
      if [ -z "$FOUND_TARGET" ]; then
        FOUND_TARGET=$(echo "$ALL_MATCHES" | head -n 1 | tr -d '\r\n ' || true)
      fi
      
      if [ -n "$FOUND_TARGET" ]; then
        NINJA_TARGETS+=("$FOUND_TARGET")
      else
        NINJA_TARGETS+=("${PROJECT}.test.src.${dir}.${func}_test.__unit__")
      fi
    fi
  done
fi

if [ ${#NINJA_TARGETS[@]} -eq 0 ]; then
  echo "No executable C++ files modified in the standard target layout."
  echo "Would trigger graceful exit here."
  exit 0
fi

BUILD_DIR="build"
VALID_TARGETS=()
for target in "${NINJA_TARGETS[@]}"; do
  if ninja -C $BUILD_DIR -t targets | grep -F "${target}:" > /dev/null; then
    VALID_TARGETS+=("$target")
  else
    echo "::notice::Target $target does not exist. A unit test is missing."
  fi
done

if [ ${#VALID_TARGETS[@]} -eq 0 ]; then
  echo "No valid test targets found. Triggering graceful exit."
  exit 0
fi

echo "Selected Ninja Targets: ${VALID_TARGETS[*]}"
echo ""
echo "=== E2E DRY RUN: EXECUTION ==="
export LLVM_PROFILE_FILE="%p.profraw"
find $BUILD_DIR -name "*.profraw" -delete || true

ninja -C $BUILD_DIR -j 2 "${VALID_TARGETS[@]}" || echo "Some tests failed, proceeding to coverage."

echo "=== E2E DRY RUN: PROFILE MERGING ==="
find $BUILD_DIR -name "*.profraw" > profraw.list
if [ ! -s profraw.list ]; then
  echo "No profraw files generated."
  exit 1
fi

llvm-profdata merge -sparse -input-files=profraw.list -o merged.profdata || {
  echo "Fallback sequential merge..."
  touch merged.profdata
  for prof in $(cat profraw.list); do
    llvm-profdata merge -sparse "$prof" merged.profdata -o merged.profdata.tmp 2>/dev/null && mv merged.profdata.tmp merged.profdata
  done
}

echo "=== E2E DRY RUN: EXPORT & PYTHON RENDERING ==="
BINS=( $(find $BUILD_DIR/projects/libc/test -name "*.__build__") )
FIRST_BIN="${BINS[0]}"
OBJECT_ARGS=()
for i in "${!BINS[@]}"; do
  if [ $i -ne 0 ]; then
    OBJECT_ARGS+=("-object=${BINS[$i]}")
  fi
done

llvm-cov export "$FIRST_BIN" "${OBJECT_ARGS[@]}" -instr-profile=merged.profdata -format=text -ignore-filename-regex=".*test.*" > cov.json

BASE_SHA=$(git rev-parse HEAD~1)
HEAD_SHA="local_unstaged"

python3 libc/utils/delta_coverage.py dry_run.patch cov.json $BASE_SHA $HEAD_SHA HEAD local || true

echo "=== E2E DRY RUN COMPLETE ==="
