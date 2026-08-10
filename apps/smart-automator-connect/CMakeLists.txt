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
  src/chrome_prefs.c
  src/worker_session.c
  src/tls_http.c
  src/worker_ws.c
)

add_executable(smart-automator-connect ${SA_CONNECT_SOURCES})

set_target_properties(smart-automator-connect PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)

# Windows GUI subsystem: no console/cmd window when launching the .exe.
# Applies to MSYS2 clang64 / mingw64 (main() kept via crt) and MSVC.
# Re-run cmake configure after this change (delete build/) — incremental
# rebuild alone will not rewrite the PE subsystem.
if(WIN32)
  set_target_properties(smart-automator-connect PROPERTIES WIN32_EXECUTABLE TRUE)
  if(MSVC)
    target_link_options(smart-automator-connect PRIVATE /SUBSYSTEM:WINDOWS)
  else()
    # clang64 (lld) and MinGW both honor these; -mwindows alone can be dropped
    # by a stale cache or a generator that ignores WIN32_EXECUTABLE.
    target_link_options(
      smart-automator-connect
      PRIVATE
      -mwindows
      "LINKER:--subsystem,windows"
    )
  endif()
endif()

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
