#include "tls_http.h"

#include "net.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <openssl/err.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>

#ifdef _WIN32
#include <winsock2.h>
#else
#include <unistd.h>
#endif

static int g_ssl_inited = 0;

static void ensure_ssl(void) {
  if (g_ssl_inited) {
    return;
  }
  SSL_library_init();
  SSL_load_error_strings();
  OpenSSL_add_all_algorithms();
  g_ssl_inited = 1;
}

static int tls_insecure_allowed(void) {
  const char *v = getenv("SMART_AUTOMATOR_INSECURE_TLS");
  if (v == NULL || v[0] == '\0') {
    return 0;
  }
  return strcmp(v, "1") == 0 || strcmp(v, "true") == 0 || strcmp(v, "yes") == 0 ||
         strcmp(v, "TRUE") == 0 || strcmp(v, "YES") == 0;
}

static int configure_client_ssl_ctx(SSL_CTX *ctx, char *err, size_t err_len) {
  if (ctx == NULL) {
    return -1;
  }
  if (tls_insecure_allowed()) {
    SSL_CTX_set_verify(ctx, SSL_VERIFY_NONE, NULL);
    return 0;
  }
  SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, NULL);
  SSL_CTX_set_verify_depth(ctx, 10);
  if (SSL_CTX_set_default_verify_paths(ctx) != 1) {
    if (err && err_len) {
      snprintf(err, err_len, "Failed to load TLS CA certificates");
    }
    return -1;
  }
  return 0;
}

static int ssl_set_hostname(SSL *ssl, const char *host, char *err, size_t err_len) {
  if (ssl == NULL || host == NULL || host[0] == '\0') {
    return -1;
  }
  SSL_set_tlsext_host_name(ssl, host);
  if (tls_insecure_allowed()) {
    return 0;
  }
#if OPENSSL_VERSION_NUMBER >= 0x10100000L
  if (SSL_set1_host(ssl, host) != 1) {
    if (err && err_len) {
      snprintf(err, err_len, "Failed to set TLS hostname check");
    }
    return -1;
  }
#else
  (void)err;
  (void)err_len;
#endif
  return 0;
}

static int parse_url(
    const char *url,
    int *is_tls,
    char *host,
    size_t host_len,
    int *port,
    char *path,
    size_t path_len) {
  const char *cursor;
  const char *slash;
  const char *colon;
  char host_port[320];

  if (url == NULL) {
    return -1;
  }
  if (strncmp(url, "https://", 8) == 0) {
    *is_tls = 1;
    cursor = url + 8;
    *port = 443;
  } else if (strncmp(url, "http://", 7) == 0) {
    *is_tls = 0;
    cursor = url + 7;
    *port = 80;
  } else {
    return -1;
  }

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
  }
  return 0;
}

static int io_write(SSL *ssl, sa_socket_t fd, const void *buf, size_t len) {
  const char *p = (const char *)buf;
  size_t left = len;
  while (left > 0) {
    int n;
    if (ssl != NULL) {
      n = SSL_write(ssl, p, (int)left);
      if (n <= 0) {
        return -1;
      }
    } else {
      if (sa_tcp_send_all(fd, p, left) != 0) {
        return -1;
      }
      return 0;
    }
    p += n;
    left -= (size_t)n;
  }
  return 0;
}

static int io_read_some(SSL *ssl, sa_socket_t fd, void *buf, size_t len) {
  if (ssl != NULL) {
    int n = SSL_read(ssl, buf, (int)len);
    return n;
  }
  return (int)sa_tcp_recv_some(fd, buf, len, 15000);
}

int sa_json_get_string(const char *json, const char *key, char *out, size_t out_len) {
  char pattern[128];
  const char *found;
  const char *cursor;
  size_t n = 0;

  if (json == NULL || key == NULL || out == NULL || out_len == 0) {
    return -1;
  }
  out[0] = '\0';
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  found = strstr(json, pattern);
  if (found == NULL) {
    return -1;
  }
  found = strchr(found + strlen(pattern), ':');
  if (found == NULL) {
    return -1;
  }
  found++;
  while (*found == ' ' || *found == '\t') {
    found++;
  }
  if (*found != '"') {
    return -1;
  }
  cursor = found + 1;
  while (*cursor && *cursor != '"' && n + 1 < out_len) {
    if (*cursor == '\\' && cursor[1]) {
      char esc = cursor[1];
      if (esc == '"' || esc == '\\' || esc == '/') {
        out[n++] = esc;
      } else if (esc == 'n') {
        out[n++] = '\n';
      } else if (esc == 'r') {
        out[n++] = '\r';
      } else if (esc == 't') {
        out[n++] = '\t';
      } else {
        out[n++] = esc;
      }
      cursor += 2;
      continue;
    }
    out[n++] = *cursor++;
  }
  if (*cursor != '"') {
    out[0] = '\0';
    return -1;
  }
  out[n] = '\0';
  return 0;
}

int sa_http_post_json(
    const char *url,
    const char *json_body,
    char *out_body,
    size_t out_body_len,
    int *out_status,
    char *err,
    size_t err_len) {
  int is_tls = 0;
  char host[256];
  char path[512];
  int port = 0;
  sa_socket_t fd = SA_INVALID_SOCKET;
  SSL_CTX *ctx = NULL;
  SSL *ssl = NULL;
  char request[4096];
  char response[8192];
  size_t response_len = 0;
  const char *body;
  int status = 0;
  size_t body_len = json_body ? strlen(json_body) : 0;

  if (out_body && out_body_len) {
    out_body[0] = '\0';
  }
  if (out_status) {
    *out_status = 0;
  }
  if (err && err_len) {
    err[0] = '\0';
  }

  ensure_ssl();
  if (parse_url(url, &is_tls, host, sizeof(host), &port, path, sizeof(path)) != 0) {
    snprintf(err, err_len, "Invalid server URL");
    return -1;
  }

  fd = sa_tcp_connect(host, port, 15000);
  if (fd == SA_INVALID_SOCKET) {
    snprintf(err, err_len, "Could not connect to %s:%d", host, port);
    return -1;
  }

  if (is_tls) {
    ctx = SSL_CTX_new(TLS_client_method());
    if (ctx == NULL) {
      snprintf(err, err_len, "TLS init failed");
      sa_tcp_close(fd);
      return -1;
    }
    if (configure_client_ssl_ctx(ctx, err, err_len) != 0) {
      SSL_CTX_free(ctx);
      sa_tcp_close(fd);
      return -1;
    }
    ssl = SSL_new(ctx);
    if (ssl == NULL) {
      snprintf(err, err_len, "TLS init failed");
      SSL_CTX_free(ctx);
      sa_tcp_close(fd);
      return -1;
    }
    if (ssl_set_hostname(ssl, host, err, err_len) != 0) {
      SSL_free(ssl);
      SSL_CTX_free(ctx);
      sa_tcp_close(fd);
      return -1;
    }
    SSL_set_fd(ssl, (int)fd);
    if (SSL_connect(ssl) != 1) {
      long verify = SSL_get_verify_result(ssl);
      if (!tls_insecure_allowed() && verify != X509_V_OK) {
        snprintf(
            err,
            err_len,
            "TLS certificate verify failed: %s (set SMART_AUTOMATOR_INSECURE_TLS=1 to bypass)",
            X509_verify_cert_error_string(verify));
      } else {
        snprintf(err, err_len, "TLS handshake failed");
      }
      SSL_free(ssl);
      SSL_CTX_free(ctx);
      sa_tcp_close(fd);
      return -1;
    }
  }

  snprintf(
      request,
      sizeof(request),
      "POST %s HTTP/1.1\r\n"
      "Host: %s\r\n"
      "User-Agent: smart-automator-connect\r\n"
      "Content-Type: application/json\r\n"
      "Content-Length: %zu\r\n"
      "Connection: close\r\n"
      "Accept: application/json\r\n"
      "\r\n"
      "%s",
      path,
      host,
      body_len,
      json_body ? json_body : "");

  if (io_write(ssl, fd, request, strlen(request)) != 0) {
    snprintf(err, err_len, "Failed to send login request");
    goto fail;
  }

  while (response_len + 1 < sizeof(response)) {
    int n = io_read_some(ssl, fd, response + response_len, sizeof(response) - response_len - 1);
    if (n <= 0) {
      break;
    }
    response_len += (size_t)n;
  }
  response[response_len] = '\0';

  if (sscanf(response, "HTTP/%*s %d", &status) != 1) {
    snprintf(err, err_len, "Invalid HTTP response");
    goto fail;
  }
  if (out_status) {
    *out_status = status;
  }
  body = strstr(response, "\r\n\r\n");
  if (body != NULL) {
    body += 4;
    if (out_body && out_body_len) {
      snprintf(out_body, out_body_len, "%s", body);
    }
  }

  if (ssl) {
    SSL_shutdown(ssl);
    SSL_free(ssl);
  }
  if (ctx) {
    SSL_CTX_free(ctx);
  }
  sa_tcp_close(fd);
  return 0;

fail:
  if (ssl) {
    SSL_free(ssl);
  }
  if (ctx) {
    SSL_CTX_free(ctx);
  }
  sa_tcp_close(fd);
  return -1;
}
