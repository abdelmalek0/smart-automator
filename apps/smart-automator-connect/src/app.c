#include "app.h"

#include "chrome.h"
#include "common.h"
#include "config.h"
#include "connections.h"
#include "runtime.h"
#include "util.h"

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
  GtkWidget *connections_box;
  GtkWidget *add_btn;
  GtkWidget *disconnect_btn;
  GtkWidget *status_label;
  GtkWidget *cdp_label;
  GtkWidget *ui_label;
  sa_connections_t connections;
  sa_runtime_t *runtime;
  char active_connection_id[SA_CONNECTION_ID_LEN];
  int pending_bootstrap;
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
  char cdp_url[256];
  char ui_url[256];
} ui_event_t;

static sa_mode_t mode_from_combo(int index) {
  switch (index) {
    case 1:
      return SA_MODE_LAN;
    case 2:
      return SA_MODE_REMOTE;
    default:
      return SA_MODE_AUTO;
  }
}

static int combo_from_mode(sa_mode_t mode) {
  switch (mode) {
    case SA_MODE_LAN:
      return 1;
    case SA_MODE_REMOTE:
      return 2;
    default:
      return 0;
  }
}

static void set_list_sensitive(app_ctx_t *app, gboolean sensitive) {
  gtk_widget_set_sensitive(app->connections_box, sensitive);
  gtk_widget_set_sensitive(app->add_btn, sensitive);
}

static void refresh_connections_list(app_ctx_t *app);
static void on_connect_row_clicked(GtkButton *button, gpointer user_data);
static void on_edit_row_clicked(GtkButton *button, gpointer user_data);
static void on_delete_row_clicked(GtkButton *button, gpointer user_data);

static gboolean apply_ui_event(gpointer data) {
  ui_event_t *event = (ui_event_t *)data;
  app_ctx_t *app = event->app;

  gtk_label_set_text(GTK_LABEL(app->status_label), event->status);
  gtk_label_set_text(GTK_LABEL(app->cdp_label), event->cdp_url[0] ? event->cdp_url : "—");
  gtk_label_set_text(GTK_LABEL(app->ui_label), event->ui_url[0] ? event->ui_url : "—");

  if (event->state == SA_CONN_ERROR) {
    GtkWidget *dialog = gtk_message_dialog_new(
        GTK_WINDOW(app->window),
        GTK_DIALOG_MODAL,
        GTK_MESSAGE_ERROR,
        GTK_BUTTONS_OK,
        "%s",
        event->status);
    gtk_dialog_run(GTK_DIALOG(dialog));
    gtk_widget_destroy(dialog);

    if (app->active_connection_id[0] != '\0') {
      sa_connection_t *conn = sa_connections_find(&app->connections, app->active_connection_id);
      if (conn != NULL && conn->key_installed) {
        conn->key_installed = 0;
        sa_connections_save(&app->connections);
        refresh_connections_list(app);
      }
    }
    app->active_connection_id[0] = '\0';
    app->pending_bootstrap = 0;
  } else if (event->state == SA_CONN_CONNECTED) {
    char message[768];
    sa_connection_t *conn;

    if (app->pending_bootstrap && app->active_connection_id[0] != '\0') {
      conn = sa_connections_find(&app->connections, app->active_connection_id);
      if (conn != NULL) {
        conn->key_installed = 1;
        sa_connections_save(&app->connections);
        refresh_connections_list(app);
      }
      app->pending_bootstrap = 0;
    }

    snprintf(
        message,
        sizeof(message),
        "%s\n\nCDP URL (set on gaming PC):\n%s\n\nSmart Automator UI:\n%s",
        event->status,
        event->cdp_url[0] ? event->cdp_url : "—",
        event->ui_url[0] ? event->ui_url : "—");
    GtkWidget *dialog = gtk_message_dialog_new(
        GTK_WINDOW(app->window),
        GTK_DIALOG_MODAL,
        GTK_MESSAGE_INFO,
        GTK_BUTTONS_OK,
        "%s",
        message);
    gtk_dialog_run(GTK_DIALOG(dialog));
    gtk_widget_destroy(dialog);
  }

  if (event->state == SA_CONN_CONNECTING || event->state == SA_CONN_CONNECTED) {
    set_list_sensitive(app, FALSE);
    gtk_widget_set_sensitive(app->disconnect_btn, TRUE);
  } else {
    set_list_sensitive(app, TRUE);
    gtk_widget_set_sensitive(app->disconnect_btn, FALSE);
    if (event->state == SA_CONN_IDLE) {
      app->active_connection_id[0] = '\0';
    }
  }

  free(event);
  return G_SOURCE_REMOVE;
}

static void on_runtime_status(void *userdata, sa_conn_state_t state, const char *status, const char *cdp_url, const char *ui_url) {
  app_ctx_t *app = (app_ctx_t *)userdata;
  ui_event_t *event = calloc(1, sizeof(*event));

  if (event == NULL) {
    return;
  }

  event->app = app;
  event->state = state;
  snprintf(event->status, sizeof(event->status), "%s", status != NULL ? status : "");
  snprintf(event->cdp_url, sizeof(event->cdp_url), "%s", cdp_url != NULL ? cdp_url : "");
  snprintf(event->ui_url, sizeof(event->ui_url), "%s", ui_url != NULL ? ui_url : "");

  g_main_context_invoke(NULL, (GSourceFunc)apply_ui_event, event);
}

static GtkWidget *make_connection_row(app_ctx_t *app, const sa_connection_t *conn) {
  GtkWidget *row;
  GtkWidget *box;
  GtkWidget *text_box;
  GtkWidget *name_label;
  GtkWidget *sub_label;
  GtkWidget *btn_box;
  GtkWidget *connect_btn;
  GtkWidget *edit_btn;
  GtkWidget *delete_btn;
  char subtitle[512];

  row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
  gtk_widget_set_margin_top(row, 6);
  gtk_widget_set_margin_bottom(row, 6);
  g_object_set_data_full(G_OBJECT(row), "connection-id", g_strdup(conn->id), g_free);

  text_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
  gtk_widget_set_hexpand(text_box, TRUE);
  gtk_widget_set_halign(text_box, GTK_ALIGN_START);

  name_label = gtk_label_new(NULL);
  gtk_label_set_xalign(GTK_LABEL(name_label), 0.0);
  gtk_label_set_markup(GTK_LABEL(name_label), conn->name[0] ? conn->name : conn->host);
  gtk_widget_set_halign(name_label, GTK_ALIGN_START);

  snprintf(
      subtitle,
      sizeof(subtitle),
      "%s · %s · %s%s",
      conn->host,
      conn->user,
      sa_mode_label(conn->mode),
      conn->key_installed ? " · key" : "");
  sub_label = gtk_label_new(subtitle);
  gtk_label_set_xalign(GTK_LABEL(sub_label), 0.0);
  gtk_widget_set_halign(sub_label, GTK_ALIGN_START);
  gtk_widget_set_opacity(sub_label, 0.75);

  gtk_box_pack_start(GTK_BOX(text_box), name_label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(text_box), sub_label, FALSE, FALSE, 0);

  btn_box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
  connect_btn = gtk_button_new_with_label("Connect");
  edit_btn = gtk_button_new_with_label("Edit");
  delete_btn = gtk_button_new_with_label("Delete");
  g_object_set_data(G_OBJECT(connect_btn), "connection-id", (gpointer)conn->id);
  g_object_set_data(G_OBJECT(edit_btn), "connection-id", (gpointer)conn->id);
  g_object_set_data(G_OBJECT(delete_btn), "connection-id", (gpointer)conn->id);
  g_signal_connect(connect_btn, "clicked", G_CALLBACK(on_connect_row_clicked), app);
  g_signal_connect(edit_btn, "clicked", G_CALLBACK(on_edit_row_clicked), app);
  g_signal_connect(delete_btn, "clicked", G_CALLBACK(on_delete_row_clicked), app);

  gtk_box_pack_start(GTK_BOX(btn_box), connect_btn, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(btn_box), edit_btn, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(btn_box), delete_btn, FALSE, FALSE, 0);

  box = row;
  gtk_box_pack_start(GTK_BOX(box), text_box, TRUE, TRUE, 0);
  gtk_box_pack_start(GTK_BOX(box), btn_box, FALSE, FALSE, 0);

  return row;
}

static void refresh_connections_list(app_ctx_t *app) {
  GList *children;
  GList *iter;
  int i;

  children = gtk_container_get_children(GTK_CONTAINER(app->connections_box));
  for (iter = children; iter != NULL; iter = iter->next) {
    gtk_widget_destroy(GTK_WIDGET(iter->data));
  }
  g_list_free(children);

  if (app->connections.count == 0) {
    GtkWidget *empty = gtk_label_new("No saved connections. Add one to get started.");
    gtk_label_set_xalign(GTK_LABEL(empty), 0.0);
    gtk_widget_set_margin_top(empty, 8);
    gtk_box_pack_start(GTK_BOX(app->connections_box), empty, FALSE, FALSE, 0);
    gtk_widget_show_all(app->connections_box);
    return;
  }

  for (i = 0; i < app->connections.count; i++) {
    GtkWidget *row = make_connection_row(app, &app->connections.items[i]);
    gtk_box_pack_start(GTK_BOX(app->connections_box), row, FALSE, FALSE, 0);
  }
  gtk_widget_show_all(app->connections_box);
}

static GtkWidget *dialog_labeled_entry(GtkWidget *grid, int row, const char *label_text, gboolean password) {
  GtkWidget *label = gtk_label_new(label_text);
  GtkWidget *entry = gtk_entry_new();

  gtk_widget_set_halign(label, GTK_ALIGN_START);
  gtk_grid_attach(GTK_GRID(grid), label, 0, row, 1, 1);
  gtk_grid_attach(GTK_GRID(grid), entry, 1, row, 1, 1);
  if (password) {
    gtk_entry_set_visibility(GTK_ENTRY(entry), FALSE);
  }
  return entry;
}

static gboolean run_connection_dialog(app_ctx_t *app, sa_connection_t *conn, int is_edit) {
  GtkWidget *dialog;
  GtkWidget *content;
  GtkWidget *grid;
  GtkWidget *name_entry;
  GtkWidget *host_entry;
  GtkWidget *user_entry;
  GtkWidget *local_ip_entry;
  GtkWidget *mode_combo;
  GtkWidget *mode_label;
  int response;
  gboolean saved = FALSE;

  dialog = gtk_dialog_new_with_buttons(
      is_edit ? "Edit connection" : "Add connection",
      GTK_WINDOW(app->window),
      GTK_DIALOG_MODAL | GTK_DIALOG_DESTROY_WITH_PARENT,
      "_Cancel",
      GTK_RESPONSE_CANCEL,
      "_Save",
      GTK_RESPONSE_OK,
      NULL);

  content = gtk_dialog_get_content_area(GTK_DIALOG(dialog));
  grid = gtk_grid_new();
  gtk_grid_set_row_spacing(GTK_GRID(grid), 8);
  gtk_grid_set_column_spacing(GTK_GRID(grid), 12);
  gtk_container_set_border_width(GTK_CONTAINER(grid), 12);
  gtk_container_add(GTK_CONTAINER(content), grid);

  name_entry = dialog_labeled_entry(grid, 0, "Name", FALSE);
  host_entry = dialog_labeled_entry(grid, 1, "Server PC IP", FALSE);
  user_entry = dialog_labeled_entry(grid, 2, "SSH user", FALSE);
  local_ip_entry = dialog_labeled_entry(grid, 3, "Local IP (optional)", FALSE);

  mode_label = gtk_label_new("Mode");
  gtk_widget_set_halign(mode_label, GTK_ALIGN_START);
  mode_combo = gtk_combo_box_text_new();
  gtk_combo_box_text_append_text(GTK_COMBO_BOX_TEXT(mode_combo), "Auto");
  gtk_combo_box_text_append_text(GTK_COMBO_BOX_TEXT(mode_combo), "LAN");
  gtk_combo_box_text_append_text(GTK_COMBO_BOX_TEXT(mode_combo), "Remote");
  gtk_grid_attach(GTK_GRID(grid), mode_label, 0, 4, 1, 1);
  gtk_grid_attach(GTK_GRID(grid), mode_combo, 1, 4, 1, 1);

  gtk_entry_set_text(GTK_ENTRY(name_entry), conn->name);
  gtk_entry_set_text(GTK_ENTRY(host_entry), conn->host);
  gtk_entry_set_text(GTK_ENTRY(user_entry), conn->user);
  gtk_entry_set_text(GTK_ENTRY(local_ip_entry), conn->local_ip);
  gtk_combo_box_set_active(GTK_COMBO_BOX(mode_combo), combo_from_mode(conn->mode));

  gtk_widget_show_all(dialog);
  response = gtk_dialog_run(GTK_DIALOG(dialog));

  if (response == GTK_RESPONSE_OK) {
    const char *name = gtk_entry_get_text(GTK_ENTRY(name_entry));
    const char *host = gtk_entry_get_text(GTK_ENTRY(host_entry));
    const char *user = gtk_entry_get_text(GTK_ENTRY(user_entry));
    const char *local_ip = gtk_entry_get_text(GTK_ENTRY(local_ip_entry));

    if (host == NULL || host[0] == '\0') {
      GtkWidget *err = gtk_message_dialog_new(
          GTK_WINDOW(app->window),
          GTK_DIALOG_MODAL,
          GTK_MESSAGE_ERROR,
          GTK_BUTTONS_OK,
          "Enter the Server PC IP address.");
      gtk_dialog_run(GTK_DIALOG(err));
      gtk_widget_destroy(err);
    } else {
      snprintf(conn->name, sizeof(conn->name), "%s", name != NULL ? name : "");
      if (conn->name[0] == '\0') {
        snprintf(conn->name, sizeof(conn->name), "%s", host);
      }
      snprintf(conn->host, sizeof(conn->host), "%s", host);
      snprintf(conn->user, sizeof(conn->user), "%s", user != NULL && user[0] ? user : SA_DEFAULT_SSH_USER);
      snprintf(conn->local_ip, sizeof(conn->local_ip), "%s", local_ip != NULL ? local_ip : "");
      conn->mode = mode_from_combo(gtk_combo_box_get_active(GTK_COMBO_BOX(mode_combo)));
      saved = TRUE;
    }
  }

  gtk_widget_destroy(dialog);
  return saved;
}

static const char *password_prompt(app_ctx_t *app, const char *host) {
  GtkWidget *dialog;
  GtkWidget *content;
  GtkWidget *label;
  GtkWidget *entry;
  GtkWidget *box;
  int response;
  static char password[256];

  password[0] = '\0';
  dialog = gtk_dialog_new_with_buttons(
      "SSH password",
      GTK_WINDOW(app->window),
      GTK_DIALOG_MODAL | GTK_DIALOG_DESTROY_WITH_PARENT,
      "_Cancel",
      GTK_RESPONSE_CANCEL,
      "_OK",
      GTK_RESPONSE_OK,
      NULL);

  content = gtk_dialog_get_content_area(GTK_DIALOG(dialog));
  box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
  gtk_container_set_border_width(GTK_CONTAINER(box), 12);
  label = gtk_label_new(NULL);
  gtk_label_set_markup(
      GTK_LABEL(label),
      "Enter the SSH password once to install your key on the gaming PC.\n"
      "Later connects will not need a password.");
  gtk_label_set_line_wrap(GTK_LABEL(label), TRUE);
  entry = gtk_entry_new();
  gtk_entry_set_visibility(GTK_ENTRY(entry), FALSE);
  gtk_entry_set_activates_default(GTK_ENTRY(entry), TRUE);
  gtk_box_pack_start(GTK_BOX(box), label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(box), entry, FALSE, FALSE, 0);
  gtk_container_add(GTK_CONTAINER(content), box);
  gtk_widget_show_all(dialog);
  gtk_dialog_set_default_response(GTK_DIALOG(dialog), GTK_RESPONSE_OK);

  response = gtk_dialog_run(GTK_DIALOG(dialog));
  if (response == GTK_RESPONSE_OK) {
    const char *text = gtk_entry_get_text(GTK_ENTRY(entry));
    snprintf(password, sizeof(password), "%s", text != NULL ? text : "");
  }
  gtk_widget_destroy(dialog);

  return password[0] != '\0' ? password : NULL;
}

static void start_connection(app_ctx_t *app, sa_connection_t *conn, const char *password, int bootstrap_key) {
  sa_config_t cfg;
  char err[512];
  int use_key = conn->key_installed && !bootstrap_key;

  if (sa_runtime_is_busy(app->runtime)) {
    return;
  }

  snprintf(app->active_connection_id, sizeof(app->active_connection_id), "%s", conn->id);
  app->pending_bootstrap = bootstrap_key;

  sa_connection_to_config(conn, &cfg);
  set_list_sensitive(app, FALSE);
  gtk_widget_set_sensitive(app->disconnect_btn, TRUE);
  gtk_label_set_text(GTK_LABEL(app->status_label), "Starting Chrome...");

  while (g_main_context_pending(NULL)) {
    g_main_context_iteration(NULL, FALSE);
  }

  if (sa_chrome_start(cfg.chrome_port, err, sizeof(err)) != 0) {
    GtkWidget *dialog = gtk_message_dialog_new(
        GTK_WINDOW(app->window),
        GTK_DIALOG_MODAL,
        GTK_MESSAGE_ERROR,
        GTK_BUTTONS_OK,
        "%s",
        err);
    gtk_label_set_text(GTK_LABEL(app->status_label), err);
    gtk_dialog_run(GTK_DIALOG(dialog));
    gtk_widget_destroy(dialog);
    set_list_sensitive(app, TRUE);
    gtk_widget_set_sensitive(app->disconnect_btn, FALSE);
    app->active_connection_id[0] = '\0';
    app->pending_bootstrap = 0;
    return;
  }

  sa_runtime_connect(app->runtime, &cfg, password != NULL ? password : "", use_key, bootstrap_key, 1);
}

static void on_connect_row_clicked(GtkButton *button, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  const char *id = g_object_get_data(G_OBJECT(button), "connection-id");
  sa_connection_t *conn;
  const char *password = NULL;
  int bootstrap = 0;

  (void)button;
  if (id == NULL) {
    return;
  }

  conn = sa_connections_find(&app->connections, id);
  if (conn == NULL) {
    return;
  }

  if (conn->host[0] == '\0') {
    gtk_label_set_text(GTK_LABEL(app->status_label), "This connection has no host. Edit it first.");
    return;
  }

#ifndef _WIN32
  if (conn->mode != SA_MODE_LAN) {
    if (!conn->key_installed) {
      password = password_prompt(app, conn->host);
      if (password == NULL) {
        return;
      }
      bootstrap = 1;
    }
  }
#else
  if (conn->mode != SA_MODE_LAN && !conn->key_installed) {
    password = password_prompt(app, conn->host);
    if (password == NULL) {
      return;
    }
    bootstrap = 1;
  }
#endif

  start_connection(app, conn, password, bootstrap);
}

static void on_edit_row_clicked(GtkButton *button, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  const char *id = g_object_get_data(G_OBJECT(button), "connection-id");
  sa_connection_t *conn;

  (void)button;
  if (id == NULL) {
    return;
  }

  conn = sa_connections_find(&app->connections, id);
  if (conn == NULL) {
    return;
  }

  {
    char old_host[256];
    char old_user[128];
    snprintf(old_host, sizeof(old_host), "%s", conn->host);
    snprintf(old_user, sizeof(old_user), "%s", conn->user);

    if (run_connection_dialog(app, conn, 1)) {
      if (strcmp(old_host, conn->host) != 0 || strcmp(old_user, conn->user) != 0) {
        conn->key_installed = 0;
      }
      sa_connections_save(&app->connections);
      refresh_connections_list(app);
    }
  }
}

static void on_delete_row_clicked(GtkButton *button, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  const char *id = g_object_get_data(G_OBJECT(button), "connection-id");
  sa_connection_t *conn;
  GtkWidget *dialog;
  int response;

  (void)button;
  if (id == NULL) {
    return;
  }

  conn = sa_connections_find(&app->connections, id);
  if (conn == NULL) {
    return;
  }

  dialog = gtk_message_dialog_new(
      GTK_WINDOW(app->window),
      GTK_DIALOG_MODAL,
      GTK_MESSAGE_QUESTION,
      GTK_BUTTONS_YES_NO,
      "Delete connection \"%s\"?",
      conn->name[0] ? conn->name : conn->host);
  response = gtk_dialog_run(GTK_DIALOG(dialog));
  gtk_widget_destroy(dialog);

  if (response == GTK_RESPONSE_YES) {
    sa_connections_remove(&app->connections, id);
    sa_connections_save(&app->connections);
    refresh_connections_list(app);
  }
}

static void on_add_clicked(GtkButton *button, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  sa_connection_t *conn;

  (void)button;
  conn = sa_connections_add(&app->connections);
  if (conn == NULL) {
    GtkWidget *dialog = gtk_message_dialog_new(
        GTK_WINDOW(app->window),
        GTK_DIALOG_MODAL,
        GTK_MESSAGE_ERROR,
        GTK_BUTTONS_OK,
        "Maximum number of saved connections reached.");
    gtk_dialog_run(GTK_DIALOG(dialog));
    gtk_widget_destroy(dialog);
    return;
  }

  if (run_connection_dialog(app, conn, 0)) {
    sa_connections_save(&app->connections);
    refresh_connections_list(app);
  } else {
    sa_connections_remove(&app->connections, conn->id);
  }
}

static void on_disconnect_clicked(GtkButton *button, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  (void)button;
  sa_runtime_disconnect(app->runtime);
  gtk_label_set_text(GTK_LABEL(app->status_label), "Stopping...");
}

static void on_destroy(GtkWidget *widget, gpointer user_data) {
  app_ctx_t *app = (app_ctx_t *)user_data;
  (void)widget;
#ifndef _WIN32
  g_signal_window = NULL;
#endif
  sa_runtime_destroy(app->runtime);
  gtk_main_quit();
}

void sa_app_run(int argc, char **argv) {
  app_ctx_t app;
  GtkWidget *outer;
  GtkWidget *list_frame;
  GtkWidget *list_scroll;
  GtkWidget *info_frame;
  GtkWidget *info_box;

  gtk_init(&argc, &argv);
  memset(&app, 0, sizeof(app));

  sa_connections_load(&app.connections);
  app.runtime = sa_runtime_create(on_runtime_status, &app);

  app.window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
  gtk_window_set_title(GTK_WINDOW(app.window), "Smart Automator Connect");
  gtk_window_set_default_size(GTK_WINDOW(app.window), 620, 520);
  g_signal_connect(app.window, "destroy", G_CALLBACK(on_destroy), &app);
#ifndef _WIN32
  g_signal_window = app.window;
  g_unix_signal_add(SIGINT, on_unix_signal, NULL);
  g_unix_signal_add(SIGTERM, on_unix_signal, NULL);
#endif

  outer = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
  gtk_container_set_border_width(GTK_CONTAINER(outer), 16);
  gtk_container_add(GTK_CONTAINER(app.window), outer);

  list_frame = gtk_frame_new("Saved connections");
  list_scroll = gtk_scrolled_window_new(NULL, NULL);
  gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(list_scroll), GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
  gtk_scrolled_window_set_min_content_height(GTK_SCROLLED_WINDOW(list_scroll), 180);
  app.connections_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
  gtk_container_set_border_width(GTK_CONTAINER(app.connections_box), 10);
  gtk_container_add(GTK_CONTAINER(list_scroll), app.connections_box);
  gtk_container_add(GTK_CONTAINER(list_frame), list_scroll);
  gtk_box_pack_start(GTK_BOX(outer), list_frame, TRUE, TRUE, 0);

  app.add_btn = gtk_button_new_with_label("+ Add connection");
  g_signal_connect(app.add_btn, "clicked", G_CALLBACK(on_add_clicked), &app);
  gtk_box_pack_start(GTK_BOX(outer), app.add_btn, FALSE, FALSE, 0);

  info_frame = gtk_frame_new("Connection status");
  info_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
  gtk_container_set_border_width(GTK_CONTAINER(info_box), 10);
  app.status_label = gtk_label_new("Idle. Add a connection and click Connect.");
  app.cdp_label = gtk_label_new("—");
  app.ui_label = gtk_label_new("—");
  gtk_label_set_xalign(GTK_LABEL(app.status_label), 0.0);
  gtk_label_set_xalign(GTK_LABEL(app.cdp_label), 0.0);
  gtk_label_set_xalign(GTK_LABEL(app.ui_label), 0.0);
  gtk_label_set_line_wrap(GTK_LABEL(app.status_label), TRUE);
  gtk_label_set_line_wrap(GTK_LABEL(app.cdp_label), TRUE);
  gtk_label_set_line_wrap(GTK_LABEL(app.ui_label), TRUE);
  gtk_label_set_selectable(GTK_LABEL(app.cdp_label), TRUE);
  gtk_label_set_selectable(GTK_LABEL(app.ui_label), TRUE);
  gtk_box_pack_start(GTK_BOX(info_box), gtk_label_new("Status"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(info_box), app.status_label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(info_box), gtk_label_new("CDP URL (set on gaming PC)"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(info_box), app.cdp_label, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(info_box), gtk_label_new("Smart Automator UI"), FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(info_box), app.ui_label, FALSE, FALSE, 0);

  app.disconnect_btn = gtk_button_new_with_label("Disconnect");
  gtk_widget_set_sensitive(app.disconnect_btn, FALSE);
  g_signal_connect(app.disconnect_btn, "clicked", G_CALLBACK(on_disconnect_clicked), &app);
  gtk_box_pack_start(GTK_BOX(info_box), app.disconnect_btn, FALSE, FALSE, 0);

  gtk_container_add(GTK_CONTAINER(info_frame), info_box);
  gtk_box_pack_start(GTK_BOX(outer), info_frame, FALSE, FALSE, 0);

  refresh_connections_list(&app);
  gtk_widget_show_all(app.window);
  gtk_main();
}
