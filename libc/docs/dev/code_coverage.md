(code_coverage)=

# How to Run Code Coverage and MC/DC Locally

LLVM-libc provides native support for generating statement, branch, and Modified Condition / Decision Coverage (MC/DC) reports locally. Because LLVM-libc runs in a freestanding environment without linking against a host standard library, coverage profile counters and boolean bitmasks are captured directly through Linux kernel system calls.

---

## Prerequisites

* **Compiler:** Clang 18 or newer (Clang 21+ recommended for MC/DC).
* **LLVM Profiling Tools:** `llvm-profdata` and `llvm-cov` matching the Clang version.
* **Build System:** CMake 3.28+ and Ninja.

---

## CMake Configuration

Configure CMake as a standalone runtime build via `-S runtimes`.

### 1. Standard Statement & Branch Coverage

```bash
cmake -G Ninja -S runtimes -B build-cov \
  -DCMAKE_C_COMPILER=clang \
  -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_BUILD_TYPE=Debug \
  -DLLVM_ENABLE_RUNTIMES=libc \
  -DLLVM_LIBC_FULL_BUILD=ON \
  -DLLVM_LIBC_ENABLE_COVERAGE=ON \
  -DLIBC_TEST_UNIT_TEST_ONLY=ON \
  -DLIBC_TEST_SKIP_DEATH_TESTS=ON \
  -DLIBC_TEST_SKIP_SHARED_TESTS=ON
```

### 2. MC/DC Coverage (Modified Condition / Decision Coverage)

To enable MC/DC tracking in addition to statement and branch coverage, add `-DLIBC_ENABLE_MCDC=ON`:

```bash
cmake -G Ninja -S runtimes -B build-cov \
  -DCMAKE_C_COMPILER=clang \
  -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_BUILD_TYPE=Debug \
  -DLLVM_ENABLE_RUNTIMES=libc \
  -DLLVM_LIBC_FULL_BUILD=ON \
  -DLLVM_LIBC_ENABLE_COVERAGE=ON \
  -DLIBC_ENABLE_MCDC=ON \
  -DLIBC_TEST_UNIT_TEST_ONLY=ON \
  -DLIBC_TEST_SKIP_DEATH_TESTS=ON \
  -DLIBC_TEST_SKIP_SHARED_TESTS=ON
```

---

## Running Coverage Locally on a Single Function / File

To measure coverage on a specific function (e.g., `isalnum` or `memchr`):

### 1. Build the Targeted Unit Test

```bash
ninja -C build-cov libc.test.src.ctype.isalnum_test.__unit__
```

### 2. Execute the Test Binary with Profile Redirection

```bash
LLVM_PROFILE_FILE="build-cov/libc_%p.profraw" \
  ./build-cov/libc/test/src/ctype/libc.test.src.ctype.isalnum_test.__unit__.__build__
```

### 3. Merge the Raw Profile

```bash
llvm-profdata merge -sparse build-cov/libc_*.profraw -o build-cov/libc_test.profdata
```

### 4. View Coverage Reports in the Terminal

**For MC/DC Truth Tables & Branch Counts:**
```bash
llvm-cov show ./build-cov/libc/test/src/ctype/libc.test.src.ctype.isalnum_test.__unit__.__build__ \
  -instr-profile=build-cov/libc_test.profdata \
  --show-mcdc \
  --show-branches=count \
  libc/src/ctype/isalnum.cpp
```

**For Standard Statement & Branch Coverage:**
```bash
llvm-cov show ./build-cov/libc/test/src/ctype/libc.test.src.ctype.isalnum_test.__unit__.__build__ \
  -instr-profile=build-cov/libc_test.profdata \
  --show-branches=count \
  libc/src/ctype/isalnum.cpp
```

Example MC/DC output:

```
   18|    517|LLVM_LIBC_FUNCTION(int, isalnum, (int c)) {
   19|    517|  if (c < 0 || c > cpp::numeric_limits<unsigned char>::max())
  ------------------
  |  Branch (19:7):  [True: 256, False: 261]
  |  Branch (19:16): [True: 0,   False: 261]
  ------------------
  |---> MC/DC Decision Region (19:7) to (19:61)
  |
  |  Number of Conditions: 2
  |     Condition C1 --> (19:7)  [c < 0]
  |     Condition C2 --> (19:16) [c > max]
  |
  |  Executed MC/DC Test Vectors:
  |     C1, C2    Result
  |  1 { F,  F  = F      }
  |  2 { T,  -  = T      }
  |
  |  C1-Pair: covered: (1,2)
  |  C2-Pair: not covered
  |  MC/DC Coverage for Decision: 50.00%
  ------------------
   20|    256|    return 0;
   21|    261|  return static_cast<int>(internal::isalnum(static_cast<char>(c)));
   22|    517|}
```

### 5. Run the In-Tree Patch Coverage Analyzer

To generate a Markdown patch coverage summary against your current git diff:

```bash
# 1. Export coverage data to JSON
llvm-cov export ./build-cov/libc/test/src/ctype/libc.test.src.ctype.isalnum_test.__unit__.__build__ \
  -instr-profile=build-cov/libc_test.profdata > build-cov/coverage.json

# 2. Generate unified diff against base commit
git diff HEAD~1 HEAD > build-cov/patch.diff

# 3. Run the patch analyzer
python3 libc/utils/coverage/patch_report.py build-cov/patch.diff build-cov/coverage.json
```

---

## Running Full Codebase Coverage Locally

To build and measure coverage across all unit tests in the entire LLVM-libc codebase:

### 1. Clean Previous Profile Counters

```bash
rm -f build-cov/libc_cov_*.profraw build-cov/libc_full.profdata
```

### 2. Execute All Unit Tests Across the Codebase

The `-k 0` flag ensures Ninja executes all targets across all subsystems even if an isolated test fails:

```bash
export LLVM_PROFILE_FILE="build-cov/libc_cov_%p.profraw"
ninja -k 0 -C build-cov libc-unit-tests || true
```

### 3. Merge All Collected Raw Profiles

```bash
find build-cov -name "libc_cov_*.profraw" > build-cov/profraw_list.txt
llvm-profdata merge -sparse --input-files=build-cov/profraw_list.txt -o build-cov/libc_full.profdata
```

### 4. Collect Test Executables and Export Coverage JSON

```bash
# Gather all test binaries
EXECUTABLES=($(find build-cov -type f -executable -name "*__build__"))
OBJECTS=("${EXECUTABLES[@]:1}")
OBJECTS=("${OBJECTS[@]/#/-object=}")

# Export JSON data
llvm-cov export \
  -format=text \
  -instr-profile=build-cov/libc_full.profdata \
  "${EXECUTABLES[0]}" "${OBJECTS[@]}" \
  -ignore-filename-regex=".*(test|utils).*" > build-cov/coverage.json
```

### 5. Generate Interactive HTML Report

**With MC/DC Truth Tables:**
```bash
llvm-cov show \
  -format=html \
  -output-dir=coverage_html \
  -instr-profile=build-cov/libc_full.profdata \
  "${EXECUTABLES[0]}" "${OBJECTS[@]}" \
  --show-directory-coverage \
  --show-branches=count \
  --show-mcdc \
  --show-mcdc-summary \
  -ignore-filename-regex=".*(test|utils).*"
```

**For Standard Statement Coverage (without MC/DC):**
```bash
llvm-cov show \
  -format=html \
  -output-dir=coverage_html \
  -instr-profile=build-cov/libc_full.profdata \
  "${EXECUTABLES[0]}" "${OBJECTS[@]}" \
  --show-directory-coverage \
  --show-branches=count \
  -ignore-filename-regex=".*(test|utils).*"
```

### 6. Print the Full Codebase Coverage Summary

```bash
python3 libc/utils/coverage/full_report.py build-cov/coverage.json
```

### 7. View the HTML Dashboard in Your Browser

```bash
xdg-open coverage_html/index.html
```
