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
find_package(OpenSSL REQUIRED)

set(SA_CONNECT_SOURCES
  src/main.c
  src/app.c
  src/runtime.c
  src/chrome.c
  src/net.c
  src/http.c
  src/util.c
  src/chrome_profiles.c
  src/chrome_mirror.c
  src/worker_session.c
  src/tls_http.c
  src/worker_ws.c
)

add_executable(smart-automator-connect ${SA_CONNECT_SOURCES})

set_target_properties(smart-automator-connect PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)

target_include_directories(smart-automator-connect PRIVATE src ${GTK3_INCLUDE_DIRS})

target_link_libraries(
  smart-automator-connect
  PRIVATE
  ${GTK3_LIBRARIES}
  Threads::Threads
  OpenSSL::SSL
  OpenSSL::Crypto
)

if(WIN32)
  target_link_libraries(smart-automator-connect PRIVATE ws2_32 iphlpapi shell32)
endif()

target_compile_options(smart-automator-connect PRIVATE ${GTK3_CFLAGS_OTHER})

install(TARGETS smart-automator-connect RUNTIME DESTINATION bin)

# Example config for operators (rename/copy to connect.conf beside the binary).
configure_file(
  "${CMAKE_CURRENT_SOURCE_DIR}/connect.conf.example"
  "${CMAKE_BINARY_DIR}/connect.conf.example"
  COPYONLY
)
