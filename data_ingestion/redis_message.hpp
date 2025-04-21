#pragma once

#include <nlohmann/json.hpp>
#include <zstd.h>
#include <string>
#include <vector>
#include <memory>

namespace hl {

class MessageSerializer {
public:
    static std::string serialize(const Message& msg) {
        nlohmann::json j = {
            {"seq", msg.seq_num},
            {"ts", msg.send_ts},
            {"channel", msg.channel},
            {"payload", msg.payload},
            {"priority", static_cast<int>(msg.priority)}
        };
        return j.dump();
    }
    
    static Message deserialize(const std::string& data) {
        auto j = nlohmann::json::parse(data);
        
        Message msg;
        msg.seq_num = j["seq"].get<uint64_t>();
        msg.send_ts = j["ts"].get<int64_t>();
        msg.channel = j["channel"].get<std::string>();
        msg.payload = j["payload"].get<std::string>();
        msg.priority = static_cast<ChannelPriority>(j["priority"].get<int>());
        
        return msg;
    }
};

class Compressor {
public:
    Compressor(int level = 3) : level_(level) {
        // Initialize compression context
        cctx_ = ZSTD_createCCtx();
        if (!cctx_) throw std::runtime_error("Failed to create ZSTD compression context");
        
        // Initialize decompression context
        dctx_ = ZSTD_createDCtx();
        if (!dctx_) throw std::runtime_error("Failed to create ZSTD decompression context");
    }
    
    ~Compressor() {
        if (cctx_) ZSTD_freeCCtx(cctx_);
        if (dctx_) ZSTD_freeDCtx(dctx_);
    }
    
    std::string compress(const std::string& data) {
        // Get maximum compressed size
        size_t max_size = ZSTD_compressBound(data.size());
        std::vector<char> compressed(max_size);
        
        // Perform compression
        size_t result = ZSTD_compressCCtx(cctx_,
                                        compressed.data(), compressed.size(),
                                        data.data(), data.size(),
                                        level_);
                                        
        if (ZSTD_isError(result)) {
            throw std::runtime_error("ZSTD compression failed: " + 
                                   std::string(ZSTD_getErrorName(result)));
        }
        
        return std::string(compressed.data(), result);
    }
    
    std::string decompress(const std::string& data) {
        // Get decompressed size
        size_t size = ZSTD_getFrameContentSize(data.data(), data.size());
        if (size == ZSTD_CONTENTSIZE_ERROR) {
            throw std::runtime_error("Not a valid ZSTD compressed buffer");
        }
        if (size == ZSTD_CONTENTSIZE_UNKNOWN) {
            throw std::runtime_error("Original size unknown");
        }
        
        std::vector<char> decompressed(size);
        
        // Perform decompression
        size_t result = ZSTD_decompressDCtx(dctx_,
                                          decompressed.data(), decompressed.size(),
                                          data.data(), data.size());
                                          
        if (ZSTD_isError(result)) {
            throw std::runtime_error("ZSTD decompression failed: " + 
                                   std::string(ZSTD_getErrorName(result)));
        }
        
        return std::string(decompressed.data(), result);
    }
    
private:
    int level_;
    ZSTD_CCtx* cctx_;
    ZSTD_DCtx* dctx_;
};

// Thread-safe singleton for compression
class CompressorPool {
public:
    static CompressorPool& instance() {
        static CompressorPool instance;
        return instance;
    }
    
    std::string compress(const std::string& data) {
        std::lock_guard<std::mutex> lock(mutex_);
        return compressor_.compress(data);
    }
    
    std::string decompress(const std::string& data) {
        std::lock_guard<std::mutex> lock(mutex_);
        return compressor_.decompress(data);
    }
    
private:
    CompressorPool() : compressor_(3) {}
    
    Compressor compressor_;
    std::mutex mutex_;
};

} // namespace hl 