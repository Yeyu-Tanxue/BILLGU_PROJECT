#include "delay.h"
#include "sys.h"
#include "usart.h"	 
#include "math.h"			
#include "stdio.h"
#include "stm32f10x_flash.h"
#include "stdlib.h"
#include "string.h"
#include "wdg.h"
#include "in.h"
#include "led.h"
#include "timer.h"
#include "stm32f10x_tim.h"
#include <stm32f10x.h>
#include "adc.h"
#include "key.h"
#include "oled.h"
#include "show.h"
#include "main.h"
#include "myiic.h"
#include "encoder.h"
#include "MyProject.h"
/********************引脚说明******************
//相电流一号通道:PA0
//相电流二号通道:PA1
//OLED屏幕SCL通道:PB0
//OLED屏幕SDA通道:PB1
//AS5600磁编码器SDA通道:PB10
//AS5600磁编码器SCL通道:PB11
//EC11旋转编码器SWA:PB12
//EC11旋转编码器SWB:PB13
//EC11旋转编码器SWC:PB14
//DRV8313功率芯片FAULT:PB15
//DRV8313功率芯片PWM1:PA8
//DRV8313功率芯片PMW2:PA9
//DRV8313功率芯片PWM3:PA10
//DRV8313功率芯片EN:PA11
//DRV8313功率芯片RESET:PA12
**********************************************/
u8 show_mode;//显示模式
u8 fault_status;//出错状态，=0出错，=1不出错
u8 reset_status;//复位状态，=0休眠，=1工作
u8 motor_en=1;//电机使能状态，=0不工作，=1工作
u8 motor_speed;//电机速度等级
float target;
float I1_data;//通道1电流
float I2_data;//通道2电流
float current_angle;//当前角度

///***使用于NB版本**************/
int main(void)
{	 
  delay_init();	    	            //延时函数初始化	  
  NVIC_Configuration(); 	        //设置NVIC中断分组2:2位抢占优先级，2位响应优先级
	
  Init_adc();                     //ADC的初始化 
	IN_Init();                      //FAULT信号检测
	KEY_Init();                     //按键的初始化
	OLED_Init();			              //初始化OLED  
	OLED_Clear();                   //OLED清屏 
  page_one();                     //显示第一个界面	
  RESET_Init();                   //休眠状态控制
	ENABLE_Init();                  //使能状态控制
	AS5600_IIC_Init();	            //磁编码器IIC初始化
  //电机参数控制
	MOTOR_PWM_Init();               //电机PWM驱动使能
	TIM4_1ms_Init();                //1ms定时工作	
	delay_ms(1000);                 //等待中断初始化
	MagneticSensor_Init();          //得到初始化角度
	voltage_power_supply=12;        //供电电压，目前暂定为12V
	pole_pairs=7;                   //极对数	
	voltage_limit=5;                //电压限制，云台电机设置为1-3即可
	velocity_limit=20;              //转速限制，20rad/s
	voltage_sensor_align=2.5;       //V 重要参数，航模电机大功率0.5-1，云台电机小功率2-3
	torque_controller=Type_voltage; //电压模式
	controller=Type_velocity;       //速度环模式
	target = 0;                  //上电后以6.28rad/s的转速转动（1圈/秒）
	
	Motor_init();
	Motor_initFOC();
	PID_init();                //PID参数设置 在init函数里
	
	TIM2_Int_Init(3599,39);         //初始化定时器,2ms执行一次,主要用来控制编码器扫描
  TIM3_Int_Init(9,7199);          //定时1ms执行特定任务
 		
  while (1)
  {	
		if(motor_speed==0)target=0;
		else if(motor_speed==1)target=6.28;
		else if(motor_speed==2)target=12.56;
		else if(motor_speed==3)target=18.84;
		else if(motor_speed==4)target=25.12;
		else if(motor_speed==5)target=31.40;
		move(target);
		loopFOC();
  }
}








