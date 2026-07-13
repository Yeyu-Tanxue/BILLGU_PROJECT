`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 2026/06/04 14:30:19
// Design Name: 
// Module Name: clk_divider
// Project Name: 
// Target Devices: 
// Tool Versions: 
// Description: 
// 
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
//////////////////////////////////////////////////////////////////////////////////

module clk_divider (
    input  wire clk,         // 100MHz 系统时钟
    input  wire rst_n,       // 复位信号
    output reg  tick_10ms,   // 10ms 单脉冲
    output reg  tick_1ms     // 1ms 单脉冲
);

    // 100MHz 时钟周期为 10ns
    // 1ms 需要 100,000 个周期
    // 10ms 需要 1,000,000 个周期
    reg [19:0] cnt_10ms;
    reg [16:0] cnt_1ms;

    // 产生 10ms 脉冲
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt_10ms <= 20'd0;
            tick_10ms <= 1'b0;
        end else if (cnt_10ms == 20'd999_999) begin
            cnt_10ms <= 20'd0;
            tick_10ms <= 1'b1;
        end else begin
            cnt_10ms <= cnt_10ms + 1'b1;
            tick_10ms <= 1'b0;
        end
    end

    // 产生 1ms 脉冲 (用于数码管扫描)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt_1ms <= 17'd0;
            tick_1ms <= 1'b0;
        end else if (cnt_1ms == 17'd99_999) begin
            cnt_1ms <= 17'd0;
            tick_1ms <= 1'b1;
        end else begin
            cnt_1ms <= cnt_1ms + 1'b1;
            tick_1ms <= 1'b0;
        end
    end

endmodule