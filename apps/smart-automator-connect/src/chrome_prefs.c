#include "chrome_prefs.h"

#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SA_PREFS_MAX_SIZE (512 * 1024)

static const char *FRESH_PREFS_JSON =
    "{\"credentials_enable_service\":false,\"profile\":{\"password_manager_enabled\":false,"
    "\"password_manager_leak_detection\":false}}";

static int replace_json_bool(char *json, const char *key, int value) {
  char pattern[128];
  char replacement[128];
  char *cursor;
  const char *truth = value ? "true" : "false";

  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  cursor = json;
  while ((cursor = strstr(cursor, pattern)) != NULL) {
    char *colon;
    char *value_start;
    char *value_end;

    colon = strchr(cursor + strlen(pattern), ':');
    if (colon == NULL) {
      break;
    }
    value_start = colon + 1;
    while (*value_start == ' ' || *value_start == '\t') {
      value_start++;
    }
    value_end = value_start;
    while (*value_end != '\0' && *value_end != ',' && *value_end != '}' && *value_end != '\n') {
      value_end++;
    }
    snprintf(replacement, sizeof(replacement), "%s", truth);
    if ((size_t)(value_end - value_start) != strlen(replacement) ||
        strncmp(value_start, replacement, strlen(replacement)) != 0) {
      size_t tail_len = strlen(value_end);
      size_t replacement_len = strlen(replacement);
      size_t old_len = (size_t)(value_end - value_start);
      size_t json_len = strlen(json);
      ptrdiff_t offset = value_start - json;

      if (replacement_len > old_len) {
        if (json_len + (replacement_len - old_len) + 1 > SA_PREFS_MAX_SIZE) {
          return -1;
        }
        memmove(value_start + replacement_len, value_end, tail_len + 1);
      } else if (replacement_len < old_len) {
        memmove(value_start + replacement_len, value_end, tail_len + 1);
      }
      memcpy(value_start, replacement, replacement_len);
    }
    cursor = value_start + strlen(truth);
  }
  return 0;
}

static int inject_profile_prefs(char *json, size_t json_len) {
  char *profile;
  char *brace;
  const char *insert =
      "\"password_manager_enabled\":false,\"password_manager_leak_detection\":false,";

  if (strstr(json, "\"password_manager_leak_detection\"") != NULL) {
    return 0;
  }

  profile = strstr(json, "\"profile\"");
  if (profile == NULL) {
  append_profile:
    if (json_len + 128 >= SA_PREFS_MAX_SIZE) {
      return -1;
    }
  strcat(json, ",\"profile\":{\"password_manager_enabled\":false,"
                "\"password_manager_leak_detection\":false}");
    return 0;
  }

  brace = strchr(profile, '{');
  if (brace == NULL) {
    goto append_profile;
  }
  brace++;
  if ((size_t)(strlen(json) + strlen(insert) + 1) >= SA_PREFS_MAX_SIZE) {
    return -1;
  }
  memmove(brace + strlen(insert), brace, strlen(brace) + 1);
  memcpy(brace, insert, strlen(insert));
  return 0;
}

static int patch_preferences_file(const char *prefs_path) {
  FILE *handle;
  long file_size;
  char *json;
  size_t read_size;

  handle = fopen(prefs_path, "rb");
  if (handle == NULL) {
    return -1;
  }
  if (fseek(handle, 0, SEEK_END) != 0) {
    fclose(handle);
    return -1;
  }
  file_size = ftell(handle);
  if (file_size < 0 || file_size >= (long)SA_PREFS_MAX_SIZE) {
    fclose(handle);
    return -1;
  }
  if (fseek(handle, 0, SEEK_SET) != 0) {
    fclose(handle);
    return -1;
  }

  json = calloc((size_t)file_size + 256, 1);
  if (json == NULL) {
    fclose(handle);
    return -1;
  }
  read_size = fread(json, 1, (size_t)file_size, handle);
  fclose(handle);
  if (read_size != (size_t)file_size) {
    free(json);
    return -1;
  }

  if (json[0] == '\0') {
    snprintf(json, (size_t)file_size + 256, "%s", FRESH_PREFS_JSON);
  } else {
    if (strstr(json, "\"credentials_enable_service\"") == NULL) {
      size_t len = strlen(json);
      if (len > 0 && json[len - 1] == '}') {
        json[len - 1] = '\0';
        strcat(json, ",\"credentials_enable_service\":false}");
      } else {
        strcat(json, ",\"credentials_enable_service\":false");
      }
    }
    (void)replace_json_bool(json, "credentials_enable_service", 0);
    (void)replace_json_bool(json, "password_manager_enabled", 0);
    (void)replace_json_bool(json, "password_manager_leak_detection", 0);
    if (inject_profile_prefs(json, strlen(json)) != 0) {
      free(json);
      return -1;
    }
  }

  handle = fopen(prefs_path, "wb");
  if (handle == NULL) {
    free(json);
    return -1;
  }
  fputs(json, handle);
  fclose(handle);
  free(json);
  return 0;
}

int sa_chrome_apply_automation_prefs(const char *profile_dir) {
  char prefs_path[896];
  FILE *handle;

  if (profile_dir == NULL || profile_dir[0] == '\0') {
    return -1;
  }
  if (sa_mkdir_p(profile_dir) != 0) {
    return -1;
  }
  sa_path_join(prefs_path, sizeof(prefs_path), profile_dir, "Preferences");

  handle = fopen(prefs_path, "rb");
  if (handle == NULL) {
    handle = fopen(prefs_path, "wb");
    if (handle == NULL) {
      return -1;
    }
    fputs(FRESH_PREFS_JSON, handle);
    fclose(handle);
    return 0;
  }
  fclose(handle);
  return patch_preferences_file(prefs_path);
}
