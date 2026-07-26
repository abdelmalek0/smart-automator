#ifndef SA_CONNECTIONS_H
#define SA_CONNECTIONS_H

#include <stddef.h>

#include "common.h"
#include "config.h"

#define SA_MAX_CONNECTIONS 32
#define SA_CONNECTION_ID_LEN 16

typedef struct {
  char id[SA_CONNECTION_ID_LEN];
  char name[128];
  char host[256];
  char user[128];
  char local_ip[64];
  sa_mode_t mode;
  int key_installed;
  char chrome_user_data_dir[512];
  char chrome_profile_directory[128];
} sa_connection_t;

typedef struct {
  sa_connection_t items[SA_MAX_CONNECTIONS];
  int count;
} sa_connections_t;

void sa_connections_path(char *out, size_t out_len);
void sa_connections_load(sa_connections_t *store);
int sa_connections_save(const sa_connections_t *store);
sa_connection_t *sa_connections_find(sa_connections_t *store, const char *id);
sa_connection_t *sa_connections_add(sa_connections_t *store);
int sa_connections_remove(sa_connections_t *store, const char *id);
void sa_connection_to_config(const sa_connection_t *conn, sa_config_t *cfg);
const char *sa_mode_label(sa_mode_t mode);

#endif
