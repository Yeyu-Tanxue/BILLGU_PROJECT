/*
 * capture_for_lstm
 * ---------------------------------------------------------------
 * 自动循环：3 秒倒计时 → 30fps × 45 帧 (≈1.5s) JPEG → 串口传 PC
 *   → 暂停 5 秒 → 再来。摆好手势看倒计时，"采集中!" 时保持动作即可。
 *
 * 单通道：UART0 (CH340, COM7, 115200) —— 烧录 + ESP_LOG + 数据同一条线。
 *
 * 串口协议（ESP32→PC，全 ASCII 行）：
 *   "CLIP_START <total>\n"
 *   "FRAME <idx>/<total> <jpeg_len> <base64>\n"   每帧一行
 *   "CLIP_END <got>\n"
 *   其余行为 ESP_LOG（含倒计时 "POSE n"），PC 端按 [esp] 显示。
 *
 * 设计说明（踩过的坑，别再走回头路）：
 *   - 走 base64+UART 而非二进制：纯 ASCII，无 CRLF/字节错位问题，稳。
 *   - 走 COM7 而非原生 USB(OTG)：USB-Serial-JTAG 在本机 Windows 上反复
 *     PermissionError/halted，折腾很久放弃。COM7 实测 99% 识别率可用。
 *   - 自动倒计时而非按键/PC命令触发：console UART0 装 driver 读 RX 会与
 *     控制台冲突，收不到命令，故改无需 PC→ESP32 通道的自动循环。
 *   - send_clip 每帧 vTaskDelay(5ms)：115200 下 printf busy-wait 慢，
 *     不让出 CPU 会饿死 IDLE 触发看门狗复位。
 *   - 代价：一组 45 帧 base64@115200 传输 ~30s。识别验证够用，提速待办。
 */

#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "mbedtls/base64.h"

static const char *TAG = "capture";

/* 数据/日志波特率。运行时强制设置（见 app_main），不依赖 sdkconfig——
 * 因为 VSCode build 反复把 sdkconfig 的 baud 还原回 115200。 */
#define DATA_BAUD          921600

/* ---------- 采集参数 ---------- */
#define CLIP_FRAMES        45
#define TARGET_PERIOD_US   33333         /* 30 fps = 33.33 ms */

/* ---------- 摄像头 PIN (与 camera_test 相同) ---------- */
#define PWDN_GPIO_NUM      -1
#define RESET_GPIO_NUM     -1
#define XCLK_GPIO_NUM      15
#define SIOD_GPIO_NUM       4
#define SIOC_GPIO_NUM       5
#define Y9_GPIO_NUM        16
#define Y8_GPIO_NUM        17
#define Y7_GPIO_NUM        18
#define Y6_GPIO_NUM        12
#define Y5_GPIO_NUM        10
#define Y4_GPIO_NUM         8
#define Y3_GPIO_NUM         9
#define Y2_GPIO_NUM        11
#define VSYNC_GPIO_NUM      6
#define HREF_GPIO_NUM       7
#define PCLK_GPIO_NUM      13


typedef struct {
    uint8_t *data;
    size_t   len;
} frame_buf_t;

static frame_buf_t g_frames[CLIP_FRAMES];


static esp_err_t init_camera(void)
{
    camera_config_t config = {
        .pin_pwdn       = PWDN_GPIO_NUM,
        .pin_reset      = RESET_GPIO_NUM,
        .pin_xclk       = XCLK_GPIO_NUM,
        .pin_sccb_sda   = SIOD_GPIO_NUM,
        .pin_sccb_scl   = SIOC_GPIO_NUM,
        .pin_d7          = Y9_GPIO_NUM,
        .pin_d6          = Y8_GPIO_NUM,
        .pin_d5          = Y7_GPIO_NUM,
        .pin_d4          = Y6_GPIO_NUM,
        .pin_d3          = Y5_GPIO_NUM,
        .pin_d2          = Y4_GPIO_NUM,
        .pin_d1          = Y3_GPIO_NUM,
        .pin_d0          = Y2_GPIO_NUM,
        .pin_vsync       = VSYNC_GPIO_NUM,
        .pin_href        = HREF_GPIO_NUM,
        .pin_pclk        = PCLK_GPIO_NUM,

        .xclk_freq_hz    = 24000000,
        .ledc_timer      = LEDC_TIMER_0,
        .ledc_channel    = LEDC_CHANNEL_0,

        .pixel_format    = PIXFORMAT_JPEG,
        .frame_size      = FRAMESIZE_QVGA,        /* 320×240 */
        .jpeg_quality    = 20,                    /* 数字越大越压缩；20 把帧从~8.5KB降到~4-5KB，
                                                     传输 5.7s→~3s，MediaPipe 抽点不受影响 */
        .fb_count        = 2,
        .fb_location     = CAMERA_FB_IN_PSRAM,
        .grab_mode       = CAMERA_GRAB_WHEN_EMPTY,
    };

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_camera_init failed: 0x%x (%s)",
                 err, esp_err_to_name(err));
    }
    return err;
}


static void warmup_camera(void)
{
    for (int i = 0; i < 30; i++) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (fb) esp_camera_fb_return(fb);
    }
}


/* 倒计时：ESP_LOG 走 COM7，PC 端会以 [esp] 行显示 */
static void countdown(int seconds)
{
    for (int i = seconds; i > 0; i--) {
        ESP_LOGI(TAG, "  POSE %d ...", i);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}


/* 30fps 节流抓 CLIP_FRAMES 帧到 g_frames[] (PSRAM) */
static int capture_clip_frames(void)
{
    int64_t t_start = esp_timer_get_time();
    int got = 0;

    for (int i = 0; i < CLIP_FRAMES; i++) {
        int64_t deadline = t_start + (int64_t)(i + 1) * TARGET_PERIOD_US;
        int64_t now      = esp_timer_get_time();
        int64_t wait_us  = deadline - now;
        if (wait_us > 5000) {
            vTaskDelay(pdMS_TO_TICKS(wait_us / 1000));
        } else if (wait_us > 0) {
            esp_rom_delay_us((uint32_t)wait_us);
        }

        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            ESP_LOGE(TAG, "fb_get failed @%d", i);
            g_frames[i].data = NULL;
            g_frames[i].len  = 0;
            continue;
        }
        uint8_t *buf = heap_caps_malloc(fb->len, MALLOC_CAP_SPIRAM);
        if (buf) {
            memcpy(buf, fb->buf, fb->len);
            g_frames[i].data = buf;
            g_frames[i].len  = fb->len;
            got++;
        } else {
            ESP_LOGE(TAG, "PSRAM alloc fail @%d (%u bytes)", i, (unsigned)fb->len);
            g_frames[i].data = NULL;
            g_frames[i].len  = 0;
        }
        esp_camera_fb_return(fb);
    }

    int64_t elapsed_ms = (esp_timer_get_time() - t_start) / 1000;
    ESP_LOGI(TAG, "capture: %d/%d frames in %lld ms (target=1500ms)",
             got, CLIP_FRAMES, (long long)elapsed_ms);
    return got;
}


/* base64 一帧一行送 COM7：FRAME idx/total jpeg_len <base64> */
static void send_frame(int idx, int total, const uint8_t *data, size_t len)
{
    size_t b64_max = ((len + 2) / 3) * 4 + 1;
    uint8_t *b64 = heap_caps_malloc(b64_max, MALLOC_CAP_SPIRAM);
    if (!b64) {
        printf("FRAME_ERR %d alloc\n", idx);
        return;
    }
    size_t b64_len = 0;
    int ret = mbedtls_base64_encode(b64, b64_max, &b64_len, data, len);
    if (ret == 0) {
        printf("FRAME %d/%d %u ", idx, total, (unsigned)len);
        fwrite(b64, 1, b64_len, stdout);
        putchar('\n');
        fflush(stdout);
    } else {
        printf("FRAME_ERR %d b64=%d\n", idx, ret);
    }
    heap_caps_free(b64);
}


static void send_clip(int got)
{
    int64_t t0 = esp_timer_get_time();
    printf("\nCLIP_START %d\n", got);
    fflush(stdout);

    uint32_t total_bytes = 0;
    for (int i = 0; i < CLIP_FRAMES; i++) {
        if (!g_frames[i].data) {
            continue;     /* 缺帧 PC 端按 idx 跳号自然感知 */
        }
        send_frame(i, CLIP_FRAMES, g_frames[i].data, g_frames[i].len);
        total_bytes += g_frames[i].len;
        heap_caps_free(g_frames[i].data);
        g_frames[i].data = NULL;
        g_frames[i].len  = 0;
        /* 每帧让出 CPU 喂看门狗：115200 下 printf busy-wait 慢，必须 ≥1 tick */
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    printf("CLIP_END %d\n", got);
    fflush(stdout);

    int64_t t_send_ms = (esp_timer_get_time() - t0) / 1000;
    ESP_LOGI(TAG, "send: %u bytes in %lld ms",
             (unsigned)total_bytes, (long long)t_send_ms);
}


void app_main(void)
{
    /* 运行时把 console UART 切到 DATA_BAUD（绕过 sdkconfig 被还原的问题）。
     * ROM/早期日志仍是 115200（PC 以 921600 读会是乱码，忽略即可）；
     * 此调用之后的所有日志 + 帧数据都是 DATA_BAUD。 */
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(50));
    uart_set_baudrate(UART_NUM_0, DATA_BAUD);
    vTaskDelay(pdMS_TO_TICKS(50));

    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "===== capture_for_lstm (UART @ %d) =====", DATA_BAUD);
    ESP_LOGI(TAG, "free PSRAM: %u bytes",
             (unsigned int)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));

    if (heap_caps_get_total_size(MALLOC_CAP_SPIRAM) == 0) {
        ESP_LOGE(TAG, "PSRAM 未启用，sdkconfig 缺 CONFIG_SPIRAM_MODE_OCT=y");
        return;
    }
    if (init_camera() != ESP_OK) {
        return;
    }

    ESP_LOGI(TAG, "warming up ...");
    warmup_camera();

    ESP_LOGI(TAG, "READY  自动循环采集：看倒计时摆手势，'采集中' 时保持动作");

    uint32_t clip_id = 0;
    while (1) {
        ESP_LOGI(TAG, "==== 准备 CLIP #%lu，摆好手势 ====",
                 (unsigned long)(clip_id + 1));
        countdown(3);
        ESP_LOGI(TAG, "==== CLIP #%lu 采集中! 保持动作 1.5s ====",
                 (unsigned long)(++clip_id));
        int got = capture_clip_frames();
        if (got > 0) {
            send_clip(got);
        } else {
            ESP_LOGW(TAG, "no frame captured, skip send");
        }
        ESP_LOGI(TAG, "采集完成，5 秒后下一组 ...");
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}
