#include "stm32f10x.h"  //包含需要的头文件
#include "delay.h"
#include "in.h"      //包含需要的头文件
void IN_Init(void)
{	
	GPIO_InitTypeDef GPIO_InitStructure;                       
	RCC_APB2PeriphClockCmd( RCC_APB2Periph_GPIOB , ENABLE);    
	GPIO_InitStructure.GPIO_Pin =  GPIO_Pin_15;                       
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU;   		   
	GPIO_Init(GPIOB, &GPIO_InitStructure);            		   
} 





















