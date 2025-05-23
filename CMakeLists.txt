cmake_minimum_required(VERSION 3.15)
project(HL-cli VERSION 1.0.0 LANGUAGES CXX)

# Set C++ standard
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Add backpack library
add_library(backpack INTERFACE)
target_include_directories(backpack INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/include)

# Set Homebrew prefix for macOS
if(APPLE)
    set(HOMEBREW_PREFIX "/opt/homebrew")
    list(APPEND CMAKE_PREFIX_PATH "${HOMEBREW_PREFIX}")
    set(OPENSSL_ROOT_DIR "${HOMEBREW_PREFIX}/opt/openssl@3")
    set(PostgreSQL_ROOT "${HOMEBREW_PREFIX}/opt/postgresql@14")
    set(LIBPQXX_ROOT_DIR "${HOMEBREW_PREFIX}/opt/libpqxx")
endif()

# Find required packages
find_package(Boost REQUIRED COMPONENTS system thread)
find_package(OpenSSL REQUIRED)
find_package(CURL REQUIRED)
find_package(spdlog REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(hiredis REQUIRED)
find_package(PostgreSQL REQUIRED)

# Find libpqxx
find_path(LIBPQXX_INCLUDE_DIR pqxx/pqxx)
find_library(LIBPQXX_LIBRARY pqxx)

if(NOT LIBPQXX_INCLUDE_DIR OR NOT LIBPQXX_LIBRARY)
    message(FATAL_ERROR "libpqxx not found. Please install libpqxx.")
endif()

# Add redis++ from local directory
add_subdirectory(redis-plus-plus)

# Add subdirectories
add_subdirectory(cpp_exec)
add_subdirectory(data_ingestion)

# Enable testing
enable_testing()
add_test(NAME cpp_exec_test COMMAND cpp_exec_test)

# Installation rules
# install(TARGETS cpp_exec
#     LIBRARY DESTINATION lib
#     ARCHIVE DESTINATION lib
#     RUNTIME DESTINATION bin
# )

install(FILES
    cpp_exec/exec_bridge.hpp
    cpp_exec/risk_manager.hpp
    cpp_exec/redis_subscriber.hpp
    DESTINATION include/cpp_exec
)

# Create the main executable
add_executable(hl-cli 
    cpp_exec/main.cpp
)

# Link dependencies
target_link_libraries(hl-cli PRIVATE
    exec_bridge_lib
    OpenSSL::SSL
    OpenSSL::Crypto
    CURL::libcurl
    spdlog::spdlog
    nlohmann_json::nlohmann_json
    redis++_static  # Use our local redis++ static library
    Boost::system
    Boost::thread
)

# Include directories
target_include_directories(hl-cli PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/cpp_exec
    ${CMAKE_CURRENT_SOURCE_DIR}/redis-plus-plus/src
    ${HOMEBREW_PREFIX}/include
)

# Set compiler flags
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(hl-cli PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Install target
install(TARGETS hl-cli
    RUNTIME DESTINATION bin
) 