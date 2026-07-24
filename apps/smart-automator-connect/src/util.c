#include "util.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifdef _WIN32
#include <direct.h>
#include <shlobj.h>
#define mkdir(path, mode) _mkdir(path)
#else
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

  for (cursor = copy + 1; *cursor != '\0'; cursor++) {
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
#ifdef _WIN32
  char base[MAX_PATH];

  if (SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, base) != S_OK) {
    snprintf(out, out_len, "connect.conf");
    return;
  }
  snprintf(out, out_len, "%s\\smart-automator\\connect.conf", base);
#else
  const char *home = getenv("HOME");
  if (home == NULL || *home == '\0') {
    snprintf(out, out_len, "connect.conf");
    return;
  }
  snprintf(out, out_len, "%s/.config/smart-automator/connect.conf", home);
#endif
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

int sa_is_zerotier_ip(const char *host) {
  unsigned int a, b, c, d;
  return host != NULL && sscanf(host, "%u.%u.%u.%u", &a, &b, &c, &d) == 4 && a == 192 && b == 168 && c == 192;
}
