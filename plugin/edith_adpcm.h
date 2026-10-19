// Wwise IMA ADPCM (codec id 2, plugin 0x00020001), mono: her voice lines in her banks and her new
// lines over the relay. A block is 36 bytes and 64 samples: int16 sample 0, u8 step index, u8 0,
// then 32 bytes of nibbles (low nibble first) for samples 1..63, the last nibble unused (as
// vgmstream's decode_wwise_ima reads it). 4:1 against int16 PCM.
#pragma once
#include <stdint.h>
#include <stddef.h>

#define EDITH_ADPCM_BLOCK 36
#define EDITH_ADPCM_SAMPLES 64

static const int16_t kImaStep[89] = {
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88,
    97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658,
    724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660,
    4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818,
    18500, 20350, 22385, 24623, 27086, 29794, 32767};
static const int8_t kImaIndex[16] = {-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8};

// One nibble's effect on (predictor, index), the decoder's way.
static inline void edith_ima_step(int nib, int *pred, int *index) {
    int step = kImaStep[*index];
    int diff = step >> 3;
    if (nib & 4) diff += step;
    if (nib & 2) diff += step >> 1;
    if (nib & 1) diff += step >> 2;
    *pred += (nib & 8) ? -diff : diff;
    if (*pred > 32767) *pred = 32767;
    if (*pred < -32768) *pred = -32768;
    *index += kImaIndex[nib];
    if (*index < 0) *index = 0;
    if (*index > 88) *index = 88;
}

static inline size_t edith_adpcm_blocks(size_t samples) {
    return (samples + EDITH_ADPCM_SAMPLES - 1) / EDITH_ADPCM_SAMPLES;
}

// `n` samples -> edith_adpcm_blocks(n) * 36 bytes at `out` (the tail is padded with silence).
// `*index` carries the step index from block to block (start with 0).
static inline void edith_adpcm_encode(const int16_t *pcm, size_t n, uint8_t *out, int *index) {
    for (size_t b = 0; b < edith_adpcm_blocks(n); ++b) {
        int16_t s[EDITH_ADPCM_SAMPLES];
        for (int k = 0; k < EDITH_ADPCM_SAMPLES; ++k) {
            size_t i = b * EDITH_ADPCM_SAMPLES + k;
            s[k] = i < n ? pcm[i] : 0;
        }
        uint8_t *blk = out + b * EDITH_ADPCM_BLOCK;
        int pred = s[0];
        blk[0] = (uint8_t)(s[0] & 0xff);
        blk[1] = (uint8_t)((uint16_t)s[0] >> 8);
        blk[2] = (uint8_t)*index;
        blk[3] = 0;
        for (int k = 4; k < EDITH_ADPCM_BLOCK; ++k) blk[k] = 0;
        for (int k = 1; k < EDITH_ADPCM_SAMPLES; ++k) {
            int step = kImaStep[*index];
            int diff = s[k] - pred, nib = 0;
            if (diff < 0) { nib = 8; diff = -diff; }
            if (diff >= step) { nib |= 4; diff -= step; }
            if (diff >= step >> 1) { nib |= 2; diff -= step >> 1; }
            if (diff >= step >> 2) nib |= 1;
            edith_ima_step(nib, &pred, index);
            int at = 4 + (k - 1) / 2;
            blk[at] |= (uint8_t)((k - 1) & 1 ? nib << 4 : nib);
        }
    }
}

// `blocks` blocks -> blocks * 64 samples at `pcm`.
static inline void edith_adpcm_decode(const uint8_t *in, size_t blocks, int16_t *pcm) {
    for (size_t b = 0; b < blocks; ++b) {
        const uint8_t *blk = in + b * EDITH_ADPCM_BLOCK;
        int pred = (int16_t)(blk[0] | blk[1] << 8), index = blk[2] > 88 ? 88 : blk[2];
        int16_t *o = pcm + b * EDITH_ADPCM_SAMPLES;
        o[0] = (int16_t)pred;
        for (int k = 1; k < EDITH_ADPCM_SAMPLES; ++k) {
            uint8_t byte = blk[4 + (k - 1) / 2];
            edith_ima_step((k - 1) & 1 ? byte >> 4 : byte & 15, &pred, &index);
            o[k] = (int16_t)pred;
        }
    }
}
