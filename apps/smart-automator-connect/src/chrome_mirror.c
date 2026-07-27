#include "chrome_mirror.h"

#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef _WIN32
#include <spawn.h>
#include <sys/wait.h>
extern char **environ;
#endif

#ifdef _WIN32
#include <shlobj.h>
#include <windows.h>
#endif

static int path_is_dir(const char *path) {
  struct stat st;
  return path != NULL && stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static void sanitize_mirror_key(const char *user_data_dir, const char *profile_directory, char *out, size_t out_len) {
  const char *cursor;
  size_t n = 0;

  for (cursor = user_data_dir; *cursor != '\0' && n + 1 < out_len; cursor++) {
    char c = *cursor;
    if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-') {
      out[n++] = c;
    } else {
      out[n++] = '_';
    }
  }
  if (n + 1 < out_len) {
    out[n++] = '_';
  }
  for (cursor = profile_directory; *cursor != '\0' && n + 1 < out_len; cursor++) {
    char c = *cursor;
    if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-') {
      out[n++] = c;
    } else {
      out[n++] = '_';
    }
  }
  out[n] = '\0';
  if (n == 0) {
    snprintf(out, out_len, "profile");
  }
}

int sa_chrome_mirror_is_system_dir(const char *user_data_dir) {
  char expanded[512];
  char base[512];
  const char *home;
  static const char *suffixes[] = {
      "/.config/google-chrome",
      "/.config/google-chrome-beta",
      "/.config/chromium",
      "/snap/chromium/common/chromium",
      NULL,
  };
  size_t i;

  if (user_data_dir == NULL || user_data_dir[0] == '\0') {
    return 0;
  }

  snprintf(expanded, sizeof(expanded), "%s", user_data_dir);
  home = getenv("HOME");
  if (home != NULL && strncmp(user_data_dir, "~/", 2) == 0) {
    snprintf(expanded, sizeof(expanded), "%s/%s", home, user_data_dir + 2);
  }

#ifdef _WIN32
  {
    char win_chrome[MAX_PATH];
    if (SHGetFolderPathA(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, base) == S_OK) {
      snprintf(win_chrome, sizeof(win_chrome), "%s\\Google\\Chrome\\User Data", base);
      if (_stricmp(expanded, win_chrome) == 0) {
        return 1;
      }
    }
  }
#endif

  for (i = 0; suffixes[i] != NULL; i++) {
    if (home == NULL) {
      continue;
    }
    snprintf(base, sizeof(base), "%s%s", home, suffixes[i]);
    if (strcmp(expanded, base) == 0) {
      return 1;
    }
  }
  return 0;
}

static int mirror_profile_ready(const char *dest_profile) {
  char preferences[768];
  struct stat st;

  sa_path_join(preferences, sizeof(preferences), dest_profile, "Preferences");
  return stat(preferences, &st) == 0 && S_ISREG(st.st_mode);
}

static void copy_profile_error(char *err, size_t err_len, int locked_files) {
  if (locked_files) {
    snprintf(
        err,
        err_len,
        "Could not copy Chrome profile (files may be locked). Close Chrome completely and try again.");
    return;
  }
  snprintf(err, err_len, "Failed to copy Chrome profile into mirror directory.");
}

static int write_mirror_local_state(const char *mirror_root) {
  char path[640];
  FILE *fp;

  sa_path_join(path, sizeof(path), mirror_root, "Local State");
  fp = fopen(path, "w");
  if (fp == NULL) {
    return -1;
  }
  fprintf(
      fp,
      "{\"profile\":{\"info_cache\":{\"Default\":{\"name\":\"Default\"}},\"last_used\":\"Default\"}}\n");
  fclose(fp);
  return 0;
}

static int copy_profile_tree(const char *source_profile, const char *dest_profile, char *err, size_t err_len) {
#ifdef _WIN32
  char cmd[4096];
  STARTUPINFOA si;
  PROCESS_INFORMATION pi;
  DWORD exit_code = 1;

  sa_rmdir_r(dest_profile);
  snprintf(
      cmd,
      sizeof(cmd),
      "robocopy \"%s\" \"%s\" /E /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /nc /ns /np "
      "/XD Cache \"Code Cache\" GPUCache \"Service Worker\" IndexedDB \"File System\" "
      "\"Platform Notifications\" DawnGraphiteCache DawnWebGPUCache ShaderCache GrShaderCache "
      "blob_storage BrowserMetrics Crashpad optimization_guide_hint_cache_store",
      source_profile,
      dest_profile);
  ZeroMemory(&si, sizeof(si));
  si.cb = sizeof(si);
  ZeroMemory(&pi, sizeof(pi));
  if (!CreateProcessA(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
    copy_profile_error(err, err_len, 0);
    return -1;
  }
  WaitForSingleObject(pi.hProcess, INFINITE);
  GetExitCodeProcess(pi.hProcess, &exit_code);
  CloseHandle(pi.hThread);
  CloseHandle(pi.hProcess);
  if (exit_code <= 7) {
    return 0;
  }
  copy_profile_error(err, err_len, exit_code == 8 || exit_code == 9 || exit_code == 10 || exit_code == 11);
  return -1;
#else
  char src_slash[768];
  char dst_slash[768];
  char *argv[32];
  int argc = 0;
  pid_t pid;
  int status;

  sa_rmdir_r(dest_profile);
  snprintf(src_slash, sizeof(src_slash), "%s/", source_profile);
  snprintf(dst_slash, sizeof(dst_slash), "%s/", dest_profile);

  if (access("/usr/bin/rsync", X_OK) == 0) {
    argv[argc++] = "rsync";
    argv[argc++] = "-a";
    argv[argc++] = "--delete";
    argv[argc++] = "--exclude";
    argv[argc++] = "Cache";
    argv[argc++] = "--exclude";
    argv[argc++] = "Code Cache";
    argv[argc++] = "--exclude";
    argv[argc++] = "GPUCache";
    argv[argc++] = "--exclude";
    argv[argc++] = "Service Worker";
    argv[argc++] = "--exclude";
    argv[argc++] = "IndexedDB";
    argv[argc++] = "--exclude";
    argv[argc++] = "File System";
    argv[argc++] = "--exclude";
    argv[argc++] = "Platform Notifications";
    argv[argc++] = "--exclude";
    argv[argc++] = "Singleton*";
    argv[argc++] = src_slash;
    argv[argc++] = dst_slash;
    argv[argc] = NULL;
    if (posix_spawnp(&pid, "rsync", NULL, NULL, argv, environ) != 0) {
      copy_profile_error(err, err_len, 0);
      return -1;
    }
  } else {
    argv[argc++] = "cp";
    argv[argc++] = "-a";
    argv[argc++] = (char *)source_profile;
    argv[argc++] = (char *)dest_profile;
    argv[argc] = NULL;
    if (posix_spawnp(&pid, "cp", NULL, NULL, argv, environ) != 0) {
      copy_profile_error(err, err_len, 0);
      return -1;
    }
  }

  if (waitpid(pid, &status, 0) < 0 || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
    copy_profile_error(err, err_len, 0);
    return -1;
  }
  return 0;
#endif
}

int sa_chrome_mirror_prepare(
    const char *user_data_dir,
    const char *profile_directory,
    int force_remirror,
    char *mirror_path,
    size_t mirror_path_len,
    char *err,
    size_t err_len) {
  char profile_base[512];
  char mirror_key[256];
  char mirror_root[640];
  char source_profile[768];
  char dest_profile[768];

  if (user_data_dir == NULL || user_data_dir[0] == '\0' || profile_directory == NULL || profile_directory[0] == '\0') {
    snprintf(err, err_len, "Chrome profile directory is required.");
    return -1;
  }

  snprintf(profile_base, sizeof(profile_base), "%s", user_data_dir);
  if (strncmp(profile_base, "~/", 2) == 0) {
    const char *home = getenv("HOME");
    if (home != NULL) {
      char tmp[512];
      snprintf(tmp, sizeof(tmp), "%s/%s", home, profile_base + 2);
      snprintf(profile_base, sizeof(profile_base), "%s", tmp);
    }
  }

  sa_path_join(source_profile, sizeof(source_profile), profile_base, profile_directory);
  if (!path_is_dir(source_profile)) {
    snprintf(err, err_len, "Chrome profile not found: %s", source_profile);
    return -1;
  }

  sa_chrome_profile_path(mirror_root, sizeof(mirror_root));
  sanitize_mirror_key(profile_base, profile_directory, mirror_key, sizeof(mirror_key));
  {
    char mirrors_dir[640];
    sa_path_join(mirrors_dir, sizeof(mirrors_dir), mirror_root, "mirrors");
    sa_path_join(mirror_path, mirror_path_len, mirrors_dir, mirror_key);
  }
  sa_path_join(dest_profile, sizeof(dest_profile), mirror_path, "Default");

  if (sa_mkdir_p(mirror_path) != 0) {
    snprintf(err, err_len, "Could not create Chrome mirror directory.");
    return -1;
  }

  if (!force_remirror && mirror_profile_ready(dest_profile)) {
    return 0;
  }

  if (copy_profile_tree(source_profile, dest_profile, err, err_len) != 0) {
    return -1;
  }

  if (write_mirror_local_state(mirror_path) != 0) {
    snprintf(err, err_len, "Failed to prepare mirrored Chrome profile.");
    return -1;
  }

  return 0;
}
