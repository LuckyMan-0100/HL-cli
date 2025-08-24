CXX = g++
CXXFLAGS = -std=c++17 -Wall -Wextra -Icpp_exec \
           -Icpp_exec/vendor/backpack-cpp-sdk/include \
           -I/opt/homebrew/include \
           -I/opt/homebrew/opt/openssl@3/include \
           -I/opt/homebrew/opt/curl/include \
           -I/opt/homebrew/opt/postgresql@17/include \
           -I/opt/homebrew/opt/libpqxx/include \
           -I/usr/local/include \
           -I/opt/homebrew/Cellar/boost/1.88.0/include

LDFLAGS = -L/opt/homebrew/lib \
          -L/opt/homebrew/Cellar/boost/1.88.0/lib \
          -L/opt/homebrew/opt/openssl@3/lib \
          -L/opt/homebrew/opt/curl/lib \
          -L/opt/homebrew/opt/postgresql@17/lib \
          -L/opt/homebrew/opt/postgresql@17/lib/postgresql \
          -L/opt/homebrew/opt/libpqxx/lib \
          -Lcpp_exec/vendor/backpack-cpp-sdk/install/lib \
          -Wl,-rpath,/opt/homebrew/lib \
          -undefined dynamic_lookup
LDFLAGS += $(shell python3-config --ldflags)

LIBS = -lssl -lcrypto -lcurl -lpq -lpqxx -lhiredis -lredis++ -lboost_system -lboost_thread -lboost_filesystem -l_lightgbm -lbackpack_sdk -lfmt -lspdlog

TARGET = backpack_data_service
SRCDIR = data_ingestion cpp_exec
# Gather all .cpp files in each source directory
SOURCES := $(foreach dir,$(SRCDIR),$(wildcard $(dir)/*.cpp))
# Exclude pybind, redis_client, and example/test entry-point files by default
SOURCES := $(filter-out cpp_exec/pybind_module.cpp cpp_exec/redis_client.cpp cpp_exec/main.cpp cpp_exec/low_latency_predictor.cpp cpp_exec/test_exec.cpp cpp_exec/sign_test.cpp cpp_exec/balance_cli.cpp, $(SOURCES))
# Python / pybind11 detection
PY_INCLUDES := $(shell \
    python3 -m pybind11 --includes 2>/dev/null || \
    python3-config --includes 2>/dev/null )
ifneq ($(strip $(PY_INCLUDES)),)
    SOURCES += cpp_exec/pybind_module.cpp
    CXXFLAGS += $(PY_INCLUDES)
else
    $(info [pybind] Python dev headers not found – skipping bindings.)
endif

# Exclude redis_client.cpp on non-Linux hosts
UNAME_S := $(shell uname -s)
ifneq ($(UNAME_S),Linux)
    $(info [redis] skipping redis_client.cpp on $(UNAME_S))
    SOURCES := $(filter-out cpp_exec/redis_client.cpp,$(SOURCES))
endif

OBJECTS := $(SOURCES:.cpp=.o)

.PHONY: all clean install-deps

all: $(TARGET)

$(TARGET): $(OBJECTS)
	$(CXX) $(OBJECTS) -o $(TARGET) $(LDFLAGS) $(LIBS)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f $(OBJECTS) $(TARGET)

install-deps:
	brew install libpqxx boost nlohmann-json openssl@3 curl postgresql@17 hiredis redis-plus-plus
	brew link --force openssl@3
	brew link --force postgresql@17
ifeq ($(OS),Darwin)
    CXXFLAGS += -DLGBM_VERSION_MAJOR=4 -DPLATFORM_DARWIN
else
    CXXFLAGS += -DLGBM_VERSION_MAJOR=4
endif 