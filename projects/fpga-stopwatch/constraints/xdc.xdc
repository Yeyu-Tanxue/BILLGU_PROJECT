# ==========================================
# 系统时钟 (100MHz)
# ==========================================
set_property PACKAGE_PIN P17 [get_ports clk]
set_property IOSTANDARD LVCMOS33 [get_ports clk]

# ==========================================
# 复位 (EGo1 专用复位按键 P15, 低电平有效)
# ==========================================
set_property PACKAGE_PIN P15 [get_ports rst_n]
set_property IOSTANDARD LVCMOS33 [get_ports rst_n]

# ==========================================
# 按键 (EGo1: PB0~PB4, 按下=高电平)
# ==========================================
# S0 (PB0=R11): 开始/停止
set_property PACKAGE_PIN R11 [get_ports key_s0]
set_property IOSTANDARD LVCMOS33 [get_ports key_s0]

# S1 (PB1=R17): 倒计时 +5分钟
set_property PACKAGE_PIN R17 [get_ports key_s1_inc]
set_property IOSTANDARD LVCMOS33 [get_ports key_s1_inc]

# S2 (PB2=R15): 暂停/继续
set_property PACKAGE_PIN R15 [get_ports key_s2]
set_property IOSTANDARD LVCMOS33 [get_ports key_s2]

# S3 (PB3=V1): 模式切换 (正计时/倒计时)
set_property PACKAGE_PIN V1 [get_ports key_s3_mode]
set_property IOSTANDARD LVCMOS33 [get_ports key_s3_mode]

# S4 (PB4=U4): 跑圈
set_property PACKAGE_PIN U4 [get_ports key_s4_lap]
set_property IOSTANDARD LVCMOS33 [get_ports key_s4_lap]

# ==========================================
# LED 指示灯 (LED0~LED7)
# ==========================================
set_property PACKAGE_PIN F6 [get_ports {led_status[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led_status[0]}]
set_property PACKAGE_PIN G4 [get_ports {led_status[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led_status[1]}]
set_property PACKAGE_PIN G3 [get_ports {led_status[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led_status[2]}]
set_property PACKAGE_PIN J4 [get_ports {led_status[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led_status[3]}]
set_property PACKAGE_PIN H4 [get_ports {led_status[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led_status[4]}]
set_property PACKAGE_PIN J3 [get_ports {led_status[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led_status[5]}]
set_property PACKAGE_PIN J2 [get_ports {led_status[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led_status[6]}]
set_property PACKAGE_PIN K2 [get_ports {led_status[7]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led_status[7]}]

# ==========================================
# 数码管位选：EGo1 seg_cs_pin[7:0]
# 共阴极，高电平选中
# seg_cs_pin[0]=G2(最右) ... seg_cs_pin[7]=G6(最左)
# ==========================================
set_property PACKAGE_PIN G2 [get_ports {seg_sel[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_sel[0]}]
set_property PACKAGE_PIN C2 [get_ports {seg_sel[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_sel[1]}]
set_property PACKAGE_PIN C1 [get_ports {seg_sel[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_sel[2]}]
set_property PACKAGE_PIN H1 [get_ports {seg_sel[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_sel[3]}]
set_property PACKAGE_PIN G1 [get_ports {seg_sel[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_sel[4]}]
set_property PACKAGE_PIN F1 [get_ports {seg_sel[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_sel[5]}]
set_property PACKAGE_PIN E1 [get_ports {seg_sel[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_sel[6]}]
set_property PACKAGE_PIN G6 [get_ports {seg_sel[7]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_sel[7]}]

# ==========================================
# 数码管段选 - 第一组 seg_data_0_pin[7:0]
# seg_data[7:0] = {DP,G,F,E,D,C,B,A}
# ==========================================
set_property PACKAGE_PIN B4 [get_ports {seg_data[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data[0]}]
set_property PACKAGE_PIN A4 [get_ports {seg_data[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data[1]}]
set_property PACKAGE_PIN A3 [get_ports {seg_data[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data[2]}]
set_property PACKAGE_PIN B1 [get_ports {seg_data[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data[3]}]
set_property PACKAGE_PIN A1 [get_ports {seg_data[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data[4]}]
set_property PACKAGE_PIN B3 [get_ports {seg_data[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data[5]}]
set_property PACKAGE_PIN B2 [get_ports {seg_data[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data[6]}]
set_property PACKAGE_PIN D5 [get_ports {seg_data[7]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data[7]}]

# ==========================================
# 数码管段选 - 第二组 seg_data_1_pin[7:0] (后2位)
# seg_data1[7:0] = {DP,G,F,E,D,C,B,A}
# ==========================================
set_property PACKAGE_PIN D4 [get_ports {seg_data1[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data1[0]}]
set_property PACKAGE_PIN E3 [get_ports {seg_data1[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data1[1]}]
set_property PACKAGE_PIN D3 [get_ports {seg_data1[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data1[2]}]
set_property PACKAGE_PIN F4 [get_ports {seg_data1[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data1[3]}]
set_property PACKAGE_PIN F3 [get_ports {seg_data1[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data1[4]}]
set_property PACKAGE_PIN E2 [get_ports {seg_data1[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data1[5]}]
set_property PACKAGE_PIN D2 [get_ports {seg_data1[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data1[6]}]
set_property PACKAGE_PIN H2 [get_ports {seg_data1[7]}]
set_property IOSTANDARD LVCMOS33 [get_ports {seg_data1[7]}]
