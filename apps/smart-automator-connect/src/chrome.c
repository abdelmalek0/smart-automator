#include "chrome.h"

#include "chrome_mirror.h"
#include "http.h"
#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifdef _WIN32
#include <windows.h>
#endif

#ifndef _WIN32
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
extern char **environ;
#else
#include <windows.h>
#endif

#ifdef _WIN32
static DWORD g_chrome_pid = 0;
#else
static pid_t g_chrome_pid = -1;
#endif

static void chrome_store_pid(pid_t pid) {
#ifndef _WIN32
  g_chrome_pid = pid;
#else
  (void)pid;
#endif
}

#ifdef _WIN32
static void chrome_store_win_pid(DWORD pid) {
  g_chrome_pid = pid;
}
#endif

static void chrome_kill_tracked(void) {
#ifdef _WIN32
  if (g_chrome_pid != 0) {
    HANDLE proc = OpenProcess(PROCESS_TERMINATE, FALSE, g_chrome_pid);
    if (proc != NULL) {
      TerminateProcess(proc, 1);
      CloseHandle(proc);
    }
    g_chrome_pid = 0;
  }
#else
  int status;
  if (g_chrome_pid > 0) {
    kill(g_chrome_pid, SIGTERM);
    usleep(150000);
    if (waitpid(g_chrome_pid, &status, WNOHANG) <= 0) {
      kill(g_chrome_pid, SIGKILL);
      waitpid(g_chrome_pid, &status, 0);
    }
    g_chrome_pid = -1;
  }
#endif
}

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

static int prepare_launch_profile(
    const char *user_data_dir,
    const char *profile_directory,
    int fresh_profile,
    int wipe,
    char *profile,
    size_t profile_len,
    char *launch_profile_dir,
    size_t launch_profile_dir_len,
    int *max_attempts,
    char *err,
    size_t err_len) {
  const char *profile_dir = profile_directory != NULL ? profile_directory : "";
  int use_app_profile = !fresh_profile && (user_data_dir == NULL || user_data_dir[0] == '\0');

  launch_profile_dir[0] = '\0';

  if (fresh_profile) {
    sa_chrome_fresh_profile_path(profile, profile_len);
    if (wipe) {
      sa_rmdir_r(profile);
    }
    if (sa_mkdir_p(profile) != 0) {
      snprintf(err, err_len, "Could not create Chrome profile directory.");
      return -1;
    }
    *max_attempts = 80;
    return 0;
  }

  if (use_app_profile) {
    sa_chrome_profile_path(profile, profile_len);
    if (wipe) {
      sa_rmdir_r(profile);
    }
    if (sa_mkdir_p(profile) != 0) {
      snprintf(err, err_len, "Could not create Chrome profile directory.");
      return -1;
    }
    *max_attempts = 80;
    return 0;
  }

  if (sa_chrome_mirror_is_system_dir(user_data_dir) && profile_dir[0] != '\0') {
    if (sa_chrome_mirror_prepare(user_data_dir, profile_dir, profile, profile_len, err, err_len) != 0) {
      return -1;
    }
    *max_attempts = 240;
    return 0;
  }

  snprintf(profile, profile_len, "%s", user_data_dir);
  snprintf(launch_profile_dir, launch_profile_dir_len, "%s", profile_dir);
  *max_attempts = 240;
  return 0;
}

#ifndef _WIN32
static void kill_stale_app_profile_chrome(const char *profile) {
  (void)profile;
  chrome_kill_tracked();
}
#endif

void sa_chrome_kill_debug_port(int port, const char *user_data_dir, int fresh_profile) {
  chrome_kill_tracked();
#ifndef _WIN32
  {
    char profile[512];

    if (fresh_profile) {
      sa_chrome_fresh_profile_path(profile, sizeof(profile));
    } else if (user_data_dir != NULL && user_data_dir[0] != '\0') {
      snprintf(profile, sizeof(profile), "%s", user_data_dir);
    } else {
      sa_chrome_profile_path(profile, sizeof(profile));
    }
    (void)profile;
    (void)port;
    usleep(100000);
  }
#else
  (void)user_data_dir;
  (void)fresh_profile;
  (void)port;
  chrome_kill_tracked();
  Sleep(300);
#endif
}

#ifdef _WIN32
static void append_fast_start_flags(char *cmd, size_t cmd_len) {
  static const char *suffix =
      " --disable-extensions"
      " --disable-sync"
      " --disable-background-networking"
      " --disable-default-apps"
      " --disable-component-update"
      " --disable-features=TranslateUI,ChromeWhatsNewUI,AutofillServerCommunication,OptimizationHints"
      " --no-service-autorun"
      " --disable-hang-monitor"
      " --disable-session-crashed-bubble"
      " about:blank";

  if (cmd == NULL || cmd_len == 0) {
    return;
  }
  strncat(cmd, suffix, cmd_len - strlen(cmd) - 1);
}
#endif

static int launch_chrome_process(
    const char *chrome_bin,
    int port,
    const char *profile,
    const char *profile_dir,
    char *err,
    size_t err_len) {
#ifdef _WIN32
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
      profile_dir != NULL && profile_dir[0] != '\0' ? " --profile-directory=\"" : "",
      profile_dir != NULL && profile_dir[0] != '\0' ? profile_dir : "",
      profile_dir != NULL && profile_dir[0] != '\0' ? "\"" : "");
  append_fast_start_flags(cmd, sizeof(cmd));
  ZeroMemory(&si, sizeof(si));
  si.cb = sizeof(si);
  ZeroMemory(&pi, sizeof(pi));
  if (!CreateProcessA(NULL, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
    snprintf(err, err_len, "Failed to start Chrome.");
    return -1;
  }
  CloseHandle(pi.hThread);
  chrome_store_win_pid(pi.dwProcessId);
  CloseHandle(pi.hProcess);
  return 0;
#else
  char port_opt[64];
  char profile_opt[576];
  char profile_dir_opt[192];
  char addr_opt[] = "--remote-debugging-address=127.0.0.1";
  char no_first_run[] = "--no-first-run";
  char no_default_check[] = "--no-default-browser-check";
  char no_crash_bubble[] = "--disable-session-crashed-bubble";
  char remote_allow_origins[] = "--remote-allow-origins=*";
  char disable_extensions[] = "--disable-extensions";
  char disable_sync[] = "--disable-sync";
  char disable_background_networking[] = "--disable-background-networking";
  char disable_default_apps[] = "--disable-default-apps";
  char disable_component_update[] = "--disable-component-update";
  char disable_features[] =
      "--disable-features=TranslateUI,ChromeWhatsNewUI,AutofillServerCommunication,OptimizationHints";
  char no_service_autorun[] = "--no-service-autorun";
  char disable_hang_monitor[] = "--disable-hang-monitor";
  char blank_page[] = "about:blank";
  char *argv[24];
  int argc = 0;
  posix_spawn_file_actions_t actions;
  pid_t pid;

  snprintf(port_opt, sizeof(port_opt), "--remote-debugging-port=%d", port);
  snprintf(profile_opt, sizeof(profile_opt), "--user-data-dir=%s", profile);

  argv[argc++] = (char *)chrome_bin;
  argv[argc++] = port_opt;
  argv[argc++] = addr_opt;
  argv[argc++] = profile_opt;
  if (profile_dir != NULL && profile_dir[0] != '\0') {
    snprintf(profile_dir_opt, sizeof(profile_dir_opt), "--profile-directory=%s", profile_dir);
    argv[argc++] = profile_dir_opt;
  }
  argv[argc++] = no_first_run;
  argv[argc++] = no_default_check;
  argv[argc++] = no_crash_bubble;
  argv[argc++] = remote_allow_origins;
  argv[argc++] = disable_extensions;
  argv[argc++] = disable_sync;
  argv[argc++] = disable_background_networking;
  argv[argc++] = disable_default_apps;
  argv[argc++] = disable_component_update;
  argv[argc++] = disable_features;
  argv[argc++] = no_service_autorun;
  argv[argc++] = disable_hang_monitor;
  argv[argc++] = blank_page;
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
  chrome_store_pid(pid);
  return 0;
#endif
}

static int wait_for_chrome_ready(
    int port,
    int max_attempts,
    int use_app_profile,
    char *err,
    size_t err_len) {
  int attempt;
  int poll_ms = 100;
  int timeout_ms = 150;

  for (attempt = 0; attempt < max_attempts; attempt++) {
    if (sa_chrome_ready_on_port(port, timeout_ms)) {
      return 0;
    }
#ifdef _WIN32
    Sleep(poll_ms);
#else
    usleep((useconds_t)poll_ms * 1000);
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

static int chrome_start_internal(
    int port,
    const char *user_data_dir,
    const char *profile_directory,
    int fresh_profile,
    int wipe,
    int force_relaunch,
    char *err,
    size_t err_len) {
  char chrome_bin[512];
  char profile[512];
  char launch_profile_dir[128];
  const char *profile_dir_ptr;
  int max_attempts = 60;
  int use_app_profile;

  if (!force_relaunch && sa_chrome_ready(port)) {
    return 0;
  }

  if (find_chrome(chrome_bin, sizeof(chrome_bin)) != 0) {
    snprintf(
        err,
        err_len,
        "Chrome binary not found. Install Google Chrome or Chromium.");
    return -1;
  }

  use_app_profile = !fresh_profile && (user_data_dir == NULL || user_data_dir[0] == '\0');
  if (prepare_launch_profile(
          user_data_dir,
          profile_directory,
          fresh_profile,
          wipe,
          profile,
          sizeof(profile),
          launch_profile_dir,
          sizeof(launch_profile_dir),
          &max_attempts,
          err,
          err_len) != 0) {
    return -1;
  }

  profile_dir_ptr = launch_profile_dir[0] != '\0' ? launch_profile_dir : "";

#ifndef _WIN32
  if (use_app_profile || fresh_profile) {
    kill_stale_app_profile_chrome(profile);
  }
#endif
  sa_chrome_clear_profile_locks(profile);

  if (launch_chrome_process(chrome_bin, port, profile, profile_dir_ptr, err, err_len) != 0) {
    return -1;
  }

  return wait_for_chrome_ready(port, max_attempts, use_app_profile || fresh_profile, err, err_len);
}

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
    int fresh_profile,
    char *err,
    size_t err_len) {
  return chrome_start_internal(
      port, user_data_dir, profile_directory, fresh_profile, fresh_profile ? 1 : 0, 0, err, err_len);
}

static int wait_for_port_closed(int port, int max_ms) {
  int elapsed = 0;
  int step_ms = 50;

  while (elapsed < max_ms) {
    if (!sa_chrome_ready_on_port(port, step_ms)) {
      return 0;
    }
#ifdef _WIN32
    Sleep(step_ms);
#else
    usleep((useconds_t)step_ms * 1000);
#endif
    elapsed += step_ms;
  }
  return -1;
}

int sa_chrome_reset_profile(
    int port,
    const char *user_data_dir,
    const char *profile_directory,
    int fresh_profile,
    char *err,
    size_t err_len) {
  sa_chrome_kill_debug_port(port, user_data_dir, fresh_profile);
  if (wait_for_port_closed(port, 3000) != 0) {
    sa_chrome_kill_debug_port(port, user_data_dir, fresh_profile);
    if (wait_for_port_closed(port, 1500) != 0) {
      snprintf(err, err_len, "Chrome did not release debug port %d.", port);
      return -1;
    }
  }

  return chrome_start_internal(port, user_data_dir, profile_directory, fresh_profile, 1, 1, err, err_len);
}
