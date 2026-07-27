#include "connections.h"

#include "config.h"
#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifdef _WIN32
#include <direct.h>
#include <io.h>
#include <shlobj.h>
#define access _access
#else
#include <unistd.h>
#endif

void sa_connections_path(char *out, size_t out_len) {
#ifdef _WIN32
  char base[MAX_PATH];

  if (SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, base) != S_OK) {
    snprintf(out, out_len, "connections.conf");
    return;
  }
  snprintf(out, out_len, "%s\\smart-automator\\connections.conf", base);
#else
  const char *home = getenv("HOME");
  if (home == NULL || *home == '\0') {
    snprintf(out, out_len, "connections.conf");
    return;
  }
  snprintf(out, out_len, "%s/.config/smart-automator/connections.conf", home);
#endif
}

const char *sa_mode_label(sa_mode_t mode) {
  switch (mode) {
    case SA_MODE_LAN:
      return "LAN";
    case SA_MODE_REMOTE:
      return "Remote";
    default:
      return "Auto";
  }
}

static void migrate_legacy_config(sa_connections_t *store) {
  sa_config_t legacy;
  sa_connection_t *conn;
  char connections_path[512];

  sa_connections_path(connections_path, sizeof(connections_path));
  if (access(connections_path, F_OK) == 0) {
    return;
  }

  sa_config_load(&legacy);
  if (legacy.host[0] == '\0') {
    return;
  }

  conn = sa_connections_add(store);
  if (conn == NULL) {
    return;
  }

  snprintf(conn->name, sizeof(conn->name), "Gaming PC");
  snprintf(conn->host, sizeof(conn->host), "%s", legacy.host);
  snprintf(conn->user, sizeof(conn->user), "%s", legacy.user);
  snprintf(conn->local_ip, sizeof(conn->local_ip), "%s", legacy.local_ip);
  conn->mode = legacy.mode;
  conn->key_installed = 0;
  sa_connections_save(store);
}

static void parse_connection_field(sa_connection_t *conn, const char *key, const char *value) {
  if (strcmp(key, "id") == 0) {
    snprintf(conn->id, sizeof(conn->id), "%s", value);
  } else if (strcmp(key, "name") == 0) {
    snprintf(conn->name, sizeof(conn->name), "%s", value);
  } else if (strcmp(key, "host") == 0) {
    snprintf(conn->host, sizeof(conn->host), "%s", value);
  } else if (strcmp(key, "user") == 0) {
    snprintf(conn->user, sizeof(conn->user), "%s", value);
  } else if (strcmp(key, "local_ip") == 0) {
    snprintf(conn->local_ip, sizeof(conn->local_ip), "%s", value);
  } else if (strcmp(key, "mode") == 0) {
    if (strcmp(value, "lan") == 0) {
      conn->mode = SA_MODE_LAN;
    } else if (strcmp(value, "remote") == 0) {
      conn->mode = SA_MODE_REMOTE;
    } else {
      conn->mode = SA_MODE_AUTO;
    }
  } else if (strcmp(key, "key_installed") == 0) {
    conn->key_installed = atoi(value) != 0;
  } else if (strcmp(key, "chrome_user_data_dir") == 0) {
    snprintf(conn->chrome_user_data_dir, sizeof(conn->chrome_user_data_dir), "%s", value);
  } else if (strcmp(key, "chrome_profile_directory") == 0) {
    snprintf(conn->chrome_profile_directory, sizeof(conn->chrome_profile_directory), "%s", value);
  } else if (strcmp(key, "fresh_profile") == 0) {
    conn->fresh_profile = atoi(value) != 0;
  }
}

void sa_connections_load(sa_connections_t *store) {
  char path[512];
  FILE *fp;
  char line[512];
  sa_connection_t *current = NULL;

  memset(store, 0, sizeof(*store));
  sa_connections_path(path, sizeof(path));
  fp = fopen(path, "r");
  if (fp == NULL) {
    migrate_legacy_config(store);
    return;
  }

  while (fgets(line, sizeof(line), fp) != NULL) {
    char *eq;
    char *key;
    char *value;

    sa_trim(line);
    if (*line == '\0' || *line == '#') {
      continue;
    }

    if (strcmp(line, "[connection]") == 0) {
      if (store->count < SA_MAX_CONNECTIONS) {
        current = &store->items[store->count++];
        memset(current, 0, sizeof(*current));
        snprintf(current->user, sizeof(current->user), "%s", SA_DEFAULT_SSH_USER);
        current->mode = SA_MODE_AUTO;
      } else {
        current = NULL;
      }
      continue;
    }

    if (current == NULL) {
      continue;
    }

    eq = strchr(line, '=');
    if (eq == NULL) {
      continue;
    }

    *eq = '\0';
    key = line;
    value = eq + 1;
    sa_trim(key);
    sa_trim(value);
    parse_connection_field(current, key, value);
  }

  fclose(fp);

  if (store->count == 0) {
    migrate_legacy_config(store);
  }
}

int sa_connections_save(const sa_connections_t *store) {
  char path[512];
  char dir[512];
  const char *slash;
  FILE *fp;
  int i;

  sa_connections_path(path, sizeof(path));
  snprintf(dir, sizeof(dir), "%s", path);
  slash = strrchr(dir, '/');
#ifdef _WIN32
  {
    const char *bslash = strrchr(dir, '\\');
    if (bslash != NULL && (slash == NULL || bslash > slash)) {
      slash = bslash;
    }
  }
#endif
  if (slash != NULL) {
    *((char *)slash) = '\0';
    sa_mkdir_p(dir);
  }

  fp = fopen(path, "w");
  if (fp == NULL) {
    return -1;
  }

#ifndef _WIN32
  chmod(path, S_IRUSR | S_IWUSR);
#endif

  for (i = 0; i < store->count; i++) {
    const sa_connection_t *conn = &store->items[i];
    const char *mode = "auto";

    if (conn->mode == SA_MODE_LAN) {
      mode = "lan";
    } else if (conn->mode == SA_MODE_REMOTE) {
      mode = "remote";
    }

    fprintf(fp, "[connection]\n");
    fprintf(fp, "id=%s\n", conn->id);
    fprintf(fp, "name=%s\n", conn->name);
    fprintf(fp, "host=%s\n", conn->host);
    fprintf(fp, "user=%s\n", conn->user);
    if (conn->local_ip[0] != '\0') {
      fprintf(fp, "local_ip=%s\n", conn->local_ip);
    }
    fprintf(fp, "mode=%s\n", mode);
    fprintf(fp, "key_installed=%d\n", conn->key_installed ? 1 : 0);
    if (conn->chrome_user_data_dir[0] != '\0') {
      fprintf(fp, "chrome_user_data_dir=%s\n", conn->chrome_user_data_dir);
    }
    if (conn->chrome_profile_directory[0] != '\0') {
      fprintf(fp, "chrome_profile_directory=%s\n", conn->chrome_profile_directory);
    }
    if (conn->fresh_profile) {
      fprintf(fp, "fresh_profile=1\n");
    }
    fprintf(fp, "\n");
  }

  fclose(fp);
  return 0;
}

sa_connection_t *sa_connections_find(sa_connections_t *store, const char *id) {
  int i;

  if (store == NULL || id == NULL) {
    return NULL;
  }

  for (i = 0; i < store->count; i++) {
    if (strcmp(store->items[i].id, id) == 0) {
      return &store->items[i];
    }
  }
  return NULL;
}

sa_connection_t *sa_connections_add(sa_connections_t *store) {
  sa_connection_t *conn;
  int next_id = 1;
  int i;

  if (store == NULL || store->count >= SA_MAX_CONNECTIONS) {
    return NULL;
  }

  for (i = 0; i < store->count; i++) {
    int id = atoi(store->items[i].id);
    if (id >= next_id) {
      next_id = id + 1;
    }
  }

  conn = &store->items[store->count++];
  memset(conn, 0, sizeof(*conn));
  snprintf(conn->id, sizeof(conn->id), "%d", next_id);
  snprintf(conn->user, sizeof(conn->user), "%s", SA_DEFAULT_SSH_USER);
  conn->mode = SA_MODE_AUTO;
  conn->fresh_profile = 1;
  return conn;
}

int sa_connections_remove(sa_connections_t *store, const char *id) {
  int i;
  int found = -1;

  if (store == NULL || id == NULL) {
    return -1;
  }

  for (i = 0; i < store->count; i++) {
    if (strcmp(store->items[i].id, id) == 0) {
      found = i;
      break;
    }
  }

  if (found < 0) {
    return -1;
  }

  for (i = found; i < store->count - 1; i++) {
    store->items[i] = store->items[i + 1];
  }
  store->count--;
  return 0;
}

void sa_connection_to_config(const sa_connection_t *conn, sa_config_t *cfg) {
  sa_config_defaults(cfg);
  if (conn == NULL || cfg == NULL) {
    return;
  }
  snprintf(cfg->host, sizeof(cfg->host), "%s", conn->host);
  snprintf(cfg->user, sizeof(cfg->user), "%s", conn->user);
  snprintf(cfg->local_ip, sizeof(cfg->local_ip), "%s", conn->local_ip);
  cfg->mode = conn->mode;
  snprintf(cfg->chrome_user_data_dir, sizeof(cfg->chrome_user_data_dir), "%s", conn->chrome_user_data_dir);
  snprintf(cfg->chrome_profile_directory, sizeof(cfg->chrome_profile_directory), "%s", conn->chrome_profile_directory);
  cfg->fresh_profile = conn->fresh_profile;
}
