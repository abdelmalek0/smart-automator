#ifndef SA_CHROME_H
#define SA_CHROME_H

#include <stddef.h>

int sa_chrome_start(
    int port,
    const char *user_data_dir,
    const char *profile_directory,
    int fresh_profile,
    char *err,
    size_t err_len);
int sa_chrome_reset_profile(
    int port,
    const char *user_data_dir,
    const char *profile_directory,
    int fresh_profile,
    char *err,
    size_t err_len);
void sa_chrome_kill_debug_port(int port, const char *user_data_dir, int fresh_profile);
int sa_chrome_ready_on_port(int port, int timeout_ms);
int sa_chrome_ready(int port);
/* Actual CDP port from DevToolsActivePort after a successful sa_chrome_start. */
int sa_chrome_debug_port(void);
/* Cooperative cancel for in-flight sa_chrome_start readiness waits. */
void sa_chrome_request_cancel(void);
void sa_chrome_clear_cancel(void);

#endif
