#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif

#include "http.h"

#include "net.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif

int sa_http_check_url(const char *url, int timeout_ms) {
  char host[256];
  char path[512];
  int port;
  sa_socket_t fd;
  char request[1024];
  char response[1024];
  size_t response_len = 0;
  int status = 0;
  long long deadline_ms;
  long long now_ms;

#ifdef _WIN32
  deadline_ms = (long long)GetTickCount64() + (timeout_ms > 0 ? timeout_ms : 1000);
#else
  {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    deadline_ms = (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000 + (timeout_ms > 0 ? timeout_ms : 1000);
  }
#endif

  if (sa_parse_http_url(url, host, sizeof(host), &port, path, sizeof(path)) != 0) {
    return -1;
  }

  fd = sa_tcp_connect(host, port, timeout_ms > 0 ? timeout_ms : 1000);
  if (fd == SA_INVALID_SOCKET) {
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

  response[0] = '\0';
  while (response_len + 1 < sizeof(response)) {
    int remaining;
    ssize_t n;
#ifdef _WIN32
    now_ms = (long long)GetTickCount64();
#else
    {
      struct timespec ts;
      clock_gettime(CLOCK_MONOTONIC, &ts);
      now_ms = (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
    }
#endif
    remaining = (int)(deadline_ms - now_ms);
    if (remaining <= 0) {
      break;
    }
    n = sa_tcp_recv_some(fd, response + response_len, sizeof(response) - response_len - 1, remaining);
    if (n < 0) {
      break; /* peer closed or error */
    }
    if (n == 0) {
      continue; /* timeout slice */
    }
    response_len += (size_t)n;
    response[response_len] = '\0';
    if (strstr(response, "\r\n") != NULL) {
      break;
    }
  }
  sa_tcp_close(fd);

  if (response_len == 0) {
    return -1;
  }
  if (sscanf(response, "HTTP/%*s %d", &status) != 1) {
    return -1;
  }

  return (status >= 200 && status < 300) ? 0 : -1;
}
