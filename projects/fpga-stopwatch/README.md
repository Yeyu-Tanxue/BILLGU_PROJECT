# FPGA Stopwatch / FPGA 多功能数字秒表

This folder contains the public curated files from a Vivado / Verilog stopwatch project for the EGo1 FPGA board.

## Highlights

- `src/top_stopwatch.v`: top-level integration
- `src/TRY.v`: stopwatch control state machine
- `src/clk_divider.v`: 100MHz clock divider for 10ms and 1ms ticks
- `src/debounce.v`: key debounce logic
- `src/seg_driver.v`: six-digit seven-segment display scanning
- `constraints/xdc.xdc`: EGo1 pin constraints

## Features

- Start/stop control
- Pause/resume
- Up-count and countdown modes
- Countdown preset increment
- Lap record and review
- LED status indication
- Seven-segment dynamic display

Generated Vivado run directories and caches are intentionally excluded.
