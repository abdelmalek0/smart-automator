#include "mode.h"

#include "http.h"
#include "util.h"

#include <stdio.h>

sa_mode_t sa_mode_resolve(const sa_config_t *cfg) {
  char url[512];

  if (cfg->mode == SA_MODE_LAN || cfg->mode == SA_MODE_REMOTE) {
    return cfg->mode;
  }

  if (sa_is_zerotier_ip(cfg->host)) {
    return SA_MODE_REMOTE;
  }

  snprintf(url, sizeof(url), "http://%s:%d/api/auth/setup", cfg->host, cfg->ui_port);
  if (sa_http_check_url(url, 2000) == 0) {
    return SA_MODE_LAN;
  }

  return SA_MODE_REMOTE;
}
