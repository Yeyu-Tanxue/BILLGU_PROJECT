idf_component_register(
    SRCS "mic.c" "spk.c" "main.cpp" "lcd.c"
    INCLUDE_DIRS "."
    REQUIRES esp32-camera esp_timer esp_driver_uart esp_driver_spi esp_driver_gpio esp_driver_i2s esp-tflite-micro mbedtls
)
