#ifndef __TIMER_H
#define __TIMER_H
#include "sys.h"
#define PWM_Period  1440
extern uint32_t time1_cntr;
void MOTOR_PWM_Init(void);
void TIM2_Int_Init(u16 arr,u16 psc);
void TIM3_Int_Init(u16 arr,u16 psc);
void TIM4_1ms_Init(void);
void set_pwm(TIM_TypeDef* TIMx,u8 chx,u16 prec,u16 up);
#endif
