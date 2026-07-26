#ifndef SA_CONFIG_H
#define SA_CONFIG_H

#include "common.h"

typedef struct {
  char host[256];
  char user[128];
  char local_ip[64];
  sa_mode_t mode;
  char chrome_user_data_dir[512];
  char chrome_profile_directory[128];
  int ui_port;
  int chrome_port;
  int cdp_remote_port;
  int cdp_lan_port;
} sa_config_t;

void sa_config_defaults(sa_config_t *cfg);
void sa_config_load(sa_config_t *cfg);
void sa_config_save(const sa_config_t *cfg);

#endif
