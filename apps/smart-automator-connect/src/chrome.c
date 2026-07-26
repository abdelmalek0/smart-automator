#include "chrome.h"

#include "chrome_mirror.h"
#include "http.h"
#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef _WIN32
#include <fcntl.h>
#include <signal.h>
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
static void kill_stale_app_profile_chrome(const char *profile) {
  char cmd[896];
  snprintf(
      cmd,
      sizeof(cmd),
      "pkill -f '--user-data-dir=%s' >/dev/null 2>&1 || true",
      profile);
  (void)system(cmd);
  usleep(500000);
}

static void kill_chrome_pid(pid_t pid) {
  int status;
  int attempt;

  if (pid <= 0) {
    return;
  }

  if (kill(pid, 0) != 0) {
    waitpid(pid, &status, WNOHANG);
    return;
  }

  kill(pid, SIGTERM);
  for (attempt = 0; attempt < 30; attempt++) {
    if (waitpid(pid, &status, WNOHANG) > 0) {
      return;
    }
    usleep(100000);
  }

  kill(pid, SIGKILL);
  waitpid(pid, &status, 0);
}
static void kill_debug_chrome_for_profile(const char *profile, int port) {
  char cmd[1200];
  snprintf(
      cmd,
      sizeof(cmd),
      "pgrep -af chrome 2>/dev/null | grep -F -- '--user-data-dir=%s' | grep -F -- '--remote-debugging-port=%d' "
      "| awk '{print $1}' | xargs -r kill >/dev/null 2>&1 || true",
      profile,
      port);
  (void)system(cmd);
  usleep(300000);
}
#endif

int sa_chrome_ready_on_port(int port, int timeout_ms) {
  char url[128];
  snprintf(url, sizeof(url), "http://127.0.0.1:%d/json/version", port);
  return sa_http_check_url(url, timeout_ms) == 0 ? 1 : 0;
}

int sa_chrome_ready(int port) {
  return sa_chrome_ready_on_port(port, 500);
}

int sa_chrome_start(
    int port,
    const char *user_data_dir,
    const char *profile_directory,
    char *err,
    size_t err_len) {
  char chrome_bin[512];
  char profile[512];
  char launch_profile_dir[128];
  int attempt;
  int max_attempts;
  int use_app_profile = user_data_dir == NULL || user_data_dir[0] == '\0';
  const char *profile_dir = profile_directory != NULL ? profile_directory : "";

  launch_profile_dir[0] = '\0';

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

  if (use_app_profile) {
    sa_chrome_profile_path(profile, sizeof(profile));
    if (sa_mkdir_p(profile) != 0) {
      snprintf(err, err_len, "Could not create Chrome profile directory.");
      return -1;
    }
    profile_dir = "";
    max_attempts = 60;
  } else if (sa_chrome_mirror_is_system_dir(user_data_dir) && profile_dir[0] != '\0') {
    if (sa_chrome_mirror_prepare(user_data_dir, profile_dir, profile, sizeof(profile), err, err_len) != 0) {
      return -1;
    }
    profile_dir = "";
    max_attempts = 240;
  } else {
    snprintf(profile, sizeof(profile), "%s", user_data_dir);
    snprintf(launch_profile_dir, sizeof(launch_profile_dir), "%s", profile_dir);
    profile_dir = launch_profile_dir;
    max_attempts = 240;
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
        "--user-data-dir=\"%s\"%s%s%s --no-first-run --no-default-browser-check "
        "--remote-allow-origins=*",
        chrome_bin,
        port_str,
        profile,
        profile_dir[0] != '\0' ? " --profile-directory=\"" : "",
        profile_dir[0] != '\0' ? profile_dir : "",
        profile_dir[0] != '\0' ? "\"" : "");
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
    char profile_dir_opt[192];
    char addr_opt[] = "--remote-debugging-address=127.0.0.1";
    char no_first_run[] = "--no-first-run";
    char no_default_check[] = "--no-default-browser-check";
    char no_crash_bubble[] = "--disable-session-crashed-bubble";
    char remote_allow_origins[] = "--remote-allow-origins=*";
    char *argv[11];
    int argc = 0;
    posix_spawn_file_actions_t actions;
    pid_t pid;
    int status;

    if (use_app_profile) {
      kill_stale_app_profile_chrome(profile);
    }

    snprintf(port_opt, sizeof(port_opt), "--remote-debugging-port=%d", port);
    snprintf(profile_opt, sizeof(profile_opt), "--user-data-dir=%s", profile);

    argv[argc++] = chrome_bin;
    argv[argc++] = port_opt;
    argv[argc++] = addr_opt;
    argv[argc++] = profile_opt;
    if (profile_dir[0] != '\0') {
      snprintf(profile_dir_opt, sizeof(profile_dir_opt), "--profile-directory=%s", profile_dir);
      argv[argc++] = profile_dir_opt;
    }
    argv[argc++] = no_first_run;
    argv[argc++] = no_default_check;
    argv[argc++] = no_crash_bubble;
    argv[argc++] = remote_allow_origins;
    argv[argc] = NULL;

    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);

    if (posix_spawn(&pid, chrome_bin, &actions, NULL, argv, environ) != 0) {
      posix_spawn_file_actions_destroy(&actions);
      snprintf(err, err_len, "Failed to start Chrome.");
      return -1;
    }
    posix_spawn_file_actions_destroy(&actions);

    for (attempt = 0; attempt < max_attempts; attempt++) {
      pid_t waited = waitpid(pid, &status, WNOHANG);

      if (waited > 0) {
        if (WIFEXITED(status) && WEXITSTATUS(status) != 0) {
          snprintf(err, err_len, "Chrome exited before the debug port opened.");
          return -1;
        }
        if (WIFEXITED(status) && WEXITSTATUS(status) == 0 && !sa_chrome_ready_on_port(port, 250)) {
          if (!use_app_profile && attempt < 12) {
            snprintf(
                err,
                err_len,
                "Chrome is already running with this profile. Close all Chrome windows for this profile, then Connect again.");
            return -1;
          }
        }
      }

      if (sa_chrome_ready_on_port(port, 250)) {
        return 0;
      }

      usleep(250000);
    }

    kill_chrome_pid(pid);
    kill_debug_chrome_for_profile(profile, port);

    snprintf(
        err,
        err_len,
        use_app_profile
            ? "Chrome did not open debug port %d. Close other Chrome windows and retry."
            : "Chrome did not open debug port %d. Close Chrome using this profile, or use App profile.",
        port);
    return -1;
  }
#endif

  for (attempt = 0; attempt < max_attempts; attempt++) {
    if (sa_chrome_ready_on_port(port, 250)) {
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
      use_app_profile
          ? "Chrome did not open debug port %d. Close other Chrome windows and retry."
          : "Chrome did not open debug port %d. Close Chrome using this profile, or use App profile.",
      port);
  return -1;
}
