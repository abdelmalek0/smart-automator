#include "ssh_cli.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#ifdef __linux__
#include <sys/prctl.h>
#endif

typedef struct sa_ssh_cli_tunnel {
  char control_path[256];
  char user_host[320];
  char askpass_file[256];
  int remote_port;
  pid_t ssh_pid;
} sa_ssh_cli_tunnel_t;

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

static void read_stderr_file(const char *path, char *err, size_t err_len) {
  FILE *fp;
  char buf[384];
  size_t n;

  if (path == NULL || err == NULL || err_len == 0) {
    return;
  }

  fp = fopen(path, "r");
  if (fp == NULL) {
    return;
  }

  n = fread(buf, 1, sizeof(buf) - 1, fp);
  fclose(fp);
  if (n == 0) {
    return;
  }

  buf[n] = '\0';
  while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r' || buf[n - 1] == ' ')) {
    buf[--n] = '\0';
  }

  if (buf[0] != '\0') {
    snprintf(err, err_len, "%s", buf);
  }
}

static int ssh_control_check(const char *control_path, const char *user_host) {
  char cmd[640];
  snprintf(
      cmd,
      sizeof(cmd),
      "ssh -S '%s' -o ConnectTimeout=5 -O check '%s' >/dev/null 2>&1",
      control_path,
      user_host);
  return system(cmd) == 0 ? 0 : -1;
}

static void kill_ssh_pid(pid_t pid) {
  int status;
  int attempt;

  if (pid <= 0) {
    return;
  }

  kill(pid, SIGTERM);
  for (attempt = 0; attempt < 30; attempt++) {
    if (waitpid(pid, &status, WNOHANG) > 0) {
      return;
    }
    usleep(100000);
  }

  kill(pid, SIGKILL);
  waitpid(pid, &status, 0);
}

static pid_t run_ssh_forward(
    const char *control_path,
    const char *user_host,
    const char *askpass_bin,
    const char *askpass_file,
    const char *key_path,
    int remote_port,
    int local_chrome_port,
    char *err,
    size_t err_len) {
  char port_fwd[64];
  char stderr_template[] = "/tmp/sa-ssh-err-XXXXXX";
  char stderr_path[256];
  const char *display;
  pid_t pid;
  int stderr_fd;
  int elapsed_ms;
  int use_key = key_path != NULL && key_path[0] != '\0';

  snprintf(port_fwd, sizeof(port_fwd), "%d:127.0.0.1:%d", remote_port, local_chrome_port);

  stderr_fd = mkstemp(stderr_template);
  if (stderr_fd < 0) {
    snprintf(err, err_len, "Could not create SSH error log.");
    return -1;
  }
  close(stderr_fd);
  snprintf(stderr_path, sizeof(stderr_path), "%s", stderr_template);

  pid = fork();
  if (pid < 0) {
    unlink(stderr_path);
    snprintf(err, err_len, "Failed to fork ssh process.");
    return -1;
  }

  if (pid == 0) {
    int err_fd = open(stderr_path, O_WRONLY | O_APPEND);
    if (err_fd >= 0) {
      dup2(err_fd, STDERR_FILENO);
      close(err_fd);
    }
    {
      int null_fd = open("/dev/null", O_RDONLY);
      if (null_fd >= 0) {
        dup2(null_fd, STDIN_FILENO);
        close(null_fd);
      }
    }
    if (!use_key && askpass_bin != NULL && askpass_file != NULL) {
      setenv("SA_ASKPASS_FILE", askpass_file, 1);
      setenv("SSH_ASKPASS", askpass_bin, 1);
      setenv("SSH_ASKPASS_REQUIRE", "force", 1);
      display = getenv("DISPLAY");
      if (display == NULL || display[0] == '\0') {
        setenv("DISPLAY", ":0", 0);
      }
    }
#ifdef __linux__
    prctl(PR_SET_PDEATHSIG, SIGTERM);
#endif
    if (key_path != NULL && key_path[0] != '\0') {
      execlp(
          "ssh",
          "ssh",
          "-N",
          "-M",
          "-S",
          control_path,
          "-i",
          key_path,
          "-o",
          "PreferredAuthentications=publickey",
          "-o",
          "PasswordAuthentication=no",
          "-o",
          "ControlPersist=10m",
          "-o",
          "ExitOnForwardFailure=yes",
          "-o",
          "ServerAliveInterval=30",
          "-o",
          "ServerAliveCountMax=3",
          "-o",
          "StrictHostKeyChecking=accept-new",
          "-R",
          port_fwd,
          user_host,
          (char *)NULL);
    } else {
      execlp(
          "ssh",
          "ssh",
          "-N",
          "-M",
          "-S",
          control_path,
          "-o",
          "ControlPersist=10m",
          "-o",
          "ExitOnForwardFailure=yes",
          "-o",
          "ServerAliveInterval=30",
          "-o",
          "ServerAliveCountMax=3",
          "-R",
          port_fwd,
          user_host,
          (char *)NULL);
    }
    _exit(127);
  }

  elapsed_ms = 0;
  while (elapsed_ms < 20000) {
    int status;
    pid_t waited = waitpid(pid, &status, WNOHANG);
    if (waited > 0) {
      read_stderr_file(stderr_path, err, err_len);
      if (err[0] == '\0') {
        snprintf(err, err_len, "SSH connection failed. Check host, user, and password.");
      }
      unlink(stderr_path);
      return -1;
    }
    if (waited < 0 && errno != EINTR) {
      unlink(stderr_path);
      kill_ssh_pid(pid);
      snprintf(err, err_len, "Failed while waiting for ssh process.");
      return -1;
    }
    if (access(control_path, F_OK) == 0 && ssh_control_check(control_path, user_host) == 0) {
      unlink(stderr_path);
      return pid;
    }
    usleep(100000);
    elapsed_ms += 100;
  }

  unlink(stderr_path);
  kill_ssh_pid(pid);
  snprintf(err, err_len, "SSH master connection is not ready.");
  return -1;
}

sa_ssh_cli_tunnel_t *sa_ssh_cli_start(
    const char *host,
    const char *user,
    const char *password,
    const char *key_path,
    int remote_port,
    int local_chrome_port,
    int *bound_remote_port,
    char *err,
    size_t err_len) {
  sa_ssh_cli_tunnel_t *tunnel;
  char askpass_bin[PATH_MAX];
  char control_template[] = "/tmp/sa-ssh-XXXXXX";
  int fd;
  pid_t ssh_pid;
  int use_key = key_path != NULL && key_path[0] != '\0';

  if (host == NULL || user == NULL) {
    snprintf(err, err_len, "Missing SSH connection details.");
    return NULL;
  }

  if (!use_key && (password == NULL || password[0] == '\0')) {
    snprintf(err, err_len, "Missing SSH password or key.");
    return NULL;
  }

  tunnel = calloc(1, sizeof(*tunnel));
  if (tunnel == NULL) {
    snprintf(err, err_len, "Out of memory.");
    return NULL;
  }

  tunnel->ssh_pid = -1;
  snprintf(tunnel->user_host, sizeof(tunnel->user_host), "%s@%s", user, host);
  tunnel->remote_port = remote_port;

  fd = mkstemp(control_template);
  if (fd < 0) {
    snprintf(err, err_len, "Could not create SSH control socket path.");
    free(tunnel);
    return NULL;
  }
  close(fd);
  unlink(control_template);
  snprintf(tunnel->control_path, sizeof(tunnel->control_path), "%s", control_template);

  if (!use_key) {
    if (write_askpass_file(password, tunnel->askpass_file, sizeof(tunnel->askpass_file)) != 0) {
      snprintf(err, err_len, "Could not prepare SSH password helper.");
      free(tunnel);
      return NULL;
    }

    find_askpass(askpass_bin, sizeof(askpass_bin));
    if (access(askpass_bin, X_OK) != 0) {
      snprintf(err, err_len, "SSH askpass helper not found at: %s", askpass_bin);
      unlink(tunnel->askpass_file);
      free(tunnel);
      return NULL;
    }
  } else {
    askpass_bin[0] = '\0';
    tunnel->askpass_file[0] = '\0';
  }

  ssh_pid = run_ssh_forward(
      tunnel->control_path,
      tunnel->user_host,
      askpass_bin,
      use_key ? NULL : tunnel->askpass_file,
      use_key ? key_path : NULL,
      remote_port,
      local_chrome_port,
      err,
      err_len);
  if (ssh_pid < 0) {
    if (tunnel->askpass_file[0] != '\0') {
      unlink(tunnel->askpass_file);
    }
    unlink(tunnel->control_path);
    free(tunnel);
    return NULL;
  }

  tunnel->ssh_pid = ssh_pid;
  if (tunnel->askpass_file[0] != '\0') {
    unlink(tunnel->askpass_file);
    tunnel->askpass_file[0] = '\0';
  }

  if (bound_remote_port != NULL) {
    *bound_remote_port = remote_port;
  }

  return tunnel;
}

int sa_ssh_cli_verify_cdp(const sa_ssh_cli_tunnel_t *tunnel, int remote_port) {
  char cmd[1024];
  int rc;

  if (tunnel == NULL) {
    return -1;
  }

  if (ssh_control_check(tunnel->control_path, tunnel->user_host) != 0) {
    return -1;
  }

  snprintf(
      cmd,
      sizeof(cmd),
      "ssh -S '%s' -o ConnectTimeout=5 '%s' "
      "curl -sf --connect-timeout 2 http://127.0.0.1:%d/json/version >/dev/null 2>&1",
      tunnel->control_path,
      tunnel->user_host,
      remote_port);

  rc = system(cmd);
  return rc == 0 ? 0 : -1;
}

void sa_ssh_cli_stop(sa_ssh_cli_tunnel_t *tunnel) {
  char cmd[768];

  if (tunnel == NULL) {
    return;
  }

  snprintf(
      cmd,
      sizeof(cmd),
      "ssh -S '%s' -O exit '%s' >/dev/null 2>&1",
      tunnel->control_path,
      tunnel->user_host);
  system(cmd);

  kill_ssh_pid(tunnel->ssh_pid);
  tunnel->ssh_pid = -1;

  unlink(tunnel->control_path);
  if (tunnel->askpass_file[0] != '\0') {
    unlink(tunnel->askpass_file);
  }
  free(tunnel);
}
