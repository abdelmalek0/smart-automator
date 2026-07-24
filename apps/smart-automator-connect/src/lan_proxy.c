#include "lan_proxy.h"

#include "net.h"

#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <process.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <pthread.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

struct sa_lan_proxy {
  atomic_int running;
  int listen_port;
  int target_port;
#ifdef _WIN32
  HANDLE thread;
  SOCKET listen_fd;
#else
  pthread_t thread;
  int listen_fd;
#endif
};

typedef struct {
  sa_socket_t client_fd;
  int target_port;
} relay_args_t;

static void relay_pair(sa_socket_t a, sa_socket_t b) {
  char buf[8192];
  fd_set rfds;

  while (1) {
    FD_ZERO(&rfds);
    FD_SET(a, &rfds);
    FD_SET(b, &rfds);

#ifdef _WIN32
    if (select(0, &rfds, NULL, NULL, NULL) <= 0) {
      break;
    }
#else
    if (select((int)((a > b) ? a : b) + 1, &rfds, NULL, NULL, NULL) <= 0) {
      break;
    }
#endif

    if (FD_ISSET(a, &rfds)) {
      ssize_t n = recv(a, buf, sizeof(buf), 0);
      if (n <= 0 || sa_tcp_send_all(b, buf, (size_t)n) != 0) {
        break;
      }
    }
    if (FD_ISSET(b, &rfds)) {
      ssize_t n = recv(b, buf, sizeof(buf), 0);
      if (n <= 0 || sa_tcp_send_all(a, buf, (size_t)n) != 0) {
        break;
      }
    }
  }

  sa_tcp_close(a);
  sa_tcp_close(b);
}

#ifdef _WIN32
static unsigned __stdcall relay_thread(void *arg) {
#else
static void *relay_thread(void *arg) {
#endif
  relay_args_t *args = (relay_args_t *)arg;
  sa_socket_t upstream = sa_tcp_connect("127.0.0.1", args->target_port, 3000);

  if (upstream != SA_INVALID_SOCKET) {
    relay_pair(args->client_fd, upstream);
  } else {
    sa_tcp_close(args->client_fd);
  }

  free(args);
#ifdef _WIN32
  return 0;
#else
  return NULL;
#endif
}

#ifdef _WIN32
static unsigned __stdcall lan_proxy_main(void *arg) {
#else
static void *lan_proxy_main(void *arg) {
#endif
  sa_lan_proxy_t *proxy = (sa_lan_proxy_t *)arg;
  struct sockaddr_in addr;
  int yes = 1;

  proxy->listen_fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (proxy->listen_fd == SA_INVALID_SOCKET) {
    atomic_store(&proxy->running, 0);
#ifdef _WIN32
    return 0;
#else
    return NULL;
#endif
  }

  setsockopt(proxy->listen_fd, SOL_SOCKET, SO_REUSEADDR, (const char *)&yes, sizeof(yes));
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons((uint16_t)proxy->listen_port);

  if (bind(proxy->listen_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0 ||
      listen(proxy->listen_fd, 16) != 0) {
    sa_tcp_close(proxy->listen_fd);
    proxy->listen_fd = SA_INVALID_SOCKET;
    atomic_store(&proxy->running, 0);
#ifdef _WIN32
    return 0;
#else
    return NULL;
#endif
  }

  while (atomic_load(&proxy->running)) {
    struct sockaddr_in client_addr;
    socklen_t client_len = sizeof(client_addr);
    sa_socket_t client_fd = accept(proxy->listen_fd, (struct sockaddr *)&client_addr, &client_len);
    relay_args_t *args;

    if (client_fd == SA_INVALID_SOCKET) {
      continue;
    }

    args = calloc(1, sizeof(*args));
    if (args == NULL) {
      sa_tcp_close(client_fd);
      continue;
    }
    args->client_fd = client_fd;
    args->target_port = proxy->target_port;

#ifdef _WIN32
    _beginthreadex(NULL, 0, relay_thread, args, 0, NULL);
#else
    {
      pthread_t tid;
      pthread_attr_t attr;
      pthread_attr_init(&attr);
      pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
      pthread_create(&tid, &attr, relay_thread, args);
      pthread_attr_destroy(&attr);
    }
#endif
  }

  if (proxy->listen_fd != SA_INVALID_SOCKET) {
    sa_tcp_close(proxy->listen_fd);
    proxy->listen_fd = SA_INVALID_SOCKET;
  }

#ifdef _WIN32
  return 0;
#else
  return NULL;
#endif
}

sa_lan_proxy_t *sa_lan_proxy_start(int listen_port, int target_port, char *err, size_t err_len) {
  sa_lan_proxy_t *proxy = calloc(1, sizeof(*proxy));

  if (proxy == NULL) {
    snprintf(err, err_len, "Out of memory.");
    return NULL;
  }

  proxy->listen_port = listen_port;
  proxy->target_port = target_port;
  atomic_store(&proxy->running, 1);

#ifdef _WIN32
  proxy->thread = (HANDLE)_beginthreadex(NULL, 0, lan_proxy_main, proxy, 0, NULL);
  if (proxy->thread == NULL) {
    free(proxy);
    snprintf(err, err_len, "Failed to start LAN proxy thread.");
    return NULL;
  }
#else
  if (pthread_create(&proxy->thread, NULL, lan_proxy_main, proxy) != 0) {
    free(proxy);
    snprintf(err, err_len, "Failed to start LAN proxy thread.");
    return NULL;
  }
#endif

  return proxy;
}

void sa_lan_proxy_stop(sa_lan_proxy_t *proxy) {
  if (proxy == NULL) {
    return;
  }

  atomic_store(&proxy->running, 0);
  if (proxy->listen_fd != SA_INVALID_SOCKET) {
    sa_tcp_close(proxy->listen_fd);
    proxy->listen_fd = SA_INVALID_SOCKET;
  }

#ifdef _WIN32
  if (proxy->thread != NULL) {
    WaitForSingleObject(proxy->thread, 5000);
    CloseHandle(proxy->thread);
  }
#else
  pthread_join(proxy->thread, NULL);
#endif

  free(proxy);
}
