#ifndef SA_WORKER_WS_H
#define SA_WORKER_WS_H

#include <stddef.h>

typedef struct sa_worker_ws sa_worker_ws_t;

typedef void (*sa_worker_ws_text_cb)(void *userdata, const char *json);
typedef void (*sa_worker_ws_status_cb)(void *userdata, const char *status);

sa_worker_ws_t *sa_worker_ws_create(void);
void sa_worker_ws_destroy(sa_worker_ws_t *ws);

int sa_worker_ws_connect(
    sa_worker_ws_t *ws,
    const char *server_url,
    const char *token,
    char *err,
    size_t err_len);
void sa_worker_ws_close(sa_worker_ws_t *ws);
int sa_worker_ws_is_connected(const sa_worker_ws_t *ws);

int sa_worker_ws_send_text(sa_worker_ws_t *ws, const char *text);
int sa_worker_ws_send_binary(sa_worker_ws_t *ws, const void *data, size_t len);

/* Poll once: dispatch text callbacks; pump CDP mux sockets. Returns 0 ok, -1 closed/error. */
int sa_worker_ws_poll(
    sa_worker_ws_t *ws,
    sa_worker_ws_text_cb on_text,
    void *userdata,
    int timeout_ms);

void sa_worker_ws_set_chrome_port(sa_worker_ws_t *ws, int chrome_port);
void sa_worker_ws_close_cdp_channels(sa_worker_ws_t *ws);

#endif
