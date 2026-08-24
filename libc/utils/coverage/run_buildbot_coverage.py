#!/usr/bin/env python3
#===-- run_buildbot_coverage.py - LLVM-libc Buildbot Coverage Driver -------===#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
#===----------------------------------------------------------------------===#
"""
Automated Buildbot Coverage Driver for LLVM-libc on x86_64.

This script executes the complete coverage workflow:
1. Validates and discovers matching LLVM toolchain utilities.
2. Configures CMake with freestanding coverage flags.
3. Compiles instrumented unit test binaries via Ninja.
4. Executes tests in parallel with PID-isolated raw counter profiles.
5. Aggregates profiles into a sparse profdata binary and purges raw counters.
6. Exports JSON metrics and generates an interactive HTML dashboard.
7. Computes overall and subsystem-level metrics for Buildbot logs and summary JSON.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def log(msg: str) -> None:
    print(f"[coverage-bot] {msg}", flush=True)


def find_tool(base_name: str, preferred_version: Optional[str] = None) -> str:
    candidates = []
    if preferred_version:
        candidates.append(f"{base_name}-{preferred_version}")
    candidates.append(base_name)

    for cand in candidates:
        path = shutil.which(cand)
        if path:
            return path

    for ver in ["23", "22", "21", "20", "19"]:
        path = shutil.which(f"{base_name}-{ver}")
        if path:
            return path

    raise RuntimeError(f"Could not locate tool: {base_name}")


def get_compiler_version(compiler_path: str) -> Optional[str]:
    try:
        res = subprocess.run(
            [compiler_path, "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        match = re.search(r"clang version (\d+)", res.stdout)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def run_command(
    cmd: List[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None
) -> None:
    log(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def execute_test(binary_path: Path, env: Dict[str, str]) -> Tuple[str, bool]:
    try:
        res = subprocess.run(
            [str(binary_path)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return (binary_path.name, res.returncode == 0)
    except Exception:
        return (binary_path.name, False)


def parse_and_summarize(
    json_path: Path,
    summary_json_path: Path,
    html_dir: Path,
    commit_sha: str,
    target_arch: str,
    enable_mcdc: bool,
) -> int:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "data" not in data or not data["data"]:
        log("Error: coverage.json contains no valid profile data.")
        return 1

    subsystems: Dict[str, Dict[str, Any]] = {}
    total_lines_cov = 0
    total_lines_tot = 0
    total_func_cov = 0
    total_func_tot = 0
    total_mcdc_cov = 0
    total_mcdc_tot = 0
    untested_functions = []

    for file_obj in data["data"][0].get("files", []):
        fpath = file_obj.get("filename", "")
        if "src/" not in fpath or "/test/" in fpath or "/utils/" in fpath:
            continue

        idx = fpath.find("src/")
        if idx == -1:
            continue
        rel_path = fpath[idx:]

        summary = file_obj.get("summary", {})
        lines = summary.get("lines", {})
        funcs = summary.get("functions", {})
        mcdc = summary.get("mcdc", {})

        l_tot = lines.get("count", 0)
        l_cov = lines.get("covered", 0)
        f_tot = funcs.get("count", 0)
        f_cov = funcs.get("covered", 0)
        m_tot = mcdc.get("count", 0)
        m_cov = mcdc.get("covered", 0)

        if l_tot == 0:
            continue

        total_lines_cov += l_cov
        total_lines_tot += l_tot
        total_func_cov += f_cov
        total_func_tot += f_tot
        total_mcdc_cov += m_cov
        total_mcdc_tot += m_tot

        if f_tot > 0 and f_cov == 0:
            untested_functions.append(rel_path)

        parts = rel_path.split("/")
        subsys = parts[1] if len(parts) >= 2 else "core"

        if subsys not in subsystems:
            subsystems[subsys] = {
                "lines_cov": 0,
                "lines_tot": 0,
                "func_cov": 0,
                "func_tot": 0,
                "mcdc_cov": 0,
                "mcdc_tot": 0,
            }

        subsystems[subsys]["lines_cov"] += l_cov
        subsystems[subsys]["lines_tot"] += l_tot
        subsystems[subsys]["func_cov"] += f_cov
        subsystems[subsys]["func_tot"] += f_tot
        subsystems[subsys]["mcdc_cov"] += m_cov
        subsystems[subsys]["mcdc_tot"] += m_tot

    line_pct = (total_lines_cov / total_lines_tot * 100) if total_lines_tot > 0 else 0.0
    func_pct = (total_func_cov / total_func_tot * 100) if total_func_tot > 0 else 0.0
    mcdc_pct = (total_mcdc_cov / total_mcdc_tot * 100) if total_mcdc_tot > 0 else 0.0

    # Build structured summary payload
    summary_payload = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "commit": commit_sha,
        "target": target_arch,
        "metrics": {
            "lines_covered": total_lines_cov,
            "lines_total": total_lines_tot,
            "line_coverage_pct": round(line_pct, 2),
            "functions_covered": total_func_cov,
            "functions_total": total_func_tot,
            "function_coverage_pct": round(func_pct, 2),
        },
        "subsystems": {},
    }

    if enable_mcdc:
        summary_payload["metrics"]["mcdc_covered"] = total_mcdc_cov
        summary_payload["metrics"]["mcdc_total"] = total_mcdc_tot
        summary_payload["metrics"]["mcdc_coverage_pct"] = round(mcdc_pct, 2)

    for subsys, s_data in sorted(subsystems.items()):
        s_line_pct = (
            (s_data["lines_cov"] / s_data["lines_tot"] * 100)
            if s_data["lines_tot"] > 0
            else 0.0
        )
        summary_payload["subsystems"][subsys] = {
            "line_pct": round(s_line_pct, 2),
            "lines_covered": s_data["lines_cov"],
            "lines_total": s_data["lines_tot"],
        }

    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)

    # Print Buildbot stdout log
    print("\n" + "=" * 70)
    print("                LLVM-libc x86 Full Codebase Coverage")
    print("=" * 70)
    print(f"Commit: {commit_sha[:10]} | Target: {target_arch} | Mode: {'MC/DC' if enable_mcdc else 'Statement & Branch'}")
    print("-" * 70)
    print(f"OVERALL LINE COVERAGE:     {line_pct:6.2f}% ( {total_lines_cov:,} / {total_lines_tot:,} lines )")
    print(f"OVERALL FUNCTION COVERAGE: {func_pct:6.2f}% ( {total_func_cov:,} / {total_func_tot:,} functions )")
    if enable_mcdc:
        print(f"OVERALL MC/DC COVERAGE:    {mcdc_pct:6.2f}% ( {total_mcdc_cov:,} / {total_mcdc_tot:,} conditions )")
    print("-" * 70)
    print("SUBSYSTEM BREAKDOWN:")
    print(f"  {'-'*55}")
    print(f"  | {'Subsystem':<16} | {'Line Coverage':<15} | {'Lines':<14} |")
    print(f"  {'-'*55}")
    for subsys, s_data in sorted(subsystems.items()):
        s_pct = (
            (s_data["lines_cov"] / s_data["lines_tot"] * 100)
            if s_data["lines_tot"] > 0
            else 0.0
        )
        lines_str = f"{s_data['lines_cov']}/{s_data['lines_tot']}"
        print(f"  | {subsys:<16} | {s_pct:13.2f}% | {lines_str:<14} |")
    print(f"  {'-'*55}")

    if untested_functions:
        print(f"\nUNTESTED ENTRYPOINTS / FILES ({len(untested_functions)}):")
        for uf in untested_functions[:10]:
            print(f"  - {uf}")
        if len(untested_functions) > 10:
            print(f"  ... and {len(untested_functions) - 10} more.")

    print(f"\nHTML Dashboard: {html_dir}/index.html")
    print(f"Summary JSON:   {summary_json_path}")
    print("=" * 70 + "\n")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LLVM-libc Buildbot Coverage Driver")
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=Path("build-cov"),
        help="Path to CMake build directory",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("."),
        help="Path to llvm-project source root",
    )
    parser.add_argument(
        "--enable-mcdc",
        action="store_true",
        help="Enable Modified Condition / Decision Coverage (MC/DC)",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip CMake configuration and Ninja build",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip test execution and reuse existing profile files",
    )
    parser.add_argument(
        "--output-html",
        type=Path,
        default=None,
        help="Output directory for HTML dashboard",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("coverage.json"),
        help="Output path for raw JSON export",
    )
    parser.add_argument(
        "--output-summary-json",
        type=Path,
        default=Path("coverage_summary.json"),
        help="Output path for structured summary JSON",
    )
    parser.add_argument(
        "--c-compiler",
        type=str,
        default="clang",
        help="C compiler binary or path",
    )
    parser.add_argument(
        "--cxx-compiler",
        type=str,
        default="clang++",
        help="C++ compiler binary or path",
    )
    parser.add_argument(
        "--num-threads",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of concurrent threads for test execution",
    )

    args = parser.parse_args()

    build_dir = args.build_dir.resolve()
    source_dir = args.source_dir.resolve()
    html_dir = (
        args.output_html.resolve()
        if args.output_html
        else (build_dir / ("coverage_mcdc_html" if args.enable_mcdc else "coverage_html"))
    )

    # 1. Discover toolchain
    c_compiler = shutil.which(args.c_compiler) or args.c_compiler
    cxx_compiler = shutil.which(args.cxx_compiler) or args.cxx_compiler
    clang_ver = get_compiler_version(c_compiler)
    profdata_bin = find_tool("llvm-profdata", clang_ver)
    cov_bin = find_tool("llvm-cov", clang_ver)
    ninja_bin = find_tool("ninja")
    cmake_bin = find_tool("cmake")

    log(f"Using Compiler: {c_compiler} (Clang {clang_ver or 'unknown'})")
    log(f"Using Profdata: {profdata_bin}")
    log(f"Using Cov:      {cov_bin}")

    # Detect compiler cache
    launcher_flags = []
    if shutil.which("sccache"):
        launcher_flags = [
            "-DCMAKE_C_COMPILER_LAUNCHER=sccache",
            "-DCMAKE_CXX_COMPILER_LAUNCHER=sccache",
        ]
    elif shutil.which("ccache"):
        launcher_flags = [
            "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
            "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
        ]

    # 2. Configure & Build
    if not args.skip_build:
        cmake_cmd = [
            cmake_bin,
            "-G", "Ninja",
            "-S", str(source_dir / "runtimes"),
            "-B", str(build_dir),
            f"-DCMAKE_C_COMPILER={c_compiler}",
            f"-DCMAKE_CXX_COMPILER={cxx_compiler}",
            "-DCMAKE_BUILD_TYPE=Debug",
            "-DLLVM_ENABLE_RUNTIMES=libc",
            "-DLLVM_LIBC_FULL_BUILD=ON",
            "-DLLVM_LIBC_ENABLE_COVERAGE=ON",
            f"-DLIBC_ENABLE_MCDC={'ON' if args.enable_mcdc else 'OFF'}",
            "-DLIBC_TEST_UNIT_TEST_ONLY=ON",
            "-DLIBC_TEST_SKIP_DEATH_TESTS=ON",
        ] + launcher_flags
        run_command(cmake_cmd, cwd=source_dir)

        ninja_cmd = [ninja_bin, "-k", "0", "-C", str(build_dir), "libc-unit-tests"]
        try:
            run_command(ninja_cmd, cwd=source_dir)
        except subprocess.CalledProcessError:
            log("Warning: some unit tests failed to compile, continuing with available targets.")

    # 3. Clean and Run Unit Tests
    if not args.skip_tests:
        for p in build_dir.glob("**/libc_cov_*.profraw"):
            try:
                p.unlink()
            except OSError:
                pass
        profdata_file = build_dir / "libc_full.profdata"
        if profdata_file.exists():
            profdata_file.unlink()

        test_binaries = [
            p for p in (build_dir / "libc" / "test").rglob("*__build__") if os.access(p, os.X_OK) and p.is_file()
        ]
        log(f"Discovered {len(test_binaries)} unit test executables.")

        test_env = os.environ.copy()
        test_env["LLVM_PROFILE_FILE"] = str(build_dir / "libc_cov_%p.profraw")

        log(f"Executing {len(test_binaries)} tests in parallel ({args.num_threads} workers)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_threads) as executor:
            futures = [executor.submit(execute_test, b, test_env) for b in test_binaries]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        passed = sum(1 for _, ok in results if ok)
        log(f"Test Execution Completed: {passed}/{len(results)} binaries succeeded.")

    # 4. Merge Profiles
    profraw_files = list(build_dir.glob("**/libc_cov_*.profraw"))
    log(f"Found {len(profraw_files)} raw profile counters.")
    if not profraw_files:
        log("Error: No raw profile files were generated.")
        return 1

    list_file = build_dir / "profraw_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in profraw_files:
            f.write(f"{p}\n")

    merged_profdata = build_dir / "libc_full.profdata"
    merge_cmd = [
        profdata_bin,
        "merge",
        "-sparse",
        f"--input-files={list_file}",
        "-o",
        str(merged_profdata),
    ]
    run_command(merge_cmd, cwd=source_dir)
    list_file.unlink(missing_ok=True)

    # Clean raw profraw files to save disk space
    for p in profraw_files:
        try:
            p.unlink()
        except OSError:
            pass

    # 5. Export JSON and Generate HTML
    test_binaries = [
        p for p in (build_dir / "libc" / "test").rglob("*__build__") if os.access(p, os.X_OK) and p.is_file()
    ]
    if not test_binaries:
        log("Error: No test executables found for coverage export.")
        return 1

    first_bin = test_binaries[0]
    extra_objects = [f"-object={b}" for b in test_binaries[1:]]

    # JSON export
    export_cmd = [
        cov_bin,
        "export",
        "-format=text",
        f"-instr-profile={merged_profdata}",
        str(first_bin),
    ] + extra_objects

    log("Exporting coverage data to JSON...")
    with open(args.output_json, "w", encoding="utf-8") as f:
        subprocess.run(export_cmd, stdout=f, check=True)

    # HTML report
    html_cmd = [
        cov_bin,
        "show",
        "-format=html",
        f"-output-dir={html_dir}",
        f"-instr-profile={merged_profdata}",
        str(first_bin),
    ] + extra_objects + [
        "--show-directory-coverage",
        "--show-branches=count",
        f"--compilation-dir={source_dir}",
        f"--path-equivalence={source_dir},.",
        "-ignore-filename-regex=.*(test|utils).*",
    ]
    if args.enable_mcdc:
        html_cmd.extend(["--show-mcdc", "--show-mcdc-summary"])

    log("Generating HTML coverage dashboard...")
    run_command(html_cmd, cwd=source_dir)
    (html_dir / ".nojekyll").touch()

    # 6. Parse and print summary
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        commit_sha = res.stdout.strip()
    except Exception:
        commit_sha = "unknown"

    return parse_and_summarize(
        args.output_json,
        args.output_summary_json,
        html_dir,
        commit_sha,
        "x86_64-unknown-linux-gnu",
        args.enable_mcdc,
    )


if __name__ == "__main__":
    sys.exit(main())
