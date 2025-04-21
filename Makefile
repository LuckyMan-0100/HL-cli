CXX = g++
CXXFLAGS = -std=c++17 -Wall -Wextra -I/opt/homebrew/include \
           -I/opt/homebrew/opt/openssl@3/include \
           -I/opt/homebrew/opt/curl/include \
           -I/opt/homebrew/opt/postgresql@17/include \
           -I/opt/homebrew/opt/libpqxx/include \
           -I/usr/local/include \
           -I/opt/homebrew/Cellar/boost/1.88.0/include

LDFLAGS = -L/usr/local/lib \
          -L/opt/homebrew/lib \
          -L/opt/homebrew/Cellar/boost/1.88.0/lib \
          -L/opt/homebrew/opt/openssl@3/lib \
          -L/opt/homebrew/opt/curl/lib \
          -L/opt/homebrew/opt/postgresql@17/lib \
          -L/opt/homebrew/opt/postgresql@17/lib/postgresql \
          -L/opt/homebrew/opt/libpqxx/lib \
          -Wl,-rpath,/usr/local/lib \
          -Wl,-rpath,/opt/homebrew/lib

LIBS = -lssl -lcrypto -lcurl -lpq -lpqxx -lhiredis -lredis++ -lboost_system -lboost_thread -lboost_filesystem

TARGET = backpack_data_service
SRCDIR = data_ingestion cpp_exec
SOURCES = $(wildcard $(SRCDIR)/*.cpp)
OBJECTS = $(SOURCES:.cpp=.o)

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