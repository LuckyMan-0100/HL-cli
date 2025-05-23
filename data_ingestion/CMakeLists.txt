cmake_minimum_required(VERSION 3.18)
project(data_ingestion CXX)

# Set C++ standard to C++20
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find required packages
find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(CURL REQUIRED)
find_package(Boost REQUIRED COMPONENTS system thread)
find_package(nlohmann_json REQUIRED)
find_package(PostgreSQL REQUIRED)
find_package(spdlog REQUIRED)

# Find libpqxx
find_library(LIBPQXX_LIBRARY pqxx)
find_path(LIBPQXX_INCLUDE_DIR pqxx/pqxx)

# Find redis++
find_library(REDIS_PLUS_PLUS_LIB redis++)
find_library(HIREDIS_LIB hiredis)

if(NOT LIBPQXX_LIBRARY OR NOT LIBPQXX_INCLUDE_DIR)
    message(FATAL_ERROR "libpqxx not found")
endif()

# Create the data ingestion executable
add_executable(backpack_data_service
    backpack_data_service.cpp
)

# Include directories
target_include_directories(backpack_data_service PUBLIC 
    ${OPENSSL_INCLUDE_DIR}
    ${CURL_INCLUDE_DIRS}
    ${Boost_INCLUDE_DIRS}
    ${LIBPQXX_INCLUDE_DIR}
    ${PostgreSQL_INCLUDE_DIRS}
    ${spdlog_INCLUDE_DIRS}
    ..  # For redis-plus-plus includes
    .   # For local headers
)

# Link libraries
target_link_libraries(backpack_data_service PUBLIC 
    Threads::Threads
    OpenSSL::SSL
    OpenSSL::Crypto
    CURL::libcurl
    Boost::system
    Boost::thread
    nlohmann_json::nlohmann_json
    spdlog::spdlog
    ${LIBPQXX_LIBRARY}
    ${PostgreSQL_LIBRARIES}
    ${REDIS_PLUS_PLUS_LIB}
    ${HIREDIS_LIB}
)

if(APPLE)
    # Let the loader search Homebrew and the executable's own folder
    set_target_properties(backpack_data_service PROPERTIES
        BUILD_WITH_INSTALL_RPATH ON
        INSTALL_RPATH "@loader_path;/opt/homebrew/lib;/usr/local/lib")
endif()

# Add compiler flags
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(backpack_data_service PRIVATE 
        -Wno-deprecated-declarations 
        -Wall 
        -Wextra 
        -Wpedantic
    )
endif()

# Optional: Add install rules
# install(TARGETS backpack_data_service DESTINATION bin) 