`timescale 1ns / 1ps

module stopwatch_ctrl (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       tick_10ms,
    input  wire       key_s0,        // S0: 开始/停止切换
    input  wire       key_s1_inc,    // S1: 倒计时+5分钟
    input  wire       key_s2,        // S2: 暂停/继续
    input  wire       key_s3_mode,   // S3: 模式切换
    input  wire       key_s4_lap,    // S4: 跑圈/查阅

    output reg [23:0] display_data,
    output reg [7:0]  led_status
);

    // 状态编码
    localparam IDLE    = 3'd0;
    localparam RUNNING = 3'd1;
    localparam PAUSE   = 3'd2;
    localparam STOP    = 3'd3;
    localparam REVIEW  = 3'd4;

    reg [2:0] current_state, next_state;
    reg mode_up;            // 1=正计时, 0=倒计时

    // 24位BCD计数器: {min_h, min_l, sec_h, sec_l, ms_h, ms_l}
    reg [23:0] counter_bcd;
    reg [23:0] preset_bcd;  // 倒计时预设值

    // 跑圈存储 (4组)
    reg [23:0] lap_mem [0:3];
    reg [2:0]  lap_cnt;
    reg [2:0]  review_idx;

    // ==================== 状态转移 ====================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            current_state <= IDLE;
            mode_up       <= 1'b1;
            preset_bcd    <= 24'h050000;   // 默认倒计时5分钟
        end else begin
            current_state <= next_state;

            // S3: 模式切换 (仅在IDLE/STOP时有效)
            if (key_s3_mode && (current_state == IDLE || current_state == STOP))
                mode_up <= ~mode_up;

            // S1: 倒计时预设+5分钟
            if (key_s1_inc && !mode_up && (current_state == IDLE || current_state == STOP))
                preset_bcd <= bcd_add_5min(preset_bcd);
        end
    end

    // ==================== 次态组合逻辑 ====================
    always @(*) begin
        next_state = current_state;
        case (current_state)
            IDLE: begin
                if (key_s0) next_state = RUNNING;
            end
            RUNNING: begin
                if (key_s0)
                    next_state = STOP;
                else if (key_s2)
                    next_state = PAUSE;
                else if (~mode_up && counter_bcd == 24'h000000)
                    next_state = STOP;  // 倒计时到0自动停止
            end
            PAUSE: begin
                if (key_s2)
                    next_state = RUNNING;
                else if (key_s0)
                    next_state = STOP;
            end
            STOP: begin
                if (key_s0)
                    next_state = IDLE;
                else if (key_s4_lap && lap_cnt > 0)
                    next_state = REVIEW;
            end
            REVIEW: begin
                if (key_s0)
                    next_state = STOP;
            end
            default: next_state = IDLE;
        endcase
    end

    // ==================== 数据路径 ====================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            counter_bcd <= 24'h000000;
            lap_cnt     <= 3'd0;
            review_idx  <= 3'd0;
            led_status  <= 8'b10101010;
        end else begin
            case (current_state)
                IDLE: begin
                    counter_bcd <= mode_up ? 24'h000000 : preset_bcd;
                    lap_cnt     <= 3'd0;
                    led_status  <= 8'b10101010;  // 交替闪烁
                end

                RUNNING: begin
                    // 花样灯: 正计时左4亮, 倒计时右4亮
                    led_status <= mode_up ? 8'b11110000 : 8'b00001111;

                    // 正计时/倒计时计数
                    if (tick_10ms) begin
                        if (mode_up)
                            counter_bcd <= bcd_add(counter_bcd);
                        else if (counter_bcd != 24'h000000)
                            counter_bcd <= bcd_sub(counter_bcd);
                    end

                    // 跑圈记录 (不停止计数)
                    if (key_s4_lap && lap_cnt < 4) begin
                        lap_mem[lap_cnt] <= counter_bcd;
                        lap_cnt <= lap_cnt + 1'b1;
                    end
                end

                PAUSE: begin
                    led_status <= 8'b11001100;  // 中间4亮
                    // 计数器冻结
                end

                STOP: begin
                    led_status <= 8'b00110011;  // 间隔亮
                    review_idx <= 3'd0;
                end

                REVIEW: begin
                    led_status <= 8'b11111111;  // 全亮
                    if (key_s4_lap) begin
                        if (review_idx < lap_cnt - 1)
                            review_idx <= review_idx + 1'b1;
                        else
                            review_idx <= 3'd0;
                    end
                end
            endcase
        end
    end

    // ==================== 显示数据输出 ====================
    always @(*) begin
        if (current_state == REVIEW)
            display_data = lap_mem[review_idx];
        else
            display_data = counter_bcd;
    end

    // ==================== BCD加法 ====================
    function [23:0] bcd_add;
        input [23:0] din;
        reg [3:0] ms_l, ms_h, sec_l, sec_h, min_l, min_h;
        begin
            ms_l  = din[3:0];
            ms_h  = din[7:4];
            sec_l = din[11:8];
            sec_h = din[15:12];
            min_l = din[19:16];
            min_h = din[23:20];

            if (ms_l == 4'd9) begin
                ms_l = 4'd0;
                if (ms_h == 4'd9) begin
                    ms_h = 4'd0;
                    if (sec_l == 4'd9) begin
                        sec_l = 4'd0;
                        if (sec_h == 4'd5) begin
                            sec_h = 4'd0;
                            if (min_l == 4'd9) begin
                                min_l = 4'd0;
                                if (min_h == 4'd5)
                                    min_h = 4'd0;
                                else
                                    min_h = min_h + 1'b1;
                            end else
                                min_l = min_l + 1'b1;
                        end else
                            sec_h = sec_h + 1'b1;
                    end else
                        sec_l = sec_l + 1'b1;
                end else
                    ms_h = ms_h + 1'b1;
            end else
                ms_l = ms_l + 1'b1;

            bcd_add = {min_h, min_l, sec_h, sec_l, ms_h, ms_l};
        end
    endfunction

    // ==================== BCD减法 ====================
    function [23:0] bcd_sub;
        input [23:0] din;
        reg [3:0] ms_l, ms_h, sec_l, sec_h, min_l, min_h;
        begin
            ms_l  = din[3:0];
            ms_h  = din[7:4];
            sec_l = din[11:8];
            sec_h = din[15:12];
            min_l = din[19:16];
            min_h = din[23:20];

            if (ms_l == 4'd0) begin
                ms_l = 4'd9;
                if (ms_h == 4'd0) begin
                    ms_h = 4'd9;
                    if (sec_l == 4'd0) begin
                        sec_l = 4'd9;
                        if (sec_h == 4'd0) begin
                            sec_h = 4'd5;
                            if (min_l == 4'd0) begin
                                min_l = 4'd9;
                                if (min_h == 4'd0)
                                    min_h = 4'd5;
                                else
                                    min_h = min_h - 1'b1;
                            end else
                                min_l = min_l - 1'b1;
                        end else
                            sec_h = sec_h - 1'b1;
                    end else
                        sec_l = sec_l - 1'b1;
                end else
                    ms_h = ms_h - 1'b1;
            end else
                ms_l = ms_l - 1'b1;

            bcd_sub = {min_h, min_l, sec_h, sec_l, ms_h, ms_l};
        end
    endfunction

    // ==================== +5分钟BCD加法 ====================
    function [23:0] bcd_add_5min;
        input [23:0] din;
        reg [3:0] min_l, min_h;
        begin
            min_h = din[23:20];
            min_l = din[19:16];

            if (min_l < 5)
                min_l = min_l + 5;
            else begin
                min_l = min_l - 5;  // 相当于 +5-10
                if (min_h < 5)
                    min_h = min_h + 1;
                else
                    min_h = 4'd0;   // 超过59分回到00
            end

            bcd_add_5min = {min_h, min_l, din[15:0]};
        end
    endfunction

endmodule
