#ifndef SA_SSH_CLI_H
#define SA_SSH_CLI_H

#include <stddef.h>

typedef struct sa_ssh_cli_tunnel sa_ssh_cli_tunnel_t;

sa_ssh_cli_tunnel_t *sa_ssh_cli_start(
    const char *host,
    const char *user,
    const char *password,
    const char *key_path,
    int remote_port,
    int local_chrome_port,
    int *bound_remote_port,
    char *err,
    size_t err_len);

int sa_ssh_cli_verify_cdp(const sa_ssh_cli_tunnel_t *tunnel, int remote_port);
void sa_ssh_cli_stop(sa_ssh_cli_tunnel_t *tunnel);

#endif
