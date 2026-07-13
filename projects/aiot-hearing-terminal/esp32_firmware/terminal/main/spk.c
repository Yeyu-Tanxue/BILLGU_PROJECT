/*
 * spk.c —— terminal 固件的扬声器播放模块
 * ===============================================================
 * I2S 扬声器：BCLK=40 LRCK=41 DOUT=39, 16kHz 16-bit mono。
 * 行协议（整句累积播放，根治块间断续/回音）：
 *   SPKBEGIN <total_samples>\n     —— 开始一整句，声明总样本数
 *   SPK <n> <base64_int16_pcm>\n   —— 分块追加；攒齐 total 后一次性连续播放
 *   (无 SPKBEGIN 的单条 SPK 仍单块即播，向后兼容)
 *
 * 为什么累积：边传边播时固件单线程读串口+解码+被摄像头抢占，喂 I2S 常晚于
 * DMA 缓冲深度 → underrun，默认 auto_clear=false 重复旧缓冲 → 听感"回音/断续"。
 * 改为整句一次性 i2s_channel_write，DMA 由单次调用连续供数，物理上无空档。
 *
 * 音量：强制缩放到最小，适合近耳听。播放阻塞返回，避免与 LCD 刷新抢 SPI。
 */
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "spk.h"

static const char *TAG = "spk";

#define SPK_BCLK     GPIO_NUM_40
#define SPK_LRCK     GPIO_NUM_41
#define SPK_DOUT     GPIO_NUM_39

#define SAMPLE_RATE  16000

/* 音量：int16 满幅 32767，这里缩到 ~2000（最小可闻）*/
#define VOLUME_SCALE  6000

#define PCM_MAX       32768
#define BUF_MAX       (64 * 1024)    /* 最多 64KB PCM = 2 秒语音 */

static i2s_chan_handle_t g_spk_tx;
static uint8_t *g_raw;   /* 单块 fallback 解码缓冲(PSRAM) */

/* 整句累积播放：PC 分块传，固件攒成完整一句再一次性连续播放（根治块间断续/回音）*/
#define ACC_CAP_SAMPLES  320000   /* 20s @16kHz，足够任何润色句 */
static int16_t *g_acc;        /* 累积缓冲(PSRAM) */
static int      g_acc_cap;    /* 容量(samples) */
static int      g_acc_total;  /* 本句目标样本数；0=空闲 */
static int      g_acc_have;   /* 已累积样本数 */

void spk_setup(void)
{
    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    cc.dma_desc_num  = 8;     /* 默认 6 */
    cc.dma_frame_num = 600;   /* 默认 240 → 8×600 frames ≈ 300ms 缓冲，吸收串口供数/被抢占抖动防断音 */
    ESP_ERROR_CHECK(i2s_new_channel(&cc, &g_spk_tx, NULL));

    i2s_std_config_t cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = SPK_BCLK,
            .ws   = SPK_LRCK,
            .dout = SPK_DOUT,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(g_spk_tx, &cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(g_spk_tx));

    g_raw = (uint8_t *)heap_caps_malloc(BUF_MAX, MALLOC_CAP_SPIRAM);
    if (!g_raw) ESP_LOGE(TAG, "SPK 缓冲分配失败 (%d bytes)", BUF_MAX);

    g_acc_cap = ACC_CAP_SAMPLES;
    g_acc = (int16_t *)heap_caps_malloc((size_t)g_acc_cap * 2, MALLOC_CAP_SPIRAM);
    if (!g_acc) ESP_LOGE(TAG, "SPK 累积缓冲分配失败 (%d samples)", g_acc_cap);

    ESP_LOGI(TAG, "I2S 就绪 BCLK=%d LRCK=%d DOUT=%d %dHz",
             SPK_BCLK, SPK_LRCK, SPK_DOUT, SAMPLE_RATE);
}

static int b64_decode(const char *src, int slen, uint8_t *dst, int cap)
{
    int acc = 0, nbits = 0, out = 0;
    for (int i = 0; i < slen; i++) {
        char c = src[i];
        int v;
        if      (c >= 'A' && c <= 'Z') v = c - 'A';
        else if (c >= 'a' && c <= 'z') v = c - 'a' + 26;
        else if (c >= '0' && c <= '9') v = c - '0' + 52;
        else if (c == '+')             v = 62;
        else if (c == '/')             v = 63;
        else                           continue;
        acc = (acc << 6) | v;
        nbits += 6;
        if (nbits >= 8) {
            nbits -= 8;
            if (out >= cap) return -1;
            dst[out++] = (acc >> nbits) & 0xFF;
        }
    }
    return out;
}

/* int16 缩到最小音量（就地）*/
static inline void scale_volume(int16_t *p, int n)
{
    for (int i = 0; i < n; i++) {
        int v = (int)p[i] * VOLUME_SCALE / PCM_MAX;
        if (v > 32767) v = 32767;
        if (v < -32768) v = -32768;
        p[i] = (int16_t)v;
    }
}

void spk_handle_line(const char *line)
{
    /* SPKBEGIN <total_samples>：开始累积一整句 */
    int total = 0, cb = 0;
    if (sscanf(line, "SPKBEGIN %d %n", &total, &cb) == 1 && cb > 0) {
        if (!g_acc || total <= 0 || total > g_acc_cap) {
            ESP_LOGW(TAG, "SPKBEGIN total 非法/缓冲缺失: %d", total);
            g_acc_total = 0; g_acc_have = 0;
            return;
        }
        g_acc_total = total;
        g_acc_have  = 0;
        ESP_LOGI(TAG, "SPKBEGIN %d 样本 (%.2fs)", total, total / (float)SAMPLE_RATE);
        return;
    }

    /* SPK <n> <b64> */
    int nsamples = 0, consumed = 0;
    if (sscanf(line, "SPK %d %n", &nsamples, &consumed) != 1 || consumed == 0)
        return;
    if (nsamples <= 0 || nsamples > BUF_MAX / 2) {
        ESP_LOGW(TAG, "SPK 样本数非法: %d", nsamples);
        return;
    }
    const char *b64 = line + consumed;
    int b64len  = strlen(b64);
    int raw_len = nsamples * 2;

    /* —— 累积模式：解码追加到整句缓冲，攒齐后一次性连续播放 —— */
    if (g_acc_total > 0) {
        if (g_acc_have + nsamples > g_acc_total) {
            ESP_LOGW(TAG, "SPK 累积超出 total，丢弃本句");
            g_acc_total = 0; g_acc_have = 0;
            return;
        }
        int16_t *dst = g_acc + g_acc_have;
        int got = b64_decode(b64, b64len, (uint8_t *)dst, raw_len);
        if (got != raw_len) {
            ESP_LOGW(TAG, "SPK 数据长度不符: 期望 %d 实得 %d，丢弃本句", raw_len, got);
            g_acc_total = 0; g_acc_have = 0;
            return;
        }
        scale_volume(dst, nsamples);
        g_acc_have += nsamples;

        if (g_acc_have >= g_acc_total) {
            int n = g_acc_total;
            g_acc_total = 0; g_acc_have = 0;
            ESP_LOGI(TAG, "SPK 整句播放 %d 样本 (%.2fs)", n, n / (float)SAMPLE_RATE);
            size_t bw = 0;
            i2s_channel_write(g_spk_tx, g_acc, (size_t)n * 2, &bw, portMAX_DELAY);
            ESP_LOGI(TAG, "SPK 整句播放完成 (%u bytes)", (unsigned)bw);
        }
        return;
    }

    /* —— 无 SPKBEGIN：回退单块即播（向后兼容）—— */
    uint8_t *raw = g_raw;
    if (!raw) { ESP_LOGW(TAG, "SPK 缓冲未就绪"); return; }
    int got = b64_decode(b64, b64len, raw, raw_len);
    if (got != raw_len) {
        ESP_LOGW(TAG, "SPK 数据长度不符: 期望 %d 实得 %d", raw_len, got);
        return;
    }
    scale_volume((int16_t *)raw, nsamples);
    size_t bw = 0;
    i2s_channel_write(g_spk_tx, (int16_t *)raw, raw_len, &bw, portMAX_DELAY);
}