#include "chrome_profiles.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef _WIN32
#include <dirent.h>
#endif

#ifdef _WIN32
#include <shlobj.h>
#include <windows.h>
#endif

typedef struct {
  const char *browser;
  char path[512];
} chrome_root_t;

static int path_is_dir(const char *path) {
  struct stat st;
  return path != NULL && stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static int path_is_file(const char *path) {
  struct stat st;
  return path != NULL && stat(path, &st) == 0 && S_ISREG(st.st_mode);
}

static void join_path(char *out, size_t out_len, const char *a, const char *b) {
  size_t n = strlen(a);
  int needs_sep = n > 0 && a[n - 1] != '/' && a[n - 1] != '\\';

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

static int profile_seen(const sa_chrome_profile_list_t *list, const char *id) {
  int i;
  for (i = 0; i < list->count; i++) {
    if (strcmp(list->items[i].id, id) == 0) {
      return 1;
    }
  }
  return 0;
}

static int profile_has_preferences(const char *root, const char *profile_directory) {
  char profile_path[896];
  char prefs_path[896];
  join_path(profile_path, sizeof(profile_path), root, profile_directory);
  join_path(prefs_path, sizeof(prefs_path), profile_path, "Preferences");
  return path_is_file(prefs_path);
}

static int add_profile(
    sa_chrome_profile_list_t *list,
    const char *browser,
    const char *user_data_dir,
    const char *profile_directory,
    const char *name) {
  char id[SA_CHROME_PROFILE_ID_LEN];
  sa_chrome_profile_t *profile;

  if (!profile_has_preferences(user_data_dir, profile_directory)) {
    return -1;
  }

  if (list->count >= SA_MAX_CHROME_PROFILES) {
    return -1;
  }

  snprintf(id, sizeof(id), "%s|%s", user_data_dir, profile_directory);
  if (profile_seen(list, id)) {
    return 0;
  }

  profile = &list->items[list->count++];
  snprintf(profile->id, sizeof(profile->id), "%s", id);
  snprintf(profile->browser, sizeof(profile->browser), "%s", browser);
  snprintf(profile->user_data_dir, sizeof(profile->user_data_dir), "%s", user_data_dir);
  snprintf(profile->profile_directory, sizeof(profile->profile_directory), "%s", profile_directory);

  if (name != NULL && name[0] != '\0') {
    snprintf(profile->name, sizeof(profile->name), "%s", name);
  } else if (strcmp(profile_directory, "Default") == 0) {
    snprintf(profile->name, sizeof(profile->name), "Default");
  } else {
    snprintf(profile->name, sizeof(profile->name), "%s", profile_directory);
  }
  return 0;
}

static void expand_home(const char *in, char *out, size_t out_len) {
#ifdef _WIN32
  (void)in;
  snprintf(out, out_len, "%s", in);
#else
  const char *home;

  if (in == NULL || strncmp(in, "~/", 2) != 0) {
    snprintf(out, out_len, "%s", in != NULL ? in : "");
    return;
  }

  home = getenv("HOME");
  if (home == NULL || home[0] == '\0') {
    snprintf(out, out_len, "%s", in + 2);
    return;
  }
  snprintf(out, out_len, "%s/%s", home, in + 2);
#endif
}

static void collect_roots(chrome_root_t *roots, int *root_count) {
  int n = 0;

#ifdef _WIN32
  char base[MAX_PATH];
  if (SHGetFolderPathA(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, base) == S_OK) {
    snprintf(roots[n].path, sizeof(roots[n].path), "%s\\Google\\Chrome\\User Data", base);
    roots[n].browser = "Chrome";
    if (path_is_dir(roots[n].path)) {
      n++;
    }
  }
#else
  static const struct {
    const char *browser;
    const char *path;
  } templates[] = {
      {"Chrome", "~/.config/google-chrome"},
      {"Chrome Beta", "~/.config/google-chrome-beta"},
      {"Chromium", "~/.config/chromium"},
      {"Chromium (snap)", "~/snap/chromium/common/chromium"},
  };
  size_t i;

  for (i = 0; i < sizeof(templates) / sizeof(templates[0]); i++) {
    expand_home(templates[i].path, roots[n].path, sizeof(roots[n].path));
    roots[n].browser = templates[i].browser;
    if (path_is_dir(roots[n].path)) {
      n++;
    }
  }
#endif

  *root_count = n;
}

static int extract_json_string_value(const char *start, const char *key, char *out, size_t out_len) {
  char pattern[128];
  const char *pos;
  const char *value;
  size_t i;

  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  pos = strstr(start, pattern);
  if (pos == NULL) {
    return -1;
  }
  pos = strchr(pos + strlen(pattern), ':');
  if (pos == NULL) {
    return -1;
  }
  pos++;
  while (*pos == ' ' || *pos == '\t' || *pos == '\n' || *pos == '\r') {
    pos++;
  }
  if (*pos != '"') {
    return -1;
  }
  pos++;
  value = pos;
  for (i = 0; value[i] != '\0' && value[i] != '"' && i + 1 < out_len; i++) {
    out[i] = value[i];
  }
  out[i] = '\0';
  return out[0] != '\0' ? 0 : -1;
}

static char *load_local_state(const char *root) {
  char local_state_path[640];
  FILE *fp;
  char *buf;
  long size;

  join_path(local_state_path, sizeof(local_state_path), root, "Local State");
  if (!path_is_file(local_state_path)) {
    return NULL;
  }

  fp = fopen(local_state_path, "rb");
  if (fp == NULL) {
    return NULL;
  }

  if (fseek(fp, 0, SEEK_END) != 0) {
    fclose(fp);
    return NULL;
  }
  size = ftell(fp);
  if (size <= 0 || size > 1024 * 1024) {
    fclose(fp);
    return NULL;
  }
  rewind(fp);

  buf = malloc((size_t)size + 1);
  if (buf == NULL) {
    fclose(fp);
    return NULL;
  }
  if (fread(buf, 1, (size_t)size, fp) != (size_t)size) {
    free(buf);
    fclose(fp);
    return NULL;
  }
  fclose(fp);
  buf[size] = '\0';
  return buf;
}

static const char *info_cache_section(const char *buf) {
  const char *profile;
  const char *cache;

  if (buf == NULL) {
    return NULL;
  }

  profile = strstr(buf, "\"profile\"");
  if (profile == NULL) {
    return NULL;
  }

  cache = strstr(profile, "\"info_cache\"");
  if (cache == NULL) {
    return NULL;
  }

  return cache;
}

static int read_profile_name_from_local_state(
    const char *local_state,
    const char *profile_directory,
    char *out,
    size_t out_len) {
  const char *cache;
  char pattern[160];
  const char *entry;
  const char *brace;
  const char *end;
  size_t span;

  out[0] = '\0';
  cache = info_cache_section(local_state);
  if (cache == NULL) {
    return -1;
  }

  snprintf(pattern, sizeof(pattern), "\"%s\"", profile_directory);
  entry = strstr(cache, pattern);
  if (entry == NULL) {
    return -1;
  }

  brace = strchr(entry, '{');
  if (brace == NULL) {
    return -1;
  }

  end = strchr(brace, '}');
  if (end == NULL) {
    return -1;
  }

  span = (size_t)(end - brace + 1);
  if (span >= 4096) {
    return -1;
  }

  {
    char block[4096];
    memcpy(block, brace, span);
    block[span] = '\0';
    return extract_json_string_value(block, "name", out, out_len);
  }
}

static void discover_from_preferences_dirs(
    sa_chrome_profile_list_t *list,
    const char *browser,
    const char *root,
    const char *local_state) {
  char profile_name[128];

#ifndef _WIN32
  DIR *dir;
  struct dirent *entry;

  dir = opendir(root);
  if (dir == NULL) {
    return;
  }

  while ((entry = readdir(dir)) != NULL) {
    if (entry->d_name[0] == '.') {
      continue;
    }
    if (!profile_has_preferences(root, entry->d_name)) {
      continue;
    }

    profile_name[0] = '\0';
    if (local_state != NULL) {
      read_profile_name_from_local_state(local_state, entry->d_name, profile_name, sizeof(profile_name));
    }
    add_profile(list, browser, root, entry->d_name, profile_name);
  }

  closedir(dir);
#else
  char pattern[MAX_PATH + 4];
  WIN32_FIND_DATAA fd;
  HANDLE h;

  snprintf(pattern, sizeof(pattern), "%s\\*", root);
  h = FindFirstFileA(pattern, &fd);
  if (h == INVALID_HANDLE_VALUE) {
    return;
  }

  do {
    if (strcmp(fd.cFileName, ".") == 0 || strcmp(fd.cFileName, "..") == 0) {
      continue;
    }
    if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
      continue;
    }
    if (!profile_has_preferences(root, fd.cFileName)) {
      continue;
    }

    profile_name[0] = '\0';
    if (local_state != NULL) {
      read_profile_name_from_local_state(local_state, fd.cFileName, profile_name, sizeof(profile_name));
    }
    add_profile(list, browser, root, fd.cFileName, profile_name);
  } while (FindNextFileA(h, &fd));

  FindClose(h);
#endif
}

void sa_chrome_profiles_discover(sa_chrome_profile_list_t *list) {
  chrome_root_t roots[8];
  int root_count = 0;
  int i;

  memset(list, 0, sizeof(*list));
  collect_roots(roots, &root_count);

  for (i = 0; i < root_count; i++) {
    char *local_state = load_local_state(roots[i].path);
    discover_from_preferences_dirs(list, roots[i].browser, roots[i].path, local_state);
    free(local_state);
  }
}

int sa_chrome_profiles_find_index(
    const sa_chrome_profile_list_t *list,
    const char *user_data_dir,
    const char *profile_directory) {
  char id[SA_CHROME_PROFILE_ID_LEN];
  int i;

  if (list == NULL) {
    return -1;
  }

  if (user_data_dir == NULL || user_data_dir[0] == '\0') {
    return -1;
  }

  snprintf(id, sizeof(id), "%s|%s", user_data_dir, profile_directory != NULL ? profile_directory : "");
  for (i = 0; i < list->count; i++) {
    if (strcmp(list->items[i].id, id) == 0) {
      return i;
    }
  }
  return -1;
}

const char *sa_chrome_profile_short_label(
    const char *user_data_dir,
    const char *profile_directory,
    const char *profile_name) {
  static char label[160];

  if (user_data_dir == NULL || user_data_dir[0] == '\0') {
    return "App";
  }

  if (profile_name != NULL && profile_name[0] != '\0') {
    snprintf(label, sizeof(label), "%s", profile_name);
  } else if (profile_directory != NULL && profile_directory[0] != '\0') {
    snprintf(label, sizeof(label), "%s", profile_directory);
  } else {
    snprintf(label, sizeof(label), "Chrome");
  }
  return label;
}
