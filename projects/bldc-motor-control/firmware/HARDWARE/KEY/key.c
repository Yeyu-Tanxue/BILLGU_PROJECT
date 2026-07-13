#include "stm32f10x.h"  //包含需要的头文件
#include "delay.h"
#include "key.h"      //包含需要的头文件
void KEY_Init(void)
{	
	GPIO_InitTypeDef GPIO_InitStructure;                       
	RCC_APB2PeriphClockCmd( RCC_APB2Periph_GPIOB , ENABLE);    
	GPIO_InitStructure.GPIO_Pin =  GPIO_Pin_14;                       
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU;   		   
	GPIO_Init(GPIOB, &GPIO_InitStructure);            		   
} 

u8 KEY_Scan(u8 mode)
{	 
	static u8 key_up=1;//按键按松开标志
	if(mode)key_up=1;  //支持连按		  
	if(key_up&&START==0)
	{
		delay_ms(10);//去抖动 
		key_up=0;
		if(START==0)return START_PRES;

	}else if(START==1)key_up=1; 	    
 	return 0;// 无按键按下
}




















