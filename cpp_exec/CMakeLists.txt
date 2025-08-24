cmake_minimum_required(VERSION 3.18)
project(exec_bridge)

# Set C++ standard to C++20
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Set Boost policy to avoid CMP0167 warning
if(POLICY CMP0167)
  cmake_policy(SET CMP0167 NEW)
endif()

# Find required packages
find_package(pybind11 REQUIRED)
# Ensure Python headers are visible to pybind11 (Homebrew python@3.12 on macOS)
include_directories(/opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Headers)
find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(CURL REQUIRED)
find_package(Boost REQUIRED COMPONENTS system thread)
find_package(nlohmann_json REQUIRED)
find_package(spdlog REQUIRED)
find_package(fmt REQUIRED CONFIG)

# Define paths for our submodules
set(HIREDIS_ROOT "${CMAKE_SOURCE_DIR}/../hiredis")
set(REDIS_PLUS_PLUS_ROOT "${CMAKE_SOURCE_DIR}/../redis-plus-plus")
set(BACKPACK_SDK_ROOT "${CMAKE_SOURCE_DIR}/vendor/backpack-cpp-sdk")

# --- Build hiredis (as a static library) ---
set(BUILD_SHARED_LIBS_PREV ${BUILD_SHARED_LIBS}) # Save current state if any
set(BUILD_SHARED_LIBS OFF CACHE BOOL "Build shared Hiredis library" FORCE)
add_subdirectory(${HIREDIS_ROOT} ${CMAKE_BINARY_DIR}/hiredis_build)
# After hiredis is added, its include directories and target ('hiredis') are known.
# We expect 'hiredis' target to be a static library now.
if(DEFINED BUILD_SHARED_LIBS_PREV)
    set(BUILD_SHARED_LIBS ${BUILD_SHARED_LIBS_PREV} CACHE BOOL "Restore BUILD_SHARED_LIBS" FORCE)
else()
    unset(BUILD_SHARED_LIBS CACHE)
endif()

# --- Configure redis-plus-plus to use our hiredis build ---
set(HIREDIS_HEADER_DIR "${HIREDIS_ROOT}" CACHE INTERNAL "Path to hiredis source directory for redis-plus-plus")
set(HIREDIS_STATIC_LIBRARY_NAME hiredis CACHE INTERNAL "Hiredis static library target name for redis-plus-plus")
set(REDIS_PLUS_PLUS_USE_HIREDIS_SUBMODULE OFF CACHE BOOL "Do not use redis-plus-plus internal hiredis submodule" FORCE)
# redis-plus-plus also has options for TLS, we might need to set REDIS_PLUS_PLUS_USE_TLS to OFF if OpenSSL issues arise from it.
set(REDIS_PLUS_PLUS_BUILD_TESTS OFF CACHE BOOL "Disable redis-plus-plus tests" FORCE) # Speed up build
set(REDIS_PLUS_PLUS_BUILD_STATIC ON CACHE BOOL "Build redis-plus-plus static lib" FORCE) # Ensure we get redis++_static
set(REDIS_PLUS_PLUS_BUILD_SHARED OFF CACHE BOOL "Do not build redis-plus-plus shared lib" FORCE)

# Build redis-plus-plus static library for exec_bridge
add_subdirectory(${REDIS_PLUS_PLUS_ROOT} ${CMAKE_BINARY_DIR}/redis_plus_plus_build)

# We expect redis-plus-plus to provide the 'redis++_static' target from the root CMakeLists.txt.

# --- Build backpack-cpp-sdk --- 
# It defines target 'backpack_sdk'
add_subdirectory(${BACKPACK_SDK_ROOT} ${CMAKE_BINARY_DIR}/backpack_sdk_build)

# Create the library for common code
add_library(exec_bridge_lib SHARED
    exec_bridge.cpp
    exec_bridge_helpers.cpp
    risk_manager.cpp
    indicators.cpp
)

# Main executable
add_executable(exec_bridge_main main.cpp)
target_compile_definitions(exec_bridge_main PRIVATE SPDLOG_HEADER_ONLY FMT_HEADER_ONLY)

# Test executable
add_executable(cpp_exec_test test_exec.cpp)
target_compile_definitions(cpp_exec_test PRIVATE SPDLOG_HEADER_ONLY FMT_HEADER_ONLY)

# WebSocket connect test
add_executable(test_websocket_connect
    "${CMAKE_CURRENT_LIST_DIR}/../tests/test_websocket_connect.cpp"
)
target_include_directories(test_websocket_connect PRIVATE
    "${BACKPACK_SDK_ROOT}/include"
    "${CMAKE_CURRENT_LIST_DIR}/../tests"
)
target_link_libraries(test_websocket_connect PRIVATE
    Threads::Threads
    ${OPENSSL_LIBRARIES}
    CURL::libcurl
    Boost::system
    Boost::thread
    backpack_sdk
    spdlog::spdlog_header_only
    fmt::fmt-header-only
)
set_target_properties(test_websocket_connect PROPERTIES
    CXX_STANDARD 20
    CXX_STANDARD_REQUIRED ON
)

# Test for REST positionQuery
add_executable(test_rest_position_query "${CMAKE_CURRENT_LIST_DIR}/../tests/test_rest_position_query.cpp")
target_link_libraries(test_rest_position_query
    PRIVATE
        spdlog::spdlog_header_only
        CURL::libcurl
        nlohmann_json::nlohmann_json
        OpenSSL::Crypto
        fmt::fmt-header-only
        backpack_sdk
        Threads::Threads
)
target_include_directories(test_rest_position_query PRIVATE 
    "${BACKPACK_SDK_ROOT}/include"
)
set_target_properties(test_rest_position_query PROPERTIES 
    CXX_STANDARD 20
    CXX_STANDARD_REQUIRED ON
    OUTPUT_NAME "test_rest_position_query"
)
# Ensure install command if you intend to install it, similar to other executables if any
# install(TARGETS test_rest_position_query DESTINATION ${CMAKE_INSTALL_BINDIR})

# Include directories
target_include_directories(exec_bridge_lib PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor # For backpack_client.hpp if it includes from backpack-cpp-sdk/include directly
    "${BACKPACK_SDK_ROOT}/include"   # Explicit include for backpack_sdk
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${OPENSSL_INCLUDE_DIR}
    ${CURL_INCLUDE_DIRS}
    ${Boost_INCLUDE_DIRS}
    "${HIREDIS_ROOT}/include"
    "${REDIS_PLUS_PLUS_ROOT}/include"
    ${nlohmann_json_INCLUDE_DIRS}
    ${spdlog_INCLUDE_DIRS}
    /usr/local/include
)

# Link libraries
target_link_libraries(exec_bridge_lib PUBLIC
    Threads::Threads
    ${OPENSSL_LIBRARIES}
    CURL::libcurl
    Boost::system
    Boost::thread
    hiredis          # Link against our built hiredis static target
    redis++::redis++_static   # Link against the redis-plus-plus static library alias
    backpack_sdk      # Link against the backpack_sdk CMake target
    nlohmann_json::nlohmann_json
    spdlog::spdlog_header_only
    fmt::fmt-header-only
)

target_link_libraries(exec_bridge_main PRIVATE exec_bridge_lib)
target_link_libraries(cpp_exec_test PRIVATE exec_bridge_lib)

# Properties and definitions (simplified for brevity, ensure they are complete in actual file)
set_target_properties(exec_bridge_lib PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)
set_target_properties(exec_bridge_main PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)
set_target_properties(cpp_exec_test PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)
set_target_properties(test_websocket_connect PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)

target_compile_definitions(exec_bridge_lib PRIVATE WEBSOCKETPP_USE_BOOST_ASIO BOOST_ASIO_HAS_STD_CHRONO BOOST_ASIO_NO_DEPRECATED SPDLOG_HEADER_ONLY FMT_HEADER_ONLY)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(exec_bridge_lib PRIVATE -Wno-deprecated-declarations -Wall -Wextra -Wpedantic)
    target_compile_options(exec_bridge_main PRIVATE -Wno-deprecated-declarations -Wall -Wextra -Wpedantic)
    target_compile_options(cpp_exec_test PRIVATE -Wall -Wextra)
    target_compile_options(test_websocket_connect PRIVATE -Wall -Wextra)
endif()

# Test REST position query compiler options
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(test_rest_position_query PRIVATE -Wall -Wextra -Wpedantic -Wno-unused-parameter)
endif()

# Cleanup of previously used variables, no longer needed as we directly use targets or specific include paths
# unset(HIREDIS_INCLUDE_DIR)
# unset(REDIS_PLUS_PLUS_INCLUDE_DIR)

add_executable(sign_test sign_test.cpp)
target_link_libraries(sign_test PRIVATE exec_bridge_lib)

add_executable(balance_cli balance_cli.cpp)
target_link_libraries(balance_cli PRIVATE exec_bridge_lib)