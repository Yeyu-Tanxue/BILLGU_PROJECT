/*
 * gesture_cam —— 端侧手势识别（esp-tflite-micro 本地推理）
 * ---------------------------------------------------------------
 * 摄像头灰度 96x96 → INT8 CNN 本地推理 → 手势 → 状态机/动作。
 * 真正的边端 AI：识别全在 ESP32 上跑，不依赖 PC/网络。
 *
 * 手势映射（与训练 gesture_labels.json 顺序一致）：
 *   background 待机 / fist 唤醒 / one 手语识别 / two 语音识别 / palm 紧急求助
 *
 * 串口输出（COM7 @921600）：
 *   det: <gesture> <conf>     稳定手势变化时
 *   ACTION <gesture>          确认触发时（PC 端可据此联动，如 palm→紧急推送）
 *
 * 注：采集固件备份在 main.c.collect.bak（需重新采数据时换回它）。
 */

extern "C" {
#include <stdio.h>
#include <math.h>
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "mbedtls/base64.h"
}

/* 预览：把灰度帧也发给 PC 显示（识别仍在端侧跑，这只是给人看画面）。
 * 独立部署（无 PC）时改 0，避免无人读串口时 printf 阻塞。 */
#define STREAM_PREVIEW   1

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "gesture_model.h"   // gesture_model[], gesture_model_len, gesture_n_classes, gesture_img_size

static const char *TAG = "gcam";

#define DATA_BAUD   921600
#define IMG         96
#define IMG_BYTES   (IMG * IMG)

/* 类别名：必须与训练时 sorted 顺序一致 → background/fist/one/palm/thumbup/two */
static const char *CLASS_NAMES[] = {"background", "fist", "one", "palm", "thumbup", "two"};
static const char *CLASS_ACTION[] = {"待机", "唤醒", "手语识别", "紧急求助

/* 触发参数 */
#define CONF_TH        0.70f   /* 置信度阈值 */
#define STABLE_FRAMES  4       /* 连续 N 帧同手势才确认（去抖）*/
#define MARGIN_TH      0.15f   /* top1 须比 top2 高这么多才触发（轻度防近似误判）*/
#define COOLDOWN_US    1500000 /* 触发后冷却 1.5s */

/* ---- 摄像头 PIN（安信可 ESP32-S3-CAM）---- */
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

/* ---- TFLite Micro 全局 ---- */
namespace {
const tflite::Model *g_model = nullptr;
tflite::MicroInterpreter *g_interp = nullptr;
TfLiteTensor *g_input = nullptr;
TfLiteTensor *g_output = nullptr;
constexpr int kArenaSize = 300 * 1024;     /* 推理内存，放 PSRAM */
uint8_t *g_arena = nullptr;
}


static esp_err_t init_camera(void)
{
    camera_config_t config = {};
    config.pin_pwdn = -1;
    config.pin_reset = -1;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.xclk_freq_hz = 24000000;
    config.ledc_timer = LEDC_TIMER_0;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.pixel_format = PIXFORMAT_GRAYSCALE;
    config.frame_size = FRAMESIZE_96X96;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.grab_mode = CAMERA_GRAB_LATEST;

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_camera_init failed: 0x%x", err);
    } else {
        /* 180° 旋转：与 terminal 固件保持一致（外壳内摄像头倒装）。
         * 采集数据的方向必须等于部署运行的方向，否则训练白做。*/
        sensor_t *s = esp_camera_sensor_get();
        if (s) { s->set_vflip(s, 1); s->set_hmirror(s, 1); }
    }
    return err;
}


static bool setup_model(void)
{
    g_model = tflite::GetModel(gesture_model);
    if (g_model->version() != TFLITE_SCHEMA_VERSION) {
        ESP_LOGE(TAG, "模型 schema 版本不匹配: %d vs %d",
                 (int)g_model->version(), TFLITE_SCHEMA_VERSION);
        return false;
    }

    /* 模型用到的算子（由 TF Analyzer 确认）：
       CONV_2D / MAX_POOL_2D / SHAPE / STRIDED_SLICE / PACK / RESHAPE
       / FULLY_CONNECTED / SOFTMAX —— 共 8 个 */
    static tflite::MicroMutableOpResolver<8> resolver;
    resolver.AddConv2D();
    resolver.AddMaxPool2D();
    resolver.AddShape();
    resolver.AddStridedSlice();
    resolver.AddPack();
    resolver.AddReshape();
    resolver.AddFullyConnected();
    resolver.AddSoftmax();

    g_arena = (uint8_t *)heap_caps_malloc(kArenaSize, MALLOC_CAP_SPIRAM);
    if (!g_arena) {
        ESP_LOGE(TAG, "arena 分配失败 (%d KB PSRAM)", kArenaSize / 1024);
        return false;
    }

    static tflite::MicroInterpreter interp(g_model, resolver, g_arena, kArenaSize);
    g_interp = &interp;
    if (g_interp->AllocateTensors() != kTfLiteOk) {
        ESP_LOGE(TAG, "AllocateTensors 失败（arena 不够或算子缺失）");
        return false;
    }
    g_input = g_interp->input(0);
    g_output = g_interp->output(0);
    ESP_LOGI(TAG, "模型就绪: 输入[%d,%d,%d,%d] int8 scale=%.5f zp=%d  arena 用了 %d KB",
             g_input->dims->data[0], g_input->dims->data[1],
             g_input->dims->data[2], g_input->dims->data[3],
             g_input->params.scale, (int)g_input->params.zero_point,
             (int)g_interp->arena_used_bytes() / 1024);
    return true;
}


#if STREAM_PREVIEW
/* 把灰度帧 base64 发给 PC 预览 */
static void send_preview(const uint8_t *data, size_t len)
{
    static uint8_t b64[((IMG_BYTES + 2) / 3) * 4 + 1];
    size_t olen = 0;
    if (mbedtls_base64_encode(b64, sizeof(b64), &olen, data, len) == 0) {
        printf("GFRAME %u ", (unsigned)len);
        fwrite(b64, 1, olen, stdout);
        putchar('\n');
        fflush(stdout);
    }
}
#endif


/* 灰度帧 → 量化填入 → 推理 → 返回 top1 类别；输出 top1 置信度 + 与 top2 的差距 */
static int classify(const uint8_t *gray, float *conf_out, float *margin_out)
{
    const float s = g_input->params.scale;
    const int zp = g_input->params.zero_point;
    int8_t *in = g_input->data.int8;
    for (int i = 0; i < IMG_BYTES; i++) {
        /* 与训练一致：x = pixel/255 → q = x/scale + zero_point */
        int q = (int)lroundf((gray[i] / 255.0f) / s) + zp;
        if (q < -128) q = -128;
        if (q > 127) q = 127;
        in[i] = (int8_t)q;
    }
    if (g_interp->Invoke() != kTfLiteOk) {
        *conf_out = 0.0f;
        *margin_out = 0.0f;
        return -1;
    }
    const float os = g_output->params.scale;
    const int ozp = g_output->params.zero_point;
    int8_t *out = g_output->data.int8;
    int best = 0;
    for (int i = 1; i < gesture_n_classes; i++) {
        if (out[i] > out[best]) best = i;
    }
    int second = -1;
    for (int i = 0; i < gesture_n_classes; i++) {
        if (i == best) continue;
        if (second < 0 || out[i] > out[second]) second = i;
    }
    *conf_out = (out[best] - ozp) * os;   /* 反量化得 softmax 概率 */
    float second_conf = (second >= 0) ? (out[second] - ozp) * os : 0.0f;
    *margin_out = *conf_out - second_conf;
    return best;
}


extern "C" void app_main(void)
{
    /* 运行时强制 921600（绕过 sdkconfig 被 build 还原）*/
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(50));
    uart_set_baudrate(UART_NUM_0, DATA_BAUD);
    vTaskDelay(pdMS_TO_TICKS(50));

    ESP_LOGI(TAG, "===== gesture_cam 端侧推理 (UART %d) =====", DATA_BAUD);
    ESP_LOGI(TAG, "free PSRAM: %u", (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));

    if (init_camera() != ESP_OK) return;
    if (!setup_model()) return;

    /* 预热摄像头 */
    for (int i = 0; i < 30; i++) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (fb) esp_camera_fb_return(fb);
    }
    ESP_LOGI(TAG, "READY 端侧手势识别中（fist唤醒/one手语/two语音/palm紧急）");

    int last_stable = -1;       /* 上次确认的稳定手势 */
    int cand = -1, cand_cnt = 0;
    int64_t last_trigger = 0;
    bool armed = true;          /* 回到 background 后才允许再次触发 */

    while (1) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) { vTaskDelay(pdMS_TO_TICKS(50)); continue; }

        float conf = 0.0f, margin = 0.0f;
        int cls = -1;
        if (fb->len == IMG_BYTES) {
            cls = classify(fb->buf, &conf, &margin);
#if STREAM_PREVIEW
            send_preview(fb->buf, fb->len);
#endif
        }
        esp_camera_fb_return(fb);

        if (cls < 0) { vTaskDelay(pdMS_TO_TICKS(50)); continue; }

        /* 去抖：连续 STABLE_FRAMES 帧同类且置信度够，才算"稳定手势" */
        if (cls == cand) cand_cnt++;
        else { cand = cls; cand_cnt = 1; }

        if (cand_cnt == STABLE_FRAMES && conf >= CONF_TH) {
            if (cand != last_stable) {
                last_stable = cand;
                printf("det: %s %.2f\n", CLASS_NAMES[cand], conf);
                fflush(stdout);
            }
            /* 回到背景 → 重新武装，允许下一次触发 */
            if (cand == 0) armed = true;

            int64_t now = esp_timer_get_time();
            bool cooled = (now - last_trigger) > COOLDOWN_US;
            /* margin 闸：top1 须明显高于 top2，相似手势(palm/two)模糊时不触发 */
            if (cand != 0 && armed && cooled && margin >= MARGIN_TH) {
                last_trigger = now;
                armed = false;   /* 触发后需回 background 再武装，避免一直触发 */
                ESP_LOGI(TAG, ">>> 手势[%s] → %s", CLASS_NAMES[cand], CLASS_ACTION[cand]);
                printf("ACTION %s\n", CLASS_NAMES[cand]);
                fflush(stdout);
            }
        }

        vTaskDelay(pdMS_TO_TICKS(70));   /* ~10fps + 喂看门狗 */
    }
}
