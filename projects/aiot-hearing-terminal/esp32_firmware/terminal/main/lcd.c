/*
 * lcd.c —— terminal 固件的 LCD 显示模块（从已验证的 lcd_test 逐字移植）
 * ===============================================================
 * ST7789 原生横屏 320×240：PC 发"上正横屏 1-bit 位图"，固件内部顺时针转 90°
 * (=PIL ROTATE_270) 再贴，屏横着摆即为正。不碰 MADCTL（复用已验证竖屏扫描）。
 * 与摄像头共存：LCD 走 SPI2，摄像头走 DVP/LCD_CAM，引脚/外设互不冲突。
 * UART0 由 main 统一安装驱动（TX 发帧 + RX 收文字）；本模块只 uart_read_bytes 收 + 画屏。
 * 引脚：CLK19 MOSI20 RST21 DC47 CS45 BL38
 *
 * 行协议（与 tools/lcd_send.py 配对，w/h 为"上正横屏"尺寸 w≤320 h≤240）：
 *   TXT <w> <h> <row_bytes> <base64-1bit>\n   横屏黑底白字居中
 *   CLR\n                                      清屏
 */
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "lcd.h"
#include "text_bitmap.h"
#include "spk.h"

static const char *TAG = "lcd";

/* ---- 引脚 ---- */
#define PIN_MOSI    GPIO_NUM_20
#define PIN_CLK     GPIO_NUM_19
#define PIN_CS      GPIO_NUM_45
#define PIN_DC      GPIO_NUM_47
#define PIN_RST     GPIO_NUM_21
#define PIN_BL      GPIO_NUM_38

#define LCD_W       240
#define LCD_H       320
#define X_OFFSET    0
#define Y_OFFSET    0

#define UART_PORT       UART_NUM_0
#define RX_LINE_MAX     65536                  /* 容纳 320×240 1-bit + SPK 音频 base64 */
#define MAX_BMP_BYTES   (LCD_W / 8 * LCD_H)    /* 9600 */
#define LCD_LAND_W      LCD_H                  /* 横屏宽 = 320 */
#define LCD_LAND_H      LCD_W                  /* 横屏高 = 240 */
#define COLOR_FG        0xFFFF                  /* 白字 */
#define COLOR_BG        0x0000                  /* 黑底 */

static spi_device_handle_t g_spi;
static uint16_t g_row[LCD_W];                  /* 每行 240 像素 */
static char     g_line[RX_LINE_MAX];
static uint8_t  g_bmp[MAX_BMP_BYTES];          /* 收到的"上正横屏"位图 */
static uint8_t  g_rot[MAX_BMP_BYTES];          /* 转 90° 后的竖屏位图 */


/* ================================================================
 *  SPI 底层 + ST7789 驱动
 * ================================================================ */
static void lcd_cmd(uint8_t cmd)
{
    gpio_set_level(PIN_DC, 0);
    spi_transaction_t t = { .length = 8, .tx_buffer = &cmd };
    spi_device_transmit(g_spi, &t);
}

static void lcd_data(uint8_t dat)
{
    gpio_set_level(PIN_DC, 1);
    spi_transaction_t t = { .length = 8, .tx_buffer = &dat };
    spi_device_transmit(g_spi, &t);
}

static void lcd_set_window(uint16_t xs, uint16_t ys, uint16_t xe, uint16_t ye)
{
    uint16_t cas1 = ys + Y_OFFSET, cas2 = ye + Y_OFFSET;
    uint16_t ras1 = xs + X_OFFSET, ras2 = xe + X_OFFSET;

    lcd_cmd(0x2A);                      /* CASET → 屏幕 Y */
    lcd_data(cas1 >> 8); lcd_data(cas1 & 0xFF);
    lcd_data(cas2 >> 8); lcd_data(cas2 & 0xFF);

    lcd_cmd(0x2B);                      /* RASET → 屏幕 X */
    lcd_data(ras1 >> 8); lcd_data(ras1 & 0xFF);
    lcd_data(ras2 >> 8); lcd_data(ras2 & 0xFF);

    lcd_cmd(0x2C);                      /* RAMWR */
}

static void lcd_fill(uint16_t rgb565)
{
    uint16_t swp = __builtin_bswap16(rgb565);
    for (int x = 0; x < LCD_W; x++) g_row[x] = swp;

    lcd_set_window(0, 0, LCD_W - 1, LCD_H - 1);
    gpio_set_level(PIN_DC, 1);
    for (int y = 0; y < LCD_H; y++) {
        spi_transaction_t t = { .length = LCD_W * 16, .tx_buffer = g_row };
        spi_device_transmit(g_spi, &t);
    }
}

/* 填充子矩形（竖屏彩色 UI 用）*/
static void lcd_fill_rect(int x, int y, int w, int h, uint16_t rgb565)
{
    if (w <= 0 || h <= 0 || x < 0 || y < 0 || x + w > LCD_W || y + h > LCD_H) return;
    uint16_t swp = __builtin_bswap16(rgb565);
    for (int i = 0; i < w; i++) g_row[i] = swp;
    for (int yy = 0; yy < h; yy++) {
        lcd_set_window(x, y + yy, x + w - 1, y + yy);
        gpio_set_level(PIN_DC, 1);
        spi_transaction_t t = { .length = w * 16, .tx_buffer = g_row };
        spi_device_transmit(g_spi, &t);
    }
}

/* 在屏幕 (px,py) 处画 1-bit 位图（8像素/字节，高位在前）*/
static void lcd_draw_bitmap(int px, int py, const uint8_t *bmp,
                            int bw, int bh, int row_bytes,
                            uint16_t fg, uint16_t bg)
{
    uint16_t fg_sw = __builtin_bswap16(fg);
    uint16_t bg_sw = __builtin_bswap16(bg);

    for (int y = 0; y < bh; y++) {
        for (int x = 0; x < bw; x++) {
            int byte_idx = y * row_bytes + (x / 8);
            int bit = 7 - (x % 8);
            g_row[x] = (bmp[byte_idx] & (1 << bit)) ? fg_sw : bg_sw;
        }
        lcd_set_window(px, py + y, px + bw - 1, py + y);
        gpio_set_level(PIN_DC, 1);
        spi_transaction_t t = { .length = bw * 16, .tx_buffer = g_row };
        spi_device_transmit(g_spi, &t);
    }
}

static void lcd_init(void)
{
    gpio_set_level(PIN_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(PIN_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(150));

    lcd_cmd(0x11);                       /* Sleep Out */
    vTaskDelay(pdMS_TO_TICKS(120));
    lcd_cmd(0x3A); lcd_data(0x55);       /* 16-bit RGB565 */
    lcd_cmd(0x36); lcd_data(0x20);       /* MADCTL：MV=1 交换 XY */
    lcd_cmd(0x21);                       /* Display Inversion On */
    lcd_cmd(0x13);                       /* Normal Display Mode On */
    lcd_cmd(0x29);                       /* Display On */
    vTaskDelay(pdMS_TO_TICKS(50));
    ESP_LOGI(TAG, "ST7789 init done");
}


/* ================================================================
 *  base64 解码 + 横屏旋转 + 行协议
 * ================================================================ */
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

/* 上正横屏位图(sw×sh) 顺时针转 90°(=PIL ROTATE_270) 到 g_rot；输出 dw=sh dh=sw */
static int rotate_cw_90(const uint8_t *src, int sw, int sh, int srb,
                        int *dw, int *dh, int *drb)
{
    int DW = sh, DH = sw, DRB = (sh + 7) / 8;
    if (DRB * DH > MAX_BMP_BYTES) return -1;
    memset(g_rot, 0, DRB * DH);
    for (int dy = 0; dy < DH; dy++) {
        for (int dx = 0; dx < DW; dx++) {
            int sx = dy, sy = sh - 1 - dx;
            if ((src[sy * srb + (sx >> 3)] >> (7 - (sx & 7))) & 1)
                g_rot[dy * DRB + (dx >> 3)] |= 1 << (7 - (dx & 7));
        }
    }
    *dw = DW; *dh = DH; *drb = DRB;
    return 0;
}

static void draw_landscape(const uint8_t *bmp, int sw, int sh, int srb)
{
    int dw, dh, drb;
    if (rotate_cw_90(bmp, sw, sh, srb, &dw, &dh, &drb) != 0) {
        ESP_LOGW(TAG, "旋转缓冲溢出 sw=%d sh=%d", sw, sh);
        return;
    }
    lcd_fill(COLOR_BG);
    lcd_draw_bitmap((LCD_W - dw) / 2, (LCD_H - dh) / 2,
                    g_rot, dw, dh, drb, COLOR_FG, COLOR_BG);
}

static void handle_line(char *line)
{
    if (line[0] == '\0') return;

    if (strcmp(line, "CLR") == 0) {
        lcd_fill(COLOR_BG);
        ESP_LOGI(TAG, "CLR");
        return;
    }

    if (strncmp(line, "SPK ", 4) == 0) {
        spk_handle_line(line);
        return;
    }

    /* ---- 竖屏彩色 UI 原语：PC 端组屏，固件只填色 / 贴图（坐标为竖屏 240×320）---- */
    {
        unsigned col;
        if (sscanf(line, "FILL %x", &col) == 1) { lcd_fill((uint16_t)col); return; }
        int rx, ry, rw, rh; unsigned rc;
        if (sscanf(line, "RECT %d %d %d %d %x", &rx, &ry, &rw, &rh, &rc) == 5) {
            lcd_fill_rect(rx, ry, rw, rh, (uint16_t)rc); return;
        }
        int bx, by, bw, bh, brb, cons = 0; unsigned fg, bg;
        if (sscanf(line, "BMP %d %d %d %d %d %x %x %n",
                   &bx, &by, &bw, &bh, &brb, &fg, &bg, &cons) == 7 && cons > 0) {
            if (bw < 1 || bw > LCD_W || bh < 1 || bh > LCD_H ||
                brb != (bw + 7) / 8 || brb * bh > MAX_BMP_BYTES) {
                ESP_LOGW(TAG, "BMP 参数非法 w=%d h=%d rb=%d", bw, bh, brb); return;
            }
            const char *b64 = line + cons;
            int got = b64_decode(b64, strlen(b64), g_bmp, MAX_BMP_BYTES);
            if (got != brb * bh) { ESP_LOGW(TAG, "BMP 长度不符 %d/%d", got, brb * bh); return; }
            lcd_draw_bitmap(bx, by, g_bmp, bw, bh, brb, (uint16_t)fg, (uint16_t)bg);
            return;
        }
    }

    int sw = 0, sh = 0, srb = 0, consumed = 0;
    if (sscanf(line, "TXT %d %d %d %n", &sw, &sh, &srb, &consumed) == 3 && consumed > 0) {
        if (sw < 1 || sw > LCD_LAND_W || sh < 1 || sh > LCD_LAND_H ||
            srb != (sw + 7) / 8 || srb * sh > MAX_BMP_BYTES) {
            ESP_LOGW(TAG, "TXT 参数非法 w=%d h=%d rb=%d", sw, sh, srb);
            return;
        }
        const char *b64 = line + consumed;
        int got = b64_decode(b64, strlen(b64), g_bmp, MAX_BMP_BYTES);
        if (got != srb * sh) {
            ESP_LOGW(TAG, "TXT 数据长度不符 期望 %d 实得 %d", srb * sh, got);
            return;
        }
        draw_landscape(g_bmp, sw, sh, srb);
        ESP_LOGI(TAG, "TXT 横屏 %dx%d 已显示", sw, sh);
        return;
    }

    ESP_LOGW(TAG, "未知命令: %.16s", line);
}


/* ================================================================
 *  对外接口
 * ================================================================ */
void lcd_setup(void)
{
    /* 背光 */
    gpio_config_t bl = { .pin_bit_mask = BIT64(PIN_BL), .mode = GPIO_MODE_OUTPUT };
    gpio_config(&bl);
    gpio_set_level(PIN_BL, 1);

    /* DC + RST */
    gpio_config_t ctl = { .pin_bit_mask = BIT64(PIN_DC) | BIT64(PIN_RST), .mode = GPIO_MODE_OUTPUT };
    gpio_config(&ctl);
    gpio_set_level(PIN_DC, 1);
    gpio_set_level(PIN_RST, 1);

    /* SPI2 总线（摄像头走 DVP，不冲突）*/
    spi_bus_config_t bus = {
        .mosi_io_num = PIN_MOSI, .miso_io_num = -1, .sclk_io_num = PIN_CLK,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = 4096,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO));

    spi_device_interface_config_t dev = {
        .clock_speed_hz = 30 * 1000 * 1000,
        .mode = 0, .spics_io_num = PIN_CS, .queue_size = 7,
        .flags = SPI_DEVICE_NO_DUMMY,
    };
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST, &dev, &g_spi));

    lcd_init();
    /* 开机竖屏待机底色（深青）；terminal/PC 连上后会发完整待机屏 */
    lcd_fill(0x0946);
    ESP_LOGI(TAG, "LCD 就绪（竖屏 240x320）");
}

void lcd_task(void *arg)
{
    static uint8_t rxbuf[1024];   /* 批量读：逐字节 5000+ 次 syscall → 几次，喂 SPK 累积更及时 */
    int len = 0;
    while (1) {
        int n = uart_read_bytes(UART_PORT, rxbuf, sizeof(rxbuf), pdMS_TO_TICKS(20));
        if (n <= 0) continue;
        for (int i = 0; i < n; i++) {
            uint8_t c = rxbuf[i];
            if (c == '\r') continue;
            if (c == '\n') {
                g_line[len] = '\0';
                handle_line(g_line);
                len = 0;
            } else if (len < RX_LINE_MAX - 1) {
                g_line[len++] = (char)c;
            } else {
                len = 0;
                ESP_LOGW(TAG, "行溢出，丢弃");
            }
        }
    }
}
