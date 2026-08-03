#include "worker_session.h"

#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <shlobj.h>
#include <windows.h>
#else
#include <sys/stat.h>
#endif

void sa_worker_session_path(char *out, size_t out_len) {
#ifdef _WIN32
  char base[MAX_PATH];
  if (SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, base) != S_OK) {
    snprintf(out, out_len, "worker.conf");
    return;
  }
  snprintf(out, out_len, "%s\\smart-automator\\worker.conf", base);
#else
  const char *home = getenv("HOME");
  if (home == NULL || *home == '\0') {
    snprintf(out, out_len, "worker.conf");
    return;
  }
  snprintf(out, out_len, "%s/.config/smart-automator/worker.conf", home);
#endif
}

void sa_worker_session_clear(sa_worker_session_t *session) {
  if (session == NULL) {
    return;
  }
  memset(session, 0, sizeof(*session));
}

void sa_worker_session_load(sa_worker_session_t *session) {
  char path[512];
  FILE *fp;
  char line[768];

  sa_worker_session_clear(session);
  sa_worker_session_path(path, sizeof(path));
  fp = fopen(path, "r");
  if (fp == NULL) {
    return;
  }
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
      snprintf(session->server_url, sizeof(session->server_url), "%s", eq + 1);
    } else if (strcmp(line, "worker_token") == 0) {
      snprintf(session->worker_token, sizeof(session->worker_token), "%s", eq + 1);
    } else if (strcmp(line, "username") == 0) {
      snprintf(session->username, sizeof(session->username), "%s", eq + 1);
    }
  }
  fclose(fp);
}

int sa_worker_session_save(const sa_worker_session_t *session) {
  char path[512];
  char dir[512];
  FILE *fp;

  if (session == NULL) {
    return -1;
  }
  sa_worker_session_path(path, sizeof(path));
  snprintf(dir, sizeof(dir), "%s", path);
  {
    char *slash = strrchr(dir, '/');
#ifdef _WIN32
    char *bslash = strrchr(dir, '\\');
    if (bslash != NULL && (slash == NULL || bslash > slash)) {
      slash = bslash;
    }
#endif
    if (slash != NULL) {
      *slash = '\0';
      sa_mkdir_p(dir);
    }
  }
  fp = fopen(path, "w");
  if (fp == NULL) {
    return -1;
  }
  fprintf(fp, "server_url=%s\n", session->server_url);
  fprintf(fp, "worker_token=%s\n", session->worker_token);
  fprintf(fp, "username=%s\n", session->username);
  fclose(fp);
#ifndef _WIN32
  chmod(path, 0600);
#endif
  return 0;
}

int sa_worker_session_has_token(const sa_worker_session_t *session) {
  return session != NULL && session->server_url[0] != '\0' && session->worker_token[0] != '\0';
}
