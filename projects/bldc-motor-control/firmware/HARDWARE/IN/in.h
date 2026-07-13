#ifndef __IN_H
#define __IN_H	
#include "sys.h"
#define FAULT  GPIO_ReadInputDataBit(GPIOB,GPIO_Pin_15)
void IN_Init(void);	  
#endif
