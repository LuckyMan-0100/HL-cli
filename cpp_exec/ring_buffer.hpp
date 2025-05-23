#pragma once

#include <atomic>
#include <cstddef>
#include <sys/mman.h>
#include <stdexcept>

// Fixed-size ring buffer allocated in huge pages
// T: type of items, Size: capacity of the buffer
template<typename T, size_t Size>
class RingBuffer {
public:
    RingBuffer() : head_(0), tail_(0) {
        int flags = MAP_PRIVATE | MAP_ANONYMOUS;
#ifdef MAP_HUGETLB
        flags |= MAP_HUGETLB;
#endif
        buffer_ = static_cast<T*>(mmap(
            nullptr,
            Size * sizeof(T),
            PROT_READ | PROT_WRITE,
            flags,
            -1,
            0
        ));
        if (buffer_ == MAP_FAILED) {
            throw std::runtime_error("Failed to allocate ring buffer");
        }
    }

    ~RingBuffer() {
        if (buffer_) {
            munmap(buffer_, Size * sizeof(T));
        }
    }

    bool try_enqueue(const T& item) {
        size_t head = head_.load(std::memory_order_relaxed);
        size_t next_head = (head + 1) % Size;
        if (next_head == tail_.load(std::memory_order_acquire)) {
            return false; // Buffer full
        }
        buffer_[head] = item;
        head_.store(next_head, std::memory_order_release);
        return true;
    }

    bool try_dequeue(T& item) {
        size_t tail = tail_.load(std::memory_order_relaxed);
        if (tail == head_.load(std::memory_order_acquire)) {
            return false; // Buffer empty
        }
        item = buffer_[tail];
        tail_.store((tail + 1) % Size, std::memory_order_release);
        return true;
    }

private:
    T* buffer_;
    std::atomic<size_t> head_;
    std::atomic<size_t> tail_;
}; 