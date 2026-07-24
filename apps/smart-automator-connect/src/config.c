#include "config.h"

#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void sa_config_defaults(sa_config_t *cfg) {
  memset(cfg, 0, sizeof(*cfg));
  snprintf(cfg->user, sizeof(cfg->user), "%s", SA_DEFAULT_SSH_USER);
  cfg->mode = SA_MODE_AUTO;
  cfg->ui_port = SA_DEFAULT_UI_PORT;
  cfg->chrome_port = SA_DEFAULT_CHROME_PORT;
  cfg->cdp_remote_port = SA_DEFAULT_CDP_REMOTE_PORT;
  cfg->cdp_lan_port = SA_DEFAULT_CDP_LAN_PORT;
}

static void parse_line(sa_config_t *cfg, char *line) {
  char *eq;
  char *key;
  char *value;

  sa_trim(line);
  if (*line == '\0' || *line == '#') {
    return;
  }

  eq = strchr(line, '=');
  if (eq == NULL) {
    return;
  }

  *eq = '\0';
  key = line;
  value = eq + 1;
  sa_trim(key);
  sa_trim(value);

  if (strcmp(key, "host") == 0) {
    snprintf(cfg->host, sizeof(cfg->host), "%s", value);
  } else if (strcmp(key, "user") == 0) {
    snprintf(cfg->user, sizeof(cfg->user), "%s", value);
  } else if (strcmp(key, "local_ip") == 0) {
    snprintf(cfg->local_ip, sizeof(cfg->local_ip), "%s", value);
  } else if (strcmp(key, "mode") == 0) {
    if (strcmp(value, "lan") == 0) {
      cfg->mode = SA_MODE_LAN;
    } else if (strcmp(value, "remote") == 0) {
      cfg->mode = SA_MODE_REMOTE;
    } else {
      cfg->mode = SA_MODE_AUTO;
    }
  } else if (strcmp(key, "ui_port") == 0) {
    cfg->ui_port = atoi(value);
  } else if (strcmp(key, "chrome_port") == 0) {
    cfg->chrome_port = atoi(value);
  } else if (strcmp(key, "cdp_remote_port") == 0) {
    cfg->cdp_remote_port = atoi(value);
  } else if (strcmp(key, "cdp_lan_port") == 0) {
    cfg->cdp_lan_port = atoi(value);
  }
}

void sa_config_load(sa_config_t *cfg) {
  char path[512];
  FILE *fp;
  char line[512];

  sa_config_defaults(cfg);
  sa_config_path(path, sizeof(path));
  fp = fopen(path, "r");
  if (fp == NULL) {
    return;
  }

  while (fgets(line, sizeof(line), fp) != NULL) {
    parse_line(cfg, line);
  }
  fclose(fp);
}

void sa_config_save(const sa_config_t *cfg) {
  char path[512];
  char dir[512];
  const char *slash;
  FILE *fp;
  const char *mode = "auto";

  sa_config_path(path, sizeof(path));
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

  if (cfg->mode == SA_MODE_LAN) {
    mode = "lan";
  } else if (cfg->mode == SA_MODE_REMOTE) {
    mode = "remote";
  }

  fp = fopen(path, "w");
  if (fp == NULL) {
    return;
  }

  fprintf(fp, "host=%s\n", cfg->host);
  fprintf(fp, "user=%s\n", cfg->user);
  if (cfg->local_ip[0] != '\0') {
    fprintf(fp, "local_ip=%s\n", cfg->local_ip);
  }
  fprintf(fp, "mode=%s\n", mode);
  fprintf(fp, "ui_port=%d\n", cfg->ui_port);
  fprintf(fp, "chrome_port=%d\n", cfg->chrome_port);
  fprintf(fp, "cdp_remote_port=%d\n", cfg->cdp_remote_port);
  fprintf(fp, "cdp_lan_port=%d\n", cfg->cdp_lan_port);
  fclose(fp);
}
