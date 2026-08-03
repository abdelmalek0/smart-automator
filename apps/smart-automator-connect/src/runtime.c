#include "runtime.h"

#include "chrome.h"
#include "chrome_profiles.h"
#include "common.h"
#include "util.h"
#include "worker_ws.h"

#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif

#define SA_RECONNECT_STABLE_MS 30000
#define SA_CHROME_REAP_WAIT_MS 3000

struct sa_runtime {
  sa_status_cb cb;
  void *userdata;
  pthread_t thread;
  pthread_mutex_t lock;
  atomic_int thread_running;
  atomic_int stop_requested;
  atomic_int connected;
  atomic_int busy;
  sa_worker_session_t session;
  sa_worker_ws_t *ws;
  char active_run_id[64];
  atomic_int browser_up;
  int chrome_port;

  /* Chrome start runs off the WSS poll thread so heartbeats stay alive. */
  pthread_t chrome_thread;
  atomic_int chrome_thread_running;
  atomic_int chrome_job_cancel;
  char chrome_start_json[8192];
  atomic_int chrome_result_pending;
  int chrome_result_ok;
  int chrome_result_port;
  char chrome_result_err[512];
};

static void emit_status(sa_runtime_t *rt, sa_conn_state_t state, const char *status) {
  if (rt->cb) {
    rt->cb(rt->userdata, state, status);
  }
}

static int json_get_string_local(const char *json, const char *key, char *out, size_t out_len) {
  char pattern[128];
  const char *found;
  const char *cursor;
  size_t n = 0;

  if (out == NULL || out_len == 0) {
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

static int json_get_bool(const char *json, const char *key, int default_value) {
  char pattern[128];
  const char *found;
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  found = strstr(json, pattern);
  if (found == NULL) {
    return default_value;
  }
  found = strchr(found + strlen(pattern), ':');
  if (found == NULL) {
    return default_value;
  }
  found++;
  while (*found == ' ' || *found == '\t') {
    found++;
  }
  if (strncmp(found, "true", 4) == 0) {
    return 1;
  }
  if (strncmp(found, "false", 5) == 0) {
    return 0;
  }
  return default_value;
}

static void append_json_escaped(char *out, size_t out_len, const char *value) {
  size_t used = strlen(out);
  size_t i;
  for (i = 0; value && value[i]; i++) {
    char c = value[i];
    if (used + 2 >= out_len) {
      break;
    }
    if (c == '\\' || c == '"') {
      if (used + 3 >= out_len) {
        break;
      }
      out[used++] = '\\';
      out[used++] = c;
    } else if (c == '\n' || c == '\r' || c == '\t') {
      continue;
    } else {
      out[used++] = c;
    }
    out[used] = '\0';
  }
}

static void send_profiles(sa_runtime_t *rt) {
  sa_chrome_profile_list_t list;
  char json[16384];
  int i;
  size_t used;

  sa_chrome_profiles_discover(&list);
  snprintf(json, sizeof(json), "{\"type\":\"profiles\",\"profiles\":[");
  used = strlen(json);
  for (i = 0; i < list.count; i++) {
    char item[1024];
    const sa_chrome_profile_t *p = &list.items[i];
    snprintf(item, sizeof(item), "%s{\"id\":\"", i == 0 ? "" : ",");
    if (used + strlen(item) >= sizeof(json) - 4) {
      break;
    }
    memcpy(json + used, item, strlen(item) + 1);
    used = strlen(json);
    append_json_escaped(json, sizeof(json), p->id);
    used = strlen(json);
    snprintf(item, sizeof(item), "\",\"browser\":\"");
    if (used + strlen(item) >= sizeof(json) - 4) {
      break;
    }
    memcpy(json + used, item, strlen(item) + 1);
    used = strlen(json);
    append_json_escaped(json, sizeof(json), p->browser);
    used = strlen(json);
    snprintf(item, sizeof(item), "\",\"name\":\"");
    if (used + strlen(item) >= sizeof(json) - 4) {
      break;
    }
    memcpy(json + used, item, strlen(item) + 1);
    used = strlen(json);
    append_json_escaped(json, sizeof(json), p->name);
    used = strlen(json);
    snprintf(item, sizeof(item), "\",\"user_data_dir\":\"");
    if (used + strlen(item) >= sizeof(json) - 4) {
      break;
    }
    memcpy(json + used, item, strlen(item) + 1);
    used = strlen(json);
    append_json_escaped(json, sizeof(json), p->user_data_dir);
    used = strlen(json);
    snprintf(item, sizeof(item), "\",\"profile_directory\":\"");
    if (used + strlen(item) >= sizeof(json) - 4) {
      break;
    }
    memcpy(json + used, item, strlen(item) + 1);
    used = strlen(json);
    append_json_escaped(json, sizeof(json), p->profile_directory);
    used = strlen(json);
    if (used + 3 >= sizeof(json)) {
      break;
    }
    json[used++] = '"';
    json[used++] = '}';
    json[used] = '\0';
  }
  if (used + 3 < sizeof(json)) {
    json[used++] = ']';
    json[used++] = '}';
    json[used] = '\0';
  }
  sa_worker_ws_send_text(rt->ws, json);
}

static void join_chrome_thread_if_done(sa_runtime_t *rt) {
  if (!atomic_load(&rt->chrome_thread_running)) {
    return;
  }
  if (!atomic_load(&rt->chrome_result_pending)) {
    return;
  }
  pthread_join(rt->chrome_thread, NULL);
  atomic_store(&rt->chrome_thread_running, 0);
}

/* Cancel + kill, then reap without blocking for a full Chrome startup timeout. */
static void reap_chrome_after_cancel(sa_runtime_t *rt, int max_wait_ms) {
  long long deadline = sa_monotonic_ms() + (max_wait_ms > 0 ? max_wait_ms : SA_CHROME_REAP_WAIT_MS);

  atomic_store(&rt->chrome_job_cancel, 1);
  sa_chrome_request_cancel();
  if (atomic_load(&rt->browser_up) || rt->chrome_port > 0) {
    sa_chrome_kill_debug_port(rt->chrome_port, NULL, 0);
    atomic_store(&rt->browser_up, 0);
  }
  sa_chrome_kill_debug_port(sa_chrome_debug_port(), NULL, 0);

  while (atomic_load(&rt->chrome_thread_running) && sa_monotonic_ms() < deadline) {
    join_chrome_thread_if_done(rt);
    if (!atomic_load(&rt->chrome_thread_running)) {
      break;
    }
    sa_sleep_ms(50);
  }
  if (atomic_load(&rt->chrome_thread_running)) {
    /* Cancelled readiness should exit soon; join to avoid leaking the thread. */
    pthread_join(rt->chrome_thread, NULL);
    atomic_store(&rt->chrome_thread_running, 0);
  }
  atomic_store(&rt->chrome_result_pending, 0);
}

/* Cancel in-flight start without blocking the WSS thread on a long Chrome wait. */
static void stop_browser(sa_runtime_t *rt, int notify) {
  atomic_store(&rt->chrome_job_cancel, 1);
  sa_chrome_request_cancel();
  join_chrome_thread_if_done(rt);

  if (atomic_load(&rt->browser_up)) {
    emit_status(rt, SA_CONN_CONNECTED, notify ? "Stopping Chrome…" : "Restarting Chrome…");
    sa_chrome_kill_debug_port(rt->chrome_port, NULL, 0);
    sa_worker_ws_close_cdp_channels(rt->ws);
    atomic_store(&rt->browser_up, 0);
    rt->active_run_id[0] = '\0';
  } else {
    sa_chrome_kill_debug_port(rt->chrome_port, NULL, 0);
    sa_worker_ws_close_cdp_channels(rt->ws);
  }
  if (notify) {
    sa_worker_ws_send_text(rt->ws, "{\"type\":\"browser.stopped\"}");
    emit_status(rt, SA_CONN_CONNECTED, "Connected — waiting for runs");
  }
}

static void *chrome_start_worker(void *arg) {
  sa_runtime_t *rt = (sa_runtime_t *)arg;
  char json[8192];
  char run_id[64];
  char user_data[512];
  char profile_dir[128];
  char err[512];
  int fresh = 0;
  const char *user_data_arg = NULL;
  const char *profile_arg = NULL;
  int debug_port = 0;
  int ok = 0;

  pthread_mutex_lock(&rt->lock);
  snprintf(json, sizeof(json), "%s", rt->chrome_start_json);
  pthread_mutex_unlock(&rt->lock);

  run_id[0] = '\0';
  user_data[0] = '\0';
  profile_dir[0] = '\0';
  err[0] = '\0';
  json_get_string_local(json, "run_id", run_id, sizeof(run_id));
  json_get_string_local(json, "chrome_user_data", user_data, sizeof(user_data));
  json_get_string_local(json, "chrome_profile_directory", profile_dir, sizeof(profile_dir));
  fresh = json_get_bool(json, "fresh_profile", 1);

  if (atomic_load(&rt->chrome_job_cancel) || atomic_load(&rt->stop_requested)) {
    snprintf(err, sizeof(err), "Chrome start cancelled");
    goto done;
  }

  /* Kill previous Chrome without notifying the server (silent relaunch). */
  if (atomic_load(&rt->browser_up)) {
    emit_status(rt, SA_CONN_CONNECTED, "Restarting Chrome…");
    sa_chrome_kill_debug_port(rt->chrome_port, NULL, 0);
    atomic_store(&rt->browser_up, 0);
  }

  snprintf(rt->active_run_id, sizeof(rt->active_run_id), "%s", run_id);
  emit_status(rt, SA_CONN_CONNECTED, "Waiting for Chrome debug port…");

  if (user_data[0]) {
    user_data_arg = user_data;
  }
  if (profile_dir[0]) {
    profile_arg = profile_dir;
  }

  /* Cancel was cleared only by queue_browser_start. If stop raced after that,
   * honour cancel without clearing it again. */
  if (atomic_load(&rt->chrome_job_cancel) || atomic_load(&rt->stop_requested)) {
    sa_chrome_request_cancel();
    snprintf(err, sizeof(err), "Chrome start cancelled");
    goto done;
  }

  if (sa_chrome_start(0, user_data_arg, profile_arg, fresh, err, sizeof(err)) != 0) {
    if (!err[0]) {
      snprintf(err, sizeof(err), "Chrome start failed");
    }
    goto done;
  }

  if (atomic_load(&rt->chrome_job_cancel) || atomic_load(&rt->stop_requested)) {
    sa_chrome_kill_debug_port(sa_chrome_debug_port(), NULL, 0);
    snprintf(err, sizeof(err), "Chrome start cancelled");
    goto done;
  }

  debug_port = sa_chrome_debug_port();
  if (debug_port <= 0) {
    snprintf(err, sizeof(err), "Chrome started but debug port is unknown");
    sa_chrome_kill_debug_port(0, NULL, 0);
    goto done;
  }

  ok = 1;

done:
  pthread_mutex_lock(&rt->lock);
  rt->chrome_result_ok = ok;
  rt->chrome_result_port = debug_port;
  snprintf(rt->chrome_result_err, sizeof(rt->chrome_result_err), "%s", err);
  atomic_store(&rt->chrome_result_pending, 1);
  /* Leave chrome_thread_running set until the WSS thread joins us. */
  pthread_mutex_unlock(&rt->lock);
  return NULL;
}

/* Called only from the WSS poll thread — keeps SSL I/O single-threaded. */
static void flush_chrome_result(sa_runtime_t *rt) {
  int ok;
  int port;
  char err[512];
  char status[160];

  join_chrome_thread_if_done(rt);

  if (!atomic_load(&rt->chrome_result_pending)) {
    return;
  }
  pthread_mutex_lock(&rt->lock);
  if (!atomic_load(&rt->chrome_result_pending)) {
    pthread_mutex_unlock(&rt->lock);
    return;
  }
  ok = rt->chrome_result_ok;
  port = rt->chrome_result_port;
  snprintf(err, sizeof(err), "%s", rt->chrome_result_err);
  atomic_store(&rt->chrome_result_pending, 0);
  pthread_mutex_unlock(&rt->lock);

  if (atomic_load(&rt->chrome_job_cancel) || atomic_load(&rt->stop_requested) ||
      !sa_worker_ws_is_connected(rt->ws)) {
    if (ok && port > 0) {
      sa_chrome_kill_debug_port(port, NULL, 0);
    }
    return;
  }

  if (!ok) {
    char msg[640];
    const char *raw = err[0] ? err : "Chrome start failed";
    snprintf(msg, sizeof(msg), "{\"type\":\"error\",\"message\":\"");
    append_json_escaped(msg, sizeof(msg), raw);
    {
      size_t used = strlen(msg);
      if (used + 3 < sizeof(msg)) {
        msg[used++] = '"';
        msg[used++] = '}';
        msg[used] = '\0';
      }
    }
    sa_worker_ws_send_text(rt->ws, msg);
    emit_status(rt, SA_CONN_CONNECTED, raw);
    rt->active_run_id[0] = '\0';
    return;
  }

  rt->chrome_port = port;
  sa_worker_ws_close_cdp_channels(rt->ws);
  sa_worker_ws_set_chrome_port(rt->ws, port);
  atomic_store(&rt->browser_up, 1);
  sa_worker_ws_send_text(rt->ws, "{\"type\":\"browser.ready\"}");
  snprintf(status, sizeof(status), "Browser ready (CDP %d) — run in progress", port);
  emit_status(rt, SA_CONN_CONNECTED, status);
}

static void queue_browser_start(sa_runtime_t *rt, const char *json) {
  if (atomic_load(&rt->chrome_thread_running)) {
    /* Cancel the in-flight start; reap only if it already finished. */
    atomic_store(&rt->chrome_job_cancel, 1);
    sa_chrome_request_cancel();
    join_chrome_thread_if_done(rt);
    if (atomic_load(&rt->chrome_thread_running)) {
      /* Previous start still running — ask the server to cancel/retry. */
      sa_worker_ws_send_text(
          rt->ws,
          "{\"type\":\"error\",\"message\":\"Chrome start already in progress; cancel and retry\"}");
      return;
    }
  }

  atomic_store(&rt->chrome_job_cancel, 0);
  sa_chrome_clear_cancel();
  snprintf(rt->chrome_start_json, sizeof(rt->chrome_start_json), "%s", json ? json : "");
  sa_worker_ws_send_text(rt->ws, "{\"type\":\"browser.starting\"}");
  emit_status(rt, SA_CONN_CONNECTED, "Starting Chrome…");

  atomic_store(&rt->chrome_thread_running, 1);
  if (pthread_create(&rt->chrome_thread, NULL, chrome_start_worker, rt) != 0) {
    atomic_store(&rt->chrome_thread_running, 0);
    sa_worker_ws_send_text(
        rt->ws,
        "{\"type\":\"error\",\"message\":\"Failed to start Chrome worker thread\"}");
    emit_status(rt, SA_CONN_CONNECTED, "Failed to start Chrome worker thread");
  }
}

static void on_ws_text(void *userdata, const char *json) {
  sa_runtime_t *rt = (sa_runtime_t *)userdata;

  if (json == NULL) {
    return;
  }
  if (strstr(json, "\"type\":\"browser.start\"") != NULL || strstr(json, "\"type\": \"browser.start\"") != NULL) {
    queue_browser_start(rt, json);
    return;
  }
  if (strstr(json, "\"type\":\"browser.stop\"") != NULL || strstr(json, "\"type\": \"browser.stop\"") != NULL) {
    stop_browser(rt, 1);
    return;
  }
  if (strstr(json, "\"type\":\"ping\"") != NULL || strstr(json, "\"type\": \"ping\"") != NULL) {
    sa_worker_ws_send_text(rt->ws, "{\"type\":\"pong\"}");
    return;
  }
  if (strstr(json, "\"type\":\"hello\"") != NULL || strstr(json, "\"type\": \"hello\"") != NULL) {
    return;
  }
}

static void *runtime_worker(void *arg) {
  sa_runtime_t *rt = (sa_runtime_t *)arg;
  char err[512];
  int backoff_ms = 1000;
  /* Consecutive failures only; reset only after a stable connected dwell. */
  const int max_reconnect_attempts = 10;
  int reconnect_attempts = 0;
  long long connected_at_ms = 0;

  atomic_store(&rt->busy, 1);

  while (!atomic_load(&rt->stop_requested)) {
    emit_status(rt, SA_CONN_CONNECTING, "Connecting to server…");
    err[0] = '\0';
    if (sa_worker_ws_connect(rt->ws, rt->session.server_url, rt->session.worker_token, err, sizeof(err)) != 0) {
      char status[640];
      reconnect_attempts++;
      if (reconnect_attempts >= max_reconnect_attempts) {
        snprintf(
            status,
            sizeof(status),
            "Gave up after %d connect attempts — click Reconnect to retry%s%s",
            max_reconnect_attempts,
            err[0] ? ": " : "",
            err[0] ? err : "");
        emit_status(rt, SA_CONN_ERROR, status);
        break;
      }
      snprintf(
          status,
          sizeof(status),
          "Reconnect failed (%d/%d): %s",
          reconnect_attempts,
          max_reconnect_attempts,
          err[0] ? err : "unknown error");
      emit_status(rt, SA_CONN_ERROR, status);
      {
        int waited = 0;
        int delay = backoff_ms > 15000 ? 15000 : backoff_ms;
        while (!atomic_load(&rt->stop_requested) && waited < delay) {
          sa_sleep_ms(200);
          waited += 200;
        }
      }
      if (backoff_ms < 15000) {
        int next = backoff_ms * 2;
        backoff_ms = next > 15000 ? 15000 : next;
      }
      continue;
    }

    backoff_ms = 1000;
    connected_at_ms = sa_monotonic_ms();
    atomic_store(&rt->connected, 1);

    sa_worker_ws_send_text(rt->ws, "{\"type\":\"hello\"}");
    send_profiles(rt);
    emit_status(rt, SA_CONN_CONNECTED, "Connected — waiting for runs");

    while (!atomic_load(&rt->stop_requested) && sa_worker_ws_is_connected(rt->ws)) {
      if (sa_worker_ws_poll(rt->ws, on_ws_text, rt, 250) != 0) {
        break;
      }
      flush_chrome_result(rt);
      /* Reset consecutive failures only after a stable session. */
      if (reconnect_attempts > 0 &&
          (sa_monotonic_ms() - connected_at_ms) >= SA_RECONNECT_STABLE_MS) {
        reconnect_attempts = 0;
      }
    }

    reap_chrome_after_cancel(rt, SA_CHROME_REAP_WAIT_MS);
    sa_worker_ws_close_cdp_channels(rt->ws);
    sa_worker_ws_close(rt->ws);
    atomic_store(&rt->connected, 0);
    rt->active_run_id[0] = '\0';

    if (atomic_load(&rt->stop_requested)) {
      break;
    }

    reconnect_attempts++;
    if (reconnect_attempts >= max_reconnect_attempts) {
      char status[160];
      snprintf(
          status,
          sizeof(status),
          "Disconnected repeatedly (%d times) — click Reconnect to retry",
          max_reconnect_attempts);
      emit_status(rt, SA_CONN_ERROR, status);
      break;
    }
    {
      char status[160];
      snprintf(
          status,
          sizeof(status),
          "Disconnected — reconnecting (%d/%d)…",
          reconnect_attempts,
          max_reconnect_attempts);
      emit_status(rt, SA_CONN_CONNECTING, status);
    }
    sa_sleep_ms(1000);
  }

  if (!atomic_load(&rt->stop_requested)) {
    /* Keep the last ERROR status (gave up reconnecting); only clear when user disconnects. */
  } else {
    emit_status(rt, SA_CONN_IDLE, "Disconnected");
  }
  atomic_store(&rt->busy, 0);
  atomic_store(&rt->thread_running, 0);
  return NULL;
}

sa_runtime_t *sa_runtime_create(sa_status_cb cb, void *userdata) {
  sa_runtime_t *rt = (sa_runtime_t *)calloc(1, sizeof(*rt));
  if (rt == NULL) {
    return NULL;
  }
  rt->cb = cb;
  rt->userdata = userdata;
  rt->chrome_port = SA_DEFAULT_CHROME_PORT;
  pthread_mutex_init(&rt->lock, NULL);
  atomic_init(&rt->thread_running, 0);
  atomic_init(&rt->stop_requested, 0);
  atomic_init(&rt->connected, 0);
  atomic_init(&rt->busy, 0);
  atomic_init(&rt->browser_up, 0);
  atomic_init(&rt->chrome_thread_running, 0);
  atomic_init(&rt->chrome_job_cancel, 0);
  atomic_init(&rt->chrome_result_pending, 0);
  rt->ws = sa_worker_ws_create();
  if (rt->ws == NULL) {
    free(rt);
    return NULL;
  }
  sa_worker_ws_set_chrome_port(rt->ws, rt->chrome_port);
  return rt;
}

void sa_runtime_destroy(sa_runtime_t *rt) {
  if (rt == NULL) {
    return;
  }
  sa_runtime_disconnect(rt);
  if (atomic_load(&rt->thread_running)) {
    pthread_join(rt->thread, NULL);
  }
  sa_worker_ws_destroy(rt->ws);
  pthread_mutex_destroy(&rt->lock);
  free(rt);
}

void sa_runtime_connect(sa_runtime_t *rt, const sa_worker_session_t *session) {
  if (rt == NULL || session == NULL) {
    return;
  }
  if (atomic_load(&rt->thread_running)) {
    return;
  }
  rt->session = *session;
  atomic_store(&rt->stop_requested, 0);
  atomic_store(&rt->thread_running, 1);
  if (pthread_create(&rt->thread, NULL, runtime_worker, rt) != 0) {
    atomic_store(&rt->thread_running, 0);
    emit_status(rt, SA_CONN_ERROR, "Failed to start worker thread");
  }
}

void sa_runtime_disconnect(sa_runtime_t *rt) {
  if (rt == NULL) {
    return;
  }
  atomic_store(&rt->stop_requested, 1);
  atomic_store(&rt->chrome_job_cancel, 1);
  sa_chrome_request_cancel();
  /* Wake the WSS thread without freeing SSL from this thread. */
  sa_worker_ws_interrupt(rt->ws);
  if (atomic_load(&rt->thread_running)) {
    pthread_join(rt->thread, NULL);
  }
  if (atomic_load(&rt->chrome_thread_running)) {
    pthread_join(rt->chrome_thread, NULL);
    atomic_store(&rt->chrome_thread_running, 0);
  }
  /* Owner thread normally closed the socket; ensure cleanup if it never ran. */
  sa_worker_ws_close(rt->ws);
  if (atomic_load(&rt->browser_up)) {
    sa_chrome_kill_debug_port(rt->chrome_port, NULL, 0);
    atomic_store(&rt->browser_up, 0);
  }
}

int sa_runtime_is_busy(const sa_runtime_t *rt) {
  if (rt == NULL) {
    return 0;
  }
  return atomic_load(&rt->busy) || atomic_load(&rt->thread_running);
}

int sa_runtime_is_connected(const sa_runtime_t *rt) {
  if (rt == NULL) {
    return 0;
  }
  return atomic_load(&rt->connected);
}
