

#ifndef MYPROJECT_H
#define MYPROJECT_H

/* Includes ------------------------------------------------------------------*/

#include "stm32f10x_it.h" 
#include "usart.h"
#include "delay.h"
#include "timer.h"
#include "stm32f10x_tim.h"

#include "MagneticSensor.h" 
#include "foc_utils.h" 
#include "FOCMotor.h" 
#include "BLDCmotor.h" 
#include "lowpass_filter.h" 
#include "pid.h"

#define M1_Enable    GPIO_SetBits(GPIOA,GPIO_Pin_11);          //高电平使能
#define M1_Disable   GPIO_ResetBits(GPIOA,GPIO_Pin_11);        //低电平解除
#define M1_Reset     GPIO_SetBits(GPIOA,GPIO_Pin_12);          //高电平使能
#define M1_Dreset    GPIO_ResetBits(GPIOA,GPIO_Pin_12);        //低电平解除

#endif

