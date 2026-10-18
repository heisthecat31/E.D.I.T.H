// Edith's lobby data served loose from <plugins>\<dll name>\data (plugin/edith_loose.cpp).
#pragma once
#include <windows.h>

typedef void (*EdithLooseLog)(const char *fmt, ...);

// Indexes <dll folder>\<dll name without .dll>\data\<type>\<name> and detours the game's resource
// request so those files are read instead of the packages. Returns how many files are served.
int EdithLoose_Install(HMODULE self, EdithLooseLog log);
