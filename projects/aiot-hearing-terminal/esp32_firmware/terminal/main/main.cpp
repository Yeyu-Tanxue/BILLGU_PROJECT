/*
 * terminal —— 听障双向沟通终端 统一固件
 * ===============================================================
 * 平时：灰度 96x96 + 端侧 CNN 跑「手势菜单」(边端 AI)。
 * 选手语：运行时切到 JPEG QVGA，拍 45 帧传 PC（MediaPipe+LSTM），再切回菜单。
 *
 * 手势语法（全程手势驱动）：
 *   🫵 one     → 采一个手语词（切JPEG拍45帧→PC识别→累加）
 *   👍 thumbup → 成句（PC 把已累加的词润色成句输出）
 *   ✌️ two     → 语音模式（占位，待麦克风引脚）
 *   🖐 palm    → 紧急求助（PC 推微信）
 *
 * 串口协议（COM7 @921600，ESP32→PC）：
 *   菜单态：  GFRAME <len> <b64>  灰度预览帧
 *            det: <g> <conf>     稳定手势
 *            EVT finalize|voice|emergency
 *   手语采集：SIGN_BEGIN
 *            CLIP_START 45 / FRAME <i>/45 <len> <b64> / CLIP_END 45
 *            SIGN_END
 *
 * 波特率运行时 uart_set_baudrate 强制 921600（不靠 sdkconfig）。
 */

extern "C" {
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "mbedtls/base64.h"
}

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "gesture_model.h"
#include "lcd.h"
#include "spk.h"
#include "mic.h"

static const char *TAG = "term";

#define DATA_BAUD   921600
#define IMG         96
#define IMG_BYTES   (IMG * IMG)

/* 手势触发参数 */
#define CONF_TH        0.70f
#define STABLE_FRAMES  3            /* 4→3：手势更灵敏，少漏触发 */
#define MARGIN_TH      0.10f        /* 0.15→0.10：同上 */
#define COOLDOWN_US    1200000

/* 手语采集参数 */
#define CLIP_FRAMES        45
#define TARGET_PERIOD_US   33333    /* 30fps */

/* 类别顺序须与训练一致（文件夹字母序）：background/fist/one/palm/thumbup/two
 * fist=循环内结束润色；thumbup=待机唤醒。thumbup 留作一类还能"吸收"手语「好/谢谢」
 * 的竖拇指，避免被误判成 fist。需重训 CNN（6 类）。*/
enum { G_BG = 0, G_FIST, G_ONE, G_PALM, G_THUMBUP, G_TWO };
static const char *CLASS_NAMES[] = {"background", "fist", "one", "palm", "thumbup", "two"};

/* 摄像头 PIN（安信可/GOOUUU ESP32-S3-CAM）*/
#define PWDN_GPIO_NUM   -1
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM   15
#define SIOD_GPIO_NUM    4
#define SIOC_GPIO_NUM    5
#define Y9_GPIO_NUM     16
#define Y8_GPIO_NUM     17
#define Y7_GPIO_NUM     18
#define Y6_GPIO_NUM     12
#define Y5_GPIO_NUM     10
#define Y4_GPIO_NUM      8
#define Y3_GPIO_NUM      9
#define Y2_GPIO_NUM     11
#define VSYNC_GPIO_NUM   6
#define HREF_GPIO_NUM    7
#define PCLK_GPIO_NUM   13

namespace {
const tflite::Model *g_model = nullptr;
tflite::MicroInterpreter *g_interp = nullptr;
TfLiteTensor *g_input = nullptr;
TfLiteTensor *g_output = nullptr;
constexpr int kArenaSize = 300 * 1024;
uint8_t *g_arena = nullptr;

typedef struct { uint8_t *data; size_t len; } frame_buf_t;
frame_buf_t g_frames[CLIP_FRAMES];
}


/* 公共 PIN 填充 */
static void fill_pins(camera_config_t *c)
{
    c->pin_pwdn = PWDN_GPIO_NUM; c->pin_reset = RESET_GPIO_NUM;
    c->pin_xclk = XCLK_GPIO_NUM; c->pin_sccb_sda = SIOD_GPIO_NUM; c->pin_sccb_scl = SIOC_GPIO_NUM;
    c->pin_d7 = Y9_GPIO_NUM; c->pin_d6 = Y8_GPIO_NUM; c->pin_d5 = Y7_GPIO_NUM; c->pin_d4 = Y6_GPIO_NUM;
    c->pin_d3 = Y5_GPIO_NUM; c->pin_d2 = Y4_GPIO_NUM; c->pin_d1 = Y3_GPIO_NUM; c->pin_d0 = Y2_GPIO_NUM;
    c->pin_vsync = VSYNC_GPIO_NUM; c->pin_href = HREF_GPIO_NUM; c->pin_pclk = PCLK_GPIO_NUM;
    c->xclk_freq_hz = 24000000; c->ledc_timer = LEDC_TIMER_0; c->ledc_channel = LEDC_CHANNEL_0;
    c->fb_location = CAMERA_FB_IN_PSRAM;
}

/* 180° 旋转：外壳内摄像头朝向与画面相反。vflip+hmirror 等价旋转 180°，
 * 保持左右手手性，对已训练的手势/手语模型无影响。每次 esp_camera_init 后都要重设。*/
static void cam_apply_180(void)
{
    sensor_t *s = esp_camera_sensor_get();
    if (s) { s->set_vflip(s, 1); s->set_hmirror(s, 1); }
}

/* 切到灰度 96x96（手势菜单）*/
static esp_err_t cam_init_gray(void)
{
    camera_config_t c = {};
    fill_pins(&c);
    c.pixel_format = PIXFORMAT_GRAYSCALE;
    c.frame_size = FRAMESIZE_96X96;
    c.fb_count = 2;
    c.grab_mode = CAMERA_GRAB_LATEST;
    esp_err_t e = esp_camera_init(&c);
    if (e == ESP_OK) cam_apply_180();
    return e;
}

/* 切到 JPEG QVGA（手语采集）*/
static esp_err_t cam_init_jpeg(void)
{
    camera_config_t c = {};
    fill_pins(&c);
    c.pixel_format = PIXFORMAT_JPEG;
    c.frame_size = FRAMESIZE_QVGA;
    c.jpeg_quality = 20;        /* 数字越大越压缩、帧更小传输更快；q20 识别率不掉（同 capture_for_lstm）*/
    c.fb_count = 2;
    c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
    esp_err_t e = esp_camera_init(&c);
    if (e == ESP_OK) cam_apply_180();
    return e;
}

static esp_err_t cam_switch(bool to_jpeg)
{
    esp_camera_deinit();
    vTaskDelay(pdMS_TO_TICKS(50));
    esp_err_t e = to_jpeg ? cam_init_jpeg() : cam_init_gray();
    if (e != ESP_OK) ESP_LOGE(TAG, "cam_switch(jpeg=%d) failed: 0x%x", to_jpeg, e);
    /* 预热：丢几帧让传感器稳定 */
    for (int i = 0; i < 8; i++) { camera_fb_t *fb = esp_camera_fb_get(); if (fb) esp_camera_fb_return(fb); }
    return e;
}


/* ---- 手势模型 ---- */
static bool setup_model(void)
{
    g_model = tflite::GetModel(gesture_model);
    if (g_model->version() != TFLITE_SCHEMA_VERSION) {
        ESP_LOGE(TAG, "模型 schema 版本不符"); return false;
    }
    static tflite::MicroMutableOpResolver<8> resolver;
    resolver.AddConv2D(); resolver.AddMaxPool2D(); resolver.AddShape();
    resolver.AddStridedSlice(); resolver.AddPack(); resolver.AddReshape();
    resolver.AddFullyConnected(); resolver.AddSoftmax();

    g_arena = (uint8_t *)heap_caps_malloc(kArenaSize, MALLOC_CAP_SPIRAM);
    if (!g_arena) { ESP_LOGE(TAG, "arena 分配失败"); return false; }

    static tflite::MicroInterpreter interp(g_model, resolver, g_arena, kArenaSize);
    g_interp = &interp;
    if (g_interp->AllocateTensors() != kTfLiteOk) { ESP_LOGE(TAG, "AllocateTensors 失败"); return false; }
    g_input = g_interp->input(0);
    g_output = g_interp->output(0);
    ESP_LOGI(TAG, "手势模型就绪，arena 用 %d KB", (int)g_interp->arena_used_bytes() / 1024);
    return true;
}

static int classify(const uint8_t *gray, float *conf_out, float *margin_out)
{
    const float s = g_input->params.scale;
    const int zp = g_input->params.zero_point;
    int8_t *in = g_input->data.int8;
    for (int i = 0; i < IMG_BYTES; i++) {
        int q = (int)lroundf((gray[i] / 255.0f) / s) + zp;
        if (q < -128) q = -128;
        if (q > 127) q = 127;
        in[i] = (int8_t)q;
    }
    if (g_interp->Invoke() != kTfLiteOk) { *conf_out = 0; *margin_out = 0; return -1; }
    const float os = g_output->params.scale;
    const int ozp = g_output->params.zero_point;
    int8_t *out = g_output->data.int8;
    int best = 0;
    for (int i = 1; i < gesture_n_classes; i++) if (out[i] > out[best]) best = i;
    int second = -1;
    for (int i = 0; i < gesture_n_classes; i++) { if (i == best) continue; if (second < 0 || out[i] > out[second]) second = i; }
    *conf_out = (out[best] - ozp) * os;
    float sc = (second >= 0) ? (out[second] - ozp) * os : 0;
    *margin_out = *conf_out - sc;
    return best;
}

static void send_preview(const uint8_t *data, size_t len)
{
    static uint8_t b64[((IMG_BYTES + 2) / 3) * 4 + 1];
    size_t olen = 0;
    if (mbedtls_base64_encode(b64, sizeof(b64), &olen, data, len) == 0) {
        printf("GFRAME %u ", (unsigned)len);
        fwrite(b64, 1, olen, stdout); putchar('\n'); fflush(stdout);
    }
}


/* ---- 手语采集：JPEG 45 帧 → base64 流 ---- */
static void send_jpeg_frame(int idx, const uint8_t *data, size_t len)
{
    size_t b64_max = ((len + 2) / 3) * 4 + 1;
    uint8_t *b64 = (uint8_t *)heap_caps_malloc(b64_max, MALLOC_CAP_SPIRAM);
    if (!b64) { printf("FRAME_ERR %d\n", idx); return; }
    size_t olen = 0;
    if (mbedtls_base64_encode(b64, b64_max, &olen, data, len) == 0) {
        printf("FRAME %d/%d %u ", idx, CLIP_FRAMES, (unsigned)len);
        fwrite(b64, 1, olen, stdout); putchar('\n'); fflush(stdout);
    }
    heap_caps_free(b64);
    vTaskDelay(pdMS_TO_TICKS(5));   /* 喂看门狗 */
}

/* 切 JPEG → 抓 45 帧 → base64 流出 → 切回灰度 */
static void capture_and_send(void)
{
    ESP_LOGI(TAG, "采集一个词，切 JPEG");
    cam_switch(true);
    int64_t t0 = esp_timer_get_time();
    int got = 0;
    for (int i = 0; i < CLIP_FRAMES; i++) {
        int64_t deadline = t0 + (int64_t)(i + 1) * TARGET_PERIOD_US;
        int64_t wait = deadline - esp_timer_get_time();
        if (wait > 5000) vTaskDelay(pdMS_TO_TICKS(wait / 1000));
        else if (wait > 0) esp_rom_delay_us((uint32_t)wait);

        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) { g_frames[i].data = NULL; g_frames[i].len = 0; continue; }
        uint8_t *buf = (uint8_t *)heap_caps_malloc(fb->len, MALLOC_CAP_SPIRAM);
        if (buf) { memcpy(buf, fb->buf, fb->len); g_frames[i].data = buf; g_frames[i].len = fb->len; got++; }
        else { g_frames[i].data = NULL; g_frames[i].len = 0; }
        esp_camera_fb_return(fb);
    }
    printf("CLIP_START %d\n", got); fflush(stdout);
    for (int i = 0; i < CLIP_FRAMES; i++) {
        if (g_frames[i].data) {
            send_jpeg_frame(i, g_frames[i].data, g_frames[i].len);
            heap_caps_free(g_frames[i].data); g_frames[i].data = NULL;
        }
    }
    printf("CLIP_END %d\n", got); fflush(stdout);
    cam_switch(false);   /* 切回灰度，供下一轮检测 thumbup */
}

/* 采一个词：SIGN_BEGIN → 倒数3-2-1 → 采45帧发出 → SIGN_END。比 L 重复触发采下一个词。*/
static void do_sign_capture(void)
{
    printf("\nSIGN_BEGIN\n"); fflush(stdout);
    /* 3-2-1 倒计时：给你摆好手势的时间（PC 据 POSE 在窗口/LCD 显示）*/
    for (int n = 3; n >= 1; n--) {
        printf("POSE %d\n", n); fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(700));
    }
    printf("POSE 0\n"); fflush(stdout);
    capture_and_send();
    printf("SIGN_END\n"); fflush(stdout);
}


extern "C" void app_main(void)
{
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(50));
    /* UART0 双向：装驱动（TX 发帧 + RX 收 LCD 文字）；vfs 走驱动，避免和控制台抢 RX */
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 16384, 0, 0, NULL, 0));
    uart_set_baudrate(UART_NUM_0, DATA_BAUD);
    uart_vfs_dev_use_driver(UART_NUM_0);
    vTaskDelay(pdMS_TO_TICKS(50));

    ESP_LOGI(TAG, "===== 听障终端 terminal (UART %d) =====", DATA_BAUD);

    /* 扬声器 I2S 初始化（I2S_NUM_0）*/
    spk_setup();

    /* 麦克风 I2S 初始化（I2S_NUM_1）*/
    mic_setup();

    /* LCD：SPI 初始化 + 开机横屏待机画面 + 启动 RX 显示任务（收润色句上屏）*/
    lcd_setup();
    xTaskCreate(lcd_task, "lcd", 4096, NULL, 5, NULL);

    if (cam_init_gray() != ESP_OK) { ESP_LOGE(TAG, "摄像头初始化失败"); return; }
    if (!setup_model()) return;
    for (int i = 0; i < 20; i++) { camera_fb_t *fb = esp_camera_fb_get(); if (fb) esp_camera_fb_return(fb); }
    ESP_LOGI(TAG, "READY 待机→thumbup唤醒→L(one)循环/two语音；fist结束、palm紧急");

    int cand = -1, cand_cnt = 0, last_stable = -1;
    int64_t last_trigger = 0;
    bool armed = true;
    bool awake = false;        /* 待机/唤醒：thumbup 唤醒后才响应 L/V */

    while (1) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) { vTaskDelay(pdMS_TO_TICKS(50)); continue; }
        float conf = 0, margin = 0;
        int cls = -1;
        if (fb->len == IMG_BYTES) { cls = classify(fb->buf, &conf, &margin); send_preview(fb->buf, fb->len); }
        esp_camera_fb_return(fb);
        if (cls < 0) { vTaskDelay(pdMS_TO_TICKS(50)); continue; }

        if (cls == cand) cand_cnt++; else { cand = cls; cand_cnt = 1; }

        if (cand_cnt == STABLE_FRAMES && conf >= CONF_TH) {
            if (cand != last_stable) {
                last_stable = cand;
                printf("det: %s %.2f\n", CLASS_NAMES[cand], conf); fflush(stdout);
            }
            if (cand == G_BG) armed = true;

            int64_t now = esp_timer_get_time();
            bool cooled = (now - last_trigger) > COOLDOWN_US;
            if (cooled) armed = true;          /* 冷却到了自动重新武装，不必特意回背景 */
            if (cand != G_BG && armed && cooled && margin >= MARGIN_TH) {
                last_trigger = now;
                armed = false;
                if (cand == G_THUMBUP) {
                    awake = true;
                    printf("EVT wake\n"); fflush(stdout);
                    ESP_LOGI(TAG, "thumbup → 唤醒");
                } else if (cand == G_ONE && awake) {
                    do_sign_capture();          /* 采一个词；比 L 重复采下一个，保持 awake */
                    cand = -1; cand_cnt = 0; last_stable = -1;   /* 复位去抖 */
                    last_trigger = esp_timer_get_time();
                } else if (cand == G_FIST && awake) {
                    printf("EVT finalize\n"); fflush(stdout);    /* fist → 润色成句、清空 */
                    awake = false;
                    ESP_LOGI(TAG, "fist → 润色");
                } else if (cand == G_TWO && awake) {
                    printf("EVT voice\n"); fflush(stdout);
                    awake = false;
                    ESP_LOGI(TAG, "two → 语音模式");

                    /* ---- 功能2：语音识别 ---- */
                    /* 3-2-1 倒计时 */
                    for (int n = 3; n >= 1; n--) {
                        printf("POSE %d\n", n); fflush(stdout);
                        vTaskDelay(pdMS_TO_TICKS(700));
                    }
                    printf("POSE 0\n"); fflush(stdout);

                    /* 录音 2.5 秒，边录边发小块（避免单行 213KB 卡死 stdio）*/
                    {
                        int n_total = (int)(MIC_SAMPLE_RATE * MIC_RECORD_SEC);
                        int sent = 0;
                        printf("AUDIO_START %d\n", MIC_SAMPLE_RATE); fflush(stdout);

                        int16_t *chunk = (int16_t *)heap_caps_malloc(CHUNK_SIZE * 2, MALLOC_CAP_SPIRAM);
                        if (!chunk) { ESP_LOGE(TAG, "chunk PSRAM 分配失败"); }
                        else {
                            mic_record_start();
                            int seq = 0, total_chunks = (n_total + CHUNK_SIZE - 1) / CHUNK_SIZE;
                            while (sent < n_total) {
                                int n = mic_record_chunk(chunk, CHUNK_SIZE);
                                if (n <= 0) break;
                                size_t rb = n * 2;
                                size_t bmax = ((rb + 2) / 3) * 4 + 1;
                                uint8_t *b64b = (uint8_t *)heap_caps_malloc(bmax, MALLOC_CAP_SPIRAM);
                                if (b64b) {
                                    size_t olen = 0;
                                    if (mbedtls_base64_encode(b64b, bmax, &olen, (const uint8_t *)chunk, rb) == 0) {
                                        printf("AUDIO_CHUNK %d/%d %d ", seq, total_chunks, n);
                                        fwrite(b64b, 1, olen, stdout); putchar('\n'); fflush(stdout);
                                    }
                                    heap_caps_free(b64b);
                                }
                                sent += n; seq++;
                                vTaskDelay(pdMS_TO_TICKS(1));
                            }
                            heap_caps_free(chunk);
                        }
                        printf("AUDIO_END %d\n", sent); fflush(stdout);
                    }
                    ESP_LOGI(TAG, "语音模式结束，回到手势循环");
                    /* 语音结束回到待机态，需重新唤醒才继续 */
                    last_trigger = esp_timer_get_time();
                } else if (cand == G_PALM) {
                    printf("EVT emergency\n"); fflush(stdout);
                    awake = false;            /* SOS（不论推送成败）后回未唤醒待机态 */
                    ESP_LOGI(TAG, "palm → 紧急求助，回待机");
                }
                /* 未唤醒时 L/V/fist 不响应；L 采一词(可重复)、fist 润色结束 */
            }
        }
        vTaskDelay(pdMS_TO_TICKS(70));
    }
}
