#pragma once
#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* I2S speaker init (BCLK=40 LRCK=41 DOUT=39, 16kHz 16-bit mono).
 * Call from app_main before starting lcd_task. */
void spk_setup(void);

/* Handle a SPK line: "SPK <num_samples> <base64_int16_pcm>\n"
 * Decodes base64 → int16 PCM → i2s_channel_write() playback (blocking until done).
 * Volume = minimum (I2S amplitude scaled to ~2000, quiet enough for close listening). */
void spk_handle_line(const char *line);

#ifdef __cplusplus
}
#endif