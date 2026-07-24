#include "app.h"
#include "net.h"

int main(int argc, char **argv) {
  if (sa_net_init() != 0) {
    return 1;
  }

  sa_app_run(argc, argv);
  sa_net_shutdown();
  return 0;
}
