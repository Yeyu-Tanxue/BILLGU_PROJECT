`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 2026/06/04 14:30:19
// Design Name: 
// Module Name: seg_driver
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

module seg_driver (
    input  wire        clk,        // 系统时钟
    input  wire        rst_n,      // 复位信号
    input  wire        tick_1ms,   // 1ms 扫描刷新脉冲
    input  wire [23:0] bcd_in,     // 核心模块传来的 24位 BCD 数据
    
    output reg  [7:0]  seg_sel,    // 8位 位选 (选择点亮哪一个管子，低电平有效)
    output reg  [7:0]  seg_data    // 8位 段选 (A~G和DP，低电平有效)
);

    reg [2:0] scan_cnt;    // 扫描计数器 (0~5，对应6个数码管)
    reg [3:0] current_bcd; // 当前需要显示的 4位 BCD 码
    reg       dot_enable;  // 小数点使能

    // 步骤1：利用 1ms 脉冲切换扫描位置
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            scan_cnt <= 3'd0;
        end else if (tick_1ms) begin
            if (scan_cnt == 3'd5)
                scan_cnt <= 3'd0;
            else
                scan_cnt <= scan_cnt + 1'b1;
        end
    end

    // 步骤2：根据扫描位置，分配位选信号和对应的数据
    // EGo1 共阴极数码管，位选高电平有效 (1=选中)
    always @(*) begin
        // 默认不亮小数点
        dot_enable = 1'b0;

        case (scan_cnt)
            // 右边第1位 (10ms位) → seg_sel[5]=F1
            3'd0: begin seg_sel = 8'b0010_0000; current_bcd = bcd_in[3:0];   end
            // 右边第2位 (100ms位) → seg_sel[4]=G1
            3'd1: begin seg_sel = 8'b0001_0000; current_bcd = bcd_in[7:4];   end
            // 右边第3位 (秒个位) → seg_sel[3]=H1, 带小数点
            3'd2: begin seg_sel = 8'b0000_1000; current_bcd = bcd_in[11:8];  dot_enable = 1'b1; end
            // 右边第4位 (秒十位) → seg_sel[2]=C1
            3'd3: begin seg_sel = 8'b0000_0100; current_bcd = bcd_in[15:12]; end
            // 右边第5位 (分个位) → seg_sel[1]=C2, 带小数点
            3'd4: begin seg_sel = 8'b0000_0010; current_bcd = bcd_in[19:16]; dot_enable = 1'b1; end
            // 右边第6位 (分十位) → seg_sel[0]=G2
            3'd5: begin seg_sel = 8'b0000_0001; current_bcd = bcd_in[23:20]; end

            default: begin seg_sel = 8'b0000_0000; current_bcd = 4'd0; end
        endcase
    end

    // 步骤3：BCD 码转 七段数码管物理电平 (EGo1 共阴极译码，1为亮，0为灭)
    // 数组排列方式: {G, F, E, D, C, B, A}
    reg [6:0] seg_decode;
    always @(*) begin
        case (current_bcd)
            4'd0: seg_decode = 7'b0111111; // 显示 0
            4'd1: seg_decode = 7'b0000110; // 显示 1
            4'd2: seg_decode = 7'b1011011; // 显示 2
            4'd3: seg_decode = 7'b1001111; // 显示 3
            4'd4: seg_decode = 7'b1100110; // 显示 4
            4'd5: seg_decode = 7'b1101101; // 显示 5
            4'd6: seg_decode = 7'b1111101; // 显示 6
            4'd7: seg_decode = 7'b0000111; // 显示 7
            4'd8: seg_decode = 7'b1111111; // 显示 8
            4'd9: seg_decode = 7'b1101111; // 显示 9
            default: seg_decode = 7'b0000000; // 全灭
        endcase
    end

    // 组合段选输出 (EGo1 共阴极，1为亮)
    // seg_data[7:0] = {DP, G, F, E, D, C, B, A}
    always @(*) begin
        if (dot_enable)
            seg_data = {1'b1, seg_decode}; // DP=1 点亮
        else
            seg_data = {1'b0, seg_decode}; // DP=0 熄灭
    end

endmodule
