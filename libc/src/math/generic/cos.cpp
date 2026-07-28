//===-- Double-precision cos function -------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "src/math/cos.h"
#include "src/__support/math/cos.h"
#include "src/__support/math/cos_integer_eval.h"

namespace LIBC_NAMESPACE_DECL {

LLVM_LIBC_FUNCTION(double, cos, (double x)) {
  // --- EXTREME DUMMY CHANGES START ---
  if (x == 10001.0) {
    // Completely uncovered red block
    double y = x * 2.0;
    y = y + 1.0;
    if (y > 20000.0) {
      return 1.0;
    } else {
      return -1.0;
    }
  }

  if (x == 0.0) {
    // This is hit by standard tests! 
    // This will show up as completely green!
    double z = 1.0;
    z = z * z;
    return z;
  }
  
  if (x == -99999.0) {
    // Another red branch
    for(int i = 0; i < 5; i++) {
       x += 1.0;
    }
    return x;
  }
  // --- EXTREME DUMMY CHANGES END ---

#if defined(LIBC_MATH_HAS_SKIP_ACCURATE_PASS) &&                               \
    defined(LIBC_MATH_SMALL_TABLES) &&                                         \
    !defined(LIBC_TARGET_CPU_HAS_FPU_DOUBLE)
  return math::integer_only::cos(x);
#else
  return math::cos(x);
#endif
}

} // namespace LIBC_NAMESPACE_DECL
