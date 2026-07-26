#ifndef SA_CHROME_PROFILES_H
#define SA_CHROME_PROFILES_H

#include <stddef.h>

#define SA_MAX_CHROME_PROFILES 64
#define SA_CHROME_PROFILE_ID_LEN 512

typedef struct {
  char id[SA_CHROME_PROFILE_ID_LEN];
  char browser[64];
  char name[128];
  char user_data_dir[512];
  char profile_directory[128];
} sa_chrome_profile_t;

typedef struct {
  sa_chrome_profile_t items[SA_MAX_CHROME_PROFILES];
  int count;
} sa_chrome_profile_list_t;

void sa_chrome_profiles_discover(sa_chrome_profile_list_t *list);
int sa_chrome_profiles_find_index(const sa_chrome_profile_list_t *list, const char *user_data_dir, const char *profile_directory);
const char *sa_chrome_profile_short_label(const char *user_data_dir, const char *profile_directory, const char *profile_name);

#endif
