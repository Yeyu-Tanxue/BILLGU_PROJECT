idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES esp32-camera esp_timer mbedtls esp_driver_uart
)
