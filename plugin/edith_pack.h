// Edith's lobby data from .edith files in <plugins>\<dll name>\ (plugin/edith_pack.cpp).
#pragma once
#include <windows.h>

typedef void (*EdithPackLog)(const char *fmt, ...);

// Unpacks each .edith next to the DLL, redirects the engine's opens of its package files, and
// mounts it (AddManifestPackage) when its level loads. Returns how many packages are ready.
int EdithPack_Install(HMODULE self, EdithPackLog log);
