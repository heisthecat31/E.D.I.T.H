// plugin/edith_adpcm.h for tools/make_voice_banks.py (ctypes): built by build_voice_banks.bat.
#include "../plugin/edith_adpcm.h"

__declspec(dllexport) size_t edith_encode(const int16_t *pcm, size_t n, uint8_t *out) {
    int index = 0;
    edith_adpcm_encode(pcm, n, out, &index);
    return edith_adpcm_blocks(n) * EDITH_ADPCM_BLOCK;
}

__declspec(dllexport) void edith_decode(const uint8_t *in, size_t blocks, int16_t *pcm) {
    edith_adpcm_decode(in, blocks, pcm);
}
