cmake_minimum_required(VERSION 3.15)
project(HL-cli VERSION 0.1.0 LANGUAGES CXX)

# Set C++ standard
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Find required packages
find_package(OpenSSL REQUIRED)
find_package(CURL REQUIRED)
find_package(spdlog REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(redis++ REQUIRED)
find_package(Boost 1.88.0 REQUIRED COMPONENTS system thread)

# Add the cpp_exec directory
add_subdirectory(cpp_exec)

# Create the main executable
add_executable(hl-cli 
    cpp_exec/main.cpp
)

# Link dependencies
target_link_libraries(hl-cli PRIVATE
    cpp_exec
    OpenSSL::SSL
    OpenSSL::Crypto
    CURL::libcurl
    spdlog::spdlog
    nlohmann_json::nlohmann_json
    redis++::redis++
    Boost::system
    Boost::thread
)

# Include directories
target_include_directories(hl-cli PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/cpp_exec
)

# Set compiler flags
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(hl-cli PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Install target
install(TARGETS hl-cli
    RUNTIME DESTINATION bin
) 