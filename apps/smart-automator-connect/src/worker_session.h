#ifndef SA_WORKER_SESSION_H
#define SA_WORKER_SESSION_H

#include <stddef.h>

typedef struct {
  char server_url[512];
  char worker_token[256];
  char username[128];
} sa_worker_session_t;

void sa_worker_session_path(char *out, size_t out_len);
void sa_worker_session_clear(sa_worker_session_t *session);
void sa_worker_session_load(sa_worker_session_t *session);
int sa_worker_session_save(const sa_worker_session_t *session);
int sa_worker_session_has_token(const sa_worker_session_t *session);

#endif
