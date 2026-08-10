#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif

#include "chrome.h"
#include "chrome_prefs.h"

#include "chrome_mirror.h"
#include "http.h"
#include "net.h"
#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifdef _WIN32
#include <shlobj.h>
#include <windows.h>
#endif

#ifndef _WIN32
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdatomic.h>
#include <sys/wait.h>
extern char **environ;
#endif

#ifdef _WIN32
static DWORD g_chrome_pid = 0;
static volatile LONG g_chrome_cancel = 0;
#else
static pid_t g_chrome_pid = -1;
static atomic_int g_chrome_cancel = 0;
#endif
static int g_chrome_debug_port = 0;
static char g_chrome_user_data[512];

void sa_chrome_request_cancel(void) {
#ifdef _WIN32
  InterlockedExchange(&g_chrome_cancel, 1);
#else
  atomic_store(&g_chrome_cancel, 1);
#endif
}

void sa_chrome_clear_cancel(void) {
#ifdef _WIN32
  InterlockedExchange(&g_chrome_cancel, 0);
#else
  atomic_store(&g_chrome_cancel, 0);
#endif
}

static int chrome_cancel_requested(void) {
#ifdef _WIN32
  return InterlockedCompareExchange(&g_chrome_cancel, 0, 0) != 0;
#else
  return atomic_load(&g_chrome_cancel) != 0;
#endif
}

static long long chrome_now_ms(void) {
#ifdef _WIN32
  return (long long)GetTickCount64();
#else
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
#endif
}

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
    sa_sleep_ms(150);
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
  char local_appdata[MAX_PATH];
  char local_chrome[MAX_PATH];
  size_t i;

  for (i = 0; i < sizeof(candidates) / sizeof(candidates[0]); i++) {
    if (GetFileAttributesA(candidates[i]) != INVALID_FILE_ATTRIBUTES) {
      snprintf(out, out_len, "%s", candidates[i]);
      return 0;
    }
  }
  if (SHGetFolderPathA(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, local_appdata) == S_OK) {
    snprintf(
        local_chrome,
        sizeof(local_chrome),
        "%s\\Google\\Chrome\\Application\\chrome.exe",
        local_appdata);
    if (GetFileAttributesA(local_chrome) != INVALID_FILE_ATTRIBUTES) {
      snprintf(out, out_len, "%s", local_chrome);
      return 0;
    }
  }
  if (out_len > 0 && SearchPathA(NULL, "chrome.exe", NULL, (DWORD)out_len, out, NULL) > 0) {
    return 0;
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
    int *max_wait_ms,
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
    *max_wait_ms = 90000;
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
    *max_wait_ms = 90000;
    return 0;
  }

  if (sa_chrome_mirror_is_system_dir(user_data_dir) && profile_dir[0] != '\0') {
    if (sa_chrome_mirror_prepare(user_data_dir, profile_dir, wipe, profile, profile_len, err, err_len) != 0) {
      return -1;
    }
    *max_wait_ms = 120000;
    return 0;
  }

  snprintf(profile, profile_len, "%s", user_data_dir);
  snprintf(launch_profile_dir, launch_profile_dir_len, "%s", profile_dir);
  *max_wait_ms = 120000;
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
    sa_sleep_ms(100);
  }
#else
  (void)user_data_dir;
  (void)fresh_profile;
  (void)port;
  chrome_kill_tracked();
  sa_sleep_ms(300);
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
      " --disable-features=TranslateUI,ChromeWhatsNewUI,AutofillServerCommunication,OptimizationHints,PasswordLeakDetection,PasswordManagerLeakDetection"
      " --disable-save-password-bubble"
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
      "--disable-features=TranslateUI,ChromeWhatsNewUI,AutofillServerCommunication,OptimizationHints,PasswordLeakDetection,PasswordManagerLeakDetection";
  char disable_save_password_bubble[] = "--disable-save-password-bubble";
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
  argv[argc++] = disable_save_password_bubble;
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

static void clear_devtools_active_port(const char *user_data_dir) {
  char path[768];
  if (user_data_dir == NULL || user_data_dir[0] == '\0') {
    return;
  }
  sa_path_join(path, sizeof(path), user_data_dir, "DevToolsActivePort");
#ifdef _WIN32
  DeleteFileA(path);
#else
  unlink(path);
#endif
}

static int read_devtools_active_port(const char *user_data_dir, int *out_port) {
  char path[768];
  FILE *fp;
  char line[64];
  int port = 0;

  if (out_port == NULL || user_data_dir == NULL || user_data_dir[0] == '\0') {
    return -1;
  }
  sa_path_join(path, sizeof(path), user_data_dir, "DevToolsActivePort");
  fp = fopen(path, "r");
  if (fp == NULL) {
    return -1;
  }
  if (fgets(line, sizeof(line), fp) == NULL) {
    fclose(fp);
    return -1;
  }
  fclose(fp);
  port = atoi(line);
  if (port <= 0 || port > 65535) {
    return -1;
  }
  *out_port = port;
  return 0;
}

static int wait_for_chrome_ready(
    int preferred_port,
    const char *user_data_dir,
    int max_wait_ms,
    int use_app_profile,
    char *err,
    size_t err_len) {
  int poll_ms = 100;
  int detected_port = 0;
  int last_seen_port = 0;
  long long deadline_ms;

  (void)preferred_port;
  if (max_wait_ms < 1000) {
    max_wait_ms = 1000;
  }
  g_chrome_debug_port = 0;
  deadline_ms = chrome_now_ms() + max_wait_ms;

  /* Chrome writes DevToolsActivePort once the debug server is bound. Prefer that
   * over a fixed port: --remote-debugging-port=0 picks a free port, and a busy
   * fixed port can leave the UI up with no CDP. Require a real /json/version
   * response — a TCP accept alone is not enough for browser.ready. */
  while (chrome_now_ms() < deadline_ms) {
    int remaining;
    int check_ms;
    if (chrome_cancel_requested()) {
      snprintf(err, err_len, "Chrome start cancelled");
      return -1;
    }
    detected_port = 0;
    remaining = (int)(deadline_ms - chrome_now_ms());
    if (remaining <= 0) {
      break;
    }
    check_ms = remaining < 400 ? remaining : 400;
    if (read_devtools_active_port(user_data_dir, &detected_port) == 0) {
      last_seen_port = detected_port;
      if (sa_chrome_ready_on_port(detected_port, check_ms)) {
        g_chrome_debug_port = detected_port;
        return 0;
      }
    }
    {
      int sleep_ms = poll_ms < remaining ? poll_ms : remaining;
      sa_sleep_ms(sleep_ms);
    }
  }

  if (chrome_cancel_requested()) {
    snprintf(err, err_len, "Chrome start cancelled");
    return -1;
  }
  if (last_seen_port > 0) {
    snprintf(
        err,
        err_len,
        "Chrome wrote DevToolsActivePort (%d) but CDP did not answer within %ds.",
        last_seen_port,
        (max_wait_ms + 999) / 1000);
  } else {
    snprintf(
        err,
        err_len,
        use_app_profile
            ? "Chrome did not write DevToolsActivePort within %ds. Close other Chrome windows and retry."
            : "Chrome did not write DevToolsActivePort within %ds. Close Chrome using this profile, or use App profile.",
        (max_wait_ms + 999) / 1000);
  }
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
  int max_wait_ms = 90000;
  int use_app_profile;

  (void)port;
  (void)force_relaunch;

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
          &max_wait_ms,
          err,
          err_len) != 0) {
    return -1;
  }

  profile_dir_ptr = launch_profile_dir[0] != '\0' ? launch_profile_dir : "";

  /* Always kill our previous tracked Chrome so remote debugging is not skipped. */
  chrome_kill_tracked();
#ifndef _WIN32
  if (use_app_profile || fresh_profile) {
    kill_stale_app_profile_chrome(profile);
  }
#endif
  sa_chrome_clear_profile_locks(profile);
  clear_devtools_active_port(profile);
  snprintf(g_chrome_user_data, sizeof(g_chrome_user_data), "%s", profile);
  g_chrome_debug_port = 0;

  {
    char prefs_profile_dir[768];
    if (profile_dir_ptr[0] != '\0') {
      sa_path_join(prefs_profile_dir, sizeof(prefs_profile_dir), profile, profile_dir_ptr);
    } else {
      sa_path_join(prefs_profile_dir, sizeof(prefs_profile_dir), profile, "Default");
    }
    (void)sa_chrome_apply_automation_prefs(prefs_profile_dir);
  }

  /* Port 0 = let Chrome pick a free ephemeral port and write it to DevToolsActivePort.
   * Avoids binding failures when 9222 is already taken (UI up, no CDP). */
  if (launch_chrome_process(chrome_bin, 0, profile, profile_dir_ptr, err, err_len) != 0) {
    return -1;
  }

  return wait_for_chrome_ready(
      0, profile, max_wait_ms, use_app_profile || fresh_profile, err, err_len);
}

int sa_chrome_ready_on_port(int port, int timeout_ms) {
  char url[128];
  snprintf(url, sizeof(url), "http://127.0.0.1:%d/json/version", port);
  return sa_http_check_url(url, timeout_ms) == 0 ? 1 : 0;
}

int sa_chrome_ready(int port) {
  return sa_chrome_ready_on_port(port, 500);
}

int sa_chrome_debug_port(void) {
  return g_chrome_debug_port > 0 ? g_chrome_debug_port : 0;
}

int sa_chrome_start(
    int port,
    const char *user_data_dir,
    const char *profile_directory,
    int fresh_profile,
    char *err,
    size_t err_len) {
  /* Do not clear cancel here — runtime arms clear only when intentionally
   * starting. Clearing here would wipe an in-flight stop/cancel. */
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
    sa_sleep_ms(step_ms);
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
