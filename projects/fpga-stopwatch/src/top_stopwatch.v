`timescale 1ns / 1ps

module top_stopwatch (
    input  wire       clk,
    input  wire       rst_n,          // EGo1 专用复位键(P15)
    input  wire       key_s0,         // S0(R11): 开始/停止切换
    input  wire       key_s1_inc,     // S1(R17): 倒计时+5分钟
    input  wire       key_s2,         // S2(R15): 暂停/继续
    input  wire       key_s3_mode,    // S3(V1): 模式切换
    input  wire       key_s4_lap,     // S4(U4): 跑圈/查阅

    output wire [7:0] led_status,
    output wire [7:0] seg_sel,
    output wire [7:0] seg_data,
    output wire [7:0] seg_data1       // EGo1 第二组段选总线
);

    // 内部信号
    wire tick_10ms;
    wire tick_1ms;
    wire [23:0] bcd_data;

    // 第二组段选与第一组相同
    assign seg_data1 = seg_data;

    // 按键去抖脉冲
    wire key_s0_pulse, key_s1_inc_pulse, key_s2_pulse;
    wire key_s3_mode_pulse, key_s4_lap_pulse;

    // 1. 时钟分频
    clk_divider u_clk_div (
        .clk        (clk),
        .rst_n      (rst_n),
        .tick_10ms  (tick_10ms),
        .tick_1ms   (tick_1ms)
    );

    // 2. 按键消抖
    debounce u_debounce_s0 (
        .clk       (clk),
        .rst_n     (rst_n),
        .key_in    (key_s0),
        .key_pulse (key_s0_pulse)
    );

    debounce u_debounce_s1 (
        .clk       (clk),
        .rst_n     (rst_n),
        .key_in    (key_s1_inc),
        .key_pulse (key_s1_inc_pulse)
    );

    debounce u_debounce_s2 (
        .clk       (clk),
        .rst_n     (rst_n),
        .key_in    (key_s2),
        .key_pulse (key_s2_pulse)
    );

    debounce u_debounce_s3 (
        .clk       (clk),
        .rst_n     (rst_n),
        .key_in    (key_s3_mode),
        .key_pulse (key_s3_mode_pulse)
    );

    debounce u_debounce_s4 (
        .clk       (clk),
        .rst_n     (rst_n),
        .key_in    (key_s4_lap),
        .key_pulse (key_s4_lap_pulse)
    );

    // 3. 秒表核心控制
    stopwatch_ctrl u_ctrl (
        .clk          (clk),
        .rst_n        (rst_n),
        .tick_10ms    (tick_10ms),
        .key_s0       (key_s0_pulse),
        .key_s1_inc   (key_s1_inc_pulse),
        .key_s2       (key_s2_pulse),
        .key_s3_mode  (key_s3_mode_pulse),
        .key_s4_lap   (key_s4_lap_pulse),

        .display_data (bcd_data),
        .led_status   (led_status)
    );

    // 4. 数码管驱动
    seg_driver u_seg (
        .clk        (clk),
        .rst_n      (rst_n),
        .tick_1ms   (tick_1ms),
        .bcd_in     (bcd_data),
        .seg_sel    (seg_sel),
        .seg_data   (seg_data)
    );

endmodule
