#include "app.h"

#include "common.h"
#include "runtime.h"
#include "tls_http.h"
#include "util.h"
#include "worker_session.h"

#include <gtk/gtk.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef _WIN32
#include <glib-unix.h>
#include <signal.h>
#else
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>
#endif

typedef struct {
  GtkWidget *window;
  GtkWidget *stack;
  GtkWidget *login_user;
  GtkWidget *login_pass;
  GtkWidget *login_btn;
  GtkWidget *login_error;
  GtkWidget *status_label;
  GtkWidget *user_label;
  GtkWidget *server_label;
  GtkWidget *reconnect_btn;
  GtkWidget *logout_btn;
#ifndef _WIN32
  GtkStatusIcon *tray_icon;
  GtkWidget *tray_menu;
#else
  NOTIFYICONDATAW nid;
  HWND tray_hwnd;
  UINT tray_msg_id;
  int tray_added;
#endif
  int quitting;
  sa_conn_state_t last_conn_state;
  sa_worker_session_t session;
  sa_runtime_t *runtime;
} app_ctx_t;

typedef struct {
  app_ctx_t *app;
  sa_conn_state_t state;
  char status[512];
} ui_event_t;

static void do_quit(app_ctx_t *app);

#ifndef _WIN32
static app_ctx_t *g_signal_app = NULL;

static gboolean on_unix_signal(gpointer user_data) {
  (void)user_data;
  if (g_signal_app != NULL) {
    do_quit(g_signal_app);
    g_signal_app = NULL;
  }
  return G_SOURCE_REMOVE;
}
#endif

static void show_window(app_ctx_t *app) {
  if (app == NULL || app->window == NULL) {
    return;
  }
  gtk_widget_show(app->window);
  gtk_window_present(GTK_WINDOW(app->window));
}

static void hide_window(app_ctx_t *app) {
  if (app == NULL || app->window == NULL) {
    return;
  }
  gtk_widget_hide(app->window);
}

static void show_login(app_ctx_t *app) {
  gtk_stack_set_visible_child_name(GTK_STACK(app->stack), "login");
  show_window(app);
}

static void show_status(app_ctx_t *app) {
  gtk_stack_set_visible_child_name(GTK_STACK(app->stack), "status");
  gtk_label_set_text(GTK_LABEL(app->user_label), app->session.username[0] ? app->session.username : "—");
  gtk_label_set_text(GTK_LABEL(app->server_label), app->session.server_url[0] ? app->session.server_url : "—");
}

static void normalize_server_url(char *url, size_t url_len) {
  size_t len;
  if (url == NULL || url[0] == '\0') {
    return;
  }
  /* Trim trailing slash */
  len = strlen(url);
  while (len > 0 && url[len - 1] == '/') {
    url[--len] = '\0';
  }
  if (strncmp(url, "http://", 7) != 0 && strncmp(url, "https://", 8) != 0) {
    char tmp[512];
    snprintf(tmp, sizeof(tmp), "https://%s", url);
    snprintf(url, url_len, "%s", tmp);
  }
}

/* Refresh session.server_url from connect.conf (or built-in default). Returns 0 on success. */
static int apply_server_url_from_config(app_ctx_t *app, char *err, size_t err_len) {
  char server_url[512];

  if (sa_connect_config_load(server_url, sizeof(server_url)) != 0) {
    if (err != NULL && err_len > 0) {
      snprintf(err, err_len, "Failed to resolve server URL");
    }
    return -1;
  }
  normalize_server_url(server_url, sizeof(server_url));
  if (server_url[0] == '\0') {
    if (err != NULL && err_len > 0) {
      snprintf(err, err_len, "Failed to resolve server URL");
    }
    return -1;
  }
  snprintf(app->session.server_url, sizeof(app->session.server_url), "%s", server_url);
  return 0;
}

static void do_quit(app_ctx_t *app) {
  if (app == NULL || app->quitting) {
    return;
  }
  app->quitting = 1;
  /* Mark early so delete-event / nested callbacks allow destroy. */
#ifdef _WIN32
  if (app->tray_added) {
    Shell_NotifyIconW(NIM_DELETE, &app->nid);
    app->tray_added = 0;
  }
  if (app->tray_hwnd != NULL) {
    DestroyWindow(app->tray_hwnd);
    app->tray_hwnd = NULL;
  }
#else
  if (app->tray_icon != NULL) {
    G_GNUC_BEGIN_IGNORE_DEPRECATIONS
    gtk_status_icon_set_visible(app->tray_icon, FALSE);
    G_GNUC_END_IGNORE_DEPRECATIONS
  }
#endif
  if (app->window != NULL) {
    gtk_widget_destroy(app->window);
  }
}

static void do_logout(app_ctx_t *app) {
  sa_runtime_disconnect(app->runtime);
  sa_worker_session_clear(&app->session);
  sa_worker_session_save(&app->session);
  app->last_conn_state = SA_CONN_IDLE;
  gtk_entry_set_text(GTK_ENTRY(app->login_pass), "");
  gtk_label_set_text(GTK_LABEL(app->login_error), "");
  show_login(app);
}

static gboolean apply_ui_event(gpointer data) {
  ui_event_t *event = (ui_event_t *)data;
  app_ctx_t *app = event->app;
  sa_conn_state_t prev = app->last_conn_state;
  gtk_label_set_text(GTK_LABEL(app->status_label), event->status);
  if (app->reconnect_btn != NULL) {
    /* Offer reconnect after give-up while a session token is still saved. */
    gtk_widget_set_sensitive(
        app->reconnect_btn,
        event->state == SA_CONN_ERROR && sa_worker_session_has_token(&app->session));
  }
  /* Auto-hide only on the transition into connected (not every CONNECTED status update). */
  if (event->state == SA_CONN_CONNECTED && prev != SA_CONN_CONNECTED) {
    hide_window(app);
  } else if (event->state == SA_CONN_ERROR) {
    show_window(app);
  }
  app->last_conn_state = event->state;
  free(event);
  return G_SOURCE_REMOVE;
}

static void on_runtime_status(void *userdata, sa_conn_state_t state, const char *status) {
  app_ctx_t *app = (app_ctx_t *)userdata;
  ui_event_t *event = (ui_event_t *)calloc(1, sizeof(*event));
  if (event == NULL) {
    return;
  }
  event->app = app;
  event->state = state;
  snprintf(event->status, sizeof(event->status), "%s", status ? status : "");
  g_idle_add(apply_ui_event, event);
}

static void on_logout_clicked(GtkButton *button, gpointer user_data) {
  (void)button;
  do_logout((app_ctx_t *)user_data);
}

static void on_reconnect_clicked(GtkButton *button, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  char err[256];
  (void)button;
  if (!sa_worker_session_has_token(&app->session)) {
    show_login(app);
    return;
  }
  if (apply_server_url_from_config(app, err, sizeof(err)) != 0) {
    gtk_label_set_text(GTK_LABEL(app->status_label), err);
    show_window(app);
    return;
  }
  gtk_label_set_text(GTK_LABEL(app->server_label), app->session.server_url);
  if (sa_runtime_is_busy(app->runtime)) {
    gtk_label_set_text(GTK_LABEL(app->status_label), "Still shutting down… click Reconnect again shortly");
    return;
  }
  gtk_widget_set_sensitive(app->reconnect_btn, FALSE);
  gtk_label_set_text(GTK_LABEL(app->status_label), "Reconnecting…");
  sa_runtime_connect(app->runtime, &app->session);
}

static void on_login_clicked(GtkButton *button, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  const char *user = gtk_entry_get_text(GTK_ENTRY(app->login_user));
  const char *password = gtk_entry_get_text(GTK_ENTRY(app->login_pass));
  char server_url[512];
  char login_url[640];
  char body[1024];
  char user_esc[256];
  char pass_esc[512];
  char response[2048];
  char err[512];
  char token[256];
  int status = 0;
  size_t ui = 0;
  size_t pi = 0;
  size_t i;

  (void)button;
  gtk_label_set_text(GTK_LABEL(app->login_error), "");

  if (user == NULL || user[0] == '\0' || password == NULL || password[0] == '\0') {
    gtk_label_set_text(GTK_LABEL(app->login_error), "Username and password are required.");
    return;
  }

  if (sa_connect_config_load(server_url, sizeof(server_url)) != 0) {
    gtk_label_set_text(GTK_LABEL(app->login_error), "Failed to resolve server URL");
    return;
  }
  normalize_server_url(server_url, sizeof(server_url));
  if (server_url[0] == '\0') {
    gtk_label_set_text(GTK_LABEL(app->login_error), "Failed to resolve server URL");
    return;
  }

  user_esc[0] = '\0';
  pass_esc[0] = '\0';
  for (i = 0; user[i] && ui + 2 < sizeof(user_esc); i++) {
    if (user[i] == '\\' || user[i] == '"') {
      user_esc[ui++] = '\\';
    }
    user_esc[ui++] = user[i];
    user_esc[ui] = '\0';
  }
  for (i = 0; password[i] && pi + 2 < sizeof(pass_esc); i++) {
    if (password[i] == '\\' || password[i] == '"') {
      pass_esc[pi++] = '\\';
    }
    pass_esc[pi++] = password[i];
    pass_esc[pi] = '\0';
  }

  snprintf(login_url, sizeof(login_url), "%s/api/workers/login", server_url);
  snprintf(body, sizeof(body), "{\"username\":\"%s\",\"password\":\"%s\"}", user_esc, pass_esc);

  gtk_widget_set_sensitive(app->login_btn, FALSE);
  gtk_label_set_text(GTK_LABEL(app->login_error), "Signing in…");

  err[0] = '\0';
  response[0] = '\0';
  if (sa_http_post_json(login_url, body, response, sizeof(response), &status, err, sizeof(err)) != 0) {
    gtk_label_set_text(GTK_LABEL(app->login_error), err[0] ? err : "Login request failed");
    gtk_widget_set_sensitive(app->login_btn, TRUE);
    return;
  }
  if (status != 200 || sa_json_get_string(response, "worker_token", token, sizeof(token)) != 0) {
    char msg[256];
    if (status == 401) {
      snprintf(msg, sizeof(msg), "Invalid username or password");
    } else {
      snprintf(msg, sizeof(msg), "Login failed (HTTP %d)", status);
    }
    gtk_label_set_text(GTK_LABEL(app->login_error), msg);
    gtk_widget_set_sensitive(app->login_btn, TRUE);
    return;
  }

  memset(&app->session, 0, sizeof(app->session));
  snprintf(app->session.server_url, sizeof(app->session.server_url), "%s", server_url);
  snprintf(app->session.worker_token, sizeof(app->session.worker_token), "%s", token);
  snprintf(app->session.username, sizeof(app->session.username), "%s", user);
  sa_worker_session_save(&app->session);

  gtk_entry_set_text(GTK_ENTRY(app->login_pass), "");
  gtk_widget_set_sensitive(app->login_btn, TRUE);
  show_status(app);
  sa_runtime_connect(app->runtime, &app->session);
}

static GtkWidget *build_login_page(app_ctx_t *app) {
  GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
  GtkWidget *title = gtk_label_new(NULL);
  GtkWidget *hint = gtk_label_new("Sign in with your account.");

  gtk_widget_set_margin_start(box, 24);
  gtk_widget_set_margin_end(box, 24);
  gtk_widget_set_margin_top(box, 24);
  gtk_widget_set_margin_bottom(box, 24);
  gtk_label_set_markup(GTK_LABEL(title), "<span size='large'><b>Smart Automator Connect</b></span>");
  gtk_label_set_line_wrap(GTK_LABEL(hint), TRUE);
  gtk_widget_set_halign(title, GTK_ALIGN_START);
  gtk_widget_set_halign(hint, GTK_ALIGN_START);

  app->login_user = gtk_entry_new();
  gtk_entry_set_placeholder_text(GTK_ENTRY(app->login_user), "Username");
  app->login_pass = gtk_entry_new();
  gtk_entry_set_placeholder_text(GTK_ENTRY(app->login_pass), "Password");
  gtk_entry_set_visibility(GTK_ENTRY(app->login_pass), FALSE);
  app->login_btn = gtk_button_new_with_label("Connect");
  app->login_error = gtk_label_new("");
  gtk_label_set_line_wrap(GTK_LABEL(app->login_error), TRUE);
  gtk_widget_set_halign(app->login_error, GTK_ALIGN_START);

  g_signal_connect(app->login_btn, "clicked", G_CALLBACK(on_login_clicked), app);

  gtk_box_pack_start(GTK_BOX(box), title, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), hint, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), gtk_label_new("Username"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->login_user, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), gtk_label_new("Password"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->login_pass, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->login_btn, FALSE, FALSE, 8);
  gtk_box_pack_start(GTK_BOX(box), app->login_error, FALSE, FALSE, 0);
  return box;
}

static GtkWidget *build_status_page(app_ctx_t *app) {
  GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
  GtkWidget *title = gtk_label_new(NULL);

  gtk_widget_set_margin_start(box, 24);
  gtk_widget_set_margin_end(box, 24);
  gtk_widget_set_margin_top(box, 24);
  gtk_widget_set_margin_bottom(box, 24);
  gtk_label_set_markup(GTK_LABEL(title), "<span size='large'><b>Connected</b></span>");
  gtk_widget_set_halign(title, GTK_ALIGN_START);

  app->status_label = gtk_label_new("Starting…");
  app->user_label = gtk_label_new("—");
  app->server_label = gtk_label_new("—");
  app->reconnect_btn = gtk_button_new_with_label("Reconnect");
  app->logout_btn = gtk_button_new_with_label("Log out");
  gtk_label_set_line_wrap(GTK_LABEL(app->status_label), TRUE);
  gtk_label_set_line_wrap(GTK_LABEL(app->server_label), TRUE);
  gtk_widget_set_halign(app->status_label, GTK_ALIGN_START);
  gtk_widget_set_halign(app->user_label, GTK_ALIGN_START);
  gtk_widget_set_halign(app->server_label, GTK_ALIGN_START);
  gtk_widget_set_sensitive(app->reconnect_btn, FALSE);

  g_signal_connect(app->reconnect_btn, "clicked", G_CALLBACK(on_reconnect_clicked), app);
  g_signal_connect(app->logout_btn, "clicked", G_CALLBACK(on_logout_clicked), app);

  gtk_box_pack_start(GTK_BOX(box), title, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), gtk_label_new("Status"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->status_label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), gtk_label_new("User"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->user_label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), gtk_label_new("Server"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->server_label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->reconnect_btn, FALSE, FALSE, 8);
  gtk_box_pack_start(GTK_BOX(box), app->logout_btn, FALSE, FALSE, 4);
  return box;
}

static gboolean on_delete_event(GtkWidget *widget, GdkEvent *event, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  (void)widget;
  (void)event;
  if (app->quitting) {
    return FALSE; /* allow destroy */
  }
  hide_window(app);
  return TRUE; /* keep running in tray */
}

static void on_destroy(GtkWidget *widget, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  (void)widget;
  app->quitting = 1;
#ifdef _WIN32
  if (app->tray_added) {
    Shell_NotifyIconW(NIM_DELETE, &app->nid);
    app->tray_added = 0;
  }
  if (app->tray_hwnd != NULL) {
    DestroyWindow(app->tray_hwnd);
    app->tray_hwnd = NULL;
  }
#else
  if (app->tray_icon != NULL) {
    g_object_unref(app->tray_icon);
    app->tray_icon = NULL;
  }
  if (app->tray_menu != NULL) {
    gtk_widget_destroy(app->tray_menu);
    app->tray_menu = NULL;
  }
#endif
  if (app->runtime) {
    sa_runtime_destroy(app->runtime);
    app->runtime = NULL;
  }
}

#ifndef _WIN32
static void on_tray_show(GtkMenuItem *item, gpointer user_data) {
  (void)item;
  show_window((app_ctx_t *)user_data);
}

static void on_tray_logout(GtkMenuItem *item, gpointer user_data) {
  (void)item;
  do_logout((app_ctx_t *)user_data);
}

static void on_tray_quit(GtkMenuItem *item, gpointer user_data) {
  (void)item;
  do_quit((app_ctx_t *)user_data);
}

static void on_tray_popup(GtkStatusIcon *status_icon, guint button, guint activate_time, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  (void)status_icon;
  (void)button;
  (void)activate_time;
  gtk_menu_popup_at_pointer(GTK_MENU(app->tray_menu), NULL);
}

static void on_tray_activate(GtkStatusIcon *status_icon, gpointer user_data) {
  (void)status_icon;
  show_window((app_ctx_t *)user_data);
}

static void setup_tray(app_ctx_t *app) {
  GtkWidget *item_show;
  GtkWidget *item_logout;
  GtkWidget *item_quit;

  G_GNUC_BEGIN_IGNORE_DEPRECATIONS
  app->tray_icon = gtk_status_icon_new_from_icon_name("network-transmit-receive");
  gtk_status_icon_set_tooltip_text(app->tray_icon, "Smart Automator Connect");
  gtk_status_icon_set_visible(app->tray_icon, TRUE);
  G_GNUC_END_IGNORE_DEPRECATIONS

  app->tray_menu = gtk_menu_new();
  item_show = gtk_menu_item_new_with_label("Show window");
  item_logout = gtk_menu_item_new_with_label("Log out");
  item_quit = gtk_menu_item_new_with_label("Quit");
  g_signal_connect(item_show, "activate", G_CALLBACK(on_tray_show), app);
  g_signal_connect(item_logout, "activate", G_CALLBACK(on_tray_logout), app);
  g_signal_connect(item_quit, "activate", G_CALLBACK(on_tray_quit), app);
  gtk_menu_shell_append(GTK_MENU_SHELL(app->tray_menu), item_show);
  gtk_menu_shell_append(GTK_MENU_SHELL(app->tray_menu), item_logout);
  gtk_menu_shell_append(GTK_MENU_SHELL(app->tray_menu), item_quit);
  gtk_widget_show_all(app->tray_menu);

  G_GNUC_BEGIN_IGNORE_DEPRECATIONS
  g_signal_connect(app->tray_icon, "activate", G_CALLBACK(on_tray_activate), app);
  g_signal_connect(app->tray_icon, "popup-menu", G_CALLBACK(on_tray_popup), app);
  G_GNUC_END_IGNORE_DEPRECATIONS
}
#else
/* Windows tray: message-only window + Shell_NotifyIcon */

#define SA_TRAY_SHOW 1
#define SA_TRAY_LOGOUT 2
#define SA_TRAY_QUIT 3

static app_ctx_t *g_win_tray_app = NULL;

static void win_show_tray_menu(HWND hwnd) {
  POINT pt;
  HMENU menu;
  UINT cmd;

  GetCursorPos(&pt);
  menu = CreatePopupMenu();
  AppendMenuW(menu, MF_STRING, SA_TRAY_SHOW, L"Show window");
  AppendMenuW(menu, MF_STRING, SA_TRAY_LOGOUT, L"Log out");
  AppendMenuW(menu, MF_STRING, SA_TRAY_QUIT, L"Quit");
  SetForegroundWindow(hwnd);
  cmd = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, hwnd, NULL);
  DestroyMenu(menu);
  if (g_win_tray_app == NULL) {
    return;
  }
  if (cmd == SA_TRAY_SHOW) {
    show_window(g_win_tray_app);
  } else if (cmd == SA_TRAY_LOGOUT) {
    do_logout(g_win_tray_app);
  } else if (cmd == SA_TRAY_QUIT) {
    do_quit(g_win_tray_app);
  }
}

static LRESULT CALLBACK tray_wnd_proc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
  app_ctx_t *app = g_win_tray_app;
  if (app != NULL && msg == app->tray_msg_id) {
    if (LOWORD(lParam) == WM_LBUTTONUP) {
      show_window(app);
    } else if (LOWORD(lParam) == WM_RBUTTONUP) {
      win_show_tray_menu(hwnd);
    }
    return 0;
  }
  return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static int setup_tray(app_ctx_t *app) {
  WNDCLASSW wc;
  HICON icon;

  memset(&wc, 0, sizeof(wc));
  wc.lpfnWndProc = tray_wnd_proc;
  wc.hInstance = GetModuleHandleW(NULL);
  wc.lpszClassName = L"SmartAutomatorConnectTray";
  RegisterClassW(&wc);

  app->tray_msg_id = RegisterWindowMessageW(L"SmartAutomatorConnectTrayMsg");
  app->tray_hwnd = CreateWindowExW(
      0, L"SmartAutomatorConnectTray", L"", 0, 0, 0, 0, 0, HWND_MESSAGE, NULL, wc.hInstance, NULL);
  if (app->tray_hwnd == NULL) {
    return -1;
  }

  g_win_tray_app = app;
  memset(&app->nid, 0, sizeof(app->nid));
  app->nid.cbSize = sizeof(app->nid);
  app->nid.hWnd = app->tray_hwnd;
  app->nid.uID = 1;
  app->nid.uFlags = NIF_ICON | NIF_TIP | NIF_MESSAGE;
  app->nid.uCallbackMessage = app->tray_msg_id;
  icon = LoadIconW(NULL, IDI_APPLICATION);
  app->nid.hIcon = icon;
  wcsncpy(app->nid.szTip, L"Smart Automator Connect", sizeof(app->nid.szTip) / sizeof(wchar_t) - 1);
  if (!Shell_NotifyIconW(NIM_ADD, &app->nid)) {
    return -1;
  }
  app->tray_added = 1;
  return 0;
}
#endif

int sa_app_run(int argc, char **argv) {
  app_ctx_t app;
  GtkWidget *login_page;
  GtkWidget *status_page;
  char cfg_err[256];

  memset(&app, 0, sizeof(app));
  gtk_init(&argc, &argv);

  app.runtime = sa_runtime_create(on_runtime_status, &app);
  if (app.runtime == NULL) {
    fprintf(stderr, "Failed to create runtime\n");
    return 1;
  }

  app.window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
  gtk_window_set_title(GTK_WINDOW(app.window), "Smart Automator Connect");
  gtk_window_set_default_size(GTK_WINDOW(app.window), 420, 360);
  g_signal_connect(app.window, "delete-event", G_CALLBACK(on_delete_event), &app);
  g_signal_connect(app.window, "destroy", G_CALLBACK(on_destroy), &app);
  g_signal_connect(app.window, "destroy", G_CALLBACK(gtk_main_quit), NULL);

#ifndef _WIN32
  g_signal_app = &app;
  g_unix_signal_add(SIGINT, on_unix_signal, NULL);
  g_unix_signal_add(SIGTERM, on_unix_signal, NULL);
#endif

  app.stack = gtk_stack_new();
  login_page = build_login_page(&app);
  status_page = build_status_page(&app);
  gtk_stack_add_named(GTK_STACK(app.stack), login_page, "login");
  gtk_stack_add_named(GTK_STACK(app.stack), status_page, "status");
  gtk_container_add(GTK_CONTAINER(app.window), app.stack);

  setup_tray(&app);

  sa_worker_session_load(&app.session);
  if (app.session.username[0]) {
    gtk_entry_set_text(GTK_ENTRY(app.login_user), app.session.username);
  }

  /* Prefer connect.conf URL over any stale value in worker.conf. */
  if (apply_server_url_from_config(&app, cfg_err, sizeof(cfg_err)) != 0) {
    gtk_label_set_text(GTK_LABEL(app.login_error), cfg_err);
  }

  if (sa_worker_session_has_token(&app.session)) {
    /* Re-apply config URL after has_token check (token still valid with updated host). */
    if (apply_server_url_from_config(&app, NULL, 0) == 0) {
      sa_worker_session_save(&app.session);
    }
    show_status(&app);
    sa_runtime_connect(app.runtime, &app.session);
  } else {
    show_login(&app);
  }

  gtk_widget_show_all(app.window);
  /* If we already have a token we will auto-hide once WS connects; keep window
   * visible during login / connecting so errors are visible. */
  gtk_main();
  return 0;
}
