`timescale 1ns / 1ps

module debounce (
    input  wire       clk,        // 100MHz
    input  wire       rst_n,      // 低电平复位
    input  wire       key_in,     // 按键输入 (高电平有效)
    output reg        key_pulse   // 单周期脉冲 (按下时产生)
);

    // 10ms 去抖 = 1_000_000 周期 @ 100MHz
    parameter DELAY = 20'd999_999;

    reg [19:0] cnt;
    reg sync0, sync1;           // 两级同步器，消除亚稳态
    reg key_debounced;          // 去抖后的稳定电平
    reg key_prev;               // 上一拍的去抖电平，用于边沿检测

    // 两级同步
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sync0 <= 1'b0;
            sync1 <= 1'b0;
        end else begin
            sync0 <= key_in;
            sync1 <= sync0;
        end
    end

    // 去抖计数器：输入稳定持续 DELAY 周期后才更新输出
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt          <= 20'd0;
            key_debounced <= 1'b0;
        end else if (sync1 != key_debounced) begin
            if (cnt == DELAY) begin
                cnt          <= 20'd0;
                key_debounced <= sync1;
            end else begin
                cnt <= cnt + 1'b1;
            end
        end else begin
            cnt <= 20'd0;
        end
    end

    // 上升沿检测 -> 单周期脉冲
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            key_prev   <= 1'b0;
            key_pulse  <= 1'b0;
        end else begin
            key_prev   <= key_debounced;
            key_pulse  <= key_debounced & ~key_prev;
        end
    end

endmodule
