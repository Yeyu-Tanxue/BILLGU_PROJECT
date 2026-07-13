/*
 * mic.c —— terminal 固件的 I2S 麦克风录音模块（流式版）
 * ===============================================================
 * I2S 数字麦克风：WS=1 SCK=2 DIN=42, 16kHz 32→16-bit mono, I2S_NUM_1。
 * 流式 API：mic_record_start() 预热 → mic_record_chunk() 反复取 1024 样本块。
 */
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "mic.h"

static const char *TAG = "mic";

#define MIC_WS          GPIO_NUM_1
#define MIC_SCK         GPIO_NUM_2
#define MIC_DIN         GPIO_NUM_42

#define GAIN_SHIFT      13
#define USE_RIGHT_SLOT  0

static i2s_chan_handle_t g_mic_rx;

void mic_setup(void)
{
    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&cc, NULL, &g_mic_rx));

    i2s_std_slot_config_t slot =
        I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO);
    slot.slot_mask = USE_RIGHT_SLOT ? I2S_STD_SLOT_RIGHT : I2S_STD_SLOT_LEFT;

    i2s_std_config_t cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(MIC_SAMPLE_RATE),
        .slot_cfg = slot,
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = MIC_SCK,
            .ws   = MIC_WS,
            .dout = I2S_GPIO_UNUSED,
            .din  = MIC_DIN,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(g_mic_rx, &cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(g_mic_rx));
    ESP_LOGI(TAG, "I2S MIC 就绪 WS=%d SCK=%d DIN=%d %dHz",
             MIC_WS, MIC_SCK, MIC_DIN, MIC_SAMPLE_RATE);
}

void mic_record_start(void)
{
    /* 预热：丢几块让麦稳定 */
    int32_t dummy[128];
    size_t br = 0;
    for (int i = 0; i < 4; i++)
        i2s_channel_read(g_mic_rx, dummy, sizeof(dummy), &br, 100);
}

int mic_record_chunk(int16_t *buf, int max_samples)
{
    int32_t raw[128];
    size_t br = 0;
    int got = 0;
    while (got < max_samples) {
        if (i2s_channel_read(g_mic_rx, raw, sizeof(raw), &br, 50) != ESP_OK)
            continue;
        int n = br / (int)sizeof(int32_t);
        for (int i = 0; i < n && got < max_samples; i++) {
            int32_t v = raw[i] >> GAIN_SHIFT;
            if (v > 32767) v = 32767;
            else if (v < -32768) v = -32768;
            buf[got++] = (int16_t)v;
        }
    }
    return got;
}