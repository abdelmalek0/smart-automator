#ifndef SA_NET_H
#define SA_NET_H

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
typedef SOCKET sa_socket_t;
#define SA_INVALID_SOCKET INVALID_SOCKET
#else
typedef int sa_socket_t;
#define SA_INVALID_SOCKET (-1)
#endif

int sa_net_init(void);
void sa_net_shutdown(void);

int sa_parse_http_url(const char *url, char *host, size_t host_len, int *port, char *path, size_t path_len);
sa_socket_t sa_tcp_connect(const char *host, int port, int timeout_ms);
int sa_tcp_set_nodelay(sa_socket_t fd);
int sa_tcp_set_nonblock(sa_socket_t fd, int enabled);
int sa_tcp_send_all(sa_socket_t fd, const void *buf, size_t len);
/* Like sa_tcp_send_all but aborts after timeout_ms (monotonic). */
int sa_tcp_send_all_deadline(sa_socket_t fd, const void *buf, size_t len, int timeout_ms);
/* Returns >0 bytes read, 0 on timeout, -1 on error/peer close. */
ssize_t sa_tcp_recv_some(sa_socket_t fd, void *buf, size_t len, int timeout_ms);
void sa_tcp_close(sa_socket_t fd);
/* Wake blocking select/recv without freeing the fd (thread-safe interrupt). */
void sa_tcp_shutdown(sa_socket_t fd);
int sa_port_in_use(int port);
int sa_detect_local_ip(const char *remote_host, char *out, size_t out_len);

#endif
