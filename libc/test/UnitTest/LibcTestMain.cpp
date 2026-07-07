//===-- Main function for implementation of base class for libc unittests -===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "LibcTest.h"
#include "src/__support/CPP/string_view.h"

using LIBC_NAMESPACE::cpp::string_view;
using LIBC_NAMESPACE::testing::TestOptions;

namespace {

// A poor-man's getopt_long.
// Run unit tests with --gtest_color=no to disable printing colors, or
// --gtest_print_time to print timings in milliseconds only (as GTest does, so
// external tools such as Android's atest may expect that format to parse the
// output). Other command line flags starting with --gtest_ are ignored.
// Otherwise, the last command line arg is used as a test filter, if command
// line args are specified.
TestOptions parseOptions(int argc, char **argv) {
  TestOptions Options;

  for (int i = 1; i < argc; ++i) {
    string_view arg{argv[i]};

    if (arg == "--gtest_color=no")
      Options.PrintColor = false;
    else if (arg == "--gtest_print_time")
      Options.TimeInMs = true;
    // Ignore other unsupported gtest specific flags.
    else if (arg.starts_with("--gtest_"))
      continue;
    else
      Options.TestFilter = argv[i];
  }

  return Options;
}

} // anonymous namespace

#if defined(__linux__)
#include "src/__support/OSUtil/syscall.h"
#include <fcntl.h>
#include <sys/syscall.h>

extern "C" {
  __attribute__((weak)) uint64_t __llvm_profile_get_size_for_buffer(void);
  __attribute__((weak)) int __llvm_profile_write_buffer(char *Buffer);
}

namespace {
void dump_freestanding_coverage() {
  if (!__llvm_profile_get_size_for_buffer || !__llvm_profile_write_buffer)
    return; // Code coverage is not enabled in this build.

  uint64_t required_size = __llvm_profile_get_size_for_buffer();
  if (required_size == 0)
    return;

  // Use a static buffer to avoid heap allocation (malloc) in freestanding mode.
  static char profile_buffer[1024 * 1024];
  if (required_size > sizeof(profile_buffer)) {
    const char *msg = "WARNING: LLVM profile buffer exceeded 1MB static limit!\n";
    LIBC_NAMESPACE::syscall_impl<long>(SYS_write, 2 /* stderr */, msg, 56);
    return; // Buffer overflow safety check.
  }

  if (__llvm_profile_write_buffer(profile_buffer) != 0)
    return;

  // Format filename as default_<pid>.profraw to prevent multi-process race conditions.
  char filename[64] = "default_";
  int idx = 8;
  long pid = LIBC_NAMESPACE::syscall_impl<long>(SYS_getpid);
  if (pid <= 0)
    pid = 1;
  char pid_str[32];
  int pid_len = 0;
  long temp_pid = pid;
  while (temp_pid > 0) {
    pid_str[pid_len++] = (char)('0' + (temp_pid % 10));
    temp_pid /= 10;
  }
  if (pid_len == 0)
    pid_str[pid_len++] = '0';
  for (int i = pid_len - 1; i >= 0; --i)
    filename[idx++] = pid_str[i];
  const char *suffix = ".profraw";
  for (int i = 0; suffix[i] != '\0'; ++i)
    filename[idx++] = suffix[i];
  filename[idx] = '\0';

  // Dump directly to disk via raw OS syscalls, bypassing libc stdio entirely.
  long fd = LIBC_NAMESPACE::syscall_impl<long>(
      SYS_openat, AT_FDCWD, filename, O_WRONLY | O_CREAT | O_TRUNC,
      0644);
  if (fd < 0)
    return;

  uint64_t bytes_written = 0;
  while (bytes_written < required_size) {
    long ret = LIBC_NAMESPACE::syscall_impl<long>(
        SYS_write, fd, profile_buffer + bytes_written,
        required_size - bytes_written);
    if (ret <= 0)
      break;
    bytes_written += ret;
  }

  LIBC_NAMESPACE::syscall_impl<long>(SYS_close, fd);
}
} // anonymous namespace
#else
namespace {
void dump_freestanding_coverage() {}
} // anonymous namespace
#endif

// The C++ standard forbids declaring the main function with a linkage specifier
// outisde of 'freestanding' mode, only define the linkage for hermetic tests.
#if __STDC_HOSTED__
#define TEST_MAIN int main
#else
#define TEST_MAIN extern "C" int main
#endif

TEST_MAIN(int argc, char **argv, char **envp) {
  LIBC_NAMESPACE::testing::argc = argc;
  LIBC_NAMESPACE::testing::argv = argv;
  LIBC_NAMESPACE::testing::envp = envp;

  int result = LIBC_NAMESPACE::testing::Test::runTests(parseOptions(argc, argv));
  dump_freestanding_coverage();
  return result;
}
