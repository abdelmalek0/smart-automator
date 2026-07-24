#ifndef SA_SSH_KEYS_H
#define SA_SSH_KEYS_H

#include <stddef.h>

void sa_ssh_key_priv_path(char *out, size_t out_len);
void sa_ssh_key_pub_path(char *out, size_t out_len);
int sa_ssh_key_ensure_exists(char *err, size_t err_len);
int sa_ssh_key_test_auth(const char *host, const char *user, char *err, size_t err_len);
int sa_ssh_key_install(const char *host, const char *user, const char *password, char *err, size_t err_len);

#endif
