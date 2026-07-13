#ifndef __KEY_H
#define __KEY_H	
#include "sys.h"
#define START  GPIO_ReadInputDataBit(GPIOB,GPIO_Pin_14)
#define START_PRES 	1	
void KEY_Init(void);	  
u8 KEY_Scan(u8 mode);  

#endif
