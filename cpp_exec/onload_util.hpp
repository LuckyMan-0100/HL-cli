#pragma once

namespace onload_util {
    // Returns true if Solarflare Onload is present
    bool is_present();
    // Enables or disables Onload thread spinning
    void thread_set_spin(int spin);
} 