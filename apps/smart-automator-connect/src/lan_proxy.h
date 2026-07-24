#ifndef SA_LAN_PROXY_H
#define SA_LAN_PROXY_H

#include <stddef.h>

typedef struct sa_lan_proxy sa_lan_proxy_t;

sa_lan_proxy_t *sa_lan_proxy_start(int listen_port, int target_port, char *err, size_t err_len);
void sa_lan_proxy_stop(sa_lan_proxy_t *proxy);

#endif
