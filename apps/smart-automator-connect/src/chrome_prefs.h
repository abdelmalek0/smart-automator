#ifndef SA_CHROME_PREFS_H
#define SA_CHROME_PREFS_H

#include <stddef.h>

/* Patch profile_dir/Preferences to disable password leak warnings. */
int sa_chrome_apply_automation_prefs(const char *profile_dir);

#endif
