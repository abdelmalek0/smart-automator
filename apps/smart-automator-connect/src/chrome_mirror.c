#include "chrome_mirror.h"

#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

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

static int write_mirror_local_state(const char *mirror_root) {
  char path[640];
  FILE *fp;

  snprintf(path, sizeof(path), "%s/Local State", mirror_root);
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

int sa_chrome_mirror_prepare(
    const char *user_data_dir,
    const char *profile_directory,
    char *mirror_path,
    size_t mirror_path_len,
    char *err,
    size_t err_len) {
  char profile_base[512];
  char mirror_key[256];
  char mirror_root[640];
  char source_profile[768];
  char dest_profile[768];
  char cmd[2048];
  int rc;

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

  snprintf(source_profile, sizeof(source_profile), "%s/%s", profile_base, profile_directory);
  if (!path_is_dir(source_profile)) {
    snprintf(err, err_len, "Chrome profile not found: %s", source_profile);
    return -1;
  }

  sa_chrome_profile_path(mirror_root, sizeof(mirror_root));
  sanitize_mirror_key(profile_base, profile_directory, mirror_key, sizeof(mirror_key));
  snprintf(mirror_path, mirror_path_len, "%s/mirrors/%s", mirror_root, mirror_key);
  snprintf(dest_profile, sizeof(dest_profile), "%s/Default", mirror_path);

  if (sa_mkdir_p(mirror_path) != 0) {
    snprintf(err, err_len, "Could not create Chrome mirror directory.");
    return -1;
  }

  snprintf(cmd, sizeof(cmd), "rm -rf '%s/Default'", mirror_path);
  (void)system(cmd);

  if (access("/usr/bin/rsync", X_OK) == 0) {
    snprintf(
        cmd,
        sizeof(cmd),
        "rsync -a --delete "
        "--exclude 'Cache' --exclude 'Code Cache' --exclude 'GPUCache' --exclude 'Service Worker' "
        "--exclude 'DawnGraphiteCache' --exclude 'DawnWebGPUCache' --exclude 'ShaderCache' "
        "--exclude 'GrShaderCache' --exclude 'blob_storage' --exclude 'BrowserMetrics' "
        "--exclude 'Crashpad' --exclude 'optimization_guide_hint_cache_store' --exclude 'Singleton*' "
        "'%s/' '%s/'",
        source_profile,
        dest_profile);
  } else {
    snprintf(cmd, sizeof(cmd), "cp -a '%s' '%s'", source_profile, dest_profile);
  }

  rc = system(cmd);
  if (rc != 0) {
    snprintf(err, err_len, "Failed to copy Chrome profile into mirror directory.");
    return -1;
  }

  if (write_mirror_local_state(mirror_path) != 0) {
    snprintf(err, err_len, "Failed to prepare mirrored Chrome profile.");
    return -1;
  }

  return 0;
}
