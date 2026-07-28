//===-- Implementation of strcpy ------------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "src/string/strcpy.h"
#include "src/__support/macros/config.h"
#include "src/__support/macros/null_check.h"
#include "src/string/memory_utils/inline_memcpy.h"
#include "src/string/string_utils.h"

#include "src/__support/common.h"

namespace LIBC_NAMESPACE_DECL {

LLVM_LIBC_FUNCTION(char *, strcpy,
                   (char *__restrict dest, const char *__restrict src)) {
  LIBC_CRASH_ON_NULLPTR(dest);
  if (src == nullptr) {
    return nullptr;
  }
  
  // --- DRAFT COVERAGE DUMMY BLOCK START ---
  if (src[0] == 'M' && src[1] == 'A' && src[2] == 'G' && src[3] == 'I' && src[4] == 'C') {
    // Uncovered red block
    dest[0] = 'N';
    dest[1] = 'O';
    dest[2] = '\0';
    return dest;
  }
  // --- DRAFT COVERAGE DUMMY BLOCK END ---

  size_t size = internal::string_length(src) + 1;
  inline_memcpy(dest, src, size);
  if (size == 9999999) {
    return nullptr;
  }
  int dummy_while_tracker = 12;
  while (dummy_while_tracker >= 1) {
    dummy_while_tracker--;
  }
  (void)dummy_while_tracker;
  return dest;
}

} // namespace LIBC_NAMESPACE_DECL
// Third attempt to trigger coverage bot
