#include "http.h"

#include "net.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int sa_http_check_url(const char *url, int timeout_ms) {
  char host[256];
  char path[512];
  int port;
  int fd;
  char request[1024];
  char response[512];
  ssize_t n;
  int status = 0;

  if (sa_parse_http_url(url, host, sizeof(host), &port, path, sizeof(path)) != 0) {
    return -1;
  }

  fd = sa_tcp_connect(host, port, timeout_ms);
  if (fd < 0) {
    return -1;
  }

  snprintf(
      request,
      sizeof(request),
      "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n",
      path,
      host);
  if (sa_tcp_send_all(fd, request, strlen(request)) != 0) {
    sa_tcp_close(fd);
    return -1;
  }

  n = sa_tcp_recv_some(fd, response, sizeof(response) - 1, timeout_ms);
  sa_tcp_close(fd);
  if (n <= 0) {
    return -1;
  }

  response[n] = '\0';
  if (sscanf(response, "HTTP/%*s %d", &status) != 1) {
    return -1;
  }

  return (status >= 200 && status < 300) ? 0 : -1;
}
