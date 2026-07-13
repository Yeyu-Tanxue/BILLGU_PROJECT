#include "timer.h"
#include "led.h"
#include "key.h"
#include "usart.h"
#include "stm32f10x_tim.h"
#include "main.h"
#include "show.h"
#include "oled.h"
#include "in.h"
#include "encoder.h"

uint32_t time1_cntr;
/*buck同步整流电路配置*/
#define MOTOR_TIMx TIM1
#define MOTOR_Plus 0  
#define MOTOR_ARR 1439//重装载值2880,频率25KHz
#define MOTOR_PSC 0//分频系数1
void MOTOR_PWM_Init(void)//buck电路输出，拟定充电
{   
	GPIO_InitTypeDef GPIO_InitStructure;
	TIM_TimeBaseInitTypeDef TIM_TimeBaseInitStruct;
	TIM_OCInitTypeDef TIM_OCInitStruct;
	
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA,ENABLE); //使能PORTA,B时钟
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_AFIO,ENABLE); //使能PORTA,B时钟
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_TIM1,ENABLE);
	//初始化GPIO,PA8	
	GPIO_InitStructure.GPIO_Mode=GPIO_Mode_AF_PP;//端口复用
	GPIO_InitStructure.GPIO_Pin=GPIO_Pin_8|GPIO_Pin_9|GPIO_Pin_10;
	GPIO_InitStructure.GPIO_Speed=GPIO_Speed_50MHz;
	GPIO_Init(GPIOA,&GPIO_InitStructure); //PA8
	
	//初始化时具单元
	TIM_DeInit(MOTOR_TIMx);
	TIM_TimeBaseInitStruct.TIM_ClockDivision=TIM_CKD_DIV1;
	TIM_TimeBaseInitStruct.TIM_CounterMode=TIM_CounterMode_CenterAligned1;
	TIM_TimeBaseInitStruct.TIM_Period=MOTOR_ARR;
	TIM_TimeBaseInitStruct.TIM_Prescaler=MOTOR_PSC;
	TIM_TimeBaseInitStruct.TIM_RepetitionCounter = 0;
	TIM_TimeBaseInit(MOTOR_TIMx,&TIM_TimeBaseInitStruct);	
	
	//将输出通道2初始化为PWM模式1
	TIM_OCInitStruct.TIM_OCMode=TIM_OCMode_PWM1;
	TIM_OCInitStruct.TIM_OutputState=TIM_OutputState_Enable;
	TIM_OCInitStruct.TIM_OCPolarity=TIM_OCPolarity_High;
//	TIM_OCInitStruct.TIM_OCIdleState=TIM_OCIdleState_Set;
	TIM_OCInitStruct.TIM_Pulse=0;
	TIM_OC1Init(MOTOR_TIMx,&TIM_OCInitStruct);
	TIM_OC2Init(MOTOR_TIMx,&TIM_OCInitStruct);
	TIM_OC3Init(MOTOR_TIMx,&TIM_OCInitStruct);
	
	//使能预装载寄存器
	TIM_OC1PreloadConfig(MOTOR_TIMx,TIM_OCPreload_Enable);
	TIM_OC2PreloadConfig(MOTOR_TIMx,TIM_OCPreload_Enable);
	TIM_OC3PreloadConfig(MOTOR_TIMx,TIM_OCPreload_Enable);
	
	//使能自动重装载
	TIM_ARRPreloadConfig(MOTOR_TIMx,ENABLE);
	
	//开启定时器
	TIM_Cmd(MOTOR_TIMx,ENABLE);
	
	//主输出使能
	TIM_CtrlPWMOutputs(MOTOR_TIMx,ENABLE);
}

void TIM2_Int_Init(u16 arr,u16 psc)
{
  TIM_TimeBaseInitTypeDef  TIM_TimeBaseStructure;
	NVIC_InitTypeDef NVIC_InitStructure;

	RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM2, ENABLE); //时钟使能

	TIM_TimeBaseStructure.TIM_Period = arr; //设置在下一个更新事件装入活动的自动重装载寄存器周期的值	 计数到5000为500ms
	TIM_TimeBaseStructure.TIM_Prescaler =psc; //设置用来作为TIMx时钟频率除数的预分频值  10Khz的计数频率  
	TIM_TimeBaseStructure.TIM_ClockDivision = 0; //设置时钟分割:TDTS = Tck_tim
	TIM_TimeBaseStructure.TIM_CounterMode = TIM_CounterMode_Up;  //TIM向上计数模式
	TIM_TimeBaseInit(TIM2, &TIM_TimeBaseStructure); //根据TIM_TimeBaseInitStruct中指定的参数初始化TIMx的时间基数单位

	TIM_ITConfig(TIM2,TIM_IT_Update|TIM_IT_Trigger,ENABLE);
	
	NVIC_InitStructure.NVIC_IRQChannel = TIM2_IRQn;  //TIM2中断
	NVIC_InitStructure.NVIC_IRQChannelPreemptionPriority = 0;  //先占优先级0级
	NVIC_InitStructure.NVIC_IRQChannelSubPriority = 2;  //从优先级3级
	NVIC_InitStructure.NVIC_IRQChannelCmd = ENABLE; //IRQ通道被使能
	NVIC_Init(&NVIC_InitStructure);  //根据NVIC_InitStruct中指定的参数初始化外设NVIC寄存器

	TIM_Cmd(TIM2, ENABLE);  //使能TIMx外设
							 
}
void TIM2_IRQHandler(void)   //TIM2中断
{	
	if (TIM_GetITStatus(TIM2, TIM_IT_Update) != RESET) //检查指定的TIM中断发生与否:TIM 中断源 
	{		
		switch(EncoderProcess())//旋转编码器函数
	  {
      case E_RIGHT:  inc(); break;
      case E_LEFT:   dec(); break;
	  }
		TIM_ClearITPendingBit(TIM2, TIM_IT_Update  );  //清除TIMx的中断待处理位:TIM 中断源 
	}
}

void TIM3_Int_Init(u16 arr,u16 psc)
{
 TIM_TimeBaseInitTypeDef  TIM_TimeBaseStructure;
	NVIC_InitTypeDef NVIC_InitStructure;

	RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM3, ENABLE); //时钟使能

	TIM_TimeBaseStructure.TIM_Period = arr; //设置在下一个更新事件装入活动的自动重装载寄存器周期的值	 计数到5000为500ms
	TIM_TimeBaseStructure.TIM_Prescaler =psc; //设置用来作为TIMx时钟频率除数的预分频值  10Khz的计数频率  
	TIM_TimeBaseStructure.TIM_ClockDivision = 0; //设置时钟分割:TDTS = Tck_tim
	TIM_TimeBaseStructure.TIM_CounterMode = TIM_CounterMode_Up;  //TIM向上计数模式
	TIM_TimeBaseInit(TIM3, &TIM_TimeBaseStructure); //根据TIM_TimeBaseInitStruct中指定的参数初始化TIMx的时间基数单位
 
	TIM_ITConfig(TIM3,TIM_IT_Update,ENABLE ); //使能指定的TIM3中断,允许更新中断

	NVIC_InitStructure.NVIC_IRQChannel = TIM3_IRQn;  //TIM3中断
	NVIC_InitStructure.NVIC_IRQChannelPreemptionPriority = 0;  //先占优先级0级
	NVIC_InitStructure.NVIC_IRQChannelSubPriority = 3;  //从优先级3级
	NVIC_InitStructure.NVIC_IRQChannelCmd = ENABLE; //IRQ通道被使能
	NVIC_Init(&NVIC_InitStructure);  //根据NVIC_InitStruct中指定的参数初始化外设NVIC寄存器

	TIM_Cmd(TIM3, ENABLE);  //不使能TIMx外设
							 
}
					 

float ADC_ConvertedValueLocal; 
float ADC_ConvertedValueLoca2;
extern __IO uint16_t ADC_ConvertedValue[2];
//定时器3中断服务程序
void TIM3_IRQHandler(void)   //TIM3中断
{
	u8 key;	
	static u16 key_count=0;
	static u16 adc_count=0;
	static u16 show_count=0;
	static float i1_zong=0.0f;
	static float i2_zong=0.0f;
	if(TIM_GetITStatus(TIM3, TIM_IT_Update) != RESET) //检查指定的TIM中断发生与否:TIM 中断源 
	{
		//按键扫描
		key_count++;
		if(key_count>=100)
		{
			key_count=0;
			key=KEY_Scan(0);
			if(key==START_PRES)
			{
        motor_en=!motor_en;
			}
		}		 
    //检测告警状态
		if(FAULT==1)fault_status=0;
		else fault_status=1;
//		//使能复位状态
		if(motor_en)MOTOR_ENABLE=1,MOTOR_RESET=1;
		else MOTOR_ENABLE=0,MOTOR_RESET=0;
		//
		
		//检测两相电流，反推出另外一相，目前此处暂定显示电流，实际工作频率肯定不走这一路
		adc_count++;
		ADC_ConvertedValueLocal=(float)ADC_ConvertedValue[0]/4095;
		ADC_ConvertedValueLoca2=(float)ADC_ConvertedValue[1]/4095;
		i1_zong+=ADC_ConvertedValueLocal;
		i2_zong+=ADC_ConvertedValueLoca2;
		if(adc_count>=500)       //500ms进行一次计算
		{
			adc_count=0;		
			I1_data=i1_zong/500*3.3;
			I2_data=i2_zong/500*3.3;
			i1_zong=0;
			i2_zong=0;
		}	

    //屏幕显示		
		show_count++;
		if(show_count>=200)
		{
			show_count=0;
			if(show_mode==0)
			{

		    if(motor_en)OLED_ShowCHinese(96,2,8);
				else OLED_ShowCHinese(96,2,9);
				if(fault_status)OLED_ShowCHinese(96,4,10);
				else OLED_ShowCHinese(96,4,11);
		    OLED_ShowNum(72,6,motor_speed,2,16);		
			}
		}
		TIM_ClearITPendingBit(TIM3, TIM_IT_Update  );  //清除TIMx的中断待处理位:TIM 中断源 
	}
}

void TIM4_1ms_Init(void)  //(u16 arr,u16 psc)
{
	TIM_TimeBaseInitTypeDef TIM_TimeBaseInitStructure;
	NVIC_InitTypeDef NVIC_InitStructure;
	
	RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM4,ENABLE);
	
	NVIC_InitStructure.NVIC_IRQChannel=TIM4_IRQn;
	NVIC_InitStructure.NVIC_IRQChannelCmd=ENABLE;
	NVIC_Init(&NVIC_InitStructure); 
	
	TIM_TimeBaseInitStructure.TIM_Period = 1000-1;      //1ms
	TIM_TimeBaseInitStructure.TIM_Prescaler=72-1;       //72分频=1MHz
	TIM_TimeBaseInitStructure.TIM_CounterMode=TIM_CounterMode_Up;
	TIM_TimeBaseInitStructure.TIM_ClockDivision=TIM_CKD_DIV1;
	TIM_TimeBaseInit(TIM4,&TIM_TimeBaseInitStructure);
	TIM_ITConfig(TIM4,TIM_IT_Update,ENABLE);
	TIM_Cmd(TIM4,ENABLE);
}

//定时器中断服务函数
void TIM4_IRQHandler(void)
{
	if(TIM_GetITStatus(TIM4,TIM_IT_Update)==SET) //溢出中断
	{
		time1_cntr++;
	}
	TIM_ClearITPendingBit(TIM4,TIM_IT_Update); //清除中断标志位
}
/*选择通道函数*/
void set_pwm(TIM_TypeDef* TIMx,u8 chx,u16 prec,u16 up)
{
	//判断输入参数是否正确
	if(chx<1||chx>4)
		return;
	if(prec>up)
		prec=up;
	//根据输入的通道设置PWM占空比
	switch(chx)
	{
		case 1:TIM_SetCompare1(TIMx,prec);break;
		case 2:TIM_SetCompare2(TIMx,prec);break;     
		case 3:TIM_SetCompare3(TIMx,prec);break;
		case 4:TIM_SetCompare4(TIMx,prec);break;           
	}
}

