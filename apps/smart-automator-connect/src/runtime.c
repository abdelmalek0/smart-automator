#include "runtime.h"

#include "chrome.h"
#include "chrome_mirror.h"
#include "http.h"
#include "lan_proxy.h"
#include "mode.h"
#include "net.h"
#include "util.h"

#ifdef _WIN32
#include "ssh_tunnel.h"
#else
#include "ssh_cli.h"
#include "ssh_keys.h"
#endif

#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <process.h>
#else
#include <pthread.h>
#include <unistd.h>
#endif

typedef struct {
  sa_runtime_t *rt;
  sa_config_t cfg;
  char password[256];
  int chrome_ready;
  int use_key_auth;
  int bootstrap_key;
} connect_args_t;

struct sa_runtime {
  sa_status_cb cb;
  void *userdata;
  atomic_int busy;
  atomic_int stop_requested;
  sa_lan_proxy_t *lan_proxy;
#ifdef _WIN32
  sa_ssh_tunnel_t *ssh_tunnel;
#else
  sa_ssh_cli_tunnel_t *ssh_cli;
  pthread_mutex_t lock;
#endif
#ifdef _WIN32
  HANDLE worker;
#else
  pthread_t worker;
#endif
};

typedef struct {
  sa_runtime_t *rt;
  sa_conn_state_t state;
  char status[512];
  char cdp_url[256];
  char ui_url[256];
} status_event_t;

static void emit_status(sa_runtime_t *rt, sa_conn_state_t state, const char *status, const char *cdp, const char *ui) {
  if (rt->cb != NULL) {
    rt->cb(rt->userdata, state, status, cdp != NULL ? cdp : "", ui != NULL ? ui : "");
  }
}

static void runtime_stop_sessions(sa_runtime_t *rt) {
  if (rt == NULL) {
    return;
  }

#ifndef _WIN32
  pthread_mutex_lock(&rt->lock);
  if (rt->ssh_cli != NULL) {
    sa_ssh_cli_stop(rt->ssh_cli);
    rt->ssh_cli = NULL;
  }
  if (rt->lan_proxy != NULL) {
    sa_lan_proxy_stop(rt->lan_proxy);
    rt->lan_proxy = NULL;
  }
  pthread_mutex_unlock(&rt->lock);
#else
  if (rt->ssh_tunnel != NULL) {
    sa_ssh_tunnel_stop(rt->ssh_tunnel);
    rt->ssh_tunnel = NULL;
  }
  if (rt->lan_proxy != NULL) {
    sa_lan_proxy_stop(rt->lan_proxy);
    rt->lan_proxy = NULL;
  }
#endif
}

static int verify_lan_cdp(const char *local_ip, int port) {
  char url[256];
  snprintf(url, sizeof(url), "http://%s:%d/json/version", local_ip, port);
  return sa_http_check_url(url, 2000);
}

#ifdef _WIN32
static unsigned __stdcall runtime_worker(void *arg) {
#else
static void *runtime_worker(void *arg) {
#endif
  connect_args_t *args = (connect_args_t *)arg;
  sa_runtime_t *rt = args->rt;
  sa_config_t cfg = args->cfg;
  char password[256];
  char err[512];
  char local_ip[64];
  char cdp_url[256];
  char ui_url[256];
  sa_mode_t mode;
  int remote_port;
  int attempt;
  int chrome_ready;
  int use_key_auth;
  int bootstrap_key;

  snprintf(password, sizeof(password), "%s", args->password);
  chrome_ready = args->chrome_ready;
  use_key_auth = args->use_key_auth;
  bootstrap_key = args->bootstrap_key;
  free(args);

  atomic_store(&rt->busy, 1);
  atomic_store(&rt->stop_requested, 0);

  if (!chrome_ready) {
    if (cfg.chrome_user_data_dir[0] != '\0' &&
        sa_chrome_mirror_is_system_dir(cfg.chrome_user_data_dir) &&
        cfg.chrome_profile_directory[0] != '\0') {
      emit_status(rt, SA_CONN_CONNECTING, "Preparing Chrome profile mirror...", "", "");
    } else {
      emit_status(rt, SA_CONN_CONNECTING, "Starting Chrome...", "", "");
    }
    if (sa_chrome_start(
            cfg.chrome_port,
            cfg.chrome_user_data_dir,
            cfg.chrome_profile_directory,
            err,
            sizeof(err)) != 0) {
      emit_status(rt, SA_CONN_ERROR, err, "", "");
      atomic_store(&rt->busy, 0);
#ifdef _WIN32
      return 0;
#else
      return NULL;
#endif
    }
  }

  mode = sa_mode_resolve(&cfg);
  snprintf(ui_url, sizeof(ui_url), "http://%s:%d", cfg.host, cfg.ui_port);

  if (mode == SA_MODE_LAN) {
    emit_status(rt, SA_CONN_CONNECTING, "Setting up LAN mode...", "", ui_url);
    if (cfg.local_ip[0] != '\0') {
      snprintf(local_ip, sizeof(local_ip), "%s", cfg.local_ip);
    } else if (sa_detect_local_ip(cfg.host, local_ip, sizeof(local_ip)) != 0) {
      emit_status(rt, SA_CONN_ERROR, "Could not detect local IP. Set it manually.", "", ui_url);
      atomic_store(&rt->busy, 0);
#ifdef _WIN32
      return 0;
#else
      return NULL;
#endif
    }

    if (sa_port_in_use(cfg.cdp_lan_port)) {
      emit_status(rt, SA_CONN_ERROR, "LAN CDP port is already in use.", "", ui_url);
      atomic_store(&rt->busy, 0);
#ifdef _WIN32
      return 0;
#else
      return NULL;
#endif
    }

    emit_status(rt, SA_CONN_CONNECTING, "Starting LAN CDP proxy...", "", ui_url);
#ifndef _WIN32
    pthread_mutex_lock(&rt->lock);
#endif
    rt->lan_proxy = sa_lan_proxy_start(cfg.cdp_lan_port, cfg.chrome_port, err, sizeof(err));
#ifndef _WIN32
    pthread_mutex_unlock(&rt->lock);
#endif
    if (rt->lan_proxy == NULL) {
      emit_status(rt, SA_CONN_ERROR, err, "", ui_url);
      atomic_store(&rt->busy, 0);
#ifdef _WIN32
      return 0;
#else
      return NULL;
#endif
    }

#ifdef _WIN32
    Sleep(500);
#else
    usleep(500000);
#endif

    if (verify_lan_cdp(local_ip, cfg.cdp_lan_port) != 0) {
      emit_status(rt, SA_CONN_ERROR, "LAN CDP proxy verification failed.", "", ui_url);
#ifndef _WIN32
      pthread_mutex_lock(&rt->lock);
#endif
      if (rt->lan_proxy != NULL) {
        sa_lan_proxy_stop(rt->lan_proxy);
        rt->lan_proxy = NULL;
      }
#ifndef _WIN32
      pthread_mutex_unlock(&rt->lock);
#endif
      atomic_store(&rt->busy, 0);
#ifdef _WIN32
      return 0;
#else
      return NULL;
#endif
    }

    snprintf(cdp_url, sizeof(cdp_url), "http://%s:%d", local_ip, cfg.cdp_lan_port);
    emit_status(rt, SA_CONN_CONNECTED, "Connected in LAN mode.", cdp_url, ui_url);

    while (!atomic_load(&rt->stop_requested)) {
#ifdef _WIN32
      Sleep(500);
#else
      usleep(500000);
#endif
    }

#ifndef _WIN32
    pthread_mutex_lock(&rt->lock);
#endif
    if (rt->lan_proxy != NULL) {
      sa_lan_proxy_stop(rt->lan_proxy);
      rt->lan_proxy = NULL;
    }
#ifndef _WIN32
    pthread_mutex_unlock(&rt->lock);
#endif
    emit_status(rt, SA_CONN_IDLE, "Disconnected.", "", "");
    atomic_store(&rt->busy, 0);
#ifdef _WIN32
    return 0;
#else
    return NULL;
#endif
  }

  emit_status(rt, SA_CONN_CONNECTING, "Setting up remote SSH tunnel...", "", ui_url);
  remote_port = 0;
  err[0] = '\0';

#ifndef _WIN32
  if (bootstrap_key) {
    emit_status(rt, SA_CONN_CONNECTING, "Installing SSH key on gaming PC...", "", ui_url);
    if (sa_ssh_key_install(cfg.host, cfg.user, password, err, sizeof(err)) != 0) {
      emit_status(rt, SA_CONN_ERROR, err, "", ui_url);
      memset(password, 0, sizeof(password));
      atomic_store(&rt->busy, 0);
      return NULL;
    }
    use_key_auth = 1;
  } else if (use_key_auth) {
    if (sa_ssh_key_test_auth(cfg.host, cfg.user, err, sizeof(err)) != 0) {
      emit_status(rt, SA_CONN_ERROR, err, "", ui_url);
      memset(password, 0, sizeof(password));
      atomic_store(&rt->busy, 0);
      return NULL;
    }
  }
#endif

  for (attempt = 0; attempt < 3; attempt++) {
    int port = cfg.cdp_remote_port + attempt;
    int bound = 0;
    char status[128];

    if (atomic_load(&rt->stop_requested)) {
      break;
    }

    snprintf(status, sizeof(status), "SSH tunnel: trying port %d...", port);
    emit_status(rt, SA_CONN_CONNECTING, status, "", ui_url);

#ifndef _WIN32
    char key_path[512];
    const char *pw = NULL;
    const char *kp = NULL;

    if (use_key_auth) {
      sa_ssh_key_priv_path(key_path, sizeof(key_path));
      kp = key_path;
    } else {
      pw = password;
    }

    pthread_mutex_lock(&rt->lock);
#endif
    rt->ssh_cli = sa_ssh_cli_start(
        cfg.host,
        cfg.user,
#ifndef _WIN32
        pw,
        kp,
#else
        password,
        NULL,
#endif
        port,
        cfg.chrome_port,
        &bound,
        err,
        sizeof(err));
#ifndef _WIN32
    pthread_mutex_unlock(&rt->lock);
#endif
    if (rt->ssh_cli == NULL) {
      continue;
    }

    for (int i = 0; i < 15; i++) {
      if (atomic_load(&rt->stop_requested)) {
        break;
      }
      if (i == 0 || i == 5) {
        emit_status(rt, SA_CONN_CONNECTING, "Verifying SSH CDP tunnel...", "", ui_url);
      }
      if (sa_ssh_cli_verify_cdp(rt->ssh_cli, bound > 0 ? bound : port) == 0) {
        remote_port = bound > 0 ? bound : port;
        break;
      }
#ifdef _WIN32
      Sleep(1000);
#else
      sleep(1);
#endif
    }

    if (remote_port > 0) {
      break;
    }

    snprintf(
        err,
        sizeof(err),
        "CDP verification failed on gaming PC port %d. Check SSH forwarding and that curl is installed on the gaming PC.",
        bound > 0 ? bound : port);
#ifndef _WIN32
    pthread_mutex_lock(&rt->lock);
#endif
    if (rt->ssh_cli != NULL) {
      sa_ssh_cli_stop(rt->ssh_cli);
      rt->ssh_cli = NULL;
    }
#ifndef _WIN32
    pthread_mutex_unlock(&rt->lock);
#endif
  }

  memset(password, 0, sizeof(password));

  if (remote_port <= 0) {
    if (err[0] == '\0') {
      snprintf(
          err,
          sizeof(err),
          "Failed to establish SSH CDP tunnel. Check SSH access and TCP forwarding.");
    }
    emit_status(rt, SA_CONN_ERROR, err, "", ui_url);
    atomic_store(&rt->busy, 0);
#ifdef _WIN32
    return 0;
#else
    return NULL;
#endif
  }

  snprintf(cdp_url, sizeof(cdp_url), "http://127.0.0.1:%d", remote_port);
  snprintf(
      err,
      sizeof(err),
      "Connected in remote mode. On gaming PC: curl http://127.0.0.1:%d/json/version",
      remote_port);
  emit_status(rt, SA_CONN_CONNECTED, err, cdp_url, ui_url);

  while (!atomic_load(&rt->stop_requested)) {
#ifdef _WIN32
    Sleep(500);
#else
    usleep(500000);
#endif
  }

#ifndef _WIN32
  pthread_mutex_lock(&rt->lock);
#endif
  if (rt->ssh_cli != NULL) {
    sa_ssh_cli_stop(rt->ssh_cli);
    rt->ssh_cli = NULL;
  }
#ifndef _WIN32
  pthread_mutex_unlock(&rt->lock);
#endif
  emit_status(rt, SA_CONN_IDLE, "Disconnected.", "", "");
  atomic_store(&rt->busy, 0);

#ifdef _WIN32
  return 0;
#else
  return NULL;
#endif
}

sa_runtime_t *sa_runtime_create(sa_status_cb cb, void *userdata) {
  sa_runtime_t *rt = calloc(1, sizeof(*rt));
  if (rt == NULL) {
    return NULL;
  }
  rt->cb = cb;
  rt->userdata = userdata;
  atomic_store(&rt->busy, 0);
  atomic_store(&rt->stop_requested, 0);
#ifndef _WIN32
  pthread_mutex_init(&rt->lock, NULL);
#endif
  return rt;
}

void sa_runtime_disconnect(sa_runtime_t *rt) {
  if (rt == NULL) {
    return;
  }
  atomic_store(&rt->stop_requested, 1);
  runtime_stop_sessions(rt);
}

int sa_runtime_is_busy(const sa_runtime_t *rt) {
  return rt != NULL && atomic_load(&rt->busy) != 0;
}

void sa_runtime_connect(
    sa_runtime_t *rt,
    const sa_config_t *cfg,
    const char *password,
    int use_key_auth,
    int bootstrap_key,
    int chrome_ready) {
  connect_args_t *args;

  if (rt == NULL || cfg == NULL || sa_runtime_is_busy(rt)) {
    return;
  }

  args = calloc(1, sizeof(*args));
  if (args == NULL) {
    return;
  }

  args->rt = rt;
  args->cfg = *cfg;
  args->chrome_ready = chrome_ready;
  args->use_key_auth = use_key_auth;
  args->bootstrap_key = bootstrap_key;
  snprintf(args->password, sizeof(args->password), "%s", password != NULL ? password : "");

#ifdef _WIN32
  rt->worker = (HANDLE)_beginthreadex(NULL, 0, runtime_worker, args, 0, NULL);
#else
  pthread_create(&rt->worker, NULL, runtime_worker, args);
  pthread_detach(rt->worker);
#endif
}

void sa_runtime_destroy(sa_runtime_t *rt) {
  if (rt == NULL) {
    return;
  }
  sa_runtime_disconnect(rt);
  while (sa_runtime_is_busy(rt)) {
#ifdef _WIN32
    Sleep(100);
#else
    usleep(100000);
#endif
  }
#ifndef _WIN32
  pthread_mutex_destroy(&rt->lock);
#endif
  free(rt);
}
