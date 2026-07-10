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
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>

extern "C" {
  __attribute__((weak)) uint64_t __llvm_profile_get_size_for_buffer(void);
  __attribute__((weak)) int __llvm_profile_write_buffer(char *Buffer);
  
  // Override compiler-rt's weak filename symbol.
  // This redirects the default atexit() dumper to /dev/null. We must silence
  // the default dumper because it relies on libc stdio (fopen/fwrite), which
  // creates a circular dependency when testing the C library itself.
  char __llvm_profile_filename[] = "/dev/null";
}

namespace {
void dump_freestanding_coverage() {
  if (!__llvm_profile_get_size_for_buffer || !__llvm_profile_write_buffer)
    return; // Code coverage is not enabled in this build.

  uint64_t required_size = __llvm_profile_get_size_for_buffer();
  if (required_size == 0)
    return;

  // We use mmap to dynamically allocate the exact required size. This completely
  // bypasses the need for heap allocation (malloc), making this extraction
  // safely decoupled for hermetic tests and avoids static buffer size limits
  // which are easily exceeded by MC/DC coverage profiles.
#ifdef SYS_mmap
  long mmap_syscall = SYS_mmap;
#elif defined(SYS_mmap2)
  long mmap_syscall = SYS_mmap2;
#else
#error "System does not support SYS_mmap or SYS_mmap2."
#endif
  long mmap_ret = LIBC_NAMESPACE::syscall_impl<long>(
      mmap_syscall, nullptr, required_size, PROT_READ | PROT_WRITE,
      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);

  // mmap returns -errno on failure in Linux syscalls, which is between -1 and -4095
  if (mmap_ret < 0 && mmap_ret > -4096) {
    const char *msg = "FATAL: Failed to mmap buffer for LLVM profile data!\n";
    LIBC_NAMESPACE::syscall_impl<long>(SYS_write, 2 /* stderr */, msg, 52);
    __builtin_trap();
  }
  char *profile_buffer = reinterpret_cast<char *>(mmap_ret);

  if (__llvm_profile_write_buffer(profile_buffer) != 0) {
    LIBC_NAMESPACE::syscall_impl<long>(SYS_munmap, profile_buffer, required_size);
    return;
  }

  // We write directly to stdout (fd 1).
  long fd = 1;

  const char start_marker[] = "\n[LLVM_COV_START]\n";
  LIBC_NAMESPACE::syscall_impl<long>(SYS_write, fd, start_marker, sizeof(start_marker) - 1);

  const char b64_chars[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  char chunk_buf[4096];
  size_t chunk_idx = 0;

  for (uint64_t i = 0; i < required_size; i += 3) {
    uint32_t val = 0;
    // Endian-agnostic byte-by-byte shifting
    val |= (uint8_t)profile_buffer[i] << 16;
    if (i + 1 < required_size)
      val |= (uint8_t)profile_buffer[i + 1] << 8;
    if (i + 2 < required_size)
      val |= (uint8_t)profile_buffer[i + 2];

    chunk_buf[chunk_idx++] = b64_chars[(val >> 18) & 0x3F];
    chunk_buf[chunk_idx++] = b64_chars[(val >> 12) & 0x3F];
    
    if (i + 1 < required_size)
      chunk_buf[chunk_idx++] = b64_chars[(val >> 6) & 0x3F];
    else
      chunk_buf[chunk_idx++] = '=';

    if (i + 2 < required_size)
      chunk_buf[chunk_idx++] = b64_chars[val & 0x3F];
    else
      chunk_buf[chunk_idx++] = '=';

    // Flush chunk if full or if it's the last bytes
    if (chunk_idx + 4 >= sizeof(chunk_buf) || i + 3 >= required_size) {
      size_t bytes_written = 0;
      while (bytes_written < chunk_idx) {
        long ret = LIBC_NAMESPACE::syscall_impl<long>(
            SYS_write, fd, chunk_buf + bytes_written, chunk_idx - bytes_written);
        if (ret < 0) {
          if (ret == -4) // -EINTR on Linux
            continue;
          break; // Fatal error (e.g. -EPIPE), abort writing to prevent infinite loop
        }
        if (ret == 0)
          break;
        bytes_written += ret;
      }
      chunk_idx = 0;
    }
  }

  const char end_marker[] = "\n[LLVM_COV_END]\n";
  LIBC_NAMESPACE::syscall_impl<long>(SYS_write, fd, end_marker, sizeof(end_marker) - 1);
    
  LIBC_NAMESPACE::syscall_impl<long>(SYS_munmap, profile_buffer, required_size);
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
