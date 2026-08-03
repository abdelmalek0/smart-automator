#ifndef SA_COMMON_H
#define SA_COMMON_H

#define SA_DEFAULT_CHROME_PORT 9222

typedef enum {
  SA_CONN_IDLE = 0,
  SA_CONN_CONNECTING,
  SA_CONN_CONNECTED,
  SA_CONN_ERROR
} sa_conn_state_t;

#endif
