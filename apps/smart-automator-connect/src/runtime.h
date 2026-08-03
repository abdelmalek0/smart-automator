#ifndef SA_RUNTIME_H
#define SA_RUNTIME_H

#include "common.h"
#include "worker_session.h"

typedef struct sa_runtime sa_runtime_t;

typedef void (*sa_status_cb)(
    void *userdata,
    sa_conn_state_t state,
    const char *status);

sa_runtime_t *sa_runtime_create(sa_status_cb cb, void *userdata);
void sa_runtime_destroy(sa_runtime_t *rt);
void sa_runtime_connect(sa_runtime_t *rt, const sa_worker_session_t *session);
void sa_runtime_disconnect(sa_runtime_t *rt);
int sa_runtime_is_busy(const sa_runtime_t *rt);
int sa_runtime_is_connected(const sa_runtime_t *rt);

#endif
