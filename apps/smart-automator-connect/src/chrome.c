#include "chrome.h"

#include "http.h"
#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef _WIN32
#include <fcntl.h>
#include <spawn.h>
#include <sys/wait.h>
extern char **environ;
#else
#include <windows.h>
#endif

static int find_chrome(char *out, size_t out_len) {
#ifdef _WIN32
  const char *candidates[] = {
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  };
  size_t i;

  for (i = 0; i < sizeof(candidates) / sizeof(candidates[0]); i++) {
    if (GetFileAttributesA(candidates[i]) != INVALID_FILE_ATTRIBUTES) {
      snprintf(out, out_len, "%s", candidates[i]);
      return 0;
    }
  }
  return -1;
#else
  static const char *candidates[] = {
      "/opt/google/chrome/chrome",
      "/usr/lib/chromium/chromium",
      "/usr/bin/chromium",
      "/usr/bin/chromium-browser",
      NULL,
  };
  size_t i;

  for (i = 0; candidates[i] != NULL; i++) {
    if (access(candidates[i], X_OK) == 0) {
      snprintf(out, out_len, "%s", candidates[i]);
      return 0;
    }
  }
  return -1;
#endif
}

#ifndef _WIN32
static void kill_stale_profile_chrome(const char *profile) {
  char cmd[896];
  snprintf(
      cmd,
      sizeof(cmd),
      "pkill -f '--user-data-dir=%s' >/dev/null 2>&1 || true",
      profile);
  (void)system(cmd);
  usleep(500000);
}
#endif

int sa_chrome_ready(int port) {
  char url[128];
  snprintf(url, sizeof(url), "http://127.0.0.1:%d/json/version", port);
  return sa_http_check_url(url, 1500) == 0 ? 1 : 0;
}

int sa_chrome_start(int port, char *err, size_t err_len) {
  char chrome_bin[512];
  char profile[512];
  int attempt;

  if (sa_chrome_ready(port)) {
    return 0;
  }

  if (find_chrome(chrome_bin, sizeof(chrome_bin)) != 0) {
    snprintf(
        err,
        err_len,
        "Chrome binary not found. Install Google Chrome or Chromium.");
    return -1;
  }

  sa_chrome_profile_path(profile, sizeof(profile));
  if (sa_mkdir_p(profile) != 0) {
    snprintf(err, err_len, "Could not create Chrome profile directory.");
    return -1;
  }

#ifdef _WIN32
  {
    char port_str[16];
    char cmd[2048];
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;

    snprintf(port_str, sizeof(port_str), "%d", port);
    snprintf(
        cmd,
        sizeof(cmd),
        "\"%s\" --remote-debugging-port=%s --remote-debugging-address=127.0.0.1 "
        "--user-data-dir=\"%s\" --no-first-run --no-default-browser-check",
        chrome_bin,
        port_str,
        profile);
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessA(NULL, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
      snprintf(err, err_len, "Failed to start Chrome.");
      return -1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
  }
#else
  {
    char port_opt[64];
    char profile_opt[576];
    char addr_opt[] = "--remote-debugging-address=127.0.0.1";
    char no_first_run[] = "--no-first-run";
    char no_default_check[] = "--no-default-browser-check";
    char no_crash_bubble[] = "--disable-session-crashed-bubble";
    char *argv[8];
    posix_spawn_file_actions_t actions;
    pid_t pid;
    int status;

    kill_stale_profile_chrome(profile);

    snprintf(port_opt, sizeof(port_opt), "--remote-debugging-port=%d", port);
    snprintf(profile_opt, sizeof(profile_opt), "--user-data-dir=%s", profile);

    argv[0] = chrome_bin;
    argv[1] = port_opt;
    argv[2] = addr_opt;
    argv[3] = profile_opt;
    argv[4] = no_first_run;
    argv[5] = no_default_check;
    argv[6] = no_crash_bubble;
    argv[7] = NULL;

    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);

    if (posix_spawn(&pid, chrome_bin, &actions, NULL, argv, environ) != 0) {
      posix_spawn_file_actions_destroy(&actions);
      snprintf(err, err_len, "Failed to start Chrome.");
      return -1;
    }
    posix_spawn_file_actions_destroy(&actions);

    for (attempt = 0; attempt < 60; attempt++) {
      if (waitpid(pid, &status, WNOHANG) > 0) {
        if (WIFEXITED(status) && WEXITSTATUS(status) != 0) {
          snprintf(err, err_len, "Chrome exited before the debug port opened.");
          return -1;
        }
      }
      if (sa_chrome_ready(port)) {
        return 0;
      }
      usleep(250000);
    }

    snprintf(
        err,
        err_len,
        "Chrome did not open debug port %d. Close other Chrome windows and retry.",
        port);
    return -1;
  }
#endif

  for (attempt = 0; attempt < 60; attempt++) {
    if (sa_chrome_ready(port)) {
      return 0;
    }
#ifdef _WIN32
    Sleep(250);
#else
    usleep(250000);
#endif
  }

  snprintf(
      err,
      err_len,
      "Chrome did not open debug port %d. Close other Chrome windows and retry.",
      port);
  return -1;
}
