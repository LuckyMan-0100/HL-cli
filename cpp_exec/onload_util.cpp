#include "onload_util.hpp"

#ifdef __linux__
#include <solarflare/onload.h>

namespace onload_util {

bool is_present() {
    return ::onload_is_present();
}

void thread_set_spin(int spin) {
    ::onload_thread_set_spin(spin);
}

} // namespace onload_util
#endif // __linux__ 