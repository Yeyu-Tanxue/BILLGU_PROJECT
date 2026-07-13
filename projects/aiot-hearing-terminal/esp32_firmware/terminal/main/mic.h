#pragma once
#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* I2S mic init (WS=1 SCK=2 DIN=42, 16kHz 32-bit→16-bit mono, I2S_NUM_1).
 * Separate I2S instance from speaker (I2S_NUM_0). */
void mic_setup(void);

/* Record 2.5 seconds — streaming API: call mic_record_start() once,
 * then repeatedly mic_record_chunk() to get chunks, until buf full or mic stops. */
#define MIC_RECORD_SEC  2.5f
#define MIC_SAMPLE_RATE 16000
#define CHUNK_SIZE      1024

void mic_record_start(void);
int  mic_record_chunk(int16_t *buf, int max_samples);

#ifdef __cplusplus
}
#endif