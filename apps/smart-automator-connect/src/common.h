#ifndef SA_COMMON_H
#define SA_COMMON_H

#define SA_DEFAULT_SSH_USER "smartprints"
#define SA_DEFAULT_UI_PORT 8400
#define SA_DEFAULT_CHROME_PORT 9222
#define SA_DEFAULT_CDP_REMOTE_PORT 9224
#define SA_DEFAULT_CDP_LAN_PORT 9223

typedef enum {
  SA_MODE_AUTO = 0,
  SA_MODE_LAN,
  SA_MODE_REMOTE
} sa_mode_t;

typedef enum {
  SA_CONN_IDLE = 0,
  SA_CONN_CONNECTING,
  SA_CONN_CONNECTED,
  SA_CONN_ERROR
} sa_conn_state_t;

#endif
