#include "ssh_keys.h"

#include "util.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void ssh_key_dir(char *out, size_t out_len) {
#ifdef _WIN32
  char base[MAX_PATH];

  if (SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, base) != S_OK) {
    snprintf(out, out_len, "ssh");
    return;
  }
  snprintf(out, out_len, "%s\\smart-automator\\ssh", base);
#else
  const char *home = getenv("HOME");
  if (home == NULL || *home == '\0') {
    snprintf(out, out_len, ".config/smart-automator/ssh");
    return;
  }
  snprintf(out, out_len, "%s/.config/smart-automator/ssh", home);
#endif
}

void sa_ssh_key_priv_path(char *out, size_t out_len) {
  char dir[512];
  ssh_key_dir(dir, sizeof(dir));
#ifdef _WIN32
  snprintf(out, out_len, "%s\\id_ed25519", dir);
#else
  snprintf(out, out_len, "%s/id_ed25519", dir);
#endif
}

void sa_ssh_key_pub_path(char *out, size_t out_len) {
  char dir[512];
  ssh_key_dir(dir, sizeof(dir));
#ifdef _WIN32
  snprintf(out, out_len, "%s\\id_ed25519.pub", dir);
#else
  snprintf(out, out_len, "%s/id_ed25519.pub", dir);
#endif
}

static void find_askpass(char *out, size_t out_len) {
  char exe[PATH_MAX];
  ssize_t n;
  char *slash;

  out[0] = '\0';
  n = readlink("/proc/self/exe", exe, sizeof(exe) - 1);
  if (n > 0) {
    exe[n] = '\0';
    slash = strrchr(exe, '/');
    if (slash != NULL) {
      *slash = '\0';
      snprintf(out, out_len, "%s/sa-askpass", exe);
      if (access(out, X_OK) == 0) {
        return;
      }
    }
  }
  snprintf(out, out_len, "sa-askpass");
}

static int write_askpass_file(const char *password, char *path, size_t path_len) {
  int fd;
  size_t len;

  snprintf(path, path_len, "/tmp/sa-askpass-XXXXXX");
  fd = mkstemp(path);
  if (fd < 0) {
    return -1;
  }

  chmod(path, S_IRUSR | S_IWUSR);
  len = strlen(password);
  if (write(fd, password, len) != (ssize_t)len || write(fd, "\n", 1) != 1) {
    close(fd);
    unlink(path);
    return -1;
  }
  close(fd);
  return 0;
}

static void setup_askpass_env(const char *askpass_bin, const char *askpass_file) {
  const char *display;

  setenv("SA_ASKPASS_FILE", askpass_file, 1);
  setenv("SSH_ASKPASS", askpass_bin, 1);
  setenv("SSH_ASKPASS_REQUIRE", "force", 1);
  display = getenv("DISPLAY");
  if (display == NULL || display[0] == '\0') {
    setenv("DISPLAY", ":0", 0);
  }
}

int sa_ssh_key_ensure_exists(char *err, size_t err_len) {
  char priv[512];
  char pub[512];
  char dir[512];
  char cmd[1024];
  int rc;

  sa_ssh_key_priv_path(priv, sizeof(priv));
  sa_ssh_key_pub_path(pub, sizeof(pub));
  ssh_key_dir(dir, sizeof(dir));

  if (access(priv, R_OK) == 0 && access(pub, R_OK) == 0) {
    chmod(priv, S_IRUSR | S_IWUSR);
    return 0;
  }

  if (sa_mkdir_p(dir) != 0) {
    snprintf(err, err_len, "Could not create SSH key directory.");
    return -1;
  }

  snprintf(
      cmd,
      sizeof(cmd),
      "ssh-keygen -t ed25519 -N '' -f '%s' -q -C 'smart-automator-connect'",
      priv);
  rc = system(cmd);
  if (rc != 0) {
    snprintf(err, err_len, "ssh-keygen failed. Install OpenSSH client tools.");
    return -1;
  }

  chmod(priv, S_IRUSR | S_IWUSR);
  return 0;
}

static int read_pubkey(char *out, size_t out_len, char *err, size_t err_len) {
  char pub_path[512];
  FILE *fp;
  size_t n;

  sa_ssh_key_pub_path(pub_path, sizeof(pub_path));
  fp = fopen(pub_path, "r");
  if (fp == NULL) {
    snprintf(err, err_len, "Could not read SSH public key.");
    return -1;
  }

  if (fgets(out, (int)out_len, fp) == NULL) {
    fclose(fp);
    snprintf(err, err_len, "SSH public key file is empty.");
    return -1;
  }
  fclose(fp);

  n = strlen(out);
  while (n > 0 && (out[n - 1] == '\n' || out[n - 1] == '\r')) {
    out[--n] = '\0';
  }

  if (out[0] == '\0') {
    snprintf(err, err_len, "SSH public key file is empty.");
    return -1;
  }
  return 0;
}

int sa_ssh_key_test_auth(const char *host, const char *user, char *err, size_t err_len) {
  char priv[512];
  char user_host[320];
  char cmd[1024];
  int rc;

  if (host == NULL || user == NULL) {
    snprintf(err, err_len, "Missing SSH host or user.");
    return -1;
  }

  if (sa_ssh_key_ensure_exists(err, err_len) != 0) {
    return -1;
  }

  sa_ssh_key_priv_path(priv, sizeof(priv));
  snprintf(user_host, sizeof(user_host), "%s@%s", user, host);
  snprintf(
      cmd,
      sizeof(cmd),
      "ssh -i '%s' -o BatchMode=yes -o ConnectTimeout=8 "
      "-o PreferredAuthentications=publickey -o PasswordAuthentication=no "
      "-o StrictHostKeyChecking=accept-new '%s' true >/dev/null 2>&1",
      priv,
      user_host);

  rc = system(cmd);
  if (rc != 0) {
    snprintf(err, err_len, "SSH key authentication failed.");
    return -1;
  }
  return 0;
}

int sa_ssh_key_install(const char *host, const char *user, const char *password, char *err, size_t err_len) {
  char priv[512];
  char pub_line[1024];
  char user_host[320];
  char askpass_bin[PATH_MAX];
  char askpass_file[256];
  char remote_cmd[2048];
  char cmd[4096];
  int rc;

  if (host == NULL || user == NULL || password == NULL || password[0] == '\0') {
    snprintf(err, err_len, "SSH password is required to install the key.");
    return -1;
  }

  if (sa_ssh_key_ensure_exists(err, err_len) != 0) {
    return -1;
  }

  if (read_pubkey(pub_line, sizeof(pub_line), err, err_len) != 0) {
    return -1;
  }

  find_askpass(askpass_bin, sizeof(askpass_bin));
  if (access(askpass_bin, X_OK) != 0) {
    snprintf(err, err_len, "SSH askpass helper not found at: %s", askpass_bin);
    return -1;
  }

  if (write_askpass_file(password, askpass_file, sizeof(askpass_file)) != 0) {
    snprintf(err, err_len, "Could not prepare SSH password helper.");
    return -1;
  }

  setup_askpass_env(askpass_bin, askpass_file);
  sa_ssh_key_priv_path(priv, sizeof(priv));
  snprintf(user_host, sizeof(user_host), "%s@%s", user, host);

  snprintf(
      remote_cmd,
      sizeof(remote_cmd),
      "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
      "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && "
      "grep -qxF '%s' ~/.ssh/authorized_keys 2>/dev/null || "
      "echo '%s' >> ~/.ssh/authorized_keys",
      pub_line,
      pub_line);

  snprintf(
      cmd,
      sizeof(cmd),
      "ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no "
      "-o StrictHostKeyChecking=accept-new '%s' \"%s\" >/dev/null 2>&1",
      user_host,
      remote_cmd);

  rc = system(cmd);
  unlink(askpass_file);

  if (rc != 0) {
    snprintf(err, err_len, "Failed to install SSH key on %s. Check password and permissions.", host);
    return -1;
  }

  if (sa_ssh_key_test_auth(host, user, err, err_len) != 0) {
    return -1;
  }

  return 0;
}
