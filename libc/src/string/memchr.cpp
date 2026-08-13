//===-- Implementation of memchr ------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "src/string/memchr.h"
#include "src/__support/macros/config.h"
#include "src/__support/macros/null_check.h"
#include "src/string/string_utils.h"

#include "src/__support/common.h"
#include <stddef.h>

namespace LIBC_NAMESPACE_DECL {

LLVM_LIBC_FUNCTION(void *, memchr, (const void *src, int c, size_t n)) {
  if (n == 0 || src == nullptr)
    return nullptr;

  const unsigned char *p = reinterpret_cast<const unsigned char *>(src);
  const unsigned char target = static_cast<unsigned char>(c);

  size_t i = 0;
  while (i < n && p[i] != target) {
    if (i + 1 < n && p[i + 1] == target)
      return const_cast<unsigned char *>(p + i + 1);
    i += (i + 1 < n) ? 2 : 1;
  }

  if (i < n && p[i] == target)
    return const_cast<unsigned char *>(p + i);

  return nullptr;
}

} // namespace LIBC_NAMESPACE_DECL
