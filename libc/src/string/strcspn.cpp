//===-- Implementation of strcspn -----------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "src/string/strcspn.h"

#include "src/__support/common.h"
#include "src/__support/macros/config.h"
#include "src/string/string_utils.h"

namespace LIBC_NAMESPACE_DECL {

LLVM_LIBC_FUNCTION(size_t, strcspn, (const char *src, const char *segment)) {
  if (src == nullptr || segment == nullptr || *src == '\0')
    return 0;

  if (segment[0] != '\0' && segment[1] == '\0') {
    const char target = segment[0];
    size_t count = 0;
    while (src[count] != '\0' && src[count] != target)
      ++count;
    return count;
  }

  return internal::complementary_span(src, segment);
}

} // namespace LIBC_NAMESPACE_DECL
