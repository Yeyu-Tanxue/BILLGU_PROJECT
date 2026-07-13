#pragma once
#ifdef __cplusplus
extern "C" {
#endif

/* SPI 初始化 + ST7789 init + 开机横屏待机画面。app_main 启动时调一次。 */
void lcd_setup(void);

/* UART0 RX 行解析任务（xTaskCreate 启动）：收 TXT/CLR → 画屏。
 * 前提：main 已 uart_driver_install + uart_vfs_dev_use_driver(UART_NUM_0)。 */
void lcd_task(void *arg);

#ifdef __cplusplus
}
#endif
