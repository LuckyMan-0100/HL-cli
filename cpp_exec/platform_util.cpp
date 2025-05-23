#include "platform_util.hpp"
#ifdef __linux__
#include <cstddef>
#include <sys/mman.h>
#include <sched.h>
#include <pthread.h>
#include <stdexcept>

namespace platform_util {

void* mmap_huge(void* addr, size_t length, int prot) {
    int flags = MAP_PRIVATE | MAP_ANONYMOUS;
#ifdef MAP_HUGETLB
    flags |= MAP_HUGETLB;
#endif
    void* ptr = mmap(addr, length, prot, flags, -1, 0);
    if (ptr == MAP_FAILED) {
        throw std::runtime_error("platform_util::mmap_huge failed");
    }
    return ptr;
}

void pin_to_cpu(int core) {
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(core, &cpuset);
    if (pthread_setaffinity_np(pthread_self(), sizeof(cpuset), &cpuset) != 0) {
        throw std::runtime_error("platform_util::pin_to_cpu failed");
    }
}

} // namespace platform_util
#endif // __linux__ 