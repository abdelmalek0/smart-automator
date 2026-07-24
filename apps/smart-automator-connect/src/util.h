#ifndef SA_UTIL_H
#define SA_UTIL_H

#include <stddef.h>

char *sa_strdup(const char *s);
void sa_trim(char *s);
int sa_mkdir_p(const char *path);
void sa_config_path(char *out, size_t out_len);
void sa_chrome_profile_path(char *out, size_t out_len);
int sa_is_zerotier_ip(const char *host);

#endif
