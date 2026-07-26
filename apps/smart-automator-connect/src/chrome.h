#ifndef SA_CHROME_H
#define SA_CHROME_H

#include <stddef.h>

int sa_chrome_start(
    int port,
    const char *user_data_dir,
    const char *profile_directory,
    char *err,
    size_t err_len);
int sa_chrome_ready_on_port(int port, int timeout_ms);
int sa_chrome_ready(int port);

#endif
