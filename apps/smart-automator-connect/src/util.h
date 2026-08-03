#ifndef SA_UTIL_H
#define SA_UTIL_H

#include <stddef.h>

char *sa_strdup(const char *s);
void sa_trim(char *s);
int sa_mkdir_p(const char *path);
void sa_config_path(char *out, size_t out_len);
void sa_chrome_profile_path(char *out, size_t out_len);
void sa_chrome_fresh_profile_path(char *out, size_t out_len);
void sa_path_join(char *out, size_t out_len, const char *a, const char *b);
int sa_rmdir_r(const char *path);
void sa_chrome_clear_profile_locks(const char *profile_dir);
int sa_is_zerotier_ip(const char *host);
/* Cross-platform sleep used by readiness/reconnect loops (avoids usleep). */
void sa_sleep_ms(int ms);
/* Monotonic milliseconds for deadlines (CLOCK_MONOTONIC / GetTickCount64). */
long long sa_monotonic_ms(void);

#endif
