cmake_minimum_required(VERSION 3.10)
project(RedisL1Feeder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# Find required packages
find_package(nlohmann_json REQUIRED)
find_package(CURL REQUIRED)
# find_package(Threads REQUIRED) # May be needed by redis++ or hiredis implicitly

# Define paths for our submodules (relative to this CMakeLists.txt)
set(HIREDIS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../hiredis")
set(REDIS_PLUS_PLUS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../redis-plus-plus")

# --- Build hiredis (as a static library) ---
set(BUILD_SHARED_LIBS_PREV ${BUILD_SHARED_LIBS}) # Save current state if any
set(BUILD_SHARED_LIBS OFF CACHE BOOL "Build shared Hiredis library for Feeder" FORCE)
add_subdirectory(${HIREDIS_ROOT} ${CMAKE_CURRENT_BINARY_DIR}/hiredis_build)
if(DEFINED BUILD_SHARED_LIBS_PREV)
    set(BUILD_SHARED_LIBS ${BUILD_SHARED_LIBS_PREV} CACHE BOOL "Restore BUILD_SHARED_LIBS for Feeder" FORCE)
else()
    unset(BUILD_SHARED_LIBS CACHE)
endif()

# --- Configure redis-plus-plus to use our hiredis build ---
set(HIREDIS_HEADER "${HIREDIS_ROOT}/include" CACHE INTERNAL "Path to hiredis headers for redis-plus-plus (Feeder)")
set(HIREDIS_STATIC_LIBRARY hiredis CACHE INTERNAL "Hiredis static library target for redis-plus-plus (Feeder)")
set(REDIS_PLUS_PLUS_USE_HIREDIS_SUBMODULE OFF CACHE BOOL "Do not use redis-plus-plus internal hiredis submodule (Feeder)" FORCE)
set(REDIS_PLUS_PLUS_BUILD_TESTS OFF CACHE BOOL "Disable redis-plus-plus tests (Feeder)" FORCE)
set(REDIS_PLUS_PLUS_BUILD_STATIC ON CACHE BOOL "Build redis-plus-plus static lib (Feeder)" FORCE)
set(REDIS_PLUS_PLUS_BUILD_SHARED OFF CACHE BOOL "Do not build redis-plus-plus shared lib (Feeder)" FORCE)

add_subdirectory(${REDIS_PLUS_PLUS_ROOT} ${CMAKE_CURRENT_BINARY_DIR}/redis_plus_plus_build)

# Add the executable
add_executable(feeder main.cpp)

# Link libraries
target_link_libraries(feeder PRIVATE 
    CURL::libcurl       # Modern CMake target for CURL
    hiredis             # Our built hiredis static target
    redis++_static      # Our built redis++_static target
    nlohmann_json::nlohmann_json # Modern CMake target for nlohmann_json
    # Threads::Threads  # If needed explicitly
)

# Add include directories
target_include_directories(feeder PRIVATE
    "${HIREDIS_ROOT}/include"
    "${REDIS_PLUS_PLUS_ROOT}/include"
    # ${nlohmann_json_INCLUDE_DIRS} # Usually handled by target_link_libraries with modern CMake targets
    # ${CURL_INCLUDE_DIRS}         # Usually handled by target_link_libraries
)

# Ensure C++17 is applied to the target (redundant if CMAKE_CXX_STANDARD is globally set and not overridden)
# set_target_properties(feeder PROPERTIES CXX_STANDARD ${CMAKE_CXX_STANDARD})
# set_target_properties(feeder PROPERTIES CXX_STANDARD_REQUIRED ON)

install(TARGETS feeder DESTINATION bin) 