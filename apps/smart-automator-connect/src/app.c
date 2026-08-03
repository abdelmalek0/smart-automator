#include "app.h"

#include "common.h"
#include "runtime.h"
#include "tls_http.h"
#include "worker_session.h"

#include <gtk/gtk.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef _WIN32
#include <glib-unix.h>
#include <signal.h>
#endif

typedef struct {
  GtkWidget *window;
  GtkWidget *stack;
  GtkWidget *login_server;
  GtkWidget *login_user;
  GtkWidget *login_pass;
  GtkWidget *login_btn;
  GtkWidget *login_error;
  GtkWidget *status_label;
  GtkWidget *user_label;
  GtkWidget *server_label;
  GtkWidget *logout_btn;
  sa_worker_session_t session;
  sa_runtime_t *runtime;
} app_ctx_t;

#ifndef _WIN32
static GtkWidget *g_signal_window = NULL;

static gboolean on_unix_signal(gpointer user_data) {
  (void)user_data;
  if (g_signal_window != NULL) {
    gtk_widget_destroy(g_signal_window);
    g_signal_window = NULL;
  }
  return G_SOURCE_REMOVE;
}
#endif

typedef struct {
  app_ctx_t *app;
  sa_conn_state_t state;
  char status[512];
} ui_event_t;

static void show_login(app_ctx_t *app) {
  gtk_stack_set_visible_child_name(GTK_STACK(app->stack), "login");
}

static void show_status(app_ctx_t *app) {
  gtk_stack_set_visible_child_name(GTK_STACK(app->stack), "status");
  gtk_label_set_text(GTK_LABEL(app->user_label), app->session.username[0] ? app->session.username : "—");
  gtk_label_set_text(GTK_LABEL(app->server_label), app->session.server_url[0] ? app->session.server_url : "—");
}

static gboolean apply_ui_event(gpointer data) {
  ui_event_t *event = (ui_event_t *)data;
  app_ctx_t *app = event->app;
  gtk_label_set_text(GTK_LABEL(app->status_label), event->status);
  if (event->state == SA_CONN_ERROR) {
    /* Keep reconnecting in background; surface message in status label. */
  }
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

static void do_logout(app_ctx_t *app) {
  sa_runtime_disconnect(app->runtime);
  sa_worker_session_clear(&app->session);
  sa_worker_session_save(&app->session);
  gtk_entry_set_text(GTK_ENTRY(app->login_pass), "");
  gtk_label_set_text(GTK_LABEL(app->login_error), "");
  show_login(app);
}

static void on_logout_clicked(GtkButton *button, gpointer user_data) {
  (void)button;
  do_logout((app_ctx_t *)user_data);
}

static void on_login_clicked(GtkButton *button, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  const char *server = gtk_entry_get_text(GTK_ENTRY(app->login_server));
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

  if (server == NULL || server[0] == '\0' || user == NULL || user[0] == '\0' || password == NULL || password[0] == '\0') {
    gtk_label_set_text(GTK_LABEL(app->login_error), "Server URL, username, and password are required.");
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

  snprintf(server_url, sizeof(server_url), "%s", server);
  normalize_server_url(server_url, sizeof(server_url));
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
  GtkWidget *hint = gtk_label_new("Sign in once. Connect stays online and starts Chrome only when a run begins.");

  gtk_widget_set_margin_start(box, 24);
  gtk_widget_set_margin_end(box, 24);
  gtk_widget_set_margin_top(box, 24);
  gtk_widget_set_margin_bottom(box, 24);
  gtk_label_set_markup(GTK_LABEL(title), "<span size='large'><b>Smart Automator Connect</b></span>");
  gtk_label_set_line_wrap(GTK_LABEL(hint), TRUE);
  gtk_widget_set_halign(title, GTK_ALIGN_START);
  gtk_widget_set_halign(hint, GTK_ALIGN_START);

  app->login_server = gtk_entry_new();
  gtk_entry_set_placeholder_text(GTK_ENTRY(app->login_server), "https://qa.example.com");
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
  gtk_box_pack_start(GTK_BOX(box), gtk_label_new("Server URL"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->login_server, FALSE, FALSE, 0);
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
  app->logout_btn = gtk_button_new_with_label("Log out");
  gtk_label_set_line_wrap(GTK_LABEL(app->status_label), TRUE);
  gtk_label_set_line_wrap(GTK_LABEL(app->server_label), TRUE);
  gtk_widget_set_halign(app->status_label, GTK_ALIGN_START);
  gtk_widget_set_halign(app->user_label, GTK_ALIGN_START);
  gtk_widget_set_halign(app->server_label, GTK_ALIGN_START);

  g_signal_connect(app->logout_btn, "clicked", G_CALLBACK(on_logout_clicked), app);

  gtk_box_pack_start(GTK_BOX(box), title, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), gtk_label_new("Status"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->status_label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), gtk_label_new("User"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->user_label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), gtk_label_new("Server"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->server_label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), app->logout_btn, FALSE, FALSE, 12);
  return box;
}

static void on_destroy(GtkWidget *widget, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  (void)widget;
  if (app->runtime) {
    sa_runtime_destroy(app->runtime);
    app->runtime = NULL;
  }
}

int sa_app_run(int argc, char **argv) {
  app_ctx_t app;
  GtkWidget *login_page;
  GtkWidget *status_page;

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
  g_signal_connect(app.window, "destroy", G_CALLBACK(on_destroy), &app);
  g_signal_connect(app.window, "destroy", G_CALLBACK(gtk_main_quit), NULL);

#ifndef _WIN32
  g_signal_window = app.window;
  g_unix_signal_add(SIGINT, on_unix_signal, NULL);
  g_unix_signal_add(SIGTERM, on_unix_signal, NULL);
#endif

  app.stack = gtk_stack_new();
  login_page = build_login_page(&app);
  status_page = build_status_page(&app);
  gtk_stack_add_named(GTK_STACK(app.stack), login_page, "login");
  gtk_stack_add_named(GTK_STACK(app.stack), status_page, "status");
  gtk_container_add(GTK_CONTAINER(app.window), app.stack);

  sa_worker_session_load(&app.session);
  if (app.session.server_url[0]) {
    gtk_entry_set_text(GTK_ENTRY(app.login_server), app.session.server_url);
  }
  if (app.session.username[0]) {
    gtk_entry_set_text(GTK_ENTRY(app.login_user), app.session.username);
  }

  if (sa_worker_session_has_token(&app.session)) {
    show_status(&app);
    sa_runtime_connect(app.runtime, &app.session);
  } else {
    show_login(&app);
  }

  gtk_widget_show_all(app.window);
  gtk_main();
  return 0;
}
