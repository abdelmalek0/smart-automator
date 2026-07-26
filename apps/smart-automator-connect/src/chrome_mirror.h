#ifndef SA_CHROME_MIRROR_H
#define SA_CHROME_MIRROR_H

#include <stddef.h>

int sa_chrome_mirror_is_system_dir(const char *user_data_dir);
int sa_chrome_mirror_prepare(
    const char *user_data_dir,
    const char *profile_directory,
    char *mirror_path,
    size_t mirror_path_len,
    char *err,
    size_t err_len);

#endif
