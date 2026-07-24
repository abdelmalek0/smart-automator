#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
  FILE *fp;
  char password[512];
  const char *path;

  path = getenv("SA_ASKPASS_FILE");
  if (path == NULL || path[0] == '\0') {
    return 1;
  }

  fp = fopen(path, "r");
  if (fp == NULL) {
    return 1;
  }

  if (fgets(password, sizeof(password), fp) == NULL) {
    fclose(fp);
    return 1;
  }
  fclose(fp);

  password[strcspn(password, "\r\n")] = '\0';
  if (password[0] == '\0') {
    return 1;
  }

  fputs(password, stdout);
  fputc('\n', stdout);
  fflush(stdout);
  return 0;
}
