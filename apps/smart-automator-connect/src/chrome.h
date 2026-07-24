#ifndef SA_CHROME_H
#define SA_CHROME_H

#include <stddef.h>

int sa_chrome_start(int port, char *err, size_t err_len);
int sa_chrome_ready(int port);

#endif
