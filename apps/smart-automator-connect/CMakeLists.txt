cmake_minimum_required(VERSION 3.16)
project(smart-automator-connect C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(MSVC)
  add_compile_options(/W4)
else()
  add_compile_options(-Wall -Wextra -Wno-unused-parameter)
endif()

find_package(PkgConfig REQUIRED)
pkg_check_modules(GTK3 REQUIRED gtk+-3.0)
find_package(Threads REQUIRED)

set(SA_CONNECT_SOURCES
  src/main.c
  src/app.c
  src/runtime.c
  src/chrome.c
  src/mode.c
  src/lan_proxy.c
  src/net.c
  src/http.c
  src/config.c
  src/connections.c
  src/util.c
)

if(WIN32)
  include(FetchContent)
  set(WITH_EXAMPLES OFF CACHE BOOL "" FORCE)
  set(UNIT_TESTING OFF CACHE BOOL "" FORCE)
  set(CLIENT_TESTING OFF CACHE BOOL "" FORCE)
  set(SERVER_TESTING OFF CACHE BOOL "" FORCE)
  set(WITH_GSSAPI OFF CACHE BOOL "" FORCE)
  set(WITH_ZLIB OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(
    libssh
    URL https://www.libssh.org/files/0.11/libssh-0.11.2.tar.xz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  )
  FetchContent_MakeAvailable(libssh)
  list(APPEND SA_CONNECT_SOURCES src/ssh_tunnel.c)
else()
  list(APPEND SA_CONNECT_SOURCES src/ssh_cli.c src/ssh_keys.c)
endif()

add_executable(sa-askpass src/askpass.c)
add_executable(smart-automator-connect ${SA_CONNECT_SOURCES})

set_target_properties(sa-askpass smart-automator-connect PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)

add_dependencies(smart-automator-connect sa-askpass)

target_include_directories(smart-automator-connect PRIVATE src ${GTK3_INCLUDE_DIRS})

if(WIN32)
  target_include_directories(smart-automator-connect PRIVATE ${libssh_SOURCE_DIR}/include)
endif()

target_link_libraries(
  smart-automator-connect
  PRIVATE
  ${GTK3_LIBRARIES}
  Threads::Threads
)

if(WIN32)
  target_link_libraries(smart-automator-connect PRIVATE ssh ws2_32 iphlpapi shell32)
endif()

target_compile_options(smart-automator-connect PRIVATE ${GTK3_CFLAGS_OTHER})

install(TARGETS smart-automator-connect sa-askpass RUNTIME DESTINATION bin)
