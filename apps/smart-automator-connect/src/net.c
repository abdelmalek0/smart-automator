#define _POSIX_C_SOURCE 200809L
#include "net.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#include <iphlpapi.h>
#include <windows.h>
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

static long long sa_now_ms(void) {
#ifdef _WIN32
  return (long long)GetTickCount64();
#else
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
#endif
}

sa_socket_t sa_tcp_connect(const char *host, int port, int timeout_ms) {
  struct addrinfo hints;
  struct addrinfo *result = NULL;
  struct addrinfo *rp;
  char port_str[16];
  sa_socket_t fd = SA_INVALID_SOCKET;
  int rc;
  long long deadline_ms;
  int remaining_ms;

  if (timeout_ms <= 0) {
    timeout_ms = 1;
  }
  deadline_ms = sa_now_ms() + timeout_ms;

  memset(&hints, 0, sizeof(hints));
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;

  snprintf(port_str, sizeof(port_str), "%d", port);
  /* getaddrinfo is still blocking, but TCP attempts share one deadline envelope. */
  rc = getaddrinfo(host, port_str, &hints, &result);
  if (rc != 0) {
    return SA_INVALID_SOCKET;
  }

  for (rp = result; rp != NULL; rp = rp->ai_next) {
    remaining_ms = (int)(deadline_ms - sa_now_ms());
    if (remaining_ms <= 0) {
      break;
    }

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

      remaining_ms = (int)(deadline_ms - sa_now_ms());
      if (remaining_ms <= 0) {
        sa_tcp_close(fd);
        fd = SA_INVALID_SOCKET;
        break;
      }
      FD_ZERO(&wfds);
      FD_SET(fd, &wfds);
      tv.tv_sec = remaining_ms / 1000;
      tv.tv_usec = (remaining_ms % 1000) * 1000;
      if (select((int)fd + 1, NULL, &wfds, NULL, &tv) > 0 &&
          getsockopt(fd, SOL_SOCKET, SO_ERROR, &so_error, &slen) == 0 && so_error == 0) {
        break;
      }
    }
#else
    /* Only wait when connect is still in progress; hard errors must not burn the deadline. */
    if (WSAGetLastError() == WSAEWOULDBLOCK) {
      fd_set wfds;
      struct timeval tv;
      int so_error = 0;
      int slen = sizeof(so_error);

      remaining_ms = (int)(deadline_ms - sa_now_ms());
      if (remaining_ms <= 0) {
        sa_tcp_close(fd);
        fd = SA_INVALID_SOCKET;
        break;
      }
      FD_ZERO(&wfds);
      FD_SET(fd, &wfds);
      tv.tv_sec = remaining_ms / 1000;
      tv.tv_usec = (remaining_ms % 1000) * 1000;
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
    return SA_INVALID_SOCKET;
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
  return fd;
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

int sa_tcp_set_nonblock(sa_socket_t fd, int enabled) {
  if (fd == SA_INVALID_SOCKET) {
    return -1;
  }
#ifndef _WIN32
  {
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0) {
      return -1;
    }
    if (enabled) {
      return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    }
    return fcntl(fd, F_SETFL, flags & ~O_NONBLOCK);
  }
#else
  {
    u_long mode = enabled ? 1 : 0;
    return ioctlsocket(fd, FIONBIO, &mode) == 0 ? 0 : -1;
  }
#endif
}

int sa_tcp_send_all(sa_socket_t fd, const void *buf, size_t len) {
  return sa_tcp_send_all_deadline(fd, buf, len, 15000);
}

int sa_tcp_send_all_deadline(sa_socket_t fd, const void *buf, size_t len, int timeout_ms) {
  const char *cursor = (const char *)buf;
  size_t remaining = len;
  long long deadline_ms;
  int was_nonblock = 0;

  if (fd == SA_INVALID_SOCKET) {
    return -1;
  }
  if (timeout_ms <= 0) {
    timeout_ms = 1;
  }
  deadline_ms = sa_now_ms() + timeout_ms;

  /* Prefer nonblocking + select so a stalled peer cannot freeze the WSS loop forever. */
#ifndef _WIN32
  {
    int flags = fcntl(fd, F_GETFL, 0);
    was_nonblock = (flags >= 0 && (flags & O_NONBLOCK)) ? 1 : 0;
    if (!was_nonblock) {
      sa_tcp_set_nonblock(fd, 1);
    }
  }
#else
  /* Winsock cannot query FIONBIO. Connect WSS/CDP sockets are nonblocking by
   * design — leave them nonblocking after the deadline send. */
  was_nonblock = 1;
  sa_tcp_set_nonblock(fd, 1);
#endif

  while (remaining > 0) {
    int sent;
    long long now = sa_now_ms();
    int left_ms;
    if (now >= deadline_ms) {
      if (!was_nonblock) {
        sa_tcp_set_nonblock(fd, 0);
      }
      return -1;
    }
    left_ms = (int)(deadline_ms - now);
    sent = send(fd, cursor, (int)remaining, 0);
    if (sent > 0) {
      cursor += sent;
      remaining -= (size_t)sent;
      continue;
    }
#ifdef _WIN32
    if (WSAGetLastError() == WSAEWOULDBLOCK) {
#else
    if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
#endif
      fd_set wfds;
      struct timeval tv;
      FD_ZERO(&wfds);
      FD_SET(fd, &wfds);
      tv.tv_sec = left_ms / 1000;
      tv.tv_usec = (left_ms % 1000) * 1000;
#ifdef _WIN32
      if (select(0, NULL, &wfds, NULL, &tv) <= 0) {
#else
      if (select((int)fd + 1, NULL, &wfds, NULL, &tv) <= 0) {
#endif
        if (!was_nonblock) {
          sa_tcp_set_nonblock(fd, 0);
        }
        return -1;
      }
      continue;
    }
    if (!was_nonblock) {
      sa_tcp_set_nonblock(fd, 0);
    }
    return -1;
  }

  if (!was_nonblock) {
    sa_tcp_set_nonblock(fd, 0);
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
  if (n < 0) {
#ifdef _WIN32
    if (WSAGetLastError() == WSAEWOULDBLOCK) {
      return 0;
    }
#else
    if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
      return 0;
    }
#endif
    return -1;
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

void sa_tcp_shutdown(sa_socket_t fd) {
  if (fd == SA_INVALID_SOCKET) {
    return;
  }
#ifdef _WIN32
  shutdown(fd, SD_BOTH);
#else
  shutdown(fd, SHUT_RDWR);
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
