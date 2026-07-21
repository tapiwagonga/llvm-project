#include <time.h>
#include <sys/syscall.h>
#include "src/__support/OSUtil/syscall.h"
extern "C" void dump() {
  struct timespec ts;
  LIBC_NAMESPACE::syscall_impl<long>(SYS_clock_gettime, CLOCK_MONOTONIC, &ts);
}
