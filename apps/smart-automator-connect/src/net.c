#include "net.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <iphlpapi.h>
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

static int sa_net_ready = 0;

int sa_net_init(void) {
#ifdef _WIN32
  WSADATA wsa;
  if (sa_net_ready) {
    return 0;
  }
  if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
    return -1;
  }
#endif
  sa_net_ready = 1;
  return 0;
}

void sa_net_shutdown(void) {
#ifdef _WIN32
  if (sa_net_ready) {
    WSACleanup();
    sa_net_ready = 0;
  }
#endif
}

int sa_parse_http_url(const char *url, char *host, size_t host_len, int *port, char *path, size_t path_len) {
  const char *cursor;
  const char *slash;
  const char *colon;
  char host_port[320];

  if (url == NULL || strncmp(url, "http://", 7) != 0) {
    return -1;
  }

  cursor = url + 7;
  slash = strchr(cursor, '/');
  if (slash == NULL) {
    snprintf(path, path_len, "/");
    snprintf(host_port, sizeof(host_port), "%s", cursor);
  } else {
    size_t host_part_len = (size_t)(slash - cursor);
    if (host_part_len >= sizeof(host_port)) {
      return -1;
    }
    memcpy(host_port, cursor, host_part_len);
    host_port[host_part_len] = '\0';
    snprintf(path, path_len, "%s", slash);
  }

  colon = strchr(host_port, ':');
  if (colon != NULL) {
    size_t hlen = (size_t)(colon - host_port);
    if (hlen >= host_len) {
      return -1;
    }
    memcpy(host, host_port, hlen);
    host[hlen] = '\0';
    *port = atoi(colon + 1);
  } else {
    snprintf(host, host_len, "%s", host_port);
    *port = 80;
  }

  return 0;
}

int sa_tcp_connect(const char *host, int port, int timeout_ms) {
  struct addrinfo hints;
  struct addrinfo *result = NULL;
  struct addrinfo *rp;
  char port_str[16];
  sa_socket_t fd = SA_INVALID_SOCKET;
  int rc;

  memset(&hints, 0, sizeof(hints));
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;

  snprintf(port_str, sizeof(port_str), "%d", port);
  rc = getaddrinfo(host, port_str, &hints, &result);
  if (rc != 0) {
    return -1;
  }

  for (rp = result; rp != NULL; rp = rp->ai_next) {
    fd = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
    if (fd == SA_INVALID_SOCKET) {
      continue;
    }

#ifndef _WIN32
    {
      int flags = fcntl(fd, F_GETFL, 0);
      if (flags >= 0) {
        fcntl(fd, F_SETFL, flags | O_NONBLOCK);
      }
    }
#else
    {
      u_long mode = 1;
      ioctlsocket(fd, FIONBIO, &mode);
    }
#endif

    if (connect(fd, rp->ai_addr, (int)rp->ai_addrlen) == 0) {
      break;
    }

#ifndef _WIN32
    if (errno == EINPROGRESS) {
      fd_set wfds;
      struct timeval tv;
      int so_error = 0;
      socklen_t slen = sizeof(so_error);

      FD_ZERO(&wfds);
      FD_SET(fd, &wfds);
      tv.tv_sec = timeout_ms / 1000;
      tv.tv_usec = (timeout_ms % 1000) * 1000;
      if (select((int)fd + 1, NULL, &wfds, NULL, &tv) > 0 &&
          getsockopt(fd, SOL_SOCKET, SO_ERROR, &so_error, &slen) == 0 && so_error == 0) {
        break;
      }
    }
#else
    {
      fd_set wfds;
      struct timeval tv;
      int so_error = 0;
      int slen = sizeof(so_error);

      FD_ZERO(&wfds);
      FD_SET(fd, &wfds);
      tv.tv_sec = timeout_ms / 1000;
      tv.tv_usec = (timeout_ms % 1000) * 1000;
      if (select(0, NULL, &wfds, NULL, &tv) > 0 &&
          getsockopt(fd, SOL_SOCKET, SO_ERROR, (char *)&so_error, &slen) == 0 && so_error == 0) {
        break;
      }
    }
#endif

    sa_tcp_close(fd);
    fd = SA_INVALID_SOCKET;
  }

  freeaddrinfo(result);

  if (fd == SA_INVALID_SOCKET) {
    return -1;
  }

#ifndef _WIN32
  {
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags >= 0) {
      fcntl(fd, F_SETFL, flags & ~O_NONBLOCK);
    }
  }
#else
  {
    u_long mode = 0;
    ioctlsocket(fd, FIONBIO, &mode);
  }
#endif

  sa_tcp_set_nodelay(fd);
  return (int)fd;
}

int sa_tcp_set_nodelay(sa_socket_t fd) {
  int one = 1;
  if (fd == SA_INVALID_SOCKET) {
    return -1;
  }
#ifdef _WIN32
  return setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, (const char *)&one, sizeof(one));
#else
  return setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
#endif
}

int sa_tcp_send_all(sa_socket_t fd, const void *buf, size_t len) {
  const char *cursor = (const char *)buf;
  size_t remaining = len;

  while (remaining > 0) {
    int sent = send(fd, cursor, (int)remaining, 0);
    if (sent <= 0) {
      return -1;
    }
    cursor += sent;
    remaining -= (size_t)sent;
  }
  return 0;
}

ssize_t sa_tcp_recv_some(sa_socket_t fd, void *buf, size_t len, int timeout_ms) {
  fd_set rfds;
  struct timeval tv;
  int ready;
  int n;

  FD_ZERO(&rfds);
  FD_SET(fd, &rfds);
  tv.tv_sec = timeout_ms / 1000;
  tv.tv_usec = (timeout_ms % 1000) * 1000;

#ifdef _WIN32
  ready = select(0, &rfds, NULL, NULL, &tv);
#else
  ready = select((int)fd + 1, &rfds, NULL, NULL, &tv);
#endif
  if (ready == 0) {
    return 0; /* timeout — not an error */
  }
  if (ready < 0) {
    return -1;
  }

  n = recv(fd, buf, (int)len, 0);
  if (n == 0) {
    return -1; /* peer closed */
  }
  return n;
}

void sa_tcp_close(sa_socket_t fd) {
  if (fd == SA_INVALID_SOCKET) {
    return;
  }
#ifdef _WIN32
  closesocket(fd);
#else
  close(fd);
#endif
}

int sa_port_in_use(int port) {
  struct sockaddr_in addr;
  sa_socket_t fd;
  int yes = 1;

  fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (fd == SA_INVALID_SOCKET) {
    return 0;
  }

  setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, (const char *)&yes, sizeof(yes));
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons((uint16_t)port);

  if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
    sa_tcp_close(fd);
    return 1;
  }

  sa_tcp_close(fd);
  return 0;
}

int sa_detect_local_ip(const char *remote_host, char *out, size_t out_len) {
  sa_socket_t fd;
  struct sockaddr_in remote;
  struct sockaddr_in local;
  socklen_t local_len = sizeof(local);

  if (remote_host == NULL || out == NULL || out_len == 0) {
    return -1;
  }

  fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (fd == SA_INVALID_SOCKET) {
    return -1;
  }

  memset(&remote, 0, sizeof(remote));
  remote.sin_family = AF_INET;
  remote.sin_port = htons(9);
  if (inet_pton(AF_INET, remote_host, &remote.sin_addr) != 1) {
    sa_tcp_close(fd);
    return -1;
  }

  if (connect(fd, (struct sockaddr *)&remote, sizeof(remote)) != 0) {
    sa_tcp_close(fd);
    return -1;
  }

  if (getsockname(fd, (struct sockaddr *)&local, &local_len) != 0) {
    sa_tcp_close(fd);
    return -1;
  }

  if (inet_ntop(AF_INET, &local.sin_addr, out, (socklen_t)out_len) == NULL) {
    sa_tcp_close(fd);
    return -1;
  }

  sa_tcp_close(fd);
  return 0;
}
