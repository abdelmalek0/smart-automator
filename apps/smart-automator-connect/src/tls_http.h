#ifndef SA_TLS_HTTP_H
#define SA_TLS_HTTP_H

#include <stddef.h>

/* POST JSON to https:// or http:// URL. Writes response body into out_body. */
int sa_http_post_json(
    const char *url,
    const char *json_body,
    char *out_body,
    size_t out_body_len,
    int *out_status,
    char *err,
    size_t err_len);

/* Extract a JSON string field value (simple, non-nested). */
int sa_json_get_string(const char *json, const char *key, char *out, size_t out_len);

#endif
