#!/usr/bin/env python3
#===-- coverage_report.py ------------------------------------------------===#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
#===----------------------------------------------------------------------===#
#
# Aggregates LLVM libc code coverage profiles and generates reports.
#
#===----------------------------------------------------------------------===#

import argparse
import glob
import os
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description="Generate libc coverage report")
    parser.add_argument("--build-dir", required=True, help="Path to the build directory")
    parser.add_argument("--llvm-tools-dir", default="", help="Path to LLVM tools")
    args = parser.parse_args()

    build_dir = args.build_dir
    tools_dir = args.llvm_tools_dir
    profiles_dir = os.path.join(build_dir, "profiles")
    
    # 1. Find all profraw files
    profraw_files = glob.glob(os.path.join(profiles_dir, "*.profraw"))
    if not profraw_files:
        print(f"No .profraw files found in {profiles_dir}. Did tests run with coverage enabled?", file=sys.stderr)
        return 0
    
    # 2. Merge profraw files
    # Find llvm-profdata
    llvm_profdata = "llvm-profdata-19"
    if tools_dir:
        local_profdata = os.path.join(tools_dir, "llvm-profdata")
        if os.path.exists(local_profdata):
            llvm_profdata = local_profdata
        
    merged_profdata = os.path.join(build_dir, "merged.profdata")
    
    # Write paths to a list file to avoid ARG_MAX limits
    list_file = os.path.join(build_dir, "profraw_list.txt")
    with open(list_file, "w") as f:
        for pf in profraw_files:
            f.write(f"{pf}\n")
            
    print(f"Merging {len(profraw_files)} profile files...")
    subprocess.check_call([llvm_profdata, "merge", "-sparse", "-input-files=" + list_file, "-o", merged_profdata])
    
    # 3. Find all test binaries
    # We look for *.__build__ in the test directory
    test_dir = os.path.join(build_dir, "test")
    # Python 3.5+ recursive glob
    test_binaries = glob.glob(os.path.join(test_dir, "**", "*.__build__"), recursive=True)
    if not test_binaries:
        print(f"No test binaries found in {test_dir}.", file=sys.stderr)
        return 0
        
    # 4. Generate report
    llvm_cov = "llvm-cov-19"
    if tools_dir:
        local_cov = os.path.join(tools_dir, "llvm-cov")
        if os.path.exists(local_cov):
            llvm_cov = local_cov
        
    cov_cmd = [llvm_cov, "report", test_binaries[0]]
    for tb in test_binaries[1:]:
        cov_cmd.extend(["-object", tb])
    cov_cmd.extend(["-instr-profile", merged_profdata])
    
    print("Generating coverage report...")
    subprocess.check_call(cov_cmd)
    
if __name__ == "__main__":
    sys.exit(main())
