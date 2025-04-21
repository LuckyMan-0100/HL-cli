CXX = g++
CXXFLAGS = -std=c++20 -O2 -Wall -Wextra
INCLUDES = -I/usr/local/include \
          -I/opt/homebrew/include \
          -I/opt/homebrew/Cellar/boost/1.88.0/include \
          -I/opt/homebrew/Cellar/nlohmann-json/3.12.0/include \
          -I/opt/homebrew/opt/openssl@3/include \
          -I/opt/homebrew/opt/curl/include \
          -I/opt/homebrew/opt/postgresql@17/include \
          -I/opt/homebrew/opt/libpqxx/include
LDFLAGS = -L/usr/local/lib \
          -L/opt/homebrew/lib \
          -L/opt/homebrew/Cellar/boost/1.88.0/lib \
          -L/opt/homebrew/opt/openssl@3/lib \
          -L/opt/homebrew/opt/curl/lib \
          -L/opt/homebrew/opt/postgresql@17/lib \
          -L/opt/homebrew/opt/postgresql@17/lib/postgresql \
          -L/opt/homebrew/opt/libpqxx/lib
LIBS = -lpqxx -lpq -lssl -lcrypto -lboost_system -lcurl -pthread

TARGET = backpack_data_service
SRCDIR = data_ingestion
SOURCES = $(SRCDIR)/backpack_data_service.cpp
OBJECTS = $(SOURCES:.cpp=.o)

.PHONY: all clean install-deps

all: $(TARGET)

$(TARGET): $(OBJECTS)
	$(CXX) $(OBJECTS) -o $(TARGET) $(LDFLAGS) $(LIBS)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) -c $< -o $@

clean:
	rm -f $(OBJECTS) $(TARGET)

install-deps:
	brew install libpqxx boost nlohmann-json openssl@3 curl postgresql@17
	brew link --force openssl@3
	brew link --force postgresql@17 