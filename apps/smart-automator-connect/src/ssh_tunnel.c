#include "ssh_tunnel.h"

#include "net.h"

#include <libssh/libssh.h>

#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <process.h>
#include <windows.h>
#else
#include <pthread.h>
#include <unistd.h>
#endif

struct sa_ssh_tunnel {
  atomic_int running;
  atomic_int relay_count;
  ssh_session session;
  int local_chrome_port;
  int remote_port;
#ifdef _WIN32
  HANDLE thread;
  CRITICAL_SECTION session_lock;
#else
  pthread_t thread;
  pthread_mutex_t session_lock;
#endif
  int thread_started;
};

static void session_lock_init(sa_ssh_tunnel_t *tunnel) {
#ifdef _WIN32
  InitializeCriticalSection(&tunnel->session_lock);
#else
  pthread_mutex_init(&tunnel->session_lock, NULL);
#endif
}

static void session_lock_destroy(sa_ssh_tunnel_t *tunnel) {
#ifdef _WIN32
  DeleteCriticalSection(&tunnel->session_lock);
#else
  pthread_mutex_destroy(&tunnel->session_lock);
#endif
}

static void session_lock(sa_ssh_tunnel_t *tunnel) {
#ifdef _WIN32
  EnterCriticalSection(&tunnel->session_lock);
#else
  pthread_mutex_lock(&tunnel->session_lock);
#endif
}

static void session_unlock(sa_ssh_tunnel_t *tunnel) {
#ifdef _WIN32
  LeaveCriticalSection(&tunnel->session_lock);
#else
  pthread_mutex_unlock(&tunnel->session_lock);
#endif
}

typedef struct {
  sa_ssh_tunnel_t *tunnel;
  ssh_session session;
  ssh_channel channel;
  int local_chrome_port;
} ssh_relay_args_t;

static void relay_ssh_to_tcp(ssh_session session, ssh_channel channel, int local_fd) {
  char buf[8192];
  fd_set rfds;
  struct timeval tv;

  (void)session;

  while (1) {
    FD_ZERO(&rfds);
    FD_SET(local_fd, &rfds);

    tv.tv_sec = 1;
    tv.tv_usec = 0;

#ifdef _WIN32
    if (select(0, &rfds, NULL, NULL, &tv) > 0 && FD_ISSET(local_fd, &rfds)) {
#else
    if (select((int)local_fd + 1, &rfds, NULL, NULL, &tv) > 0 && FD_ISSET(local_fd, &rfds)) {
#endif
      ssize_t n = recv(local_fd, buf, sizeof(buf), 0);
      if (n <= 0) {
        break;
      }
      if (ssh_channel_write(channel, buf, (uint32_t)n) < 0) {
        break;
      }
    }

    {
      int n = ssh_channel_read_timeout(channel, buf, sizeof(buf), 0, 500);
      if (n < 0) {
        break;
      }
      if (n > 0 && sa_tcp_send_all(local_fd, buf, (size_t)n) != 0) {
        break;
      }
    }
  }

  ssh_channel_send_eof(channel);
  ssh_channel_close(channel);
  ssh_channel_free(channel);
  sa_tcp_close(local_fd);
}

#ifdef _WIN32
static unsigned __stdcall ssh_relay_thread(void *arg) {
#else
static void *ssh_relay_thread(void *arg) {
#endif
  ssh_relay_args_t *args = (ssh_relay_args_t *)arg;
  int local_fd = sa_tcp_connect("127.0.0.1", args->local_chrome_port, 3000);

  if (local_fd >= 0) {
    relay_ssh_to_tcp(args->session, args->channel, local_fd);
  } else {
    ssh_channel_close(args->channel);
    ssh_channel_free(args->channel);
  }

  atomic_fetch_sub(&args->tunnel->relay_count, 1);
  free(args);
#ifdef _WIN32
  return 0;
#else
  return NULL;
#endif
}

#ifdef _WIN32
static unsigned __stdcall ssh_tunnel_main(void *arg) {
#else
static void *ssh_tunnel_main(void *arg) {
#endif
  sa_ssh_tunnel_t *tunnel = (sa_ssh_tunnel_t *)arg;
  int port;

  while (atomic_load(&tunnel->running)) {
    ssh_channel channel;

    session_lock(tunnel);
    channel = ssh_channel_accept_forward(tunnel->session, 1000, &port);
    session_unlock(tunnel);
    ssh_relay_args_t *args;

    if (channel == NULL) {
      if (!atomic_load(&tunnel->running)) {
        break;
      }
      continue;
    }

    args = calloc(1, sizeof(*args));
    if (args == NULL) {
      ssh_channel_close(channel);
      ssh_channel_free(channel);
      continue;
    }

    args->tunnel = tunnel;
    args->session = tunnel->session;
    args->channel = channel;
    args->local_chrome_port = tunnel->local_chrome_port;
    atomic_fetch_add(&tunnel->relay_count, 1);

#ifdef _WIN32
    {
      HANDLE relay = (HANDLE)_beginthreadex(NULL, 0, ssh_relay_thread, args, 0, NULL);
      if (relay == NULL) {
        atomic_fetch_sub(&tunnel->relay_count, 1);
        ssh_channel_close(channel);
        ssh_channel_free(channel);
        free(args);
      } else {
        CloseHandle(relay);
      }
    }
#else
    {
      pthread_t tid;
      pthread_attr_t attr;
      pthread_attr_init(&attr);
      pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
      if (pthread_create(&tid, &attr, ssh_relay_thread, args) != 0) {
        atomic_fetch_sub(&tunnel->relay_count, 1);
        ssh_channel_close(channel);
        ssh_channel_free(channel);
        free(args);
      }
      pthread_attr_destroy(&attr);
    }
#endif
  }

#ifdef _WIN32
  return 0;
#else
  return NULL;
#endif
}

static ssh_session connect_and_auth(const char *host, const char *user, const char *password, char *err, size_t err_len) {
  ssh_session session = ssh_new();
  int port = 22;
  int rc;

  if (session == NULL) {
    snprintf(err, err_len, "Could not allocate SSH session.");
    return NULL;
  }

  ssh_options_set(session, SSH_OPTIONS_HOST, host);
  ssh_options_set(session, SSH_OPTIONS_USER, user);
  ssh_options_set(session, SSH_OPTIONS_PORT, &port);

  if (ssh_connect(session) != SSH_OK) {
    snprintf(err, err_len, "SSH connect failed: %s", ssh_get_error(session));
    ssh_free(session);
    return NULL;
  }

  rc = ssh_userauth_password(session, NULL, password);
  if (rc != SSH_AUTH_SUCCESS) {
    snprintf(err, err_len, "SSH authentication failed.");
    ssh_disconnect(session);
    ssh_free(session);
    return NULL;
  }

  return session;
}

static void ssh_tunnel_wait_relays(sa_ssh_tunnel_t *tunnel) {
  int i;

  for (i = 0; i < 200; i++) {
    if (atomic_load(&tunnel->relay_count) <= 0) {
      return;
    }
#ifdef _WIN32
    Sleep(50);
#else
    usleep(50000);
#endif
  }
}

sa_ssh_tunnel_t *sa_ssh_tunnel_start(
    const char *host,
    const char *user,
    const char *password,
    int remote_port,
    int local_chrome_port,
    int *bound_remote_port,
    char *err,
    size_t err_len) {
  sa_ssh_tunnel_t *tunnel = calloc(1, sizeof(*tunnel));
  int bound = 0;
  int rc;

  if (tunnel == NULL) {
    snprintf(err, err_len, "Out of memory.");
    return NULL;
  }

  tunnel->local_chrome_port = local_chrome_port;
  tunnel->remote_port = remote_port;
  atomic_store(&tunnel->running, 1);
  atomic_store(&tunnel->relay_count, 0);
  session_lock_init(tunnel);

  tunnel->session = connect_and_auth(host, user, password, err, err_len);
  if (tunnel->session == NULL) {
    session_lock_destroy(tunnel);
    free(tunnel);
    return NULL;
  }

  session_lock(tunnel);
  rc = ssh_channel_listen_forward(tunnel->session, NULL, remote_port, &bound);
  session_unlock(tunnel);
  if (rc != SSH_OK) {
    snprintf(err, err_len, "SSH reverse forward failed: %s", ssh_get_error(tunnel->session));
    ssh_disconnect(tunnel->session);
    ssh_free(tunnel->session);
    session_lock_destroy(tunnel);
    free(tunnel);
    return NULL;
  }

  if (bound_remote_port != NULL) {
    *bound_remote_port = bound > 0 ? bound : remote_port;
  }

#ifdef _WIN32
  tunnel->thread = (HANDLE)_beginthreadex(NULL, 0, ssh_tunnel_main, tunnel, 0, NULL);
  if (tunnel->thread == NULL) {
    sa_ssh_tunnel_stop(tunnel);
    snprintf(err, err_len, "Failed to start SSH tunnel thread.");
    return NULL;
  }
  tunnel->thread_started = 1;
#else
  if (pthread_create(&tunnel->thread, NULL, ssh_tunnel_main, tunnel) != 0) {
    sa_ssh_tunnel_stop(tunnel);
    snprintf(err, err_len, "Failed to start SSH tunnel thread.");
    return NULL;
  }
  tunnel->thread_started = 1;
#endif

  return tunnel;
}

int sa_ssh_tunnel_verify_cdp(sa_ssh_tunnel_t *tunnel, int remote_port) {
  ssh_channel channel;
  char request[256];
  char response[512];
  int n;

  if (tunnel == NULL || tunnel->session == NULL) {
    return -1;
  }

  channel = ssh_channel_new(tunnel->session);
  if (channel == NULL) {
    return -1;
  }

  session_lock(tunnel);
  if (ssh_channel_open_forward(channel, "127.0.0.1", remote_port, "127.0.0.1", 0) != SSH_OK) {
    session_unlock(tunnel);
    ssh_channel_free(channel);
    return -1;
  }
  session_unlock(tunnel);

  snprintf(
      request,
      sizeof(request),
      "GET /json/version HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");

  session_lock(tunnel);
  if (ssh_channel_write(channel, request, (uint32_t)strlen(request)) < 0) {
    session_unlock(tunnel);
    ssh_channel_close(channel);
    ssh_channel_free(channel);
    return -1;
  }
  session_unlock(tunnel);

#ifdef _WIN32
  Sleep(100);
#else
  usleep(200000);
#endif

  session_lock(tunnel);
  n = ssh_channel_read_timeout(channel, response, sizeof(response) - 1, 0, 3000);
  ssh_channel_send_eof(channel);
  ssh_channel_close(channel);
  ssh_channel_free(channel);
  session_unlock(tunnel);

  if (n <= 0) {
    return -1;
  }

  response[n] = '\0';
  return strstr(response, "200") != NULL ? 0 : -1;
}

void sa_ssh_tunnel_stop(sa_ssh_tunnel_t *tunnel) {
  if (tunnel == NULL) {
    return;
  }

  atomic_store(&tunnel->running, 0);

  if (tunnel->thread_started) {
#ifdef _WIN32
    if (tunnel->thread != NULL) {
      WaitForSingleObject(tunnel->thread, 5000);
      CloseHandle(tunnel->thread);
      tunnel->thread = NULL;
    }
#else
    pthread_join(tunnel->thread, NULL);
#endif
    tunnel->thread_started = 0;
  }

  ssh_tunnel_wait_relays(tunnel);

  if (tunnel->session != NULL) {
    session_lock(tunnel);
    ssh_disconnect(tunnel->session);
    ssh_free(tunnel->session);
    tunnel->session = NULL;
    session_unlock(tunnel);
  }

  session_lock_destroy(tunnel);
  free(tunnel);
}
