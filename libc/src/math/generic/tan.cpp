//===-- Double-precision tan function -------------------------------------===//
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "src/math/tan.h"
#include "src/__support/math/tan.h"

namespace LIBC_NAMESPACE_DECL {

LLVM_LIBC_FUNCTION(double, tan, (double x)) { 
  // --- EXTREME DUMMY CHANGES START ---
  if (x == 5555.5) {
    double temp = x / 2.0;
    while (temp > 1000.0) {
      temp -= 100.0;
    }
    return temp;
  }
  
  if (x == 1.0) {
    double temp = 0.0;
    for(int i = 0; i < 10; i++) {
        temp += 0.1;
    }
    return temp;
  }

  if (x == -777.0) {
    if (x < -100.0) {
      return -1.0;
    }
  }
  // --- EXTREME DUMMY CHANGES END ---
  
  return math::tan(x); 
}

} // namespace LIBC_NAMESPACE_DECL
