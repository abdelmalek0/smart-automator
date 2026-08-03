#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif

#include "util.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#ifdef _WIN32
#include <direct.h>
#include <shlobj.h>
#include <windows.h>
#define mkdir(path, mode) _mkdir(path)
#else
#include <dirent.h>
#include <unistd.h>
#endif

char *sa_strdup(const char *s) {
  size_t n;
  char *copy;

  if (s == NULL) {
    return NULL;
  }
  n = strlen(s) + 1;
  copy = malloc(n);
  if (copy != NULL) {
    memcpy(copy, s, n);
  }
  return copy;
}

void sa_sleep_ms(int ms) {
  if (ms <= 0) {
    return;
  }
#ifdef _WIN32
  Sleep((DWORD)ms);
#else
  {
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (long)(ms % 1000) * 1000000L;
    while (nanosleep(&ts, &ts) != 0) {
      if (errno != EINTR) {
        break;
      }
    }
  }
#endif
}

long long sa_monotonic_ms(void) {
#ifdef _WIN32
  return (long long)GetTickCount64();
#else
  {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
  }
#endif
}

void sa_trim(char *s) {
  char *start;
  char *end;

  if (s == NULL || *s == '\0') {
    return;
  }

  start = s;
  while (*start == ' ' || *start == '\t' || *start == '\n' || *start == '\r') {
    start++;
  }

  if (start != s) {
    memmove(s, start, strlen(start) + 1);
  }

  end = s + strlen(s);
  while (end > s && (end[-1] == ' ' || end[-1] == '\t' || end[-1] == '\n' || end[-1] == '\r')) {
    end--;
  }
  *end = '\0';
}

int sa_mkdir_p(const char *path) {
  char *copy;
  char *cursor;
  int rc = 0;

  if (path == NULL || *path == '\0') {
    return -1;
  }

  copy = sa_strdup(path);
  if (copy == NULL) {
    return -1;
  }

  /* Skip drive letter (C:) and root separators so we never call mkdir("C:") /
   * mkdir("") — both fail on Windows and abort directory creation. */
  cursor = copy;
#ifdef _WIN32
  if (((copy[0] >= 'A' && copy[0] <= 'Z') || (copy[0] >= 'a' && copy[0] <= 'z')) &&
      copy[1] == ':') {
    cursor = copy + 2;
  }
#endif
  if (*cursor == '/' || *cursor == '\\') {
    cursor++;
  }

  for (; *cursor != '\0'; cursor++) {
    if (*cursor == '/' || *cursor == '\\') {
      char saved = *cursor;
      *cursor = '\0';
      if (mkdir(copy, 0755) != 0 && errno != EEXIST) {
        rc = -1;
        break;
      }
      *cursor = saved;
    }
  }

  if (rc == 0 && mkdir(copy, 0755) != 0 && errno != EEXIST) {
    rc = -1;
  }

  free(copy);
  return rc;
}

void sa_config_path(char *out, size_t out_len) {
  char exe[1024];
  char *slash;

  if (out == NULL || out_len == 0) {
    return;
  }
  out[0] = '\0';

#ifdef _WIN32
  if (GetModuleFileNameA(NULL, exe, (DWORD)sizeof(exe)) == 0) {
    snprintf(out, out_len, "connect.conf");
    return;
  }
#else
  {
    ssize_t n = readlink("/proc/self/exe", exe, sizeof(exe) - 1);
    if (n < 0) {
      snprintf(out, out_len, "connect.conf");
      return;
    }
    exe[n] = '\0';
  }
#endif

  slash = strrchr(exe, '/');
#ifdef _WIN32
  {
    char *bslash = strrchr(exe, '\\');
    if (bslash != NULL && (slash == NULL || bslash > slash)) {
      slash = bslash;
    }
  }
#endif
  if (slash != NULL) {
    *slash = '\0';
    snprintf(out, out_len, "%s%cconnect.conf", exe,
#ifdef _WIN32
             '\\'
#else
             '/'
#endif
    );
  } else {
    snprintf(out, out_len, "connect.conf");
  }
}

#ifndef SA_DEFAULT_SERVER_URL
#define SA_DEFAULT_SERVER_URL "http://156.67.83.177:6500/"
#endif

int sa_connect_config_load(char *server_url, size_t server_url_len) {
  char path[1024];
  FILE *fp;
  char line[768];
  int found = 0;

  if (server_url == NULL || server_url_len == 0) {
    return -1;
  }
  server_url[0] = '\0';
  sa_config_path(path, sizeof(path));
  fp = fopen(path, "r");
  if (fp != NULL) {
    while (fgets(line, sizeof(line), fp) != NULL) {
      char *eq;
      sa_trim(line);
      if (line[0] == '\0' || line[0] == '#') {
        continue;
      }
      eq = strchr(line, '=');
      if (eq == NULL) {
        continue;
      }
      *eq = '\0';
      sa_trim(line);
      sa_trim(eq + 1);
      if (strcmp(line, "server_url") == 0) {
        snprintf(server_url, server_url_len, "%s", eq + 1);
        found = 1;
        break;
      }
    }
    fclose(fp);
  }
  if (!found || server_url[0] == '\0') {
    snprintf(server_url, server_url_len, "%s", SA_DEFAULT_SERVER_URL);
  }
  return 0;
}

void sa_chrome_profile_path(char *out, size_t out_len) {
#ifdef _WIN32
  char base[MAX_PATH];

  if (SHGetFolderPathA(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, base) != S_OK) {
    snprintf(out, out_len, "smart-automator-chrome");
    return;
  }
  snprintf(out, out_len, "%s\\smart-automator-chrome", base);
#else
  const char *home = getenv("HOME");
  if (home == NULL || *home == '\0') {
    snprintf(out, out_len, ".local/share/smart-automator-chrome");
    return;
  }
  snprintf(out, out_len, "%s/.local/share/smart-automator-chrome", home);
#endif
}

void sa_chrome_fresh_profile_path(char *out, size_t out_len) {
  char base[512];
  sa_chrome_profile_path(base, sizeof(base));
#ifdef _WIN32
  snprintf(out, out_len, "%s\\fresh", base);
#else
  snprintf(out, out_len, "%s/fresh", base);
#endif
}

void sa_path_join(char *out, size_t out_len, const char *a, const char *b) {
  size_t n;
  int needs_sep;

  if (a == NULL || b == NULL) {
  if (out_len > 0) {
    out[0] = '\0';
  }
    return;
  }

  n = strlen(a);
  needs_sep = n > 0 && a[n - 1] != '/' && a[n - 1] != '\\';
#ifdef _WIN32
  if (needs_sep) {
    snprintf(out, out_len, "%s\\%s", a, b);
  } else {
    snprintf(out, out_len, "%s%s", a, b);
  }
#else
  if (needs_sep) {
    snprintf(out, out_len, "%s/%s", a, b);
  } else {
    snprintf(out, out_len, "%s%s", a, b);
  }
#endif
}

#ifdef _WIN32
static int sa_rmdir_r_win(const char *path) {
  char pattern[MAX_PATH + 4];
  WIN32_FIND_DATAA fd;
  HANDLE h;
  int rc = 0;

  if (path == NULL || path[0] == '\0') {
    return -1;
  }

  snprintf(pattern, sizeof(pattern), "%s\\*", path);
  h = FindFirstFileA(pattern, &fd);
  if (h == INVALID_HANDLE_VALUE) {
    return RemoveDirectoryA(path) ? 0 : -1;
  }

  do {
    if (strcmp(fd.cFileName, ".") == 0 || strcmp(fd.cFileName, "..") == 0) {
      continue;
    }
    {
      char child[MAX_PATH + 4];
      sa_path_join(child, sizeof(child), path, fd.cFileName);
      if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
        if (sa_rmdir_r_win(child) != 0) {
          rc = -1;
        }
      } else {
        if (!DeleteFileA(child)) {
          rc = -1;
        }
      }
    }
  } while (FindNextFileA(h, &fd));

  FindClose(h);
  if (!RemoveDirectoryA(path)) {
    rc = -1;
  }
  return rc;
}
#else
#include <dirent.h>

static int sa_rmdir_r_unix(const char *path) {
  DIR *dir;
  struct dirent *entry;
  struct stat st;
  int rc = 0;

  if (path == NULL || path[0] == '\0') {
    return -1;
  }

  dir = opendir(path);
  if (dir == NULL) {
    return rmdir(path) == 0 ? 0 : -1;
  }

  while ((entry = readdir(dir)) != NULL) {
    char child[1024];
    if (entry->d_name[0] == '.' &&
        (entry->d_name[1] == '\0' || (entry->d_name[1] == '.' && entry->d_name[2] == '\0'))) {
      continue;
    }
    sa_path_join(child, sizeof(child), path, entry->d_name);
    if (lstat(child, &st) != 0) {
      rc = -1;
      continue;
    }
    if (S_ISDIR(st.st_mode)) {
      if (sa_rmdir_r_unix(child) != 0) {
        rc = -1;
      }
    } else if (unlink(child) != 0) {
      rc = -1;
    }
  }

  closedir(dir);
  if (rmdir(path) != 0) {
    rc = -1;
  }
  return rc;
}
#endif

int sa_rmdir_r(const char *path) {
#ifdef _WIN32
  return sa_rmdir_r_win(path);
#else
  return sa_rmdir_r_unix(path);
#endif
}

void sa_chrome_clear_profile_locks(const char *profile_dir) {
  static const char *lock_names[] = {
      "SingletonLock",
      "SingletonCookie",
      "SingletonSocket",
      "lockfile",
      NULL,
  };
  size_t i;

  if (profile_dir == NULL || profile_dir[0] == '\0') {
    return;
  }

  for (i = 0; lock_names[i] != NULL; i++) {
    char path[768];
    sa_path_join(path, sizeof(path), profile_dir, lock_names[i]);
#ifdef _WIN32
    DeleteFileA(path);
#else
    unlink(path);
#endif
  }
}

int sa_is_zerotier_ip(const char *host) {
  unsigned int a, b, c, d;
  return host != NULL && sscanf(host, "%u.%u.%u.%u", &a, &b, &c, &d) == 4 && a == 192 && b == 168 && c == 192;
}
