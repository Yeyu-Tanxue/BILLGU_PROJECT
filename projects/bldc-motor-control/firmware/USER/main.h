#ifndef __MAIN_H__
#define __MAIN_H__
#include "stm32f10x_gpio.h"
#include "sys.h"


extern u8 motor_speed;//电机速度等级
extern u8 show_mode;//显示模式
extern u8 fault_status;//出错状态，=0出错，=1不出错
extern u8 reset_status;//复位状态，=0休眠，=1工作
extern u8 motor_en;//电机使能状态，=0不工作，=1工作

extern float I1_data;//通道1电流
extern float I2_data;//通道2电流
extern float current_angle;//当前角度
#endif 


