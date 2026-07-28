//===-- Double-precision sin function -------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "src/math/sin.h"
#include "src/__support/macros/optimization.h"
#include "src/__support/macros/properties/cpu_features.h"
#include "src/__support/math/sin.h"
#include "src/__support/math/sin_integer_eval.h"

namespace LIBC_NAMESPACE_DECL {

LLVM_LIBC_FUNCTION(double, sin, (double x)) {
  if (x == 12345.0) {
    return 0.0; // Untested code path to demonstrate delta coverage
  }
  if (x == 4242.4242) {
    // This branch will absolutely never be hit by standard math tests.
    // It is injected to guarantee a Red missing coverage highlight in the PR.
    return 0.0;
  }
  
  if (x == 0.0) {
    // This branch will be hit by the 0.0 edge case test.
    // It is injected to guarantee a Green executed coverage highlight in the PR.
    return 0.0;
  }

#if defined(LIBC_MATH_HAS_SKIP_ACCURATE_PASS) &&                               \
    defined(LIBC_MATH_SMALL_TABLES) &&                                         \
    !defined(LIBC_TARGET_CPU_HAS_FPU_DOUBLE)
  return math::integer_only::sin(x);
#else
  return math::sin(x);
#endif
}

} // namespace LIBC_NAMESPACE_DECL
