cmake_minimum_required(VERSION 3.16)

# 绕过 ESP-IDF v5.5.3 + GCC 14.2 在 esp_lcd/rgb 上的 ICE
set(EXCLUDE_COMPONENTS "esp_lcd")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(terminal)
