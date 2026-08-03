#include "worker_ws.h"

#include "net.h"

#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <openssl/evp.h>
#include <openssl/ssl.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/select.h>
#include <unistd.h>
#endif

#define SA_MUX_FLAG_DATA 0
#define SA_MUX_FLAG_OPEN 1
#define SA_MUX_FLAG_CLOSE 2
#define SA_MAX_CDP_CHANNELS 32
/* CDP /json and protocol messages routinely exceed 64KiB; reject only truly huge frames. */
#define SA_WS_RX_SIZE (1024 * 1024)
#define SA_WS_FRAME_MAX (768 * 1024)
#define SA_WS_MASK_SCRATCH (64 * 1024)
#define SA_CDP_READ_CHUNK (48 * 1024)

typedef struct {
  int conn_id;
  sa_socket_t fd;
  int in_use;
  volatile int connecting;
  unsigned char *pending;
  size_t pending_len;
  size_t pending_cap;
} sa_cdp_channel_t;

struct sa_worker_ws {
  sa_socket_t fd;
  SSL_CTX *ctx;
  SSL *ssl;
  int connected;
  int chrome_port;
  unsigned char rx[SA_WS_RX_SIZE];
  size_t rx_len;
  unsigned char mask_scratch[SA_WS_MASK_SCRATCH];
  sa_cdp_channel_t channels[SA_MAX_CDP_CHANNELS];
};

static void ensure_ssl(void) {
  static int ready = 0;
  if (ready) {
    return;
  }
  SSL_library_init();
  SSL_load_error_strings();
  OpenSSL_add_all_algorithms();
  ready = 1;
}

static int parse_server_url(
    const char *url,
    int *is_tls,
    char *host,
    size_t host_len,
    int *port,
    char *base_path,
    size_t base_path_len) {
  const char *cursor;
  const char *slash;
  const char *colon;
  char host_port[320];

  if (strncmp(url, "https://", 8) == 0) {
    *is_tls = 1;
    cursor = url + 8;
    *port = 443;
  } else if (strncmp(url, "http://", 7) == 0) {
    *is_tls = 0;
    cursor = url + 7;
    *port = 80;
  } else if (strncmp(url, "wss://", 6) == 0) {
    *is_tls = 1;
    cursor = url + 6;
    *port = 443;
  } else if (strncmp(url, "ws://", 5) == 0) {
    *is_tls = 0;
    cursor = url + 5;
    *port = 80;
  } else {
    return -1;
  }

  slash = strchr(cursor, '/');
  if (slash == NULL) {
    base_path[0] = '\0';
    snprintf(host_port, sizeof(host_port), "%s", cursor);
  } else {
    size_t n = (size_t)(slash - cursor);
    if (n >= sizeof(host_port)) {
      return -1;
    }
    memcpy(host_port, cursor, n);
    host_port[n] = '\0';
    snprintf(base_path, base_path_len, "%s", slash);
    /* strip trailing slash from base path for joining */
    {
      size_t blen = strlen(base_path);
      while (blen > 0 && base_path[blen - 1] == '/') {
        base_path[--blen] = '\0';
      }
    }
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
  }
  return 0;
}

static int io_write_all(sa_worker_ws_t *ws, const void *buf, size_t len) {
  const unsigned char *p = (const unsigned char *)buf;
  size_t left = len;
  while (left > 0) {
    int n;
    if (ws->ssl) {
      n = SSL_write(ws->ssl, p, (int)left);
      if (n <= 0) {
        return -1;
      }
    } else {
      if (sa_tcp_send_all(ws->fd, p, left) != 0) {
        return -1;
      }
      return 0;
    }
    p += (size_t)n;
    left -= (size_t)n;
  }
  return 0;
}

static int io_read_some(sa_worker_ws_t *ws, void *buf, size_t len, int timeout_ms) {
  if (ws->ssl) {
    /* Prefer draining already-decoded TLS data without waiting on select. */
    if (SSL_pending(ws->ssl) > 0) {
      int n = SSL_read(ws->ssl, buf, (int)len);
      if (n <= 0) {
        int err = SSL_get_error(ws->ssl, n);
        if (err == SSL_ERROR_WANT_READ || err == SSL_ERROR_WANT_WRITE) {
          return 0;
        }
        return -1;
      }
      return n;
    }

    fd_set rfds;
    struct timeval tv;
    int nfds;
    FD_ZERO(&rfds);
    FD_SET(ws->fd, &rfds);
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    nfds = select((int)ws->fd + 1, &rfds, NULL, NULL, &tv);
    if (nfds == 0) {
      return 0;
    }
    if (nfds < 0) {
      return -1;
    }
    if (FD_ISSET(ws->fd, &rfds)) {
      int n = SSL_read(ws->ssl, buf, (int)len);
      if (n <= 0) {
        int err = SSL_get_error(ws->ssl, n);
        if (err == SSL_ERROR_WANT_READ || err == SSL_ERROR_WANT_WRITE) {
          return 0;
        }
        return -1;
      }
      return n;
    }
    return 0;
  }
  return (int)sa_tcp_recv_some(ws->fd, buf, len, timeout_ms);
}

static void b64_encode(const unsigned char *in, size_t in_len, char *out, size_t out_len) {
  if (out_len == 0) {
    return;
  }
  out[0] = '\0';
  if (EVP_EncodeBlock((unsigned char *)out, in, (int)in_len) < 0) {
    out[0] = '\0';
  }
  (void)out_len;
}

static int ws_send_frame(sa_worker_ws_t *ws, int opcode, const void *payload, size_t len) {
  unsigned char header[14];
  size_t header_len = 0;
  unsigned char mask[4];
  unsigned char *masked = NULL;
  unsigned char *scratch = NULL;
  int scratch_owned = 0;
  size_t i;
  int rc;

  header[0] = (unsigned char)(0x80 | (opcode & 0x0f));
  if (len < 126) {
    header[1] = (unsigned char)(0x80 | len);
    header_len = 2;
  } else if (len <= 0xffff) {
    header[1] = (unsigned char)(0x80 | 126);
    header[2] = (unsigned char)((len >> 8) & 0xff);
    header[3] = (unsigned char)(len & 0xff);
    header_len = 4;
  } else if (len <= SA_WS_FRAME_MAX) {
    header[1] = (unsigned char)(0x80 | 127);
    header[2] = 0;
    header[3] = 0;
    header[4] = 0;
    header[5] = 0;
    header[6] = (unsigned char)((len >> 24) & 0xff);
    header[7] = (unsigned char)((len >> 16) & 0xff);
    header[8] = (unsigned char)((len >> 8) & 0xff);
    header[9] = (unsigned char)(len & 0xff);
    header_len = 10;
  } else {
    return -1;
  }

  mask[0] = (unsigned char)(rand() & 0xff);
  mask[1] = (unsigned char)(rand() & 0xff);
  mask[2] = (unsigned char)(rand() & 0xff);
  mask[3] = (unsigned char)(rand() & 0xff);
  memcpy(header + header_len, mask, 4);
  header_len += 4;

  if (io_write_all(ws, header, header_len) != 0) {
    return -1;
  }
  if (len == 0) {
    return 0;
  }
  if (len <= SA_WS_MASK_SCRATCH) {
    scratch = ws->mask_scratch;
  } else {
    scratch = (unsigned char *)malloc(len);
    if (scratch == NULL) {
      return -1;
    }
    scratch_owned = 1;
  }
  masked = scratch;
  for (i = 0; i < len; i++) {
    masked[i] = ((const unsigned char *)payload)[i] ^ mask[i % 4];
  }
  rc = io_write_all(ws, masked, len);
  if (scratch_owned) {
    free(scratch);
  }
  return rc;
}

static int pack_mux(unsigned char *out, size_t out_len, unsigned int conn_id, unsigned char flags, const void *payload, size_t payload_len) {
  if (out_len < 9 + payload_len) {
    return -1;
  }
  out[0] = (unsigned char)((conn_id >> 24) & 0xff);
  out[1] = (unsigned char)((conn_id >> 16) & 0xff);
  out[2] = (unsigned char)((conn_id >> 8) & 0xff);
  out[3] = (unsigned char)(conn_id & 0xff);
  out[4] = flags;
  out[5] = (unsigned char)((payload_len >> 24) & 0xff);
  out[6] = (unsigned char)((payload_len >> 16) & 0xff);
  out[7] = (unsigned char)((payload_len >> 8) & 0xff);
  out[8] = (unsigned char)(payload_len & 0xff);
  if (payload_len > 0 && payload != NULL) {
    memcpy(out + 9, payload, payload_len);
  }
  return (int)(9 + payload_len);
}

static sa_cdp_channel_t *find_channel(sa_worker_ws_t *ws, int conn_id) {
  int i;
  for (i = 0; i < SA_MAX_CDP_CHANNELS; i++) {
    if (ws->channels[i].in_use && ws->channels[i].conn_id == conn_id) {
      return &ws->channels[i];
    }
  }
  return NULL;
}

static sa_cdp_channel_t *alloc_channel(sa_worker_ws_t *ws, int conn_id) {
  int i;
  sa_cdp_channel_t *existing = find_channel(ws, conn_id);
  if (existing) {
    return existing;
  }
  for (i = 0; i < SA_MAX_CDP_CHANNELS; i++) {
    if (!ws->channels[i].in_use) {
      ws->channels[i].in_use = 1;
      ws->channels[i].conn_id = conn_id;
      ws->channels[i].fd = SA_INVALID_SOCKET;
      ws->channels[i].connecting = 0;
      ws->channels[i].pending = NULL;
      ws->channels[i].pending_len = 0;
      ws->channels[i].pending_cap = 0;
      return &ws->channels[i];
    }
  }
  return NULL;
}

static void clear_channel_pending(sa_cdp_channel_t *ch) {
  if (ch == NULL) {
    return;
  }
  free(ch->pending);
  ch->pending = NULL;
  ch->pending_len = 0;
  ch->pending_cap = 0;
}

static int append_channel_pending(sa_cdp_channel_t *ch, const unsigned char *payload, size_t payload_len) {
  size_t need;
  unsigned char *next;
  if (ch == NULL || payload == NULL || payload_len == 0) {
    return 0;
  }
  need = ch->pending_len + payload_len;
  if (need > ch->pending_cap) {
    size_t cap = ch->pending_cap == 0 ? 4096 : ch->pending_cap;
    while (cap < need) {
      cap *= 2;
    }
    next = (unsigned char *)realloc(ch->pending, cap);
    if (next == NULL) {
      return -1;
    }
    ch->pending = next;
    ch->pending_cap = cap;
  }
  memcpy(ch->pending + ch->pending_len, payload, payload_len);
  ch->pending_len = need;
  return 0;
}

static void flush_channel_pending(sa_cdp_channel_t *ch) {
  if (ch == NULL || ch->fd == SA_INVALID_SOCKET || ch->pending_len == 0) {
    clear_channel_pending(ch);
    return;
  }
  if (sa_tcp_send_all(ch->fd, ch->pending, ch->pending_len) != 0) {
    /* Caller will close on next activity if needed. */
  }
  clear_channel_pending(ch);
}

typedef struct {
  sa_worker_ws_t *ws;
  sa_cdp_channel_t *ch;
  int port;
} sa_chrome_open_job_t;

static void *chrome_open_worker(void *arg) {
  sa_chrome_open_job_t *job = (sa_chrome_open_job_t *)arg;
  sa_socket_t fd;
  sa_cdp_channel_t *ch;

  if (job == NULL) {
    return NULL;
  }
  ch = job->ch;
  fd = (sa_socket_t)sa_tcp_connect("127.0.0.1", job->port, 750);
  if (!ch->in_use) {
    if (fd != SA_INVALID_SOCKET) {
      sa_tcp_close(fd);
    }
    free(job);
    return NULL;
  }
  if (fd == SA_INVALID_SOCKET) {
    ch->connecting = 0;
    clear_channel_pending(ch);
    ch->in_use = 0;
    free(job);
    return NULL;
  }
  sa_tcp_set_nodelay(fd);
  ch->fd = fd;
  flush_channel_pending(ch);
  ch->connecting = 0;
  free(job);
  return NULL;
}

static void close_channel(sa_worker_ws_t *ws, sa_cdp_channel_t *ch) {
  unsigned char frame[9];
  int n;
  if (ch == NULL || !ch->in_use) {
    return;
  }
  if (ch->fd != SA_INVALID_SOCKET) {
    sa_tcp_close(ch->fd);
    ch->fd = SA_INVALID_SOCKET;
  }
  clear_channel_pending(ch);
  ch->connecting = 0;
  n = pack_mux(frame, sizeof(frame), (unsigned int)ch->conn_id, SA_MUX_FLAG_CLOSE, NULL, 0);
  if (n > 0 && ws->connected) {
    ws_send_frame(ws, 0x2, frame, (size_t)n);
  }
  ch->in_use = 0;
}

static void handle_mux_frame(sa_worker_ws_t *ws, const unsigned char *data, size_t len) {
  unsigned int conn_id;
  unsigned char flags;
  unsigned int payload_len;
  const unsigned char *payload;
  sa_cdp_channel_t *ch;

  if (len < 9) {
    return;
  }
  conn_id = ((unsigned int)data[0] << 24) | ((unsigned int)data[1] << 16) | ((unsigned int)data[2] << 8) | (unsigned int)data[3];
  flags = data[4];
  payload_len = ((unsigned int)data[5] << 24) | ((unsigned int)data[6] << 16) | ((unsigned int)data[7] << 8) | (unsigned int)data[8];
  if (len < 9 + payload_len) {
    return;
  }
  payload = data + 9;

  if (flags == SA_MUX_FLAG_OPEN) {
    pthread_t opener;
    sa_chrome_open_job_t *job;
    ch = alloc_channel(ws, (int)conn_id);
    if (ch == NULL) {
      return;
    }
    if (ch->fd != SA_INVALID_SOCKET) {
      sa_tcp_close(ch->fd);
      ch->fd = SA_INVALID_SOCKET;
    }
    clear_channel_pending(ch);
    ch->connecting = 1;
    job = (sa_chrome_open_job_t *)malloc(sizeof(*job));
    if (job == NULL) {
      ch->connecting = 0;
      close_channel(ws, ch);
      return;
    }
    job->ws = ws;
    job->ch = ch;
    job->port = ws->chrome_port > 0 ? ws->chrome_port : 9222;
    if (pthread_create(&opener, NULL, chrome_open_worker, job) != 0) {
      int port = job->port;
      free(job);
      ch->connecting = 0;
      /* Fallback: blocking connect so the channel still works. */
      ch->fd = (sa_socket_t)sa_tcp_connect("127.0.0.1", port, 750);
      if (ch->fd == SA_INVALID_SOCKET) {
        close_channel(ws, ch);
        return;
      }
      sa_tcp_set_nodelay(ch->fd);
      flush_channel_pending(ch);
      return;
    }
    pthread_detach(opener);
    return;
  }

  ch = find_channel(ws, (int)conn_id);
  if (flags == SA_MUX_FLAG_CLOSE) {
    if (ch) {
      if (ch->fd != SA_INVALID_SOCKET) {
        sa_tcp_close(ch->fd);
        ch->fd = SA_INVALID_SOCKET;
      }
      clear_channel_pending(ch);
      ch->connecting = 0;
      ch->in_use = 0;
    }
    return;
  }

  if (flags == SA_MUX_FLAG_DATA && ch && payload_len > 0) {
    if (ch->connecting || ch->fd == SA_INVALID_SOCKET) {
      if (append_channel_pending(ch, payload, payload_len) != 0) {
        close_channel(ws, ch);
      }
      return;
    }
    if (sa_tcp_send_all(ch->fd, payload, payload_len) != 0) {
      close_channel(ws, ch);
    }
  }
}

static int process_ws_buffer(sa_worker_ws_t *ws, sa_worker_ws_text_cb on_text, void *userdata) {
  while (ws->rx_len >= 2) {
    unsigned char b0 = ws->rx[0];
    unsigned char b1 = ws->rx[1];
    int opcode = b0 & 0x0f;
    int masked = (b1 & 0x80) != 0;
    size_t payload_len = b1 & 0x7f;
    size_t header_len = 2;
    size_t i;
    unsigned char mask[4];
    unsigned char *payload;

    if (payload_len == 126) {
      if (ws->rx_len < 4) {
        return 0;
      }
      payload_len = ((size_t)ws->rx[2] << 8) | (size_t)ws->rx[3];
      header_len = 4;
    } else if (payload_len == 127) {
      uint64_t len64;
      if (ws->rx_len < 10) {
        return 0;
      }
      /* Servers may send CDP mux frames >65535; accept 64-bit lengths that fit size_t. */
      len64 = ((uint64_t)ws->rx[2] << 56) | ((uint64_t)ws->rx[3] << 48) | ((uint64_t)ws->rx[4] << 40) |
              ((uint64_t)ws->rx[5] << 32) | ((uint64_t)ws->rx[6] << 24) | ((uint64_t)ws->rx[7] << 16) |
              ((uint64_t)ws->rx[8] << 8) | (uint64_t)ws->rx[9];
      if (len64 > (uint64_t)SA_WS_FRAME_MAX) {
        return -1;
      }
      payload_len = (size_t)len64;
      header_len = 10;
    }
    if (payload_len > SA_WS_FRAME_MAX) {
      return -1;
    }
    if (masked) {
      if (ws->rx_len < header_len + 4) {
        return 0;
      }
      memcpy(mask, ws->rx + header_len, 4);
      header_len += 4;
    }
    if (header_len + payload_len > sizeof(ws->rx)) {
      return -1;
    }
    if (ws->rx_len < header_len + payload_len) {
      return 0;
    }
    payload = ws->rx + header_len;
    if (masked) {
      for (i = 0; i < payload_len; i++) {
        payload[i] ^= mask[i % 4];
      }
    }

    if (opcode == 0x8) {
      return -1;
    }
    if (opcode == 0x9) {
      ws_send_frame(ws, 0xA, payload, payload_len);
    } else if (opcode == 0x1 && on_text) {
      char *text = (char *)malloc(payload_len + 1);
      if (text) {
        memcpy(text, payload, payload_len);
        text[payload_len] = '\0';
        on_text(userdata, text);
        free(text);
      }
    } else if (opcode == 0x2) {
      handle_mux_frame(ws, payload, payload_len);
    }

    memmove(ws->rx, ws->rx + header_len + payload_len, ws->rx_len - header_len - payload_len);
    ws->rx_len -= header_len + payload_len;
  }
  return 0;
}

static int pump_cdp_channel(sa_worker_ws_t *ws, sa_cdp_channel_t *ch) {
  unsigned char buf[SA_CDP_READ_CHUNK];
  unsigned char frame[9 + SA_CDP_READ_CHUNK];
  int forwarded = 0;

  if (ch == NULL || !ch->in_use || ch->fd == SA_INVALID_SOCKET || ch->connecting) {
    return 0;
  }

  /* Drain while Chrome has data — large CDP replies need many reads. */
  for (;;) {
    ssize_t n = sa_tcp_recv_some(ch->fd, buf, sizeof(buf), 0);
    int packed;
    if (n < 0) {
      close_channel(ws, ch);
      return -1;
    }
    if (n == 0) {
      break;
    }
    packed = pack_mux(frame, sizeof(frame), (unsigned int)ch->conn_id, SA_MUX_FLAG_DATA, buf, (size_t)n);
    if (packed <= 0) {
      continue;
    }
    if (ws_send_frame(ws, 0x2, frame, (size_t)packed) != 0) {
      ws->connected = 0;
      return -1;
    }
    forwarded = 1;
  }
  return forwarded;
}

static int pump_cdp_reads(sa_worker_ws_t *ws) {
  int i;
  int any = 0;
  for (i = 0; i < SA_MAX_CDP_CHANNELS; i++) {
    int rc = pump_cdp_channel(ws, &ws->channels[i]);
    if (rc < 0) {
      return -1;
    }
    if (rc > 0) {
      any = 1;
    }
  }
  return any;
}

static int wait_for_ws_or_cdp(sa_worker_ws_t *ws, int timeout_ms) {
  fd_set rfds;
  struct timeval tv;
  int max_fd;
  int i;
  int nfds;
  int has_ssl_pending = 0;

  if (ws->ssl && SSL_pending(ws->ssl) > 0) {
    has_ssl_pending = 1;
  }

  FD_ZERO(&rfds);
  FD_SET(ws->fd, &rfds);
  max_fd = (int)ws->fd;
  for (i = 0; i < SA_MAX_CDP_CHANNELS; i++) {
    sa_cdp_channel_t *ch = &ws->channels[i];
    if (!ch->in_use || ch->fd == SA_INVALID_SOCKET || ch->connecting) {
      continue;
    }
    FD_SET(ch->fd, &rfds);
    if ((int)ch->fd > max_fd) {
      max_fd = (int)ch->fd;
    }
  }

  if (has_ssl_pending) {
    timeout_ms = 0;
  } else if (timeout_ms > 25) {
    /* Keep CDP duty cycle high even when the runtime passes a large timeout. */
    timeout_ms = 25;
  }
  if (timeout_ms < 0) {
    timeout_ms = 0;
  }

  tv.tv_sec = timeout_ms / 1000;
  tv.tv_usec = (timeout_ms % 1000) * 1000;
#ifdef _WIN32
  nfds = select(0, &rfds, NULL, NULL, &tv);
#else
  nfds = select(max_fd + 1, &rfds, NULL, NULL, &tv);
#endif
  if (nfds < 0) {
    return -1;
  }

  for (i = 0; i < SA_MAX_CDP_CHANNELS; i++) {
    sa_cdp_channel_t *ch = &ws->channels[i];
    if (!ch->in_use || ch->fd == SA_INVALID_SOCKET) {
      continue;
    }
    if (FD_ISSET(ch->fd, &rfds)) {
      if (pump_cdp_channel(ws, ch) < 0) {
        return -1;
      }
    }
  }

  if (has_ssl_pending || FD_ISSET(ws->fd, &rfds)) {
    return 1; /* WS side may have data */
  }
  return 0;
}

sa_worker_ws_t *sa_worker_ws_create(void) {
  sa_worker_ws_t *ws = (sa_worker_ws_t *)calloc(1, sizeof(*ws));
  if (ws == NULL) {
    return NULL;
  }
  ws->fd = SA_INVALID_SOCKET;
  ws->chrome_port = 9222;
  srand((unsigned)time(NULL));
  return ws;
}

void sa_worker_ws_destroy(sa_worker_ws_t *ws) {
  if (ws == NULL) {
    return;
  }
  sa_worker_ws_close(ws);
  free(ws);
}

void sa_worker_ws_set_chrome_port(sa_worker_ws_t *ws, int chrome_port) {
  if (ws) {
    ws->chrome_port = chrome_port > 0 ? chrome_port : 9222;
  }
}

void sa_worker_ws_close_cdp_channels(sa_worker_ws_t *ws) {
  int i;
  if (ws == NULL) {
    return;
  }
  for (i = 0; i < SA_MAX_CDP_CHANNELS; i++) {
    if (ws->channels[i].in_use) {
      if (ws->channels[i].fd != SA_INVALID_SOCKET) {
        sa_tcp_close(ws->channels[i].fd);
        ws->channels[i].fd = SA_INVALID_SOCKET;
      }
      clear_channel_pending(&ws->channels[i]);
      ws->channels[i].connecting = 0;
      ws->channels[i].in_use = 0;
    }
  }
}

void sa_worker_ws_close(sa_worker_ws_t *ws) {
  if (ws == NULL) {
    return;
  }
  sa_worker_ws_close_cdp_channels(ws);
  if (ws->connected) {
    ws_send_frame(ws, 0x8, NULL, 0);
  }
  if (ws->ssl) {
    SSL_shutdown(ws->ssl);
    SSL_free(ws->ssl);
    ws->ssl = NULL;
  }
  if (ws->ctx) {
    SSL_CTX_free(ws->ctx);
    ws->ctx = NULL;
  }
  if (ws->fd != SA_INVALID_SOCKET) {
    sa_tcp_close(ws->fd);
    ws->fd = SA_INVALID_SOCKET;
  }
  ws->connected = 0;
  ws->rx_len = 0;
}

int sa_worker_ws_is_connected(const sa_worker_ws_t *ws) {
  return ws != NULL && ws->connected;
}

int sa_worker_ws_send_text(sa_worker_ws_t *ws, const char *text) {
  if (ws == NULL || !ws->connected || text == NULL) {
    return -1;
  }
  return ws_send_frame(ws, 0x1, text, strlen(text));
}

int sa_worker_ws_send_binary(sa_worker_ws_t *ws, const void *data, size_t len) {
  if (ws == NULL || !ws->connected) {
    return -1;
  }
  return ws_send_frame(ws, 0x2, data, len);
}

int sa_worker_ws_connect(
    sa_worker_ws_t *ws,
    const char *server_url,
    const char *token,
    char *err,
    size_t err_len) {
  int is_tls = 0;
  char host[256];
  char base_path[256];
  char ws_path[768];
  int port = 0;
  char key_raw[16];
  char key_b64[32];
  char request[2048];
  char response[2048];
  size_t response_len = 0;
  int i;

  if (err && err_len) {
    err[0] = '\0';
  }
  if (ws == NULL || server_url == NULL || token == NULL) {
    snprintf(err, err_len, "Missing connection parameters");
    return -1;
  }

  sa_worker_ws_close(ws);
  ensure_ssl();

  if (parse_server_url(server_url, &is_tls, host, sizeof(host), &port, base_path, sizeof(base_path)) != 0) {
    snprintf(err, err_len, "Invalid server URL");
    return -1;
  }
  if (base_path[0] == '\0') {
    snprintf(ws_path, sizeof(ws_path), "/ws/workers?token=%s", token);
  } else {
    snprintf(ws_path, sizeof(ws_path), "%s/ws/workers?token=%s", base_path, token);
  }

  ws->fd = (sa_socket_t)sa_tcp_connect(host, port, 15000);
  if (ws->fd == SA_INVALID_SOCKET) {
    snprintf(err, err_len, "Could not connect to %s:%d", host, port);
    return -1;
  }
  sa_tcp_set_nodelay(ws->fd);

  if (is_tls) {
    ws->ctx = SSL_CTX_new(TLS_client_method());
    if (ws->ctx == NULL) {
      snprintf(err, err_len, "TLS init failed");
      sa_worker_ws_close(ws);
      return -1;
    }
    SSL_CTX_set_default_verify_paths(ws->ctx);
    ws->ssl = SSL_new(ws->ctx);
    SSL_set_tlsext_host_name(ws->ssl, host);
    SSL_set_fd(ws->ssl, (int)ws->fd);
    if (SSL_connect(ws->ssl) != 1) {
      snprintf(err, err_len, "TLS handshake failed");
      sa_worker_ws_close(ws);
      return -1;
    }
  }

  for (i = 0; i < 16; i++) {
    key_raw[i] = (char)(rand() & 0xff);
  }
  b64_encode((unsigned char *)key_raw, 16, key_b64, sizeof(key_b64));

  snprintf(
      request,
      sizeof(request),
      "GET %s HTTP/1.1\r\n"
      "Host: %s\r\n"
      "Upgrade: websocket\r\n"
      "Connection: Upgrade\r\n"
      "Sec-WebSocket-Key: %s\r\n"
      "Sec-WebSocket-Version: 13\r\n"
      "User-Agent: smart-automator-connect\r\n"
      "\r\n",
      ws_path,
      host,
      key_b64);

  if (io_write_all(ws, request, strlen(request)) != 0) {
    snprintf(err, err_len, "Failed to send WebSocket upgrade");
    sa_worker_ws_close(ws);
    return -1;
  }

  while (response_len + 1 < sizeof(response)) {
    int n = io_read_some(ws, response + response_len, sizeof(response) - response_len - 1, 10000);
    if (n < 0) {
      snprintf(err, err_len, "WebSocket upgrade read failed");
      sa_worker_ws_close(ws);
      return -1;
    }
    if (n == 0) {
      continue;
    }
    response_len += (size_t)n;
    response[response_len] = '\0';
    if (strstr(response, "\r\n\r\n") != NULL) {
      break;
    }
  }

  if (strstr(response, "101") == NULL) {
    snprintf(err, err_len, "WebSocket upgrade rejected");
    sa_worker_ws_close(ws);
    return -1;
  }

  /* Keep leftover bytes after headers as WS payload start */
  {
    char *hdr_end = strstr(response, "\r\n\r\n");
    if (hdr_end != NULL) {
      size_t header_bytes = (size_t)(hdr_end + 4 - response);
      size_t leftover = response_len > header_bytes ? response_len - header_bytes : 0;
      if (leftover > 0) {
        if (leftover > sizeof(ws->rx)) {
          leftover = sizeof(ws->rx);
        }
        memcpy(ws->rx, response + header_bytes, leftover);
        ws->rx_len = leftover;
      }
    }
  }

  ws->connected = 1;
  return 0;
}

int sa_worker_ws_poll(
    sa_worker_ws_t *ws,
    sa_worker_ws_text_cb on_text,
    void *userdata,
    int timeout_ms) {
  unsigned char buf[16384];
  int ready;
  int n;

  if (ws == NULL || !ws->connected) {
    return -1;
  }

  /* Always drain any already-buffered Chrome bytes, then wait on WSS+CDP together. */
  if (pump_cdp_reads(ws) < 0 || !ws->connected) {
    ws->connected = 0;
    return -1;
  }

  ready = wait_for_ws_or_cdp(ws, timeout_ms);
  if (ready < 0 || !ws->connected) {
    ws->connected = 0;
    return -1;
  }

  if (ready > 0 || (ws->ssl && SSL_pending(ws->ssl) > 0)) {
    n = io_read_some(ws, buf, sizeof(buf), 0);
    if (n < 0) {
      ws->connected = 0;
      return -1;
    }
    if (n > 0) {
      if (ws->rx_len + (size_t)n > sizeof(ws->rx)) {
        ws->connected = 0;
        return -1;
      }
      memcpy(ws->rx + ws->rx_len, buf, (size_t)n);
      ws->rx_len += (size_t)n;
      if (process_ws_buffer(ws, on_text, userdata) != 0) {
        ws->connected = 0;
        return -1;
      }
      /* After inbound CDP traffic toward Chrome, drain replies immediately. */
      if (pump_cdp_reads(ws) < 0 || !ws->connected) {
        ws->connected = 0;
        return -1;
      }
    }
  }
  return 0;
}
