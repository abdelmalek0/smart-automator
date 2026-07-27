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
#include <windows.h>
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
  atomic_int worker_active;
  atomic_int stop_requested;
  atomic_int connected;
  atomic_int reset_requested;
  sa_config_t active_cfg;
  char active_cdp_url[256];
  char active_ui_url[256];
  int chrome_started;
  sa_lan_proxy_t *lan_proxy;
#ifdef _WIN32
  sa_ssh_tunnel_t *ssh_tunnel;
  CRITICAL_SECTION lock;
  HANDLE worker;
#else
  sa_ssh_cli_tunnel_t *ssh_cli;
  pthread_mutex_t lock;
  pthread_t worker;
#endif
  int worker_started;
};

#ifdef _WIN32
static void rt_lock(sa_runtime_t *rt) {
  EnterCriticalSection(&rt->lock);
}

static void rt_unlock(sa_runtime_t *rt) {
  LeaveCriticalSection(&rt->lock);
}
#else
static void rt_lock(sa_runtime_t *rt) {
  pthread_mutex_lock(&rt->lock);
}

static void rt_unlock(sa_runtime_t *rt) {
  pthread_mutex_unlock(&rt->lock);
}
#endif

static void emit_status(sa_runtime_t *rt, sa_conn_state_t state, const char *status, const char *cdp, const char *ui) {
  if (rt->cb != NULL) {
    rt->cb(rt->userdata, state, status, cdp != NULL ? cdp : "", ui != NULL ? ui : "");
  }
}

static void runtime_kill_chrome(sa_runtime_t *rt) {
  sa_config_t cfg;

  if (rt == NULL || !rt->chrome_started) {
    return;
  }

  cfg = rt->active_cfg;
  sa_chrome_kill_debug_port(cfg.chrome_port, cfg.chrome_user_data_dir, cfg.fresh_profile);
  rt->chrome_started = 0;
}

static void runtime_cleanup_sessions(sa_runtime_t *rt) {
  if (rt == NULL) {
    return;
  }

  rt_lock(rt);
#ifdef _WIN32
  if (rt->ssh_tunnel != NULL) {
    sa_ssh_tunnel_t *tunnel = rt->ssh_tunnel;
    rt->ssh_tunnel = NULL;
    rt_unlock(rt);
    sa_ssh_tunnel_stop(tunnel);
    rt_lock(rt);
  }
#else
  if (rt->ssh_cli != NULL) {
    sa_ssh_cli_tunnel_t *cli = rt->ssh_cli;
    rt->ssh_cli = NULL;
    rt_unlock(rt);
    sa_ssh_cli_stop(cli);
    rt_lock(rt);
  }
#endif
  if (rt->lan_proxy != NULL) {
    sa_lan_proxy_t *proxy = rt->lan_proxy;
    rt->lan_proxy = NULL;
    rt_unlock(rt);
    sa_lan_proxy_stop(proxy);
    return;
  }
  rt_unlock(rt);
}

static void runtime_worker_finish(sa_runtime_t *rt) {
  runtime_cleanup_sessions(rt);
  runtime_kill_chrome(rt);
  atomic_store(&rt->connected, 0);
  atomic_store(&rt->worker_active, 0);
}

static void runtime_join_worker(sa_runtime_t *rt) {
  if (rt == NULL || !rt->worker_started) {
    return;
  }

#ifdef _WIN32
  if (rt->worker != NULL) {
    WaitForSingleObject(rt->worker, INFINITE);
    CloseHandle(rt->worker);
    rt->worker = NULL;
  }
#else
  pthread_join(rt->worker, NULL);
#endif
  rt->worker_started = 0;
}

static int verify_lan_cdp(const char *local_ip, int port) {
  char url[256];
  snprintf(url, sizeof(url), "http://%s:%d/json/version", local_ip, port);
  return sa_http_check_url(url, 2000);
}

static void runtime_handle_reset(sa_runtime_t *rt) {
  char err[512];
  sa_config_t cfg = rt->active_cfg;

  emit_status(rt, SA_CONN_CONNECTING, "Refreshing Chrome profile...", rt->active_cdp_url, rt->active_ui_url);
  if (sa_chrome_reset_profile(
          cfg.chrome_port,
          cfg.chrome_user_data_dir,
          cfg.chrome_profile_directory,
          cfg.fresh_profile,
          err,
          sizeof(err)) != 0) {
    emit_status(rt, SA_CONN_CONNECTED, err, rt->active_cdp_url, rt->active_ui_url);
    return;
  }
  emit_status(rt, SA_CONN_CONNECTED, "Chrome profile refreshed.", rt->active_cdp_url, rt->active_ui_url);
}

static void runtime_wait_connected(sa_runtime_t *rt) {
  while (!atomic_load(&rt->stop_requested)) {
    if (atomic_exchange(&rt->reset_requested, 0)) {
      runtime_handle_reset(rt);
      continue;
    }
#ifdef _WIN32
    Sleep(100);
#else
    usleep(100000);
#endif
  }
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

  rt->active_cfg = cfg;
  rt->active_cdp_url[0] = '\0';
  rt->active_ui_url[0] = '\0';
  rt->chrome_started = 0;
  atomic_store(&rt->connected, 0);

  if (atomic_load(&rt->stop_requested)) {
    emit_status(rt, SA_CONN_IDLE, "Disconnected.", "", "");
    runtime_worker_finish(rt);
#ifdef _WIN32
    return 0;
#else
    return NULL;
#endif
  }

  if (!chrome_ready) {
    if (cfg.chrome_user_data_dir[0] != '\0' &&
        sa_chrome_mirror_is_system_dir(cfg.chrome_user_data_dir) &&
        cfg.chrome_profile_directory[0] != '\0') {
      emit_status(rt, SA_CONN_CONNECTING, "Preparing Chrome profile mirror...", "", "");
    } else if (cfg.fresh_profile) {
      emit_status(rt, SA_CONN_CONNECTING, "Preparing fresh Chrome profile...", "", "");
    } else {
      emit_status(rt, SA_CONN_CONNECTING, "Starting Chrome...", "", "");
    }
    if (sa_chrome_start(
            cfg.chrome_port,
            cfg.chrome_user_data_dir,
            cfg.chrome_profile_directory,
            cfg.fresh_profile,
            err,
            sizeof(err)) != 0) {
      emit_status(rt, SA_CONN_ERROR, err, "", "");
      runtime_worker_finish(rt);
#ifdef _WIN32
      return 0;
#else
      return NULL;
#endif
    }
    rt->chrome_started = 1;
  }

  if (atomic_load(&rt->stop_requested)) {
    emit_status(rt, SA_CONN_IDLE, "Disconnected.", "", "");
    runtime_worker_finish(rt);
#ifdef _WIN32
    return 0;
#else
    return NULL;
#endif
  }

  mode = sa_mode_resolve(&cfg);
  snprintf(ui_url, sizeof(ui_url), "http://%s:%d", cfg.host, cfg.ui_port);

  if (mode == SA_MODE_LAN) {
    sa_lan_proxy_t *proxy;

    emit_status(rt, SA_CONN_CONNECTING, "Setting up LAN mode...", "", ui_url);
    if (cfg.local_ip[0] != '\0') {
      snprintf(local_ip, sizeof(local_ip), "%s", cfg.local_ip);
    } else if (sa_detect_local_ip(cfg.host, local_ip, sizeof(local_ip)) != 0) {
      emit_status(rt, SA_CONN_ERROR, "Could not detect local IP. Set it manually.", "", ui_url);
      runtime_worker_finish(rt);
#ifdef _WIN32
      return 0;
#else
      return NULL;
#endif
    }

    if (sa_port_in_use(cfg.cdp_lan_port)) {
      emit_status(rt, SA_CONN_ERROR, "LAN CDP port is already in use.", "", ui_url);
      runtime_worker_finish(rt);
#ifdef _WIN32
      return 0;
#else
      return NULL;
#endif
    }

    emit_status(rt, SA_CONN_CONNECTING, "Starting LAN CDP proxy...", "", ui_url);
    proxy = sa_lan_proxy_start(local_ip, cfg.cdp_lan_port, cfg.chrome_port, err, sizeof(err));
    if (proxy == NULL) {
      emit_status(rt, SA_CONN_ERROR, err, "", ui_url);
      runtime_worker_finish(rt);
#ifdef _WIN32
      return 0;
#else
      return NULL;
#endif
    }

    rt_lock(rt);
    rt->lan_proxy = proxy;
    rt_unlock(rt);

    {
      int i;
      for (i = 0; i < 20; i++) {
        if (atomic_load(&rt->stop_requested)) {
          break;
        }
        if (verify_lan_cdp(local_ip, cfg.cdp_lan_port) == 0) {
          break;
        }
#ifdef _WIN32
        Sleep(100);
#else
        usleep(100000);
#endif
      }
      if (i >= 20 && !atomic_load(&rt->stop_requested)) {
        emit_status(rt, SA_CONN_ERROR, "LAN CDP proxy verification failed.", "", ui_url);
        runtime_worker_finish(rt);
#ifdef _WIN32
        return 0;
#else
        return NULL;
#endif
      }
    }

    if (!atomic_load(&rt->stop_requested)) {
      snprintf(cdp_url, sizeof(cdp_url), "http://%s:%d", local_ip, cfg.cdp_lan_port);
      snprintf(rt->active_cdp_url, sizeof(rt->active_cdp_url), "%s", cdp_url);
      snprintf(rt->active_ui_url, sizeof(rt->active_ui_url), "%s", ui_url);
      atomic_store(&rt->connected, 1);
      emit_status(rt, SA_CONN_CONNECTED, "Connected in LAN mode.", cdp_url, ui_url);
      runtime_wait_connected(rt);
    }

    emit_status(rt, SA_CONN_IDLE, "Disconnected.", "", "");
    runtime_worker_finish(rt);
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
      runtime_worker_finish(rt);
      return NULL;
    }
    use_key_auth = 1;
  } else if (use_key_auth) {
    if (sa_ssh_key_test_auth(cfg.host, cfg.user, err, sizeof(err)) != 0) {
      emit_status(rt, SA_CONN_ERROR, err, "", ui_url);
      memset(password, 0, sizeof(password));
      runtime_worker_finish(rt);
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

#ifdef _WIN32
    {
      sa_ssh_tunnel_t *tunnel;

      tunnel = sa_ssh_tunnel_start(
          cfg.host,
          cfg.user,
          password,
          port,
          cfg.chrome_port,
          &bound,
          err,
          sizeof(err));
      if (tunnel == NULL) {
        continue;
      }
      if (atomic_load(&rt->stop_requested)) {
        sa_ssh_tunnel_stop(tunnel);
        break;
      }
      rt_lock(rt);
      rt->ssh_tunnel = tunnel;
      rt_unlock(rt);
    }
#else
    {
      char key_path[512];
      const char *pw = NULL;
      const char *kp = NULL;
      sa_ssh_cli_tunnel_t *cli;

      if (use_key_auth) {
        sa_ssh_key_priv_path(key_path, sizeof(key_path));
        kp = key_path;
      } else {
        pw = password;
      }

      cli = sa_ssh_cli_start(
          cfg.host,
          cfg.user,
          pw,
          kp,
          port,
          cfg.chrome_port,
          &bound,
          err,
          sizeof(err));
      if (cli == NULL) {
        continue;
      }
      if (atomic_load(&rt->stop_requested)) {
        sa_ssh_cli_stop(cli);
        break;
      }
      rt_lock(rt);
      rt->ssh_cli = cli;
      rt_unlock(rt);
    }
#endif

    for (int i = 0; i < 20; i++) {
      if (atomic_load(&rt->stop_requested)) {
        break;
      }
      if (i == 0 || i == 8) {
        emit_status(rt, SA_CONN_CONNECTING, "Verifying SSH CDP tunnel...", "", ui_url);
      }
#ifdef _WIN32
      {
        sa_ssh_tunnel_t *tunnel;

        rt_lock(rt);
        tunnel = rt->ssh_tunnel;
        rt_unlock(rt);
        if (tunnel != NULL && sa_ssh_tunnel_verify_cdp(tunnel, bound > 0 ? bound : port) == 0) {
          remote_port = bound > 0 ? bound : port;
          break;
        }
      }
#else
      {
        sa_ssh_cli_tunnel_t *cli;

        rt_lock(rt);
        cli = rt->ssh_cli;
        rt_unlock(rt);
        if (cli != NULL && sa_ssh_cli_verify_cdp(cli, bound > 0 ? bound : port) == 0) {
          remote_port = bound > 0 ? bound : port;
          break;
        }
      }
#endif
      {
        int delay_ms = 200 + (i * 100);
        if (delay_ms > 800) {
          delay_ms = 800;
        }
#ifdef _WIN32
        Sleep(delay_ms);
#else
        usleep((useconds_t)delay_ms * 1000);
#endif
      }
    }

    if (remote_port > 0) {
      break;
    }

    snprintf(
        err,
        sizeof(err),
        "CDP verification failed on gaming PC port %d. Check SSH forwarding and that curl is installed on the gaming PC.",
        bound > 0 ? bound : port);
#ifdef _WIN32
    rt_lock(rt);
    if (rt->ssh_tunnel != NULL) {
      sa_ssh_tunnel_t *tunnel = rt->ssh_tunnel;
      rt->ssh_tunnel = NULL;
      rt_unlock(rt);
      sa_ssh_tunnel_stop(tunnel);
    } else {
      rt_unlock(rt);
    }
#else
    rt_lock(rt);
    if (rt->ssh_cli != NULL) {
      sa_ssh_cli_tunnel_t *cli = rt->ssh_cli;
      rt->ssh_cli = NULL;
      rt_unlock(rt);
      sa_ssh_cli_stop(cli);
    } else {
      rt_unlock(rt);
    }
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
    if (!atomic_load(&rt->stop_requested)) {
      emit_status(rt, SA_CONN_ERROR, err, "", ui_url);
    }
    runtime_worker_finish(rt);
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
  snprintf(rt->active_cdp_url, sizeof(rt->active_cdp_url), "%s", cdp_url);
  snprintf(rt->active_ui_url, sizeof(rt->active_ui_url), "%s", ui_url);
  atomic_store(&rt->connected, 1);
  emit_status(rt, SA_CONN_CONNECTED, err, cdp_url, ui_url);

  runtime_wait_connected(rt);

  emit_status(rt, SA_CONN_IDLE, "Disconnected.", "", "");
  runtime_worker_finish(rt);

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
  atomic_store(&rt->worker_active, 0);
  atomic_store(&rt->stop_requested, 0);
  atomic_store(&rt->connected, 0);
#ifdef _WIN32
  InitializeCriticalSection(&rt->lock);
#else
  pthread_mutex_init(&rt->lock, NULL);
#endif
  return rt;
}

void sa_runtime_disconnect(sa_runtime_t *rt) {
  if (rt == NULL) {
    return;
  }
  atomic_store(&rt->stop_requested, 1);
  atomic_store(&rt->connected, 0);
}

int sa_runtime_is_busy(const sa_runtime_t *rt) {
  return rt != NULL && atomic_load(&rt->worker_active) != 0;
}

int sa_runtime_is_connected(const sa_runtime_t *rt) {
  return rt != NULL && atomic_load(&rt->connected) != 0;
}

void sa_runtime_reset_chrome(sa_runtime_t *rt) {
  if (rt == NULL || !sa_runtime_is_connected(rt)) {
    return;
  }
  atomic_store(&rt->reset_requested, 1);
}

void sa_runtime_connect(
    sa_runtime_t *rt,
    const sa_config_t *cfg,
    const char *password,
    int use_key_auth,
    int bootstrap_key,
    int chrome_ready) {
  connect_args_t *args;
  int expected = 0;

  if (rt == NULL || cfg == NULL) {
    return;
  }

  if (!atomic_compare_exchange_strong(&rt->worker_active, &expected, 1)) {
    return;
  }

  atomic_store(&rt->stop_requested, 0);
  atomic_store(&rt->reset_requested, 0);

  args = calloc(1, sizeof(*args));
  if (args == NULL) {
    atomic_store(&rt->worker_active, 0);
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
  if (rt->worker == NULL) {
    free(args);
    atomic_store(&rt->worker_active, 0);
    emit_status(rt, SA_CONN_ERROR, "Failed to start connection worker.", "", "");
    return;
  }
  rt->worker_started = 1;
#else
  if (pthread_create(&rt->worker, NULL, runtime_worker, args) != 0) {
    free(args);
    atomic_store(&rt->worker_active, 0);
    emit_status(rt, SA_CONN_ERROR, "Failed to start connection worker.", "", "");
    return;
  }
  rt->worker_started = 1;
#endif
}

void sa_runtime_destroy(sa_runtime_t *rt) {
  if (rt == NULL) {
    return;
  }
  sa_runtime_disconnect(rt);
  runtime_join_worker(rt);
#ifdef _WIN32
  DeleteCriticalSection(&rt->lock);
#else
  pthread_mutex_destroy(&rt->lock);
#endif
  free(rt);
}
