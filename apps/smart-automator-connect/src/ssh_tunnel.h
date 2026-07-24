#ifndef SA_SSH_TUNNEL_H
#define SA_SSH_TUNNEL_H

#include <stddef.h>

typedef struct sa_ssh_tunnel sa_ssh_tunnel_t;

sa_ssh_tunnel_t *sa_ssh_tunnel_start(
    const char *host,
    const char *user,
    const char *password,
    int remote_port,
    int local_chrome_port,
    int *bound_remote_port,
    char *err,
    size_t err_len);
void sa_ssh_tunnel_stop(sa_ssh_tunnel_t *tunnel);
int sa_ssh_tunnel_verify_cdp(sa_ssh_tunnel_t *tunnel, int remote_port);

#endif
